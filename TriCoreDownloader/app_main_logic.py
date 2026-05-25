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

from PyQt6.QtWidgets import (QApplication, QMessageBox, QWidget, QGraphicsOpacityEffect, 
                             QDialog, QComboBox, QHBoxLayout, QVBoxLayout, QSlider, QLabel, 
                             QCheckBox, QPushButton, QGridLayout, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QByteArray, QSize, QLockFile, QDir, QThread, pyqtSignal, QAbstractAnimation
from PyQt6.QtGui import QIcon, QPixmap, QCursor, QTextOption, QPainter, QColor

from .config import EULA_FILE, APPDATA_DIR, save_config, APP_VERSION
from .custom_widgets import EulaDialog
from .app_utils_dialogs import exception_hook, ComboScrollFilter
from .ui_core_layout import FirmwareAppUI
from .audio_manager import AudioManager
from .logos import (NX_LOGO_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_BLACK_SVG, 
                    CTR_LOGO_CLEAN_SVG, CAFE_LOGO_SVG, VOL_MUTE_SVG, 
                    VOL_LOW_SVG, VOL_HIGH_SVG, RESTART_SVG, TCD_MAIN_LOGO)
from .app_downloader import DownloadManagerMixin
from .app_ui_interactions import UiInteractionsMixin

sys.excepthook = exception_hook

class FirmwareApp(DownloadManagerMixin, FirmwareAppUI, UiInteractionsMixin):
    sigint_caught = pyqtSignal()

    def __init__(self, config_data, is_corrupted, tampered_rainbow):
        self.app_version = APP_VERSION
        
        self.app_lock = QLockFile(os.path.join(QDir.tempPath(), "TriCoreDownloader.lock"))
        if not self.app_lock.tryLock(100):
            sys.exit(0)

        super().__init__(config_data)
        
        appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "TriCoreDownloader")
        self.keys_dir = os.path.join(appdata_dir, "temp_keys")
        
        self.perform_security_cleanup()
        
        self.is_rainbow_active = self.config.get("rainbow_mode", False) or tampered_rainbow
        
        self.audio = AudioManager(self, self.config)
        if not self.config.get("first_launch", True):
            self.audio.play_tricore_boot()
            
        if hasattr(self, "console_selector") and self.console_selector.parentWidget():
            parent_layout = self.console_selector.parentWidget().layout()
            if parent_layout:
                parent_layout.setAlignment(self.console_selector, Qt.AlignmentFlag.AlignVCenter)
            
        self.console_selector.currentIndexChanged.connect(self.switch_console_mode)
        self.nav_group.idClicked.connect(self.switch_tab_animated)
        self.btn_tab_restart.clicked.connect(self.prompt_restart)

        self.spinner_frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self.spinner_idx = 0
        self.updater_spinner_timer = QTimer(self)
        self.updater_spinner_timer.timeout.connect(self.update_update_spinner)
        self.is_auto_check = False

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
                
                self.btn_update = QPushButton(self.T("btn_update") if hasattr(self, "T") else "btn_update")
                self.btn_update.setObjectName("btnHeader")
                self.btn_update.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                self.btn_update.clicked.connect(self.manual_check_updates)
                
                self.update_right_layout.addWidget(self.lbl_update_spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
                self.update_right_layout.addWidget(self.btn_update, alignment=Qt.AlignmentFlag.AlignVCenter)
                
                if isinstance(header_layout, QGridLayout):
                    header_layout.addWidget(self.update_container, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    header_layout.addWidget(self.update_container)
        
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
            
            self.chk_unlimited_console = QCheckBox(self.T("chk_unlimited_console") if hasattr(self, "T") else "chk_unlimited_console")
            self.chk_unlimited_console.setToolTip(self.T("tt_unlimited") if hasattr(self, "T") else "tt_unlimited")
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
            save_config(self.config)
            self.perform_security_cleanup()
            
        atexit.register(safe_cleanup)
        
        def crash_handler(exc_type, exc_value, exc_traceback):
            save_config(self.config)
            self.perform_security_cleanup()
            self.handle_fatal_crash(exc_type, exc_value, exc_traceback)
            
        sys.excepthook = crash_handler
        
        self.sigint_caught.connect(self.prompt_ctrl_c_quit)
        signal.signal(signal.SIGINT, self._signal_handler)
        self._sigint_timer = QTimer(self)
        self._sigint_timer.timeout.connect(lambda: None)
        self._sigint_timer.start(200)

        self.startup_anim.start()
        
        if is_corrupted:
            save_config(self.config)
            QTimer.singleShot(200, self.show_corruption_warning)
        elif tampered_rainbow:
            save_config(self.config)
            QTimer.singleShot(200, self.show_easter_egg)
            
        QTimer.singleShot(100, self.show_eula_if_needed)
        QTimer.singleShot(500, lambda: self.start_update_check(auto=True) if self.current_console != "WELCOME" else None)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.config.get("volume", 50)))
        if hasattr(self, "T"):
            self.volume_slider.setToolTip(self.T("lbl_volume"))
        
        self.lbl_vol_icon = QLabel()
        self.lbl_vol_icon.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        def update_main_vol_icon(val=None):
            if val is None: 
                val = self.volume_slider.value()
            theme_pref = self.config.get("theme", "auto")
            is_dark = False
            if theme_pref in ["dark", "oled"]:
                is_dark = True
            elif theme_pref == "auto":
                if hasattr(self, "get_effective_is_dark"):
                    is_dark = self.get_effective_is_dark()
            
            text_color = "#FFFFFF" if is_dark else "#333333"
            if val == 0: svg_data = VOL_MUTE_SVG
            elif val < 50: svg_data = VOL_LOW_SVG
            else: svg_data = VOL_HIGH_SVG

            pm_vol = QPixmap()
            pm_vol.loadFromData(QByteArray(svg_data), "SVG")
            painter = QPainter(pm_vol)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pm_vol.rect(), QColor(text_color))
            painter.end()
            self.lbl_vol_icon.setPixmap(pm_vol.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        self._update_vol_icon = update_main_vol_icon
        self._update_vol_icon(self.volume_slider.value())
        
        self._pre_mute_main_vol = self.volume_slider.value() if self.volume_slider.value() > 0 else 50
        
        def toggle_main_mute(event):
            if self.volume_slider.value() > 0:
                self._pre_mute_main_vol = self.volume_slider.value()
                self.volume_slider.setValue(0)
            else:
                self.volume_slider.setValue(self._pre_mute_main_vol if self._pre_mute_main_vol > 0 else 50)
                
        self.lbl_vol_icon.mousePressEvent = toggle_main_mute

        def on_main_vol_changed(val):
            self.config["volume"] = val
            self._update_vol_icon(val)

        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        self.volume_slider.valueChanged.connect(on_main_vol_changed)
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
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.symbol_reset_timer = QTimer(self)
        self.symbol_reset_timer.setSingleShot(True)
        self.symbol_reset_timer.timeout.connect(self.update_dl_mode_label)
        
        self.update_dynamic_ui()
        
        if self.config.get("first_launch", True):
            self.header_widget.setVisible(False)
            self.nav_wrapper.setVisible(False)
            self.bottom_widget.setVisible(True)
            self.tabs.setCurrentWidget(self.tab_welcome)
            
            if hasattr(self, "T"):
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
            
            self.btn_welcome_nx.clicked.connect(lambda *args: self.finish_welcome_setup(0))
            self.btn_welcome_ctr.clicked.connect(lambda *args: self.finish_welcome_setup(1))
            self.btn_welcome_cafe.clicked.connect(lambda *args: self.finish_welcome_setup(2))
            
            QTimer.singleShot(500, self.audio.play_welcome)
        else:
            self.tabs.setCurrentIndex(0)
            QTimer.singleShot(500, self.verify_application_version)

    def perform_security_cleanup(self):
        if hasattr(self, "keys_dir") and os.path.exists(self.keys_dir):
            try:
                shutil.rmtree(self.keys_dir, ignore_errors=True)
            except Exception:
                pass
                
        appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "TriCoreDownloader")
        temp_updater_path = os.path.join(appdata_dir, "TempUpdater.py")
        if os.path.exists(temp_updater_path):
            try:
                os.remove(temp_updater_path)
            except Exception:
                pass

    def apply_visual_settings(self):
        try:
            super().apply_visual_settings()
        except AttributeError:
            pass
        if hasattr(self, "refresh_all_static_icons"):
            self.refresh_all_static_icons()

    def refresh_dynamic_icons(self):
        try:
            super().refresh_dynamic_icons()
        except AttributeError:
            pass
        if hasattr(self, "refresh_all_static_icons"):
            self.refresh_all_static_icons()

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
        
        lines = text.split("\n")
        html_lines = []
        in_code = False
        in_list = False
        in_blockquote = False
        
        for line in lines:
            line_str = line.strip()
            
            if line_str.startswith("```"):
                if in_code:
                    html_lines.append("</pre></div>")
                    in_code = False
                else:
                    html_lines.append("<div style='background-color: #2D2D36; padding: 8px; border-radius: 6px; margin: 6px 0;'><pre style='margin: 0; color: #E8E8E8; font-family: Consolas, monospace; white-space: pre-wrap;'>")
                    in_code = True
                continue
                
            if in_code:
                escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                html_lines.append(escaped + "\n")
                continue
                
            if not line_str:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                if in_blockquote:
                    html_lines.append("</blockquote>")
                    in_blockquote = False
                html_lines.append("<br>")
                continue
                
            if line_str.startswith(">"):
                line_str = line_str.lstrip(">").strip()
                if not in_blockquote:
                    html_lines.append("<blockquote style='color: #A0A0AB; font-style: italic; margin: 4px 0; padding-left: 10px; border-left: 3px solid #4A4A55;'>")
                    in_blockquote = True
            else:
                if in_blockquote:
                    html_lines.append("</blockquote>")
                    in_blockquote = False
                    
            is_list_item = False
            if line_str.startswith("- ") or line_str.startswith("* "):
                is_list_item = True
                line_str = line_str[2:].strip()
                if not in_list:
                    html_lines.append("<ul style='margin-top: 4px; margin-bottom: 4px; padding-left: 20px;'>")
                    in_list = True
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                    
            is_header = False
            header_match = re.match(r'^(#{1,6})\s+(.*)', line_str)
            if header_match:
                is_header = True
                level = len(header_match.group(1))
                line_str = header_match.group(2).strip()
                
                size_map = {1: "18pt", 2: "15pt", 3: "13pt", 4: "11pt", 5: "10pt", 6: "9pt"}
                margin_top = "12px" if level <= 3 else "8px"
                header_open = f"<div style='color: #FFFFFF; font-size: {size_map.get(level, '11pt')}; font-weight: bold; margin-top: {margin_top}; margin-bottom: 6px;'>"
                header_close = "</div>"
                
            line_str = re.sub(r'`(.*?)`', r'<code style="background-color: #2D2D36; padding: 2px 4px; border-radius: 4px; color: #C4A1FF;">\1</code>', line_str)
            line_str = re.sub(r'(?<!\w)\*\*(.*?)\*\*(?!\w)', r'<b style="color: #FFFFFF;">\1</b>', line_str)
            line_str = re.sub(r'(?<!\w)__(.*?)__(?!\w)', r'<b style="color: #FFFFFF;">\1</b>', line_str)
            line_str = re.sub(r'(?<!\w)\*(.*?)\*(?!\w)', r'<i style="color: #E8E8E8;">\1</i>', line_str)
            line_str = re.sub(r'(?<!\w)_(.*?)_(?!\w)', r'<i style="color: #E8E8E8;">\1</i>', line_str)
            line_str = re.sub(r'~~(.*?)~~', r'<s style="color: #8A8A95;">\1</s>', line_str)
            line_str = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" style="color: #00A2E8; text-decoration: none;">\1</a>', line_str)
            
            if is_header:
                html_lines.append(f"{header_open}{line_str}{header_close}")
            elif is_list_item:
                html_lines.append(f"<li>{line_str}</li>")
            else:
                html_lines.append(f"<div>{line_str}</div>")
                
        if in_list:
            html_lines.append("</ul>")
        if in_blockquote:
            html_lines.append("</blockquote>")
        if in_code:
            html_lines.append("</pre></div>")
            
        return "".join(html_lines)

    def _get_changelog_from_tag(self, releases, version_tag):
        for rel in releases:
            if rel.get("tag_name", "").strip().lstrip('v') == version_tag:
                return rel.get("body") or ""
        return ""

    def _get_api_error_message(self, json_payload):
        try:
            data = json.loads(json_payload)
            if isinstance(data, dict) and "message" in data and "documentation_url" in data:
                return data["message"]
        except Exception:
            pass
        return ""

    def _handle_updater_log(self, text):
        if self.config.get("advanced_logs", False):
            print(text)
            sys.stdout.flush()

    def start_update_check(self, auto=False, *args):
        if self.current_console == "WELCOME":
            return
            
        self.pulse_anim.stop()
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
        if hasattr(self, "updater_spinner_timer"): self.updater_spinner_timer.stop()
        if hasattr(self, "lbl_update_spinner"): self.lbl_update_spinner.setText("")
        if hasattr(self, "btn_update"): self.btn_update.setEnabled(True)
            
        def get_text(key):
            if hasattr(self, "T"):
                val = self.T(key)
                return val if val != key else key
            return key

        api_error = self._get_api_error_message(json_payload) if not error_msg else error_msg
        
        if api_error:
            if hasattr(self, "lbl_update_spinner"): 
                self.lbl_update_spinner.setText("❌ ")
                QTimer.singleShot(5000, lambda: self.lbl_update_spinner.setText(""))
            if not self.is_auto_check:
                msg_box = QMessageBox(self)
                msg_box.setWindowIcon(self.get_app_icon())
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle(get_text("msg_error_title"))
                msg_box.setText(f"{get_text('msg_error_title')}:\n{api_error}")
                msg_box.exec()
            return

        try:
            releases = json.loads(json_payload) if isinstance(json_payload, str) else json_payload
        except Exception:
            releases = []

        try:
            def parse_ver(v_str):
                return [int(x) for x in re.findall(r'\d+', str(v_str))]
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
            current_parsed = [0]
            latest_parsed = [0]
            stable_parsed = [0]
            target_version = latest_stable
            has_valid_prerelease = False

        is_main_branch = current_parsed > stable_parsed
        is_strictly_equal = current_parsed == stable_parsed
        update_available = current_parsed < latest_parsed

        if update_available or is_main_branch or has_valid_prerelease:
            self.lbl_update_spinner.setText("⚠️")
            if self.pulse_anim.state() != QAbstractAnimation.State.Running:
                self.pulse_anim.start()
            QApplication.processEvents()
        else:
            self.lbl_update_spinner.setText("✔ ")
            QTimer.singleShot(5000, lambda: self.lbl_update_spinner.setText("") if self.lbl_update_spinner.text() == "✔ " else None)

        if self.is_auto_check and not update_available and not is_main_branch:
            return

        dialog = QDialog(self)
        dialog.setWindowIcon(self.get_app_icon())
        dialog.setWindowTitle(get_text("title_update_manager"))
        dialog.setMinimumSize(600, 450)
        
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(25, 25, 25, 20)
        dlg_layout.setSpacing(16)
        
        lbl_msg = QLabel()
        lbl_msg.setWordWrap(True)
        lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_msg.setStyleSheet("font-size: 12pt; font-weight: bold;")
        
        if update_available:
            lbl_msg.setText(get_text("upd_msg_available").format(target_version=target_version, latest_version=target_version))
        elif is_main_branch:
            lbl_msg.setText(get_text("upd_msg_main_branch").format(app_version=self.app_version, target_version=target_version, latest_version=target_version))
        else:
            lbl_msg.setText(get_text("upd_msg_up_to_date").format(app_version=self.app_version))
            
        dlg_layout.addWidget(lbl_msg)

        btn_layout = QHBoxLayout()
        btn_view_all = QPushButton(get_text("btn_view_releases"))
        btn_view_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        btn_action = QPushButton()
        btn_action.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        if update_available:
            btn_action.setText(get_text("btn_install_update"))
        elif is_main_branch:
            btn_action.setText(get_text("btn_downgrade"))
        else:
            btn_action.setText(get_text("btn_reinstall"))
            
        btn_prerelease = None
        if has_valid_prerelease:
            btn_prerelease = QPushButton(get_text("btn_install_prerelease").format(version=latest_prerelease))
            btn_prerelease.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        btn_cancel = QPushButton(get_text("btn_cancel"))
        btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        btn_css = ""
        stable_changelog = self._get_changelog_from_tag(releases, latest_stable)

        if stable_changelog and stable_changelog.strip():
            lbl_change = QLabel(get_text("lbl_recent_changelog"))
            lbl_change.setStyleSheet("font-weight: 600; color: #8A8A95; font-size: 10pt;")
            dlg_layout.addWidget(lbl_change)
            
            browser = QTextEdit() 
            browser.setReadOnly(True)
            browser.setMinimumHeight(180)
            browser.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere) 
            
            html_changelog = self._convert_markdown_to_html(stable_changelog)
            browser.setHtml(html_changelog)
            
            tmp_dir = QDir.tempPath() + "/TriCore_SVGs"
            QDir().mkpath(tmp_dir)
            
            def create_svg_file(name, color, is_up):
                path = tmp_dir + "/" + name
                pts = "18 15 12 9 6 15" if is_up else "6 9 12 15 18 9"
                content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="{pts}"/></svg>"""
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return path

            up_idle_path = create_svg_file("up_idle.svg", "#8A8A95", True)
            up_hover_path = create_svg_file("up_hover.svg", "#FFFFFF", True)
            down_idle_path = create_svg_file("down_idle.svg", "#8A8A95", False)
            down_hover_path = create_svg_file("down_hover.svg", "#FFFFFF", False)

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
                    current_hex = self.config.get("accent_color", "#bc181a")
                
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
                        image: url("{up_idle_path}");
                        width: 14px;
                        height: 14px;
                    }}
                    QScrollBar::down-arrow:vertical {{
                        image: url("{down_idle_path}");
                        width: 14px;
                        height: 14px;
                    }}
                    QScrollBar::up-arrow:vertical:hover, QScrollBar::up-arrow:vertical:pressed {{
                        image: url("{up_hover_path}");
                    }}
                    QScrollBar::down-arrow:vertical:hover, QScrollBar::down-arrow:vertical:pressed {{
                        image: url("{down_hover_path}");
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
                    try: self.rainbow_timer.timeout.disconnect(update_dynamic_colors)
                    except TypeError: pass
                dialog.finished.connect(cleanup_timer)

            dlg_layout.addWidget(browser, 1) 
        else:
            current_hex = getattr(self, "last_rainbow_hex", "") if self.is_rainbow_active else ""
            if not current_hex:
                current_hex = self.config.get("accent_color", "#bc181a")
            
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
            """
            btn_view_all.setStyleSheet(btn_css)
            btn_action.setStyleSheet(btn_css)
            if btn_prerelease:
                btn_prerelease.setStyleSheet(btn_css)
            btn_cancel.setStyleSheet(btn_css)

            lbl_no_change = QLabel(get_text("lbl_no_changelog"))
            lbl_no_change.setStyleSheet("font-style: italic; color: #6A6A75; padding: 30px; font-size: 10pt;")
            lbl_no_change.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dlg_layout.addWidget(lbl_no_change, 1)
        
        def run_updater_pipeline(target_mode="stable"):
            if target_mode == "all":
                confirm_box = QMessageBox(dialog)
                confirm_box.setWindowIcon(self.get_app_icon())
                confirm_box.setIcon(QMessageBox.Icon.Question)
                confirm_box.setWindowTitle(get_text("title_confirm"))
                confirm_box.setText(get_text("upd_msg_handoff_warn"))
                confirm_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if confirm_box.exec() != QMessageBox.StandardButton.Yes:
                    return

            updater_script = os.path.join(os.getcwd(), "Updater.py")
            if os.path.exists(updater_script):
                dialog.accept()
                
                appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "TriCoreDownloader")
                os.makedirs(appdata_dir, exist_ok=True)
                temp_updater = os.path.join(appdata_dir, "TempUpdater.py")
                
                plan_a_success = False
                try:
                    shutil.copy2(updater_script, temp_updater)
                    for _ in range(10):
                        if os.path.exists(temp_updater) and os.path.getsize(temp_updater) > 0:
                            break
                        time.sleep(0.05)
                        
                    args = [sys.executable, temp_updater, "--install-dir", os.getcwd()]
                    if target_mode == "all": args.append("--view-all")
                    elif target_mode == "stable" and is_strictly_equal: args.append("--reinstall")
                    elif target_mode == "prerelease": args.append("--prerelease")
                    
                    kwargs = {
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL
                    }
                    if os.name == 'nt':
                        kwargs['creationflags'] = 0x00000008 | 0x00000200
                        
                    proc = subprocess.Popen(args, **kwargs)
                    time.sleep(0.4)
                    if proc.poll() is None:
                        plan_a_success = True
                except Exception:
                    plan_a_success = False
                    
                if not plan_a_success:
                    args = [sys.executable, updater_script, "--install-dir", os.getcwd()]
                    if target_mode == "all": args.append("--view-all")
                    elif target_mode == "stable" and is_strictly_equal: args.append("--reinstall")
                    elif target_mode == "prerelease": args.append("--prerelease")
                    
                    kwargs = {
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL
                    }
                    if os.name == 'nt':
                        kwargs['creationflags'] = 0x00000008 | 0x00000200
                    subprocess.Popen(args, **kwargs)
                    
                QApplication.quit()
                sys.exit(0)
            else:
                crit_box = QMessageBox(dialog)
                crit_box.setWindowIcon(self.get_app_icon())
                crit_box.setIcon(QMessageBox.Icon.Critical)
                crit_box.setWindowTitle(get_text("msg_error_title"))
                crit_box.setText(get_text("upd_err_missing_script"))
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
            msg_box.setWindowTitle(self.T("close_blocked_title") if hasattr(self, "T") else "Action bloquée")
            msg_box.setText(self.T("close_blocked_msg") if hasattr(self, "T") else "L'application travaille, vous ne pouvez pas quitter maintenant.")
            msg_box.exec()
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowIcon(self.get_app_icon())
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(self.T("ctrl_c_title") if hasattr(self, "T") else "Interruption")
        msg_box.setText(self.T("ctrl_c_msg") if hasattr(self, "T") else "Voulez-vous vraiment éteindre le script ?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            save_config(self.config)
            self.close()

    def closeEvent(self, event):
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            msg_box = QMessageBox(self)
            msg_box.setWindowIcon(self.get_app_icon())
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle(self.T("close_blocked_title") if hasattr(self, "T") else "")
            msg_box.setText(self.T("close_blocked_msg") if hasattr(self, "T") else "")
            event.ignore()
        else:
            save_config(self.config)
            self.perform_security_cleanup()
            event.accept()

class UpdateCheckerThread(QThread):
    finished_signal = pyqtSignal(str, str, str, bool, str)
    log_signal = pyqtSignal(str)

    def run(self):
        url = "https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/releases"
        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Main'})
            with opener.open(req, timeout=8) as response:
                raw_data = response.read().decode('utf-8')
                releases = json.loads(raw_data)
                
            if not releases:
                self.finished_signal.emit("", "", "", False, "")
                return
                
            latest_stable = ""
            latest_prerelease = ""
            is_target_prerelease = False

            for rel in releases:
                tag = rel.get("tag_name", "").strip().lstrip('v')
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
                    return [int(x) for x in re.findall(r'\d+', str(v_str))]
                if not latest_stable or parse_ver(latest_prerelease) > parse_ver(latest_stable):
                    is_target_prerelease = True

            self.finished_signal.emit(latest_stable, latest_prerelease, raw_data, is_target_prerelease, "")
                
        except urllib.error.HTTPError as he:
            err_details = f"HTTP Error {he.code}: {he.reason}"
            self.finished_signal.emit("", "", "", False, err_details)
        except Exception as e:
            self.finished_signal.emit("", "", "", False, str(e))
