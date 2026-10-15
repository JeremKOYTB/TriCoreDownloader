import os
import sys
import signal
import datetime
import subprocess
import atexit
import json
import re
import shutil
import urllib.request
import urllib.error
import time
import ssl
import platform

ssl._create_default_https_context = ssl._create_unverified_context

from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QWidget, QGraphicsOpacityEffect,
    QDialog, QComboBox, QHBoxLayout, QVBoxLayout, QSlider, QLabel,
    QCheckBox, QPushButton, QGridLayout, QTextEdit
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QByteArray,
    QSize, QLockFile, QDir, QThread, pyqtSignal, QAbstractAnimation
)
from PyQt6.QtGui import QIcon, QPixmap, QCursor, QTextOption, QPainter, QColor

from .config import EULA_FILE, APPDATA_DIR, save_config, APP_VERSION
from .custom_widgets import EulaDialog
from .app_utils_dialogs import exception_hook, ComboScrollFilter
from .ui_core_layout import FirmwareAppUI
from .audio_manager import AudioManager
from .logos import (
    NX_LOGO_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_BLACK_SVG,
    CTR_LOGO_CLEAN_SVG, CAFE_LOGO_SVG, VOL_MUTE_SVG,
    VOL_LOW_SVG, VOL_HIGH_SVG, RESTART_SVG, TCD_MAIN_LOGO
)
from .app_downloader import DownloadManagerMixin, _urlopen_safe
from .app_ui_interactions import UiInteractionsMixin, get_mac_app_bundle_path

sys.excepthook = exception_hook

RE_DIGITS = re.compile(r"\d+")
RE_MARKDOWN_NL = re.compile(r"(?<!\n)\n(?!\n)")


def _is_arm64_arch_string(arch_str: str) -> bool:
    clean = (arch_str or "").strip().lower()
    return clean.startswith("arm64") or clean.startswith("aarch64")


def _is_macos_apple_silicon() -> bool:
    machine = (platform.machine() or "").strip().lower()
    if _is_arm64_arch_string(machine):
        return True

    if hasattr(os, "uname"):
        try:
            if _is_arm64_arch_string(os.uname().machine):
                return True
        except Exception:
            pass

    if sys.platform == "darwin":
        for sysctl_key in ("hw.optional.arm64", "sysctl.proc_translated"):
            try:
                res = subprocess.run(
                    ["sysctl", "-n", sysctl_key],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1,
                )
                if res.stdout.strip() == "1":
                    return True
            except Exception:
                pass

        try:
            res = subprocess.run(
                ["uname", "-m"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1,
            )
            if _is_arm64_arch_string(res.stdout):
                return True
        except Exception:
            pass

    return False


def find_compatible_asset(release, is_frozen=False):
    if not isinstance(release, dict):
        return None, False

    if release.get("is_main_branch_node", False):
        if is_frozen:
            return None, False
        return release.get("zipball_url"), False

    assets = release.get("assets", [])

    if not is_frozen:
        os_keywords = (
            "win", "windows", "mac", "macos", "darwin", "linux",
            "appimage", ".exe", ".dmg", "x64", "x86_64", "arm64", "aarch64", "intel", "apple", "silicon"
        )
        for asset in assets:
            name = asset.get("name", "").lower()
            if name in ("tricoredownloader.zip", "tricoredownloader.7z"):
                return asset, False
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith((".zip", ".7z")):
                if not any(kw in name for kw in os_keywords):
                    return asset, False
        return None, False

    sys_plat = sys.platform.lower()

    if sys_plat == "darwin":
        is_arm = _is_macos_apple_silicon()
        exact_target = "tricoredownloader_macos_arm64.dmg" if is_arm else "tricoredownloader_macos_x64.dmg"
        for asset in assets:
            if asset.get("name", "").lower() == exact_target:
                return asset, False
        for asset in assets:
            name = asset.get("name", "").lower()
            if not name.endswith(".dmg"):
                continue
            if is_arm and ("arm64" in name or "aarch64" in name or "silicon" in name or "apple" in name):
                return asset, False
            if not is_arm and ("x64" in name or "x86_64" in name or "intel" in name):
                return asset, False
        return None, False

    elif sys_plat == "win32":
        for asset in assets:
            if asset.get("name", "").lower() == "tricoredownloader_windows_x64.exe":
                return asset, True
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".exe") and "updater" not in name:
                return asset, True
        return None, False

    elif "linux" in sys_plat:
        for asset in assets:
            if asset.get("name", "").lower() == "tricoredownloader_linux_x86_64.appimage":
                return asset, True
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".appimage") and "updater" not in name:
                return asset, True
        return None, False

    return None, False


class FirmwareApp(DownloadManagerMixin, FirmwareAppUI, UiInteractionsMixin):
    sigint_caught = pyqtSignal()

    def __init__(self, config_data, is_corrupted, tampered_rainbow):
        self.app_version = APP_VERSION

        appdata_dir = str(APPDATA_DIR)
        os.makedirs(appdata_dir, exist_ok=True)

        lock_path = Path(appdata_dir) / "TriCoreDownloader.lock"
        self.app_lock = QLockFile(str(lock_path))
        self.app_lock.setStaleLockTime(2000)

        if not self.app_lock.tryLock(100):
            self.app_lock.removeStaleLockFile()
            if not self.app_lock.tryLock(100):
                if sys.__stderr__ is not None:
                    print("[INFO] Une autre instance de TriCoreDownloader est déjà en cours d'exécution.", file=sys.__stderr__)
                sys.exit(0)

        super().__init__(config_data)

        if sys.platform.startswith("linux"):
            self.setWindowIcon(self.get_app_icon())
            if QApplication.instance():
                QApplication.instance().setWindowIcon(self.get_app_icon())
        elif sys.platform == "win32":
            self.setWindowIcon(self.get_app_icon())

        self.keys_dir = os.path.join(appdata_dir, "temp_keys")

        self.perform_security_cleanup()

        self.is_rainbow_active = bool(self.config.get("rainbow_mode", False) or tampered_rainbow)

        self.audio = AudioManager(self, self.config)
        if not self.config.get("first_launch", True):
            self.audio.play_tricore_boot()

        if hasattr(self, "console_selector") and self.console_selector.parentWidget():
            parent_layout = self.console_selector.parentWidget().layout()
            if parent_layout:
                parent_layout.setAlignment(self.console_selector, Qt.AlignmentFlag.AlignVCenter)

        try:
            self.console_selector.currentIndexChanged.disconnect()
        except Exception:
            pass
        self.console_selector.currentIndexChanged.connect(self.switch_console_mode)

        try:
            self.nav_group.idClicked.disconnect()
        except Exception:
            pass
        self.nav_group.idClicked.connect(self.switch_tab_animated)

        try:
            self.btn_tab_restart.clicked.disconnect()
        except Exception:
            pass
        self.btn_tab_restart.clicked.connect(self.prompt_restart)

        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.updater_spinner_timer = QTimer(self)
        self.updater_spinner_timer.timeout.connect(self.update_update_spinner)
        self.is_auto_check = False
        self._is_checking_update = False

        if hasattr(self, "console_selector") and self.console_selector.parentWidget():
            header_layout = self.console_selector.parentWidget().layout()
            if header_layout:
                self.update_container = QWidget()
                self.update_right_layout = QHBoxLayout(self.update_container)
                self.update_right_layout.setContentsMargins(0, 0, 0, 0)
                self.update_right_layout.setSpacing(6)

                self.lbl_update_spinner = QLabel("")
                self.lbl_update_spinner.setMinimumWidth(15)
                self.lbl_update_spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)

                self.opacity_effect = QGraphicsOpacityEffect(self.lbl_update_spinner)
                self.lbl_update_spinner.setGraphicsEffect(self.opacity_effect)

                self.pulse_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
                self.pulse_anim.setStartValue(1.0)
                self.pulse_anim.setKeyValueAt(0.5, 0.3)
                self.pulse_anim.setEndValue(1.0)
                self.pulse_anim.setLoopCount(-1)
                self.pulse_anim.setDuration(2000)

                self.btn_update = QPushButton(self.T("btn_update"))
                self.btn_update.setObjectName("btnHeader")
                self.btn_update.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                
                def _on_header_update_clicked():
                    from .custom_widgets import launch_updater
                    try:
                        launch_updater(self, getattr(self, "T", None))
                    except TypeError:
                        try:
                            launch_updater(self)
                        except TypeError:
                            launch_updater()
                
                self.btn_update.clicked.connect(_on_header_update_clicked)

                self.update_right_layout.addWidget(self.lbl_update_spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
                self.update_right_layout.addWidget(self.btn_update, alignment=Qt.AlignmentFlag.AlignVCenter)

                if isinstance(header_layout, QGridLayout):
                    header_layout.addWidget(self.update_container, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    header_layout.addWidget(self.update_container)

        if hasattr(self, "radio_mlc"):
            self.radio_mlc.toggled.connect(self.on_cafe_options_changed)
            self.radio_slc.toggled.connect(self.on_cafe_options_changed)
            self.radio_both.toggled.connect(self.on_cafe_options_changed)
            self.radio_eur.toggled.connect(self.on_cafe_options_changed)
            self.radio_usa.toggled.connect(self.on_cafe_options_changed)
            self.radio_jpn.toggled.connect(self.on_cafe_options_changed)

        if hasattr(self, "radio_ctr_eur"):
            self.radio_ctr_eur.toggled.connect(self.on_ctr_options_changed)
            self.radio_ctr_usa.toggled.connect(self.on_ctr_options_changed)
            self.radio_ctr_jpn.toggled.connect(self.on_ctr_options_changed)
            self.radio_ctr_aus.toggled.connect(self.on_ctr_options_changed)
            self.radio_ctr_kor.toggled.connect(self.on_ctr_options_changed)
            self.radio_ctr_chn.toggled.connect(self.on_ctr_options_changed)
            self.radio_ctr_twn.toggled.connect(self.on_ctr_options_changed)
            self.radio_old_3ds.toggled.connect(self.on_ctr_options_changed)
            self.radio_new_3ds.toggled.connect(self.on_ctr_options_changed)

        if hasattr(self, "input_output"):
            self.input_output.textChanged.connect(self.on_output_dir_changed)
            current_out = self.config.get(f"output_dir_{self.current_console.lower()}", "")
            self.input_output.setText(current_out)
            paths_parent = self.input_output.parentWidget()
            if paths_parent and paths_parent.layout():
                paths_parent.layout().setAlignment(Qt.AlignmentFlag.AlignTop)

        if hasattr(self, "btn_clear_console"):
            self.btn_clear_console.clicked.connect(self.clear_console_output)

            self.chk_unlimited_console = QCheckBox(self.T("chk_unlimited_console"))
            self.chk_unlimited_console.setToolTip(self.T("tt_unlimited"))
            self.chk_unlimited_console.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

            if hasattr(self, "console") and self.console.parentWidget() and self.console.parentWidget().layout():
                parent_layout = self.console.parentWidget().layout()
                parent_layout.addWidget(self.chk_unlimited_console)
                parent_layout.setAlignment(self.chk_unlimited_console, Qt.AlignmentFlag.AlignRight)

            self.chk_unlimited_console.toggled.connect(self.on_unlimited_console_toggled)
            is_unlimited = self.config.get("unlimited_console", False)
            self.chk_unlimited_console.setChecked(is_unlimited)

        if hasattr(self, "chk_adv_mode"):
            self.chk_adv_mode.stateChanged.connect(self.update_dynamic_ui)

        if hasattr(self, "radio_manual") and hasattr(self, "radio_latest"):
            self.radio_manual.toggled.connect(self.update_dynamic_ui)
            self.radio_latest.toggled.connect(self.update_dynamic_ui)

        if hasattr(self, "chk_build_nsp"):
            self.chk_build_nsp.clicked.connect(self._handle_nsp_toggle)

        if hasattr(self, "console"):
            limit = 0 if self.config.get("unlimited_console", False) else 1000
            self.console.setMaximumBlockCount(limit)

        self.apply_window_constraints()
        self._is_loading_ui = False
        if hasattr(self, "apply_visual_settings"):
            self.apply_visual_settings()
        self.apply_console_theme_colors()
        self.refresh_dynamic_icons()

        self.combo_scroll_filter = ComboScrollFilter(self)
        for combo in self.findChildren(QComboBox):
            combo.installEventFilter(self.combo_scroll_filter)

        self.center_on_screen()
        self.show()

        def safe_cleanup():
            try:
                if hasattr(self, "config") and not getattr(self, "_is_restarting", False):
                    save_config(self.config)
                if hasattr(self, "perform_security_cleanup") and not getattr(self, "_is_restarting", False):
                    self.perform_security_cleanup()
                if hasattr(self, "app_lock") and self.app_lock.isLocked():
                    self.app_lock.unlock()
            except Exception:
                pass

        atexit.register(safe_cleanup)

        def crash_handler(exc_type, exc_value, exc_traceback):
            try:
                if hasattr(self, "config") and not getattr(self, "_is_restarting", False):
                    save_config(self.config)
                if hasattr(self, "perform_security_cleanup") and not getattr(self, "_is_restarting", False):
                    self.perform_security_cleanup()
                if hasattr(self, "app_lock") and self.app_lock.isLocked():
                    self.app_lock.unlock()
                if hasattr(self, "handle_fatal_crash"):
                    self.handle_fatal_crash(exc_type, exc_value, exc_traceback)
            except Exception:
                pass

        sys.excepthook = crash_handler

        self.sigint_caught.connect(self.prompt_ctrl_c_quit)
        signal.signal(signal.SIGINT, self._signal_handler)
        self._sigint_timer = QTimer(self)
        self._sigint_timer.timeout.connect(lambda: None)
        self._sigint_timer.start(200)

        if getattr(self, "startup_anim", None) is not None:
            self.startup_anim.start()

        if is_corrupted:
            save_config(self.config)
            QTimer.singleShot(200, self.show_corruption_warning)
        elif tampered_rainbow:
            save_config(self.config)
            QTimer.singleShot(200, self.show_easter_egg)

        QTimer.singleShot(100, self.show_eula_if_needed)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.config.get("volume", 50)))
        self.volume_slider.setToolTip(self.T("lbl_volume"))

        self.lbl_vol_icon = QLabel()
        self.lbl_vol_icon.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        def update_main_vol_icon(val=None):
            if val is None:
                val = self.volume_slider.value()
            theme_pref = self.config.get("theme", "auto")
            is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
            text_color = "#FFFFFF" if is_dark else "#333333"
            svg_data = VOL_MUTE_SVG if val == 0 else (VOL_LOW_SVG if val < 50 else VOL_HIGH_SVG)

            _, pm_vol = self._get_cached_icon(svg_data, is_dark, text_color)
            if not pm_vol.isNull():
                self.lbl_vol_icon.setPixmap(
                    pm_vol.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )

        self._update_vol_icon = update_main_vol_icon
        self._update_vol_icon(self.volume_slider.value())

        self._pre_mute_main_vol = self.volume_slider.value() if self.volume_slider.value() > 0 else 50

        def toggle_main_mute(event):
            if event.button() == Qt.MouseButton.LeftButton:
                if self.volume_slider.value() > 0:
                    self._pre_mute_main_vol = self.volume_slider.value()
                    self.volume_slider.setValue(0)
                else:
                    self.volume_slider.setValue(self._pre_mute_main_vol if self._pre_mute_main_vol > 0 else 50)
                event.accept()

        self.lbl_vol_icon.mousePressEvent = toggle_main_mute
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        self.volume_slider.sliderReleased.connect(
            lambda: self._play_volume_test_sound() if hasattr(self, "_play_volume_test_sound") else None
        )

        if hasattr(self, "bottom_widget") and self.bottom_widget.layout():
            layout = self.bottom_widget.layout()
            vol_container = QWidget()
            vol_layout = QHBoxLayout(vol_container)
            vol_layout.setContentsMargins(5, 0, 15, 0)
            vol_layout.addWidget(self.lbl_vol_icon)
            vol_layout.addWidget(self.volume_slider)
            if isinstance(layout, QHBoxLayout):
                layout.insertWidget(0, vol_container)
            else:
                layout.addWidget(vol_container)

        self.spinner_timer = QTimer(self)
        self.spinner_timer.timeout.connect(self._step_spinner)
        self.symbol_reset_timer = QTimer(self)
        self.symbol_reset_timer.setSingleShot(True)
        self.symbol_reset_timer.timeout.connect(self.update_dl_mode_label)

        self.update_dynamic_ui()

        if self.config.get("first_launch", True):
            self.header_widget.setVisible(False)
            self.nav_wrapper.setVisible(False)
            self.bottom_widget.setVisible(True)
            self.tabs.setCurrentWidget(self.tab_welcome)

            self.btn_welcome_nx.setText(" " + self.T("console_nx"))
            self.btn_welcome_ctr.setText(" " + self.T("console_ctr"))
            self.btn_welcome_cafe.setText(" " + self.T("console_cafe"))

            self.btn_welcome_nx.setIcon(QIcon(self.get_svg_icon(NX_LOGO_SVG)))
            self.btn_welcome_cafe.setIcon(QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))

            theme_pref = self.config.get("theme", "auto")
            is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG
            self.btn_welcome_ctr.setIcon(QIcon(self.get_svg_icon(ctr_svg)))

            icon_size = QSize(48, 48)
            self.btn_welcome_nx.setIconSize(icon_size)
            self.btn_welcome_ctr.setIconSize(icon_size)
            self.btn_welcome_cafe.setIconSize(icon_size)

            try:
                self.btn_welcome_nx.clicked.disconnect()
                self.btn_welcome_ctr.clicked.disconnect()
                self.btn_welcome_cafe.clicked.disconnect()
            except Exception:
                pass

            self.btn_welcome_nx.clicked.connect(lambda *args: self.finish_welcome_setup(0))
            self.btn_welcome_ctr.clicked.connect(lambda *args: self.finish_welcome_setup(1))
            self.btn_welcome_cafe.clicked.connect(lambda *args: self.finish_welcome_setup(2))

            QTimer.singleShot(500, self.audio.play_welcome)
        else:
            self.tabs.setCurrentIndex(0)
            QTimer.singleShot(500, self.verify_application_version)

    def apply_visual_settings(self):
        try:
            super().apply_visual_settings()
        except AttributeError:
            pass
        if hasattr(self, "refresh_all_icons"):
            self.refresh_all_icons()

    def refresh_dynamic_icons(self):
        try:
            super().refresh_dynamic_icons()
        except AttributeError:
            pass
        if hasattr(self, "refresh_all_icons"):
            self.refresh_all_icons()

    def get_app_icon(self):
        if hasattr(self, "get_svg_icon"):
            return QIcon(self.get_svg_icon(TCD_MAIN_LOGO))
        pix = QPixmap()
        if pix.loadFromData(QByteArray(TCD_MAIN_LOGO)):
            return QIcon(pix)
        return QIcon()

    def _convert_markdown_to_html(self, text):
        if not text:
            return ""
        text_normalized = text.replace("\r\n", "\n")
        return RE_MARKDOWN_NL.sub("\n\n", text_normalized)

    def _get_changelog_from_tag(self, releases, version_tag):
        for rel in releases:
            if rel.get("tag_name", "").strip().lstrip("v") == version_tag:
                return rel.get("body") or ""
        return ""

    def _get_api_error_message(self, json_payload):
        try:
            data = json.loads(json_payload) if isinstance(json_payload, str) else json_payload
            if isinstance(data, dict) and "message" in data:
                return data["message"]
        except Exception:
            pass
        return ""

    def _handle_updater_log(self, text):
        if self.config.get("advanced_logs", False) and sys.__stderr__ is not None:
            try:
                print(text, file=sys.__stderr__)
            except Exception:
                pass

    def start_update_check(self, auto=False, *args):
        if self.current_console == "WELCOME":
            return
        if self._is_checking_update:
            return
        self._is_checking_update = True

        if not sys.platform.startswith("linux"):
            if hasattr(self, "pulse_anim") and self.pulse_anim:
                self.pulse_anim.stop()
            if hasattr(self, "opacity_effect") and self.opacity_effect:
                self.opacity_effect.setOpacity(1.0)

        if hasattr(self, "btn_update"):
            self.btn_update.setEnabled(False)
        if hasattr(self, "lbl_update_spinner"):
            self.lbl_update_spinner.setText("⠋")
            self.updater_spinner_timer.start(100)

        self.is_auto_check = auto
        self.update_thread = UpdateCheckerThread()
        self.update_thread.log_signal.connect(self._handle_updater_log)
        self.update_thread.finished_signal.connect(self.handle_update_check_result)
        self.update_thread.start()

    def handle_update_check_result(self, latest_stable, latest_prerelease, json_payload, is_target_prerelease, error_msg):
        if getattr(self, "_eula_active", False):
            QTimer.singleShot(
                300,
                lambda: self.handle_update_check_result(
                    latest_stable, latest_prerelease, json_payload, is_target_prerelease, error_msg
                )
            )
            return

        self._is_checking_update = False
        is_frozen = getattr(sys, "frozen", False)

        if hasattr(self, "updater_spinner_timer"):
            self.updater_spinner_timer.stop()
        if hasattr(self, "lbl_update_spinner"):
            self.lbl_update_spinner.setText("")
        if hasattr(self, "btn_update"):
            self.btn_update.setEnabled(True)

        api_error = self._get_api_error_message(json_payload) if not error_msg else error_msg

        if api_error:
            is_403 = False
            if "403" in str(api_error) or "rate limit" in str(api_error).lower():
                is_403 = True
            elif json_payload:
                try:
                    data = json.loads(json_payload) if isinstance(json_payload, str) else json_payload
                    if isinstance(data, dict):
                        msg_val = str(data.get("message", "")).lower()
                        if "rate limit" in msg_val or "403" in msg_val:
                            is_403 = True
                except Exception:
                    pass

            err_display = "❌ 403" if is_403 else "❌ "
            if hasattr(self, "lbl_update_spinner"):
                self.lbl_update_spinner.setText(err_display)
                if not sys.platform.startswith("linux"):
                    if hasattr(self, "pulse_anim") and self.pulse_anim:
                        self.pulse_anim.stop()
                    if hasattr(self, "opacity_effect") and self.opacity_effect:
                        self.opacity_effect.setOpacity(1.0)
                QTimer.singleShot(
                    6000,
                    lambda: self.lbl_update_spinner.setText("") if self.lbl_update_spinner.text() == err_display else None
                )

            if not self.is_auto_check:
                msg_box = QMessageBox(self)
                msg_box.setWindowIcon(self.get_app_icon())
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle(self.T("msg_error_title"))
                msg_box.setText(f"{self.T('msg_error_title')} :\n{api_error}")
                msg_box.exec()
            return

        try:
            releases = json.loads(json_payload) if isinstance(json_payload, str) else json_payload
        except Exception:
            releases = []

        stable_rel_obj = None
        prerelease_rel_obj = None
        for rel in releases:
            tag = rel.get("tag_name", "").strip().lstrip("v")
            if rel.get("prerelease", False):
                if not latest_prerelease:
                    latest_prerelease = tag
                if prerelease_rel_obj is None and tag == latest_prerelease:
                    prerelease_rel_obj = rel
            else:
                if not latest_stable:
                    latest_stable = tag
                if stable_rel_obj is None and tag == latest_stable:
                    stable_rel_obj = rel
            if stable_rel_obj and (prerelease_rel_obj or not latest_prerelease):
                break

        if not latest_stable and latest_prerelease:
            latest_stable = latest_prerelease
            stable_rel_obj = prerelease_rel_obj

        has_compat_stable = True
        if stable_rel_obj:
            asset, _ = find_compatible_asset(stable_rel_obj, is_frozen)
            has_compat_stable = (asset is not None)

        has_compat_prerelease = True
        if prerelease_rel_obj:
            asset, _ = find_compatible_asset(prerelease_rel_obj, is_frozen)
            has_compat_prerelease = (asset is not None)

        try:
            def parse_ver(v_str):
                digits = [int(x) for x in RE_DIGITS.findall(str(v_str))][:4]
                while len(digits) < 4:
                    digits.append(0)
                return digits

            current_parsed = parse_ver(self.app_version)
            stable_parsed = parse_ver(latest_stable)

            has_valid_prerelease = False
            if latest_prerelease:
                prerelease_parsed = parse_ver(latest_prerelease)
                if prerelease_parsed > stable_parsed:
                    has_valid_prerelease = True

            target_version = latest_stable
            latest_parsed = stable_parsed
        except Exception:
            current_parsed = [0, 0, 0, 0]
            latest_parsed = [0, 0, 0, 0]
            stable_parsed = [0, 0, 0, 0]
            target_version = latest_stable
            has_valid_prerelease = False

        is_main_branch = current_parsed > stable_parsed
        is_strictly_equal = current_parsed == stable_parsed
        update_available = current_parsed < latest_parsed

        if update_available or is_main_branch or has_valid_prerelease:
            self.lbl_update_spinner.setText("⚠️")
            if not sys.platform.startswith("linux") and hasattr(self, "pulse_anim") and self.pulse_anim and self.pulse_anim.state() != QAbstractAnimation.State.Running:
                self.pulse_anim.start()
            QApplication.processEvents()
        else:
            self.lbl_update_spinner.setText("✔ ")
            QTimer.singleShot(
                5000,
                lambda: self.lbl_update_spinner.setText("") if self.lbl_update_spinner.text() == "✔ " else None
            )

        if self.is_auto_check and not update_available and not is_main_branch:
            return

        dialog = QDialog(self)
        dialog.setWindowIcon(self.get_app_icon())
        dialog.setWindowTitle(self.T("title_update_manager"))
        dialog.setMinimumSize(620, 480)

        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(25, 25, 25, 20)
        dlg_layout.setSpacing(16)

        lbl_msg = QLabel()
        lbl_msg.setWordWrap(True)
        lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_msg.setStyleSheet("font-size: 12pt; font-weight: bold;")

        if update_available:
            lbl_msg.setText(self.T("upd_msg_available").format(target_version=target_version, latest_version=target_version))
        elif is_main_branch:
            lbl_msg.setText(self.T("upd_msg_main_branch").format(app_version=self.app_version, target_version=target_version, latest_version=target_version))
        else:
            lbl_msg.setText(self.T("upd_msg_up_to_date").format(app_version=self.app_version))

        dlg_layout.addWidget(lbl_msg)

        if not has_compat_stable:
            lbl_incompat = QLabel(self.T("upd_err_no_compat_stable"))
            lbl_incompat.setWordWrap(True)
            lbl_incompat.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_incompat.setStyleSheet("color: #EF5350; font-size: 9.5pt; font-weight: bold;")
            dlg_layout.addWidget(lbl_incompat)

        btn_layout = QHBoxLayout()
        btn_view_all = QPushButton(self.T("btn_view_releases"))
        btn_view_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        btn_action = QPushButton()
        btn_action.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        if not has_compat_stable:
            btn_action.setEnabled(False)
            btn_action.setText(self.T("btn_cant_install"))
        else:
            if update_available:
                btn_action.setText(self.T("btn_install_update"))
            elif is_main_branch:
                btn_action.setText(self.T("btn_downgrade"))
            else:
                btn_action.setText(self.T("btn_reinstall"))

        btn_prerelease = None
        if has_valid_prerelease:
            btn_prerelease = QPushButton(self.T("btn_install_prerelease").format(version=latest_prerelease))
            btn_prerelease.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            if not has_compat_prerelease:
                btn_prerelease.setEnabled(False)
                btn_prerelease.setText(btn_prerelease.text() + self.T("tag_unavailable"))

        btn_cancel = QPushButton(self.T("btn_cancel"))
        btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        btn_css = ""
        stable_changelog = self._get_changelog_from_tag(releases, latest_stable)

        if stable_changelog and stable_changelog.strip():
            lbl_change = QLabel(self.T("lbl_recent_changelog"))
            lbl_change.setStyleSheet("font-weight: 600; color: #8A8A95; font-size: 10pt;")
            dlg_layout.addWidget(lbl_change)

            browser = QTextEdit()
            browser.setReadOnly(True)
            browser.setMinimumHeight(180)
            browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

            html_changelog = self._convert_markdown_to_html(stable_changelog)
            browser.setMarkdown(html_changelog)

            up_idle = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238A8A95' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='18 15 12 9 6 15'/></svg>"
            up_hover = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23FFFFFF' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='18 15 12 9 6 15'/></svg>"
            down_idle = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238A8A95' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>"
            down_hover = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23FFFFFF' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>"

            browser.setStyleSheet("""
                QTextEdit {
                    background-color: #1E1E24;
                    color: #E8E8E8;
                    border: 1px solid #4A4A55;
                    border-radius: 8px;
                    padding: 10px;
                    font-size: 10pt;
                }
            """)

            last_hex_state = [""]
            scrollbar = browser.verticalScrollBar()

            def update_dynamic_colors():
                nonlocal btn_css
                current_hex = getattr(self, "last_rainbow_hex", "") if self.is_rainbow_active else ""
                if not current_hex:
                    current_hex = self.get_current_accent_color()

                if last_hex_state[0] == current_hex:
                    return
                last_hex_state[0] = current_hex

                scrollbar.setStyleSheet(f"""
                    QScrollBar:vertical {{
                        border: none;
                        background: #2D2D36;
                        width: 18px;
                        margin: 22px 0 22px 0;
                        border-radius: 6px;
                    }}
                    QScrollBar::handle:vertical {{
                        background: {current_hex};
                        min-height: 40px;
                        border-radius: 6px;
                    }}
                    QScrollBar::add-line:vertical {{
                        border: none;
                        background: #3A3A45;
                        height: 22px;
                        subcontrol-position: bottom;
                        subcontrol-origin: margin;
                        border-radius: 6px;
                    }}
                    QScrollBar::sub-line:vertical {{
                        border: none;
                        background: #3A3A45;
                        height: 22px;
                        subcontrol-position: top;
                        subcontrol-origin: margin;
                        border-radius: 6px;
                    }}
                    QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover,
                    QScrollBar::add-line:vertical:pressed, QScrollBar::sub-line:vertical:pressed {{
                        background: {current_hex};
                    }}
                    QScrollBar::up-arrow:vertical {{
                        image: url("{up_idle}");
                        width: 14px;
                        height: 14px;
                    }}
                    QScrollBar::down-arrow:vertical {{
                        image: url("{down_idle}");
                        width: 14px;
                        height: 14px;
                    }}
                    QScrollBar::up-arrow:vertical:hover, QScrollBar::up-arrow:vertical:pressed {{
                        image: url("{up_hover}");
                    }}
                    QScrollBar::down-arrow:vertical:hover, QScrollBar::down-arrow:vertical:pressed {{
                        image: url("{down_hover}");
                    }}
                    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                        background: none;
                    }}
                """)

                btn_css = f"""
                    QPushButton {{
                        background-color: #2D2D36;
                        color: #FFFFFF;
                        border: 1px solid #4A4A55;
                        border-radius: 6px;
                        padding: 8px 16px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background-color: #3A3A45;
                        border: 1px solid {current_hex};
                    }}
                    QPushButton:pressed {{
                        background-color: {current_hex};
                        color: white;
                        border: none;
                    }}
                    QPushButton:disabled {{
                        background-color: #24242A;
                        color: #6C757D;
                        border: 1px solid #3A3A45;
                    }}
                """
                btn_view_all.setStyleSheet(btn_css)
                btn_action.setStyleSheet(btn_css)
                if btn_prerelease:
                    btn_prerelease.setStyleSheet(btn_css)
                btn_cancel.setStyleSheet(btn_css)

            update_dynamic_colors()

            if self.is_rainbow_active and hasattr(self, "rainbow_timer"):
                self.rainbow_timer.timeout.connect(update_dynamic_colors)

                def cleanup_timer():
                    try:
                        self.rainbow_timer.timeout.disconnect(update_dynamic_colors)
                    except TypeError:
                        pass
                dialog.finished.connect(cleanup_timer)

            dlg_layout.addWidget(browser, 1)
        else:
            current_hex = getattr(self, "last_rainbow_hex", "") if self.is_rainbow_active else ""
            if not current_hex:
                current_hex = self.get_current_accent_color()

            btn_css = f"""
                QPushButton {{
                    background-color: #2D2D36;
                    color: #FFFFFF;
                    border: 1px solid #4A4A55;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #3A3A45;
                    border: 1px solid {current_hex};
                }}
                QPushButton:pressed {{
                    background-color: {current_hex};
                    color: white;
                    border: none;
                }}
                QPushButton:disabled {{
                    background-color: #24242A;
                    color: #6C757D;
                    border: 1px solid #3A3A45;
                }}
            """
            btn_view_all.setStyleSheet(btn_css)
            btn_action.setStyleSheet(btn_css)
            if btn_prerelease:
                btn_prerelease.setStyleSheet(btn_css)
            btn_cancel.setStyleSheet(btn_css)

            lbl_no_change = QLabel(self.T("lbl_no_changelog"))
            lbl_no_change.setStyleSheet("font-style: italic; color: #6A6A75; padding: 30px; font-size: 10pt;")
            lbl_no_change.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dlg_layout.addWidget(lbl_no_change, 1)

        def run_updater_pipeline(target_mode="stable"):
            if getattr(self, "worker", None) is not None and self.worker.isRunning():
                block_box = QMessageBox(dialog)
                block_box.setWindowIcon(self.get_app_icon())
                block_box.setIcon(QMessageBox.Icon.Information)
                block_box.setWindowTitle(self.T("close_blocked_title"))
                block_box.setText(self.T("close_blocked_msg"))
                block_box.exec()
                return

            confirm_box = QMessageBox(dialog)
            confirm_box.setWindowIcon(self.get_app_icon())
            confirm_box.setIcon(QMessageBox.Icon.Question)
            confirm_box.setWindowTitle(self.T("title_confirm"))
            confirm_box.setText(self.T("upd_msg_handoff_warn"))
            btn_yes = confirm_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
            confirm_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
            confirm_box.setDefaultButton(btn_yes)
            confirm_box.exec()

            if confirm_box.clickedButton() != btn_yes:
                return

            save_config(self.config)
            self._is_restarting = True

            clean_env = os.environ.copy()
            clean_env.pop("_MEIPASS2", None)
            clean_env.pop("_MEIPASS", None)
            clean_env.pop("APPDIR", None)

            if hasattr(self, "app_lock") and self.app_lock.isLocked():
                try:
                    self.app_lock.unlock()
                except Exception:
                    pass

            if is_frozen:
                dialog.accept()
                appimage_env = os.environ.get("ORIGINAL_APPIMAGE") or os.environ.get("APPIMAGE")
                if appimage_env and os.path.exists(appimage_env):
                    current_exe = os.path.abspath(appimage_env)
                    base_dir = os.path.dirname(current_exe)
                    orig_target = current_exe
                    clean_env["ORIGINAL_APPIMAGE"] = current_exe
                elif sys.platform == "darwin" and ".app" in os.path.abspath(sys.executable):
                    current_exe = os.path.abspath(sys.executable)
                    mac_bundle = get_mac_app_bundle_path(current_exe)
                    base_dir = mac_bundle
                    orig_target = mac_bundle
                else:
                    current_exe = os.path.abspath(sys.executable)
                    base_dir = os.path.dirname(current_exe)
                    orig_target = current_exe

                args = [current_exe, "--updater", "--install-dir", base_dir, "--original-target", orig_target]
                if target_mode == "all":
                    args.append("--view-all")
                elif target_mode == "stable" and is_strictly_equal:
                    args.append("--reinstall")
                elif target_mode == "prerelease":
                    args.append("--prerelease")

                kwargs = {
                    "cwd": os.path.expanduser("~"),
                    "env": clean_env,
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = 0x00000008 | 0x00000200
                else:
                    kwargs["start_new_session"] = True

                subprocess.Popen(args, **kwargs)
                self.close()
                QApplication.quit()
                sys.exit(0)

            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            updater_script = os.path.join(base_dir, "Updater.py")
            if not os.path.exists(updater_script):
                updater_script = os.path.join(os.getcwd(), "Updater.py")
                if os.path.exists(updater_script):
                    base_dir = os.getcwd()

            if os.path.exists(updater_script):
                dialog.accept()
                appdata_dir = str(APPDATA_DIR)
                os.makedirs(appdata_dir, exist_ok=True)
                temp_updater = os.path.join(appdata_dir, "TempUpdater.py")
                main_script = os.path.join(base_dir, "run_TriCoreDownloader.py")
                orig_target = main_script if os.path.exists(main_script) else os.path.abspath(sys.argv[0])

                plan_a_success = False
                try:
                    shutil.copy2(updater_script, temp_updater)
                    for _ in range(10):
                        if os.path.exists(temp_updater) and os.path.getsize(temp_updater) > 0:
                            break
                        time.sleep(0.05)

                    args = [sys.executable, temp_updater, "--install-dir", base_dir, "--original-target", orig_target]
                    if target_mode == "all":
                        args.append("--view-all")
                    elif target_mode == "stable" and is_strictly_equal:
                        args.append("--reinstall")
                    elif target_mode == "prerelease":
                        args.append("--prerelease")

                    kwargs = {
                        "cwd": base_dir,
                        "env": clean_env,
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                    }
                    if os.name == "nt":
                        kwargs["creationflags"] = 0x00000008 | 0x00000200
                    else:
                        kwargs["start_new_session"] = True

                    proc = subprocess.Popen(args, **kwargs)
                    time.sleep(0.4)
                    if proc.poll() is None:
                        plan_a_success = True
                except Exception:
                    plan_a_success = False

                if not plan_a_success:
                    args = [sys.executable, updater_script, "--install-dir", base_dir, "--original-target", orig_target]
                    if target_mode == "all":
                        args.append("--view-all")
                    elif target_mode == "stable" and is_strictly_equal:
                        args.append("--reinstall")
                    elif target_mode == "prerelease":
                        args.append("--prerelease")

                    kwargs = {
                        "cwd": base_dir,
                        "env": clean_env,
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                    }
                    if os.name == "nt":
                        kwargs["creationflags"] = 0x00000008 | 0x00000200
                    else:
                        kwargs["start_new_session"] = True
                    subprocess.Popen(args, **kwargs)

                self.close()
                QApplication.quit()
            else:
                self._is_restarting = False
                crit_box = QMessageBox(dialog)
                crit_box.setWindowIcon(self.get_app_icon())
                crit_box.setIcon(QMessageBox.Icon.Critical)
                crit_box.setWindowTitle(self.T("msg_error_title"))
                crit_box.setText(self.T("upd_err_missing_script"))
                crit_box.exec()

        btn_view_all.clicked.connect(lambda *args: run_updater_pipeline(target_mode="all"))
        btn_action.clicked.connect(lambda *args: run_updater_pipeline(target_mode="stable"))
        if btn_prerelease:
            btn_prerelease.clicked.connect(lambda *args: run_updater_pipeline(target_mode="prerelease"))
        btn_cancel.clicked.connect(dialog.reject)

        btn_layout.addWidget(btn_view_all)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_action)
        if btn_prerelease:
            btn_layout.addWidget(btn_prerelease)
        btn_layout.addWidget(btn_cancel)

        dlg_layout.addLayout(btn_layout)
        dialog.exec()

    def _signal_handler(self, signum, frame):
        self.sigint_caught.emit()

    def prompt_ctrl_c_quit(self):
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            msg_box = QMessageBox(self)
            msg_box.setWindowIcon(self.get_app_icon())
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle(self.T("close_blocked_title"))
            msg_box.setText(self.T("close_blocked_msg"))
            msg_box.exec()
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowIcon(self.get_app_icon())
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(self.T("ctrl_c_title"))
        msg_box.setText(self.T("ctrl_c_msg"))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        btn_yes = msg_box.button(QMessageBox.StandardButton.Yes)
        btn_no = msg_box.button(QMessageBox.StandardButton.No)
        if btn_yes:
            btn_yes.setText(self.T("btn_yes"))
        if btn_no:
            btn_no.setText(self.T("btn_no"))

        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            save_config(self.config)
            self.close()

    def closeEvent(self, event):
        if getattr(self, "worker", None) is not None and self.worker.isRunning() and not getattr(self, "_is_restarting", False):
            msg_box = QMessageBox(self)
            msg_box.setWindowIcon(self.get_app_icon())
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle(self.T("close_blocked_title"))
            msg_box.setText(self.T("close_blocked_msg"))
            msg_box.exec()
            event.ignore()
        else:
            if not getattr(self, "_is_restarting", False):
                save_config(self.config)
                self.perform_security_cleanup()
            if hasattr(self, "audio") and hasattr(self.audio, "cleanup"):
                try:
                    self.audio.cleanup()
                except Exception:
                    pass
            if hasattr(self, "app_lock") and self.app_lock.isLocked():
                try:
                    self.app_lock.unlock()
                except Exception:
                    pass
            event.accept()


class UpdateCheckerThread(QThread):
    finished_signal = pyqtSignal(str, str, str, bool, str)
    log_signal = pyqtSignal(str)

    def run(self):
        url = "https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/releases"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TriCoreDownloader-Main"})
            with _urlopen_safe(req, timeout=10) as response:
                raw_data = response.read().decode("utf-8")
                releases = json.loads(raw_data)

            if not releases:
                self.finished_signal.emit("", "", "", False, "")
                return

            latest_stable = ""
            latest_prerelease = ""
            is_target_prerelease = False

            for rel in releases:
                tag = rel.get("tag_name", "").strip().lstrip("v")
                if rel.get("prerelease", False):
                    if not latest_prerelease:
                        latest_prerelease = tag
                else:
                    if not latest_stable:
                        latest_stable = tag
                if latest_stable and latest_prerelease:
                    break

            if not latest_stable and latest_prerelease:
                latest_stable = latest_prerelease

            if latest_prerelease:
                def parse_ver(v_str):
                    digits = [int(x) for x in RE_DIGITS.findall(str(v_str))][:4]
                    while len(digits) < 4:
                        digits.append(0)
                    return digits

                if not latest_stable or parse_ver(latest_prerelease) > parse_ver(latest_stable):
                    is_target_prerelease = True

            self.finished_signal.emit(latest_stable, latest_prerelease, raw_data, is_target_prerelease, "")

        except urllib.error.HTTPError as he:
            err_details = f"HTTP Error {he.code}: {he.reason}"
            raw_body = ""
            try:
                raw_body = he.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            self.finished_signal.emit("", "", raw_body, False, err_details)
        except Exception as e:
            self.finished_signal.emit("", "", "", False, str(e))
