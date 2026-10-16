import os
import sys
import stat
import time
import ctypes
import random
import logging
import subprocess
from shutil import which
from pathlib import Path

from PyQt6.QtWidgets import (
    QMessageBox, QFileDialog, QDialog, QVBoxLayout, QLabel,
    QCheckBox, QHBoxLayout, QPushButton, QApplication,
    QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, QLocale, QPropertyAnimation, QEasingCurve, QObject
from PyQt6.QtGui import QGuiApplication

from .config import CONFIG_FILE, EULA_FILE, APP_VERSION, APPDATA_DIR, save_config

logger = logging.getLogger("TriCoreBoot")

_DEFAULT_COLORS = {"#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""}
_PATH_KEYWORDS = ("path", "dir", "keys", "prodinfo", "hactool", "boot9", "otp")


def _get_mac_app_bundle_path(path):
    abs_path = os.path.abspath(path)
    parts = abs_path.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep.join(parts[:i + 1])
    return abs_path


class ResetConfirmDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_obj = parent
        self.is_shift_mode = False

        t_func = getattr(self.parent_obj, "T", lambda k, d=None: d if d is not None else k)
        self.setWindowTitle(t_func("msg_reset_title", "Reset"))
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        self.lbl_msg = QLabel(t_func("msg_reset_warn", ""))
        self.lbl_msg.setWordWrap(True)
        layout.addWidget(self.lbl_msg)

        self.btn_yes = QPushButton(t_func("btn_yes", "Yes"))
        self.btn_yes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_no = QPushButton(t_func("btn_no", "No"))
        self.btn_no.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_no.setDefault(True)

        self.normal_yes_style = """
            QPushButton {
                background-color: #0d6efd;
                color: #ffffff;
                border: 1px solid #0b5ed7;
                border-radius: 6px;
                padding: 8px 22px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #0b5ed7;
                border-color: #0a58ca;
            }
        """

        self.shift_yes_style = """
            QPushButton {
                background-color: #dc3545;
                color: #ffffff;
                border: 1px solid #ff6b6b;
                border-radius: 6px;
                padding: 8px 22px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #bb2d3b;
                border-color: #b02a37;
            }
        """

        self.btn_yes.setStyleSheet(self.normal_yes_style)
        self.btn_no.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #adadad;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 8px 22px;
            }
            QPushButton:hover {
                background-color: #333333;
                color: #ffffff;
                border-color: #777777;
            }
        """)

        self.btn_yes.clicked.connect(self.accept)
        self.btn_no.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_yes)
        btn_layout.addWidget(self.btn_no)
        layout.addLayout(btn_layout)

        self.shift_timer = QTimer(self)
        self.shift_timer.setInterval(30)
        self.shift_timer.timeout.connect(self._check_shift_state)

    def showEvent(self, event):
        super().showEvent(event)
        audio_obj = getattr(self.parent_obj, "audio", getattr(self.parent_obj, "audio_manager", None))
        if audio_obj and hasattr(audio_obj, "play_reset_sound"):
            audio_obj.play_reset_sound()

        self.shift_timer.start()

        if not sys.platform.startswith("linux"):
            self.setWindowOpacity(0.0)
            self.anim_opacity = QPropertyAnimation(self, b"windowOpacity")
            self.anim_opacity.setDuration(200)
            self.anim_opacity.setStartValue(0.0)
            self.anim_opacity.setEndValue(1.0)
            self.anim_opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.anim_opacity.start()

        self._check_shift_state()

    def done(self, result):
        if hasattr(self, "shift_timer") and self.shift_timer.isActive():
            self.shift_timer.stop()
        super().done(result)

    def _is_shift_held_down(self) -> bool:
        if sys.platform == "win32":
            try:
                return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
            except Exception:
                pass
        return bool(QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

    def _check_shift_state(self):
        is_shift = self._is_shift_held_down()
        if is_shift != self.is_shift_mode:
            self.is_shift_mode = is_shift
            self.btn_yes.setStyleSheet(self.shift_yes_style if is_shift else self.normal_yes_style)
            self.btn_yes.style().unpolish(self.btn_yes)
            self.btn_yes.style().polish(self.btn_yes)
            self.btn_yes.update()


class SettingsMixin:
    def _spawn_new_instance_and_quit(self, save_before_exit=True):
        self._is_restarting = True

        for timer_attr in ("save_timer", "rainbow_timer", "_sigint_timer", "updater_spinner_timer", "_vol_save_timer"):
            timer = getattr(self, timer_attr, None)
            if timer and hasattr(timer, "isActive") and timer.isActive():
                timer.stop()

        audio_obj = getattr(self, "audio", getattr(self, "audio_manager", None))
        if audio_obj:
            try:
                if hasattr(audio_obj, "cleanup"):
                    audio_obj.cleanup()
                elif hasattr(audio_obj, "stop_all"):
                    audio_obj.stop_all()
            except Exception:
                pass

        if getattr(self, "worker", None) and self.worker.isRunning():
            try:
                self.worker.stop()
                self.worker.wait(500)
            except Exception:
                pass

        if save_before_exit:
            try:
                if hasattr(self, "config") and isinstance(self.config, dict):
                    save_config(self.config)
            except Exception:
                pass

        if hasattr(self, "perform_security_cleanup"):
            self.perform_security_cleanup()

        if hasattr(self, "app_lock") and self.app_lock.isLocked():
            try:
                self.app_lock.unlock()
            except Exception:
                pass

        clean_env = os.environ.copy()
        clean_env.pop("_MEIPASS2", None)
        clean_env.pop("_MEIPASS", None)
        clean_env.pop("APPDIR", None)
        clean_env.pop("OWD", None)
        clean_env.pop("ARGV0", None)

        if sys.platform.startswith("linux"):
            clean_env.pop("LD_LIBRARY_PATH", None)
            clean_env.pop("LD_LIBRARY_PATH_ORIG", None)
            clean_env.pop("LD_PRELOAD", None)
            clean_env.pop("QT_PLUGIN_PATH", None)
            clean_env.pop("QML2_IMPORT_PATH", None)
            clean_env.pop("PYTHONPATH", None)
            clean_env.pop("PYTHONHOME", None)
            clean_env.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
            for env_key in ("PATH", "XDG_DATA_DIRS", "GI_TYPELIB_PATH", "GST_PLUGIN_SYSTEM_PATH", "GST_PLUGIN_PATH"):
                if env_key in clean_env:
                    filtered = [
                        p for p in clean_env[env_key].split(os.pathsep)
                        if p and not p.startswith(("/tmp/.mount_", "/tmp/_MEI", "/tmp/appimage_extracted_"))
                    ]
                    if filtered:
                        clean_env[env_key] = os.pathsep.join(filtered)
                    else:
                        clean_env.pop(env_key, None)
            clean_env["APPIMAGE_EXTRACT_AND_RUN"] = "1"

        is_frozen = getattr(sys, "frozen", False)
        extra_args = [a for a in sys.argv[1:] if a != "--updater"]

        if sys.platform == "darwin":
            if is_frozen:
                mac_app = _get_mac_app_bundle_path(sys.executable)
                if mac_app.endswith(".app") and os.path.exists(mac_app):
                    args = ["open", "-n", mac_app]
                    work_dir = os.path.dirname(mac_app)
                else:
                    exe_target = os.path.abspath(sys.executable)
                    work_dir = os.path.dirname(exe_target)
                    args = [exe_target] + extra_args
            else:
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path) or os.getcwd()
                args = [sys.executable, script_path] + extra_args
        elif sys.platform == "win32":
            if is_frozen:
                exe_target = os.path.abspath(sys.executable)
                work_dir = os.path.dirname(exe_target)
                args = [exe_target] + extra_args
            else:
                py_exec = sys.executable
                if py_exec.lower().endswith("python.exe"):
                    pyw = os.path.join(os.path.dirname(py_exec), "pythonw.exe")
                    if os.path.exists(pyw):
                        py_exec = pyw
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path) or os.getcwd()
                args = [py_exec, script_path] + extra_args
        else:
            if is_frozen:
                appimage_env = os.environ.get("ORIGINAL_APPIMAGE") or os.environ.get("APPIMAGE")
                if appimage_env and os.path.exists(appimage_env):
                    exe_target = os.path.abspath(appimage_env)
                    work_dir = os.path.dirname(exe_target)
                    clean_env["ORIGINAL_APPIMAGE"] = exe_target
                else:
                    exe_target = os.path.abspath(sys.executable)
                    work_dir = os.path.dirname(exe_target)
                try:
                    st = os.stat(exe_target)
                    os.chmod(exe_target, st.st_mode | stat.S_IEXEC | 0o755)
                except Exception:
                    pass
                args = [exe_target] + extra_args
            else:
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path) or os.getcwd()
                args = [sys.executable, script_path] + extra_args

        kwargs = {
            "cwd": work_dir,
            "env": clean_env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True

        if sys.platform.startswith("linux"):
            launched_ok = False
            try:
                proc = subprocess.Popen(args, **kwargs)
                for _ in range(15):
                    QApplication.processEvents()
                    time.sleep(0.1)
                    if proc.poll() is not None:
                        break
                if proc.poll() is None and os.path.exists(f"/proc/{proc.pid}"):
                    launched_ok = True
            except Exception:
                launched_ok = False

            if not launched_ok and is_frozen:
                try:
                    fallback_env = clean_env.copy()
                    fallback_env.pop("APPIMAGE_EXTRACT_AND_RUN", None)
                    fallback_kwargs = dict(kwargs)
                    fallback_kwargs["env"] = fallback_env
                    proc = subprocess.Popen(args, **fallback_kwargs)
                    for _ in range(15):
                        QApplication.processEvents()
                        time.sleep(0.1)
                        if proc.poll() is not None:
                            break
                    if proc.poll() is None and os.path.exists(f"/proc/{proc.pid}"):
                        launched_ok = True
                except Exception:
                    launched_ok = False

            if not launched_ok:
                self._is_restarting = False
                return

            self.hide()
            QApplication.processEvents()
            time.sleep(0.15)
            self.close()
            app = QApplication.instance()
            if app:
                app.quit()
            return

        try:
            subprocess.Popen(args, **kwargs)
        except Exception:
            return

        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def restart_app(self):
        self._spawn_new_instance_and_quit(save_before_exit=True)

    def show_aria_info_popup(self, checked):
        if checked and not getattr(self, "_is_loading_ui", True):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("msg_aria_info_title"))
            msg_box.setText(self.T("msg_aria_info_desc"))
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.addButton(self.T("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()

    def on_aria_toggle(self, checked):
        self.trigger_auto_save()

    def on_adv_mode_toggle(self, checked):
        if not checked:
            self._is_loading_ui = True
            for attr in (
                "chk_adv_logs", "chk_use_aria2c", "chk_resize",
                "chk_exfat", "chk_hide_warn", "chk_cafe_extract",
                "chk_cemu_layout", "chk_build_nsp"
            ):
                if hasattr(self, attr):
                    getattr(self, attr).setChecked(False)
            self._is_loading_ui = False

            self.on_adv_logs_toggle(False)
            self.on_aria_toggle(False)

        self.trigger_auto_save()

    def _animate_input_highlight(self, widget):
        if not widget:
            return
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", self if isinstance(self, QObject) else widget)
        anim.setDuration(180)
        anim.setStartValue(0.2)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup():
            widget.setGraphicsEffect(None)

        anim.finished.connect(_cleanup)
        self._path_anim = anim
        anim.start()

    def suggest_export_folder(self, *args):
        if not hasattr(self, "input_output") or self.input_output is None:
            return

        base_dir = Path.home() / "Downloads"
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).upper()
        if not mode or mode == "WELCOME":
            mode = "NX"

        folders = {
            "NX": ["NX_Firmware", "NX_Updates", "NX", "Switch1", "Daybreak", "NCAs", "NX_CDN", "NX_Stock_FW"],
            "CAFE": ["Cafe_Firmware", "Cafe_Updates", "Cafe", "WiiU", "ISFSHax", "wafel_install", "CAFE_NUS", "CAFE_Stock_FW"],
            "CTR": ["CTR_Firmware", "CTR_Updates", "CTR", "3DS", "sysUpdater", "CIAs", "CTR_NUS", "CTR_Stock_FW"]
        }

        names = folders.get(mode, ["TriCore_Firmwares"])
        current_path = os.path.normpath(self.input_output.text().strip())
        candidates = [
            os.path.normpath(str(base_dir / name))
            for name in names
            if os.path.normpath(str(base_dir / name)) != current_path
        ]
        suggested_path = random.choice(candidates) if candidates else os.path.normpath(str(base_dir / names[0]))

        self.input_output.setText(suggested_path)
        self._animate_input_highlight(self.input_output)

        if hasattr(self, "config"):
            self.config[f"output_dir_{mode.lower()}"] = suggested_path
            self.config["output_dir"] = suggested_path
            self._settings_dirty = True
            self.trigger_auto_save()

    def on_output_dir_changed(self, text):
        if getattr(self, "_is_loading_ui", False):
            return
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).lower()
        clean_text = text.strip()
        self.config[f"output_dir_{mode}"] = clean_text
        self.config["output_dir"] = clean_text
        self._settings_dirty = True
        self.trigger_auto_save()

    def verify_and_create_export_folder(self, out_dir):
        if not out_dir:
            return True

        out_path = Path(out_dir)
        if not out_path.exists():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("folder_not_found_title"))
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setTextFormat(Qt.TextFormat.RichText)

            breakable_path = str(out_path).replace("\\", "\\\u200b").replace("/", "/\u200b")
            path_display = f"<br><br><code style='color: #4da8da;'>{breakable_path}</code><br><br>"
            texte_formate = self.T("folder_not_found_msg").format(path_display)
            msg_box.setText(f"<div style='width: 420px;'>{texte_formate}</div>")

            btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
            btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
            msg_box.setDefaultButton(btn_yes)
            msg_box.exec()

            if msg_box.clickedButton() == btn_yes:
                try:
                    out_path.mkdir(parents=True, exist_ok=True)
                    return True
                except Exception as e:
                    err_msg = self.T("msg_folder_err", "Unable to create destination folder:")
                    QMessageBox.critical(self, self.T("msg_error_title"), f"{err_msg}\n{e}")
                    return False
            else:
                return False
        return True

    def on_adv_logs_toggle(self, checked):
        if not checked:
            self._is_loading_ui = True
            if hasattr(self, "chk_hide_warn"):
                self.chk_hide_warn.setChecked(False)
            self.config["redact_privacy_info"] = False
            self._is_loading_ui = False
        self.trigger_auto_save()

    def on_hide_warn_toggle(self, checked):
        if checked and not getattr(self, "_is_loading_ui", True):
            dialog = QDialog(self)
            dialog.setWindowTitle(self.T("hide_warn_title"))
            dialog.setMinimumWidth(500)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(16)

            lbl_msg = QLabel(self.T("hide_warn_msg"))
            lbl_msg.setWordWrap(True)
            layout.addWidget(lbl_msg)

            cb_redact = QCheckBox(self.T("chk_redact_logs"))
            cb_redact.setChecked(self.config.get("redact_privacy_info", False))
            layout.addWidget(cb_redact)

            btn_yes, btn_no = QPushButton(self.T("btn_yes")), QPushButton(self.T("btn_no"))
            btn_yes.clicked.connect(dialog.accept)
            btn_no.clicked.connect(dialog.reject)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_layout.addWidget(btn_yes)
            btn_layout.addWidget(btn_no)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.config["redact_privacy_info"] = cb_redact.isChecked()
            else:
                self._is_loading_ui = True
                if hasattr(self, "chk_hide_warn"):
                    self.chk_hide_warn.setChecked(False)
                self.config["redact_privacy_info"] = False
                self._is_loading_ui = False
        elif not checked and not getattr(self, "_is_loading_ui", True):
            self.config["redact_privacy_info"] = False
        self.trigger_auto_save()

    def on_exfat_toggle(self, checked):
        if checked and not getattr(self, "_is_loading_ui", True):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("exfat_warn_title"))
            msg_box.setText(self.T("exfat_warn_msg"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
            btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
            msg_box.setDefaultButton(btn_no)
            msg_box.exec()

            if msg_box.clickedButton() == btn_no:
                self._is_loading_ui = True
                if hasattr(self, "chk_exfat"):
                    self.chk_exfat.setChecked(False)
                self._is_loading_ui = False

    def browse_file(self, line_edit, expected_name):
        current_val = line_edit.text().strip() if line_edit else ""
        start_dir = os.path.dirname(current_val) if (current_val and os.path.exists(os.path.dirname(current_val))) else str(Path.home())

        while True:
            file_path, _ = QFileDialog.getOpenFileName(self, self.T("dialog_select_file"), start_dir)
            if not file_path:
                break

            filename = os.path.basename(file_path)
            if filename.lower() != expected_name.lower():
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(self.T("warn_filename_title"))
                msg_box.setText(self.T("warn_filename_msg").format(expected_name, filename))
                msg_box.setIcon(QMessageBox.Icon.Question)
                msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
                btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
                msg_box.setDefaultButton(btn_no)
                msg_box.exec()
                if msg_box.clickedButton() == btn_no:
                    start_dir = os.path.dirname(file_path)
                    continue

            line_edit.setText(os.path.normpath(file_path))
            break

    def browse_folder(self, line_edit):
        current_val = line_edit.text().strip() if line_edit else ""
        start_dir = current_val if (current_val and os.path.isdir(current_val)) else str(Path.home())
        folder_path = QFileDialog.getExistingDirectory(self, self.T("dialog_select_folder"), start_dir)
        if folder_path:
            line_edit.setText(os.path.normpath(folder_path))

    def auto_detect_aria(self):
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        aria_name = "aria2c.exe" if sys.platform == "win32" else "aria2c"
        ssl_name = "openssl.exe" if sys.platform == "win32" else "openssl"

        aria_path = which(aria_name)
        if not aria_path:
            aria_candidates = [
                os.path.join(script_dir, aria_name),
                os.path.join(str(APPDATA_DIR), aria_name),
            ]
            if sys.platform == "darwin":
                aria_candidates.extend(["/opt/homebrew/bin/aria2c", "/usr/local/bin/aria2c"])
            elif sys.platform == "win32":
                local_app = os.environ.get("LOCALAPPDATA", "")
                user_prof = os.environ.get("USERPROFILE", "")
                aria_candidates.extend([
                    r"C:\Program Files\aria2\aria2c.exe",
                    os.path.join(local_app, "Microsoft", "WinGet", "Links", "aria2c.exe"),
                    os.path.join(user_prof, "scoop", "shims", "aria2c.exe"),
                    r"C:\ProgramData\chocolatey\bin\aria2c.exe",
                ])
            else:
                aria_candidates.extend(["/usr/bin/aria2c", "/usr/local/bin/aria2c"])

            for c in aria_candidates:
                if c and os.path.isfile(c):
                    aria_path = c
                    break

        ssl_path = which(ssl_name)
        if not ssl_path:
            ssl_candidates = [
                os.path.join(script_dir, ssl_name),
                os.path.join(str(APPDATA_DIR), ssl_name),
            ]
            if sys.platform == "win32":
                ssl_candidates.extend([
                    r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
                    r"C:\Program Files (x86)\OpenSSL-Win32\bin\openssl.exe",
                    r"C:\Program Files\Git\usr\bin\openssl.exe",
                ])
            elif sys.platform == "darwin":
                ssl_candidates.extend(["/opt/homebrew/bin/openssl", "/usr/local/bin/openssl", "/usr/bin/openssl"])
            else:
                ssl_candidates.extend(["/usr/bin/openssl", "/usr/local/bin/openssl"])

            for c in ssl_candidates:
                if c and os.path.isfile(c):
                    ssl_path = c
                    break

        if aria_path:
            abs_aria = os.path.abspath(aria_path)
            self.config["aria2c_path"] = abs_aria
            if hasattr(self, "input_aria2c"):
                self.input_aria2c.setText(abs_aria)
        if ssl_path:
            abs_ssl = os.path.abspath(ssl_path)
            self.config["openssl_path"] = abs_ssl
            if hasattr(self, "input_openssl"):
                self.input_openssl.setText(abs_ssl)

        self.trigger_auto_save()

        if not aria_path or not ssl_path:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("btn_auto_detect"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setTextFormat(Qt.TextFormat.RichText)
            if not aria_path and not ssl_path:
                msg_box.setText(self.T("msg_both_missing"))
            elif not aria_path:
                msg_box.setText(self.T("msg_aria_only_missing"))
            elif not ssl_path:
                msg_box.setText(self.T("msg_ssl_only_missing"))
            msg_box.exec()

    def reset_config(self):
        dialog = ResetConfirmDialog(self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            is_shift = dialog._is_shift_held_down() or dialog.is_shift_mode

            if is_shift:
                self._is_loading_ui = True
                if hasattr(self, "chk_auto_save"):
                    self.chk_auto_save.blockSignals(True)
                    self.chk_auto_save.setChecked(False)

                try:
                    from . import config
                    config._HARD_RESET_LOCK = True
                except Exception:
                    pass

                if hasattr(self, "config") and isinstance(self.config, dict):
                    self.config.clear()
                    self.config.update({
                        "version": APP_VERSION,
                        "console_mode": "WELCOME",
                        "first_launch": True,
                        "theme": "auto",
                        "accent_color": ""
                    })

                for file_to_remove in [CONFIG_FILE, EULA_FILE]:
                    try:
                        if isinstance(file_to_remove, Path) and file_to_remove.exists():
                            file_to_remove.unlink()
                        elif isinstance(file_to_remove, str) and os.path.exists(file_to_remove):
                            os.remove(file_to_remove)
                    except Exception:
                        pass

                self._spawn_new_instance_and_quit(save_before_exit=False)
            else:
                self._is_loading_ui = True

                for key in list(self.config.keys()):
                    key_lower = key.lower()
                    if any(kw in key_lower for kw in _PATH_KEYWORDS):
                        self.config[key] = ""

                self.config["accent_color"] = ""
                self.pending_color = ""

                inputs = [
                    "input_hactool", "input_keys", "input_prodinfo",
                    "input_aria2c", "input_openssl", "input_output",
                    "input_otp", "input_boot9"
                ]
                for inp_attr in inputs:
                    if hasattr(self, inp_attr):
                        inp_widget = getattr(self, inp_attr)
                        inp_widget.blockSignals(True)
                        inp_widget.clear()
                        inp_widget.blockSignals(False)

                self._is_loading_ui = False

                self.update_config_from_ui()
                self.commit_save_to_disk()
                if hasattr(self, "apply_console_theme_colors"):
                    self.apply_console_theme_colors()
                if hasattr(self, "apply_visual_settings"):
                    self.apply_visual_settings()

    def trigger_auto_save(self, *args):
        if getattr(self, "_is_loading_ui", True):
            return

        self.update_config_from_ui()

        if not hasattr(self, "save_timer"):
            self.save_timer = QTimer(self)
            self.save_timer.setSingleShot(True)
            self.save_timer.timeout.connect(self.commit_save_to_disk)

        self.save_timer.start(600)

    def _get_fallback_language(self):
        try:
            from .Languages.locales import STRINGS
            if not STRINGS:
                return "EN"

            sys_lang = QLocale.system().name()[:2].upper()
            if sys_lang in STRINGS:
                return sys_lang
            return next(iter(STRINGS.keys()))
        except Exception:
            return "EN"

    def update_config_from_ui(self):
        prev_lang = self.config.get("lang")
        prev_resize = self.config.get("allow_resize", False)
        prev_theme = self.config.get("theme", "auto")
        prev_accent = self.config.get("accent_color", "")

        out_dir = self.input_output.text().strip() if hasattr(self, "input_output") else self.config.get("output_dir", "")

        if hasattr(self, "input_hactool"):
            self.config["hactool"] = self.input_hactool.text().strip()
        if hasattr(self, "input_keys"):
            self.config["prod_keys"] = self.input_keys.text().strip()
        if hasattr(self, "input_prodinfo"):
            self.config["prodinfo"] = self.input_prodinfo.text().strip()
        if hasattr(self, "input_otp"):
            self.config["otp_path"] = self.input_otp.text().strip()
        if hasattr(self, "input_boot9"):
            self.config["boot9_path"] = self.input_boot9.text().strip()

        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).lower()
        self.config[f"output_dir_{mode}"] = out_dir
        self.config["output_dir"] = out_dir

        is_adv = self.chk_adv_mode.isChecked() if hasattr(self, "chk_adv_mode") else self.config.get("advanced_mode", False)
        self.config["advanced_mode"] = is_adv

        if not is_adv:
            self._is_loading_ui = True
            for attr in (
                "chk_adv_logs", "chk_use_aria2c", "chk_resize",
                "chk_exfat", "chk_hide_warn", "chk_cafe_extract",
                "chk_cemu_layout", "chk_build_nsp"
            ):
                if hasattr(self, attr):
                    getattr(self, attr).setChecked(False)
            self._is_loading_ui = False

            self.config["advanced_logs"] = False
            self.config["use_aria2c"] = False
            self.config["allow_resize"] = False
            self.config["exclude_exfat"] = False
            self.config["hide_privacy_warning"] = False
            self.config["cafe_extract"] = False
            self.config["cafe_cemu_layout"] = False
            self.config["build_nsp"] = False
        else:
            self.config["advanced_logs"] = self.chk_adv_logs.isChecked() if hasattr(self, "chk_adv_logs") else self.config.get("advanced_logs", False)
            self.config["use_aria2c"] = self.chk_use_aria2c.isChecked() if hasattr(self, "chk_use_aria2c") else self.config.get("use_aria2c", False)
            self.config["allow_resize"] = self.chk_resize.isChecked() if hasattr(self, "chk_resize") else self.config.get("allow_resize", False)
            self.config["exclude_exfat"] = self.chk_exfat.isChecked() if hasattr(self, "chk_exfat") else self.config.get("exclude_exfat", False)
            self.config["hide_privacy_warning"] = self.chk_hide_warn.isChecked() if hasattr(self, "chk_hide_warn") else self.config.get("hide_privacy_warning", False)
            if hasattr(self, "chk_cafe_extract"):
                self.config["cafe_extract"] = self.chk_cafe_extract.isChecked()
            if hasattr(self, "chk_cemu_layout"):
                self.config["cafe_cemu_layout"] = self.chk_cemu_layout.isChecked()
            if hasattr(self, "chk_build_nsp"):
                self.config["build_nsp"] = self.chk_build_nsp.isChecked()

        if hasattr(self, "input_aria2c"):
            self.config["aria2c_path"] = self.input_aria2c.text().strip()
        if hasattr(self, "input_openssl"):
            self.config["openssl_path"] = self.input_openssl.text().strip()

        if hasattr(self, "combo_lang"):
            selected_lang = self.combo_lang.currentData()
            self.config["lang"] = selected_lang if selected_lang else self._get_fallback_language()

        raw_accent = str(getattr(self, "pending_color", self.config.get("accent_color", ""))).strip()
        self.config["accent_color"] = "" if raw_accent.lower() in _DEFAULT_COLORS else raw_accent

        if hasattr(self, "chk_rainbow"):
            self.config["rainbow_mode"] = self.chk_rainbow.isChecked()
        if hasattr(self, "slider_speed"):
            self.config["rainbow_speed"] = self.slider_speed.value()

        if hasattr(self, "combo_theme"):
            themes = ["auto", "light", "dark", "oled"]
            idx = self.combo_theme.currentIndex()
            if 0 <= idx < len(themes):
                self.config["theme"] = themes[idx]

        if hasattr(self, "rainbow_target_cbs"):
            self.config["rainbow_targets"] = {k: cb.isChecked() for k, cb in self.rainbow_target_cbs.items()}

        if not getattr(self, "_is_loading_ui", True):
            if self.config.get("lang") != prev_lang and hasattr(self, "retranslate_ui"):
                self.retranslate_ui()
            if (
                self.config.get("theme", "auto") != prev_theme
                or self.config.get("accent_color", "") != prev_accent
            ) and hasattr(self, "apply_visual_settings"):
                self.apply_visual_settings()
            if hasattr(self, "update_dl_mode_label"):
                self.update_dl_mode_label()
            if hasattr(self, "lbl_sys_info"):
                self.lbl_sys_info.setVisible(self.config.get("advanced_logs", False))
            if self.config.get("allow_resize", False) != prev_resize and hasattr(self, "apply_window_constraints"):
                self.apply_window_constraints()

    def commit_save_to_disk(self):
        if not hasattr(self, "config") or not isinstance(self.config, dict):
            return
        save_config(self.config)
