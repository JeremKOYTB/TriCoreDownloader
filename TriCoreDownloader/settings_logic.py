import os
import sys
import ctypes
import random
import subprocess
from shutil import which
from pathlib import Path

from PyQt6.QtWidgets import (
    QMessageBox, QFileDialog, QDialog, QVBoxLayout, QLabel, 
    QCheckBox, QHBoxLayout, QPushButton, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QLocale, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QGuiApplication

from .config import CONFIG_FILE, EULA_FILE, save_config
from .custom_widgets import AutoCloseDialog

_DEFAULT_COLORS = {"#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""}
_PATH_KEYWORDS = ("path", "dir", "keys", "prodinfo", "hactool")


class ResetConfirmDialog(QDialog):
    """Fenêtre de confirmation avec fondu d'apparition et détection Shift matérielle sécurisée."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_obj = parent
        self.is_shift_mode = False

        title = self.parent_obj.T("msg_reset_title") if hasattr(self.parent_obj, "T") else "Réinitialisation"
        self.setWindowTitle(title)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        msg_text = self.parent_obj.T("msg_reset_warn") if hasattr(self.parent_obj, "T") else ""
        self.lbl_msg = QLabel(msg_text)
        self.lbl_msg.setWordWrap(True)
        layout.addWidget(self.lbl_msg)

        yes_text = self.parent_obj.T("btn_yes") if hasattr(self.parent_obj, "T") else "Oui"
        no_text = self.parent_obj.T("btn_no") if hasattr(self.parent_obj, "T") else "Non"

        self.btn_yes = QPushButton(yes_text)
        self.btn_no = QPushButton(no_text)
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

        # Timer dédié à la lecture de la touche Shift
        self.shift_timer = QTimer(self)
        self.shift_timer.setInterval(30)
        self.shift_timer.timeout.connect(self._check_shift_state)

    def showEvent(self, event):
        super().showEvent(event)

        # 1. Déclenchement du son de réinitialisation
        audio_obj = getattr(self.parent_obj, "audio", getattr(self.parent_obj, "audio_manager", None))
        if audio_obj and hasattr(audio_obj, "play_reset_sound"):
            audio_obj.play_reset_sound()

        # 2. Démarrage de la surveillance Shift
        self.shift_timer.start()

        # 3. Animation de fondu fluide à l'ouverture
        self.setWindowOpacity(0.0)
        self.anim_opacity = QPropertyAnimation(self, b"windowOpacity")
        self.anim_opacity.setDuration(200)
        self.anim_opacity.setStartValue(0.0)
        self.anim_opacity.setEndValue(1.0)
        self.anim_opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_opacity.start()

        self._check_shift_state()

    def done(self, result):
        # Arrêt du timer avant la destruction C++ de l'objet pour éviter tout crash
        if hasattr(self, "shift_timer") and self.shift_timer.isActive():
            self.shift_timer.stop()
        super().done(result)

    def _is_shift_held_down(self) -> bool:
        """Détection matérielle basse couche de la touche Shift."""
        if sys.platform == "win32":
            try:
                # VK_SHIFT = 0x10
                return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
            except Exception:
                pass
        return bool(QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

    def _check_shift_state(self):
        is_shift = self._is_shift_held_down()
        if is_shift != self.is_shift_mode:
            self.is_shift_mode = is_shift
            if is_shift:
                self.btn_yes.setStyleSheet(self.shift_yes_style)
            else:
                self.btn_yes.setStyleSheet(self.normal_yes_style)
            
            self.btn_yes.style().unpolish(self.btn_yes)
            self.btn_yes.style().polish(self.btn_yes)
            self.btn_yes.update()


class SettingsMixin:
    def restart_app(self):
        self._is_restarting = True
        
        if hasattr(self, "save_timer") and self.save_timer.isActive():
            self.save_timer.stop()
        if hasattr(self, "rainbow_timer") and self.rainbow_timer.isActive():
            self.rainbow_timer.stop()
        if hasattr(self, "_sigint_timer") and self._sigint_timer.isActive():
            self._sigint_timer.stop()
            
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
            except Exception:
                pass

        try:
            self.commit_save_to_disk()
        except Exception:
            pass

        if hasattr(self, "perform_security_cleanup"):
            self.perform_security_cleanup()

        if hasattr(self, "app_lock") and self.app_lock.isLocked():
            try:
                self.app_lock.unlock()
            except Exception:
                pass

        script_path = os.path.abspath(sys.argv[0])
        args = [sys.executable, script_path] + sys.argv[1:]

        kwargs = {"close_fds": True, "cwd": os.path.dirname(script_path) or os.getcwd()}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True

        try:
            subprocess.Popen(args, **kwargs)
        except Exception:
            return

        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

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
            if hasattr(self, "chk_adv_logs"): self.chk_adv_logs.setChecked(False)
            if hasattr(self, "chk_use_aria2c"): self.chk_use_aria2c.setChecked(False)
            if hasattr(self, "chk_resize"): self.chk_resize.setChecked(False)
            if hasattr(self, "chk_exfat"): self.chk_exfat.setChecked(False)
            if hasattr(self, "chk_hide_warn"): self.chk_hide_warn.setChecked(False)
            if hasattr(self, "chk_cafe_extract"): self.chk_cafe_extract.setChecked(False)
            if hasattr(self, "chk_cemu_layout"): self.chk_cemu_layout.setChecked(False)
            self._is_loading_ui = False
            
            self.on_adv_logs_toggle(False)
            self.on_aria_toggle(False)
            
        self.trigger_auto_save()

    def suggest_export_folder(self):
        if not hasattr(self, "input_output"):
            return
            
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX"))
        
        folders = {
            "NX": ["NX_Firmware", "NX_Updates", "NX", "Switch1", "Daybreak", "NCAs", "NX_CDN", "NX_Stock_FW"],
            "CAFE": ["Cafe_Firmware", "Cafe_Updates", "Cafe", "WiiU", "ISFSHax", "wafel_install", "CAFE_NUS", "CAFE_Stock_FW"],
            "CTR": ["CTR_Firmware", "CTR_Updates", "CTR", "3DS", "sysUpdater", "CIAs", "CTR_NUS", "CTR_Stock_FW"]
        }
        
        names = folders.get(mode, ["Firmwares"])
        current_path = self.input_output.text().strip()
        candidates = [os.path.join(base_dir, name) for name in names if os.path.join(base_dir, name) != current_path]
        suggested_path = random.choice(candidates) if candidates else os.path.join(base_dir, names[0])
                
        self.input_output.setText(suggested_path)
        self.trigger_auto_save()

    def on_output_dir_changed(self, text):
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).lower()
        self.config[f"output_dir_{mode}"] = text
        self.config["output_dir"] = text

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
                    QMessageBox.critical(self, self.T("msg_error_title"), f"{self.T('msg_folder_err')}\n{e}")
                    return False
            else: 
                return False 
        return True

    def on_adv_logs_toggle(self, checked):
        if not checked:
            self._is_loading_ui = True
            if hasattr(self, "chk_hide_warn"): self.chk_hide_warn.setChecked(False)
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
                if hasattr(self, "chk_hide_warn"): self.chk_hide_warn.setChecked(False)
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
                if hasattr(self, "chk_exfat"): self.chk_exfat.setChecked(False)
                self._is_loading_ui = False

    def browse_file(self, line_edit, expected_name):
        while True:
            file_path, _ = QFileDialog.getOpenFileName(self, self.T("dialog_select_file"))
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
                    continue
                
            line_edit.setText(os.path.normpath(file_path))
            break

    def browse_folder(self, line_edit):
        folder_path = QFileDialog.getExistingDirectory(self, self.T("dialog_select_folder"))
        if folder_path: 
            line_edit.setText(os.path.normpath(folder_path))

    def auto_detect_aria(self):
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        aria_path = which("aria2c")
        
        if not aria_path and os.name == "nt":
            local_aria = os.path.join(script_dir, "aria2c.exe")
            if os.path.isfile(local_aria):
                aria_path = local_aria
                
        ssl_path = which("openssl")
        if not ssl_path and os.name == "nt":
            local_ssl = os.path.join(script_dir, "openssl.exe")
            system_ssl = r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe"
            
            if os.path.isfile(local_ssl):
                ssl_path = local_ssl
            elif os.path.isfile(system_ssl):
                ssl_path = system_ssl
        
        if aria_path and hasattr(self, "input_aria2c"): 
            self.input_aria2c.setText(os.path.abspath(aria_path))
        if ssl_path and hasattr(self, "input_openssl"): 
            self.input_openssl.setText(os.path.abspath(ssl_path))
            
        self.trigger_auto_save()
        
        if not aria_path or not ssl_path:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("btn_auto_detect"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setTextFormat(Qt.TextFormat.RichText)
            if not aria_path and not ssl_path: msg_box.setText(self.T("msg_both_missing"))
            elif not aria_path: msg_box.setText(self.T("msg_aria_only_missing"))
            elif not ssl_path: msg_box.setText(self.T("msg_ssl_only_missing"))
            msg_box.exec()

    def reset_config(self):
        dialog = ResetConfirmDialog(self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            is_shift = dialog._is_shift_held_down() or dialog.is_shift_mode

            audio_obj = getattr(self, "audio", getattr(self, "audio_manager", None))

            if is_shift:
                self._is_restarting = True
                
                if getattr(self, "save_timer", None) and self.save_timer.isActive():
                    self.save_timer.stop()
                if getattr(self, "rainbow_timer", None) and self.rainbow_timer.isActive():
                    self.rainbow_timer.stop()
                if getattr(self, "_sigint_timer", None) and self._sigint_timer.isActive():
                    self._sigint_timer.stop()
                
                if audio_obj:
                    try:
                        if hasattr(audio_obj, "cleanup"):
                            audio_obj.cleanup()
                        elif hasattr(audio_obj, "stop_all"):
                            audio_obj.stop_all()
                    except Exception:
                        pass
                
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
                        "version": "1.0.0",
                        "console_mode": "WELCOME",
                        "first_launch": True,
                        "theme": "auto",
                        "accent_color": ""
                    })

                if getattr(self, "worker", None) and self.worker.isRunning(): 
                    try: self.worker.stop()
                    except Exception: pass
                
                for file_to_remove in [CONFIG_FILE, EULA_FILE]:
                    try:
                        if isinstance(file_to_remove, Path) and file_to_remove.exists():
                            file_to_remove.unlink()
                        elif isinstance(file_to_remove, str) and os.path.exists(file_to_remove):
                            os.remove(file_to_remove)
                    except Exception:
                        pass
                        
                if hasattr(self, "perform_security_cleanup"):
                    self.perform_security_cleanup()

                if hasattr(self, "app_lock") and self.app_lock.isLocked():
                    try:
                        self.app_lock.unlock()
                    except Exception:
                        pass

                script_path = os.path.abspath(sys.argv[0])
                args = [sys.executable, script_path] + sys.argv[1:]
                kwargs = {"close_fds": True, "cwd": os.path.dirname(script_path) or os.getcwd()}
                if sys.platform == "win32":
                    kwargs["creationflags"] = 0x00000008 | 0x00000200
                else:
                    kwargs["start_new_session"] = True
                subprocess.Popen(args, **kwargs)
                self.close()
                app = QApplication.instance()
                if app:
                    app.quit()
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
                        getattr(self, inp_attr).clear()
                
                self._is_loading_ui = False
                
                self.update_config_from_ui()
                self.commit_save_to_disk()
                if hasattr(self, "apply_console_theme_colors"):
                    self.apply_console_theme_colors()

    def trigger_auto_save(self, *args):
        if getattr(self, "_is_loading_ui", True): 
            return
        
        self.update_config_from_ui()
        
        if not hasattr(self, "save_timer"):
            self.save_timer = QTimer(self)
            self.save_timer.setSingleShot(True)
            self.save_timer.timeout.connect(self.commit_save_to_disk)
        
        self.save_timer.start(20000)

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
        out_dir = self.input_output.text().strip() if hasattr(self, "input_output") else self.config.get("output_dir", "")
        
        if hasattr(self, "input_hactool"): self.config["hactool"] = self.input_hactool.text().strip()
        if hasattr(self, "input_keys"): self.config["prod_keys"] = self.input_keys.text().strip()
        if hasattr(self, "input_prodinfo"): self.config["prodinfo"] = self.input_prodinfo.text().strip()
        if hasattr(self, "input_otp"): self.config["otp_path"] = self.input_otp.text().strip()
            
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).lower()
        self.config[f"output_dir_{mode}"] = out_dir
        self.config["output_dir"] = out_dir

        is_adv = self.chk_adv_mode.isChecked() if hasattr(self, "chk_adv_mode") else self.config.get("advanced_mode", False)
        self.config["advanced_mode"] = is_adv
        
        if not is_adv:
            self._is_loading_ui = True
            if hasattr(self, "chk_adv_logs"): self.chk_adv_logs.setChecked(False)
            if hasattr(self, "chk_use_aria2c"): self.chk_use_aria2c.setChecked(False)
            if hasattr(self, "chk_resize"): self.chk_resize.setChecked(False)
            if hasattr(self, "chk_exfat"): self.chk_exfat.setChecked(False)
            if hasattr(self, "chk_hide_warn"): self.chk_hide_warn.setChecked(False)
            if hasattr(self, "chk_cafe_extract"): self.chk_cafe_extract.setChecked(False)
            if hasattr(self, "chk_cemu_layout"): self.chk_cemu_layout.setChecked(False)
            self._is_loading_ui = False
            
            self.config["advanced_logs"] = False
            self.config["use_aria2c"] = False
            self.config["allow_resize"] = False
            self.config["exclude_exfat"] = False
            self.config["hide_privacy_warning"] = False
            self.config["cafe_extract"] = False
            self.config["cafe_cemu_layout"] = False
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

        if hasattr(self, "input_aria2c"): self.config["aria2c_path"] = self.input_aria2c.text().strip()
        if hasattr(self, "input_openssl"): self.config["openssl_path"] = self.input_openssl.text().strip()
        
        if hasattr(self, "combo_lang"):
            selected_lang = self.combo_lang.currentData()
            self.config["lang"] = selected_lang if selected_lang else self._get_fallback_language()
        
        raw_accent = str(getattr(self, "pending_color", self.config.get("accent_color", ""))).strip()
        self.config["accent_color"] = "" if raw_accent.lower() in _DEFAULT_COLORS else raw_accent

        if hasattr(self, "chk_rainbow"): self.config["rainbow_mode"] = self.chk_rainbow.isChecked()
        if hasattr(self, "slider_speed"): self.config["rainbow_speed"] = self.slider_speed.value()
        
        if hasattr(self, "combo_theme"):
            themes = ["auto", "light", "dark", "oled"]
            idx = self.combo_theme.currentIndex()
            if 0 <= idx < len(themes):
                self.config["theme"] = themes[idx]

        if hasattr(self, "rainbow_target_cbs"):
            self.config["rainbow_targets"] = {k: cb.isChecked() for k, cb in self.rainbow_target_cbs.items()}

        if not getattr(self, "_is_loading_ui", True):
            if hasattr(self, "retranslate_ui"): self.retranslate_ui()
            if hasattr(self, "apply_visual_settings"): self.apply_visual_settings()
            if hasattr(self, "update_dl_mode_label"): self.update_dl_mode_label()
            if hasattr(self, "lbl_sys_info"): self.lbl_sys_info.setVisible(self.config.get("advanced_logs", False))
            if hasattr(self, "apply_window_constraints"): self.apply_window_constraints()

    def commit_save_to_disk(self):
        if not hasattr(self, "config") or not isinstance(self.config, dict):
            return
        out_dir = self.config.get("output_dir", "")
        if out_dir and not os.path.exists(out_dir):
            self.verify_and_create_export_folder(out_dir)
            
        save_config(self.config)