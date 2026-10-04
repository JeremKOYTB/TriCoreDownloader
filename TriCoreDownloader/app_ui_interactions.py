import os
import sys
import datetime
import subprocess
import json
from PyQt6.QtWidgets import (QMessageBox, QWidget, QGraphicsOpacityEffect, QDialog, 
                             QComboBox, QTextBrowser, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QCheckBox, QApplication)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QByteArray
from PyQt6.QtGui import QIcon, QCursor, QPixmap, QColor

from .config import EULA_FILE, CONFIG_FILE, APPDATA_DIR, save_config
from .custom_widgets import EulaDialog
from .logos import (NX_LOGO_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_BLACK_SVG, 
                    CTR_LOGO_CLEAN_SVG, CAFE_LOGO_SVG, VOL_MUTE_SVG, 
                    VOL_LOW_SVG, VOL_HIGH_SVG, RESTART_SVG, TCD_MAIN_LOGO)

_SVG_CACHE = {}
_VOL_CACHE = {}

class UiInteractionsMixin:
    def verify_application_version(self):
        if getattr(self, "_eula_active", False):
            QTimer.singleShot(300, self.verify_application_version)
            return

        from .config import APP_VERSION
        adv_logs = self.config.get("advanced_logs", False)
        
        if adv_logs:
            print("[UI-VERSION] verify_application_version() triggered.")
            
        status = self.config.get("_version_status")
        saved_version = self.config.get("_old_version", "0.0.0")
        
        if adv_logs:
            print(f"[UI-VERSION] Memory flag _version_status: {status}")
            print(f"[UI-VERSION] Memory flag _old_version: {saved_version}")
        
        if not status:
            if adv_logs:
                print("[UI-VERSION] No valid status flag found. Aborting dialog.")
            return

        if adv_logs:
            print(f"[UI-VERSION] Constructing UI dialog for status: {status}")

        if status == "downgrade":
            dialog = QDialog(self)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
            
            dialog.setWindowTitle(self.T("msg_downgrade_title"))
            try:
                dialog.setWindowIcon(QIcon(self.get_svg_icon(TCD_MAIN_LOGO)))
            except Exception:
                pass

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(32, 28, 32, 24)
            layout.setSpacing(24)

            lbl = QLabel(self.T("msg_downgrade_desc").format(app_version=APP_VERSION, saved_version=saved_version))
            lbl.setTextFormat(Qt.TextFormat.PlainText)
            lbl.setStyleSheet("font-size: 10.5pt; line-height: 1.4;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_force = QPushButton(self.T("btn_force_launch"))
            btn_reset = QPushButton(self.T("btn_reset_config"))
            btn_exit = QPushButton(self.T("btn_exit"))

            for b in [btn_force, btn_reset, btn_exit]:
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet("padding: 6px 16px; font-weight: bold;")
                btn_layout.addWidget(b)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)
            layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

            choice = {"action": "exit"}
            btn_force.clicked.connect(lambda: [choice.update({"action": "launch"}), dialog.accept()])
            btn_reset.clicked.connect(lambda: [choice.update({"action": "reset"}), dialog.accept()])
            btn_exit.clicked.connect(lambda: [choice.update({"action": "exit"}), dialog.reject()])
            
            result = dialog.exec()
            
            if adv_logs:
                print(f"[UI-VERSION] Dialog executed. User choice: {choice['action']}")

            if choice["action"] == "exit":
                sys.exit(0)
            elif choice["action"] == "reset":
                try:
                    if os.path.exists(CONFIG_FILE):
                        os.remove(CONFIG_FILE)
                    if os.path.exists(EULA_FILE):
                        os.remove(EULA_FILE)
                except Exception:
                    pass
                subprocess.Popen([sys.executable] + sys.argv)
                QApplication.quit()
            else:
                self.config.pop("_version_status", None)
                self.config.pop("_old_version", None)

        elif status == "upgrade":
            dialog = QDialog(self)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
            
            dialog.setWindowTitle(self.T("msg_upgrade_title"))
            try:
                dialog.setWindowIcon(QIcon(self.get_svg_icon(TCD_MAIN_LOGO)))
            except Exception:
                pass

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(32, 28, 32, 24)
            layout.setSpacing(24)

            lbl = QLabel(self.T("msg_upgrade_desc").format(app_version=APP_VERSION, saved_version=saved_version))
            lbl.setTextFormat(Qt.TextFormat.PlainText)
            lbl.setStyleSheet("font-size: 10.5pt; line-height: 1.4;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_ok = QPushButton(self.T("btn_great"))
            btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_ok.setStyleSheet("padding: 6px 24px; font-weight: bold;")
            btn_ok.clicked.connect(dialog.accept)
            btn_layout.addWidget(btn_ok)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)
            layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
            
            dialog.exec()
            
            if adv_logs:
                print("[UI-VERSION] Upgrade dialog closed. Clearing memory flags.")
                
            self.config.pop("_version_status", None)
            self.config.pop("_old_version", None)

    def update_update_spinner(self):
        if hasattr(self, "lbl_update_spinner") and hasattr(self, "spinner_frames") and self.spinner_frames:
            self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_frames)
            self.lbl_update_spinner.setText(self.spinner_frames[self.spinner_idx])

    def manual_check_updates(self, *args):
        from .custom_widgets import launch_updater
        launch_updater(self)

    def on_unlimited_console_toggled(self, checked):
        self.config["unlimited_console"] = checked
        if hasattr(self, "console"):
            self.console.setMaximumBlockCount(0 if checked else 1000)
        self.trigger_auto_save()

    def get_svg_icon(self, svg_bytes):
        if not svg_bytes:
            svg_bytes = TCD_MAIN_LOGO
            
        theme_pref = self.config.get("theme", "auto")
        is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
        
        cache_key = (svg_bytes, is_dark)
        if cache_key in _SVG_CACHE:
            return _SVG_CACHE[cache_key]
            
        color = b"#FFFFFF" if is_dark else b"#333333"
        colored_svg = svg_bytes.replace(b"currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(colored_svg))
        _SVG_CACHE[cache_key] = pixmap
        return pixmap

    def refresh_dynamic_icons(self):
        self._update_combo_box_icons()
        
        modes = ["NX", "CTR", "CAFE", "WELCOME"]
        idx = self.console_selector.currentIndex() if hasattr(self, "console_selector") else -1
        active_console = modes[idx] if idx >= 0 and idx < len(modes) else self.config.get("console_mode", "WELCOME")
        
        theme_pref = self.config.get("theme", "auto")
        is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
        
        if active_console == "NX":
            self.setWindowIcon(QIcon(self.get_svg_icon(NX_LOGO_SVG)))
        elif active_console == "CAFE":
            self.setWindowIcon(QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))
        elif active_console == "CTR":
            self.setWindowIcon(QIcon(self.get_svg_icon(CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG)))
        else:
            self.setWindowIcon(QIcon(self.get_svg_icon(TCD_MAIN_LOGO)))
        
        if hasattr(self, "volume_slider") and hasattr(self, "lbl_vol_icon"):
            self._update_vol_icon(self.volume_slider.value())
            
        if hasattr(self, "slider_welcome_vol") and hasattr(self, "lbl_welcome_vol_icon"):
            val = self.slider_welcome_vol.value()
            if val == 0: svg = VOL_MUTE_SVG
            elif val < 50: svg = VOL_LOW_SVG
            else: svg = VOL_HIGH_SVG
            
            cache_key = (svg, is_dark, 20, 20)
            if cache_key in _VOL_CACHE:
                pixmap = _VOL_CACHE[cache_key]
            else:
                pixmap = self.get_svg_icon(svg).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                _VOL_CACHE[cache_key] = pixmap
            self.lbl_welcome_vol_icon.setPixmap(pixmap)
            
        if hasattr(self, "btn_tab_restart"):
            pm_restart = self.get_svg_icon(RESTART_SVG)
            self.btn_tab_restart.setIcon(QIcon(pm_restart))
            
        if hasattr(self, "btn_welcome_ctr"):
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG
            self.btn_welcome_ctr.setIcon(QIcon(self.get_svg_icon(ctr_svg)))

    def _update_combo_box_icons(self):
        if hasattr(self, "console_selector"):
            theme_pref = self.config.get("theme", "auto")
            is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_CLEAN_SVG
            self.console_selector.blockSignals(True)
            self.console_selector.setItemIcon(0, QIcon(self.get_svg_icon(NX_LOGO_SVG)))
            self.console_selector.setItemIcon(1, QIcon(self.get_svg_icon(ctr_svg)))
            self.console_selector.setItemIcon(2, QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))
            self.console_selector.blockSignals(False)

    def _update_vol_icon(self, value):
        if not hasattr(self, "lbl_vol_icon"):
            return
        if value == 0: svg = VOL_MUTE_SVG
        elif value < 50: svg = VOL_LOW_SVG
        else: svg = VOL_HIGH_SVG
        
        theme_pref = self.config.get("theme", "auto")
        is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
        
        cache_key = (svg, is_dark, 18, 18)
        if cache_key in _VOL_CACHE:
            pixmap = _VOL_CACHE[cache_key]
        else:
            pixmap = self.get_svg_icon(svg).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            _VOL_CACHE[cache_key] = pixmap
            
        self.lbl_vol_icon.setPixmap(pixmap)

    def on_volume_changed(self, value):
        if hasattr(self, "audio"):
            self.audio.set_global_volume(value)
        self._update_vol_icon(value)
        self.config["volume"] = value
        
        if not hasattr(self, "_vol_save_timer"):
            self._vol_save_timer = QTimer(self)
            self._vol_save_timer.setSingleShot(True)
            self._vol_save_timer.timeout.connect(lambda: save_config(self.config))
            
        self._vol_save_timer.start(2000)

    def _play_volume_test_sound(self):
        if hasattr(self, "audio") and hasattr(self.audio, "play_test_sound"):
            if self.volume_slider.value() > 0:
                self.audio.play_test_sound()

    def finish_welcome_setup(self, console_index):
        if getattr(self, "_is_finishing_welcome", False):
            return
        self._is_finishing_welcome = True

        console_names = ["NX", "CTR", "CAFE"]
        if not (0 <= console_index < len(console_names)):
            self._is_finishing_welcome = False
            return
        chosen_console = console_names[console_index]

        adv = self.chk_welcome_adv.isChecked() if hasattr(self, "chk_welcome_adv") else False
        logs = self.chk_welcome_logs.isChecked() if hasattr(self, "chk_welcome_logs") else False
        
        self.config["advanced_mode"] = adv
        self.config["advanced_logs"] = logs
        self.config["first_launch"] = False
        self.config["console_mode"] = chosen_console
        
        if hasattr(self, "chk_adv_mode"): 
            self.chk_adv_mode.blockSignals(True)
            self.chk_adv_mode.setChecked(adv)
            self.chk_adv_mode.blockSignals(False)
        if hasattr(self, "chk_adv_logs"): 
            self.chk_adv_logs.blockSignals(True)
            self.chk_adv_logs.setChecked(logs)
            self.chk_adv_logs.blockSignals(False)

        welcome_buttons = [
            getattr(self, "btn_welcome_nx", None),
            getattr(self, "btn_welcome_ctr", None),
            getattr(self, "btn_welcome_cafe", None)
        ]
        btn_map = {0: getattr(self, "btn_welcome_nx", None),
                   1: getattr(self, "btn_welcome_ctr", None),
                   2: getattr(self, "btn_welcome_cafe", None)}
        selected_btn = btn_map.get(console_index)

        for btn in welcome_buttons:
            if btn:
                btn.setEnabled(False)

        if hasattr(self, "audio"):
            self.audio.stop_all()
            self.audio.play_console_click(chosen_console)

        for btn in welcome_buttons:
            if btn and btn != selected_btn:
                op = QGraphicsOpacityEffect(btn)
                btn.setGraphicsEffect(op)
                anim = QPropertyAnimation(op, b"opacity", self)
                anim.setDuration(120)
                anim.setStartValue(1.0)
                anim.setEndValue(0.15)
                anim.setEasingCurve(QEasingCurve.Type.OutQuad)
                anim.start()

        theme_pref = self.config.get("theme", "auto")
        bg_color = "#F8F9FA"
        if theme_pref == "oled":
            bg_color = "#000000"
        elif theme_pref == "dark" or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)()):
            bg_color = "#3C3C44"

        overlay = QWidget(self.centralWidget())
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overlay.setStyleSheet(f"background-color: {bg_color};")
        overlay.setGeometry(self.centralWidget().rect())
        overlay_opacity = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(overlay_opacity)
        overlay_opacity.setOpacity(0.0)
        overlay.show()

        anim_in = QPropertyAnimation(overlay_opacity, b"opacity", self)
        anim_in.setDuration(150)
        anim_in.setStartValue(0.0)
        anim_in.setEndValue(1.0)
        anim_in.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def on_fade_in_complete():
            self.current_console = chosen_console
            
            if hasattr(self, "header_widget"):
                self.header_widget.setVisible(True)
            if hasattr(self, "nav_wrapper"):
                self.nav_wrapper.setVisible(True)
            if hasattr(self, "bottom_widget"):
                self.bottom_widget.setVisible(True)

            if hasattr(self, "console_selector"):
                self.console_selector.blockSignals(True)
                self.console_selector.setCurrentIndex(console_index)
                self.console_selector.blockSignals(False)

            self.sync_nav_buttons(0)

            if hasattr(self, "input_output"):
                self.input_output.blockSignals(True)
                new_out = self.config.get(f"output_dir_{chosen_console.lower()}", "")
                self.input_output.setText(new_out)
                self.config["output_dir"] = new_out
                self.input_output.blockSignals(False)

            save_config(self.config)

            self.tabs.setCurrentIndex(0)
            self.clear_console_output()

            if hasattr(self, "apply_visual_settings"): 
                self.apply_visual_settings()
            if hasattr(self, "apply_console_theme_colors"): 
                self.apply_console_theme_colors()
            if hasattr(self, "refresh_dynamic_icons"): 
                self.refresh_dynamic_icons()
            if hasattr(self, "retranslate_ui"): 
                self.retranslate_ui()
            if hasattr(self, "update_dynamic_ui"): 
                self.update_dynamic_ui()
            if hasattr(self, "update_manual_input_context"): 
                self.update_manual_input_context()
            if hasattr(self, "_update_settings_ui"): 
                self._update_settings_ui()

            if hasattr(self, "audio"):
                self.audio.play_boot(chosen_console)

            anim_out = QPropertyAnimation(overlay_opacity, b"opacity", self)
            anim_out.setDuration(160)
            anim_out.setStartValue(1.0)
            anim_out.setEndValue(0.0)
            anim_out.setEasingCurve(QEasingCurve.Type.OutQuad)

            def on_fade_out_complete():
                overlay.deleteLater()
                self._is_finishing_welcome = False
                if hasattr(self, "console_selector"):
                    self.console_selector.setEnabled(True)
                if hasattr(self, "btn_tab_dl"):
                    self.btn_tab_dl.setEnabled(True)
                if hasattr(self, "btn_tab_cfg"):
                    self.btn_tab_cfg.setEnabled(True)
                if hasattr(self, "btn_tab_credits"):
                    self.btn_tab_credits.setEnabled(True)

            anim_out.finished.connect(on_fade_out_complete)
            anim_out.start()

        anim_in.finished.connect(on_fade_in_complete)
        anim_in.start()

    def update_color_button(self):
        if not hasattr(self, "btn_color"): 
            return
        
        raw_color = str(getattr(self, "pending_color", self.config.get("accent_color", ""))).strip().lower()
        default_colors = ["#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""]
        
        if not raw_color or raw_color in default_colors:
            text_auto = self.T("btn_color_auto") if hasattr(self, "T") else "Auto"
            if text_auto == "btn_color_auto":
                text_auto = "Auto"
            self.btn_color.setText(text_auto)
            self.btn_color.setStyleSheet("")
        else:
            display_hex = raw_color.upper()
            c = QColor(display_hex)
            luma = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255 if c.isValid() else 0
            text_color = "#000000" if luma > 0.5 else "#FFFFFF"
            self.btn_color.setText(display_hex)
            self.btn_color.setStyleSheet(f"background-color: {display_hex}; color: {text_color}; font-weight: bold; border: 1px solid #CED4DA; border-radius: 6px; padding: 6px 16px;")

    def _step_spinner(self):
        if hasattr(self, "lbl_dl_mode") and hasattr(self, "spinner_frames") and self.spinner_frames:
            frame = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
            self.lbl_dl_mode.setText(f" {frame} ")
            self.spinner_idx += 1

    def on_cafe_options_changed(self):
        if hasattr(self, "radio_mlc"):
            if self.radio_mlc.isChecked(): parts = ["MLC"]
            elif self.radio_slc.isChecked(): parts = ["SLC"]
            else: parts = ["MLC", "SLC"]
            
            if hasattr(self, "radio_usa") and self.radio_usa.isChecked(): reg = "USA"
            elif hasattr(self, "radio_jpn") and self.radio_jpn.isChecked(): reg = "JPN"
            else: reg = "EUR"
            
            self.config["cafe_partitions"] = parts
            self.config["cafe_region"] = reg
            self.trigger_auto_save()

    def on_ctr_options_changed(self):
        if hasattr(self, "radio_ctr_usa") and self.radio_ctr_usa.isChecked(): reg = "USA"
        elif hasattr(self, "radio_ctr_jpn") and self.radio_ctr_jpn.isChecked(): reg = "JPN"
        elif hasattr(self, "radio_ctr_aus") and self.radio_ctr_aus.isChecked(): reg = "AUS"
        elif hasattr(self, "radio_ctr_kor") and self.radio_ctr_kor.isChecked(): reg = "KOR"
        elif hasattr(self, "radio_ctr_chn") and self.radio_ctr_chn.isChecked(): reg = "CHN"
        elif hasattr(self, "radio_ctr_twn") and self.radio_ctr_twn.isChecked(): reg = "TWN"
        else: reg = "EUR"
        
        if hasattr(self, "radio_new_3ds") and self.radio_new_3ds.isChecked(): model = "NEW"
        else: model = "OLD"

        self.config["ctr_region"] = reg
        self.config["ctr_model"] = model
        self.trigger_auto_save()

    def _handle_nsp_toggle(self, checked):
        if checked:
            title = self.T("nsp_warning_title") if hasattr(self, "T") else "Avertissement !"
            msg = self.T("nsp_warning_msg") if hasattr(self, "T") else "La création de fichiers NSP est expérimentale et destinée UNIQUEMENT à la préservation ou aux tests sur émulateur. N'installez PAS ces NSP sur une console physique, cela pourrait causer une corruption.\n\nÊtes-vous sûr de vouloir activer cette option ?"
            
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(title)
            msg_box.setText(msg)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            
            btn_yes_text = self.T("btn_yes") if hasattr(self, "T") else "Oui"
            btn_no_text = self.T("btn_no") if hasattr(self, "T") else "Non"
            
            btn_yes = msg_box.addButton(btn_yes_text, QMessageBox.ButtonRole.YesRole)
            btn_no = msg_box.addButton(btn_no_text, QMessageBox.ButtonRole.NoRole)
            msg_box.setDefaultButton(btn_no)
            
            if hasattr(self, "get_app_icon"):
                msg_box.setWindowIcon(self.get_app_icon())
            
            msg_box.exec()
            
            if msg_box.clickedButton() == btn_no:
                if hasattr(self, "chk_build_nsp"):
                    self.chk_build_nsp.blockSignals(True)
                    self.chk_build_nsp.setChecked(False)
                    self.chk_build_nsp.blockSignals(False)
                if hasattr(self, "config"):
                    self.config["build_nsp"] = False
                return
                
        if hasattr(self, "config"):
            self.config["build_nsp"] = checked
        self.trigger_auto_save()

    def update_dynamic_ui(self):
        is_nx = (self.current_console == "NX")
        is_ctr = (self.current_console == "CTR")
        is_cafe = (self.current_console == "CAFE")
        is_welcome = (self.current_console == "WELCOME")
        is_adv = self.chk_adv_mode.isChecked() if hasattr(self, "chk_adv_mode") else False
            
        if hasattr(self, "header_widget"):
            self.header_widget.setVisible(not is_welcome)
        if hasattr(self, "nav_wrapper"):
            self.nav_wrapper.setVisible(not is_welcome)
        if hasattr(self, "btn_tab_credits"):
            self.btn_tab_credits.setVisible(not is_welcome)
        if hasattr(self, "volume_slider") and self.volume_slider.parentWidget():
            self.volume_slider.parentWidget().setVisible(not is_welcome)
            
        if hasattr(self, "chk_unlimited_console"):
            self.chk_unlimited_console.setVisible(is_adv and not is_welcome)
            
        if hasattr(self, "radio_latest") and hasattr(self, "radio_manual"):
            if is_cafe or is_ctr or is_nx:
                self.radio_latest.setVisible(True)
                self.radio_manual.setVisible(is_adv)
                if not is_adv and self.radio_manual.isChecked(): 
                    self.radio_latest.setChecked(True)
            else:
                self.radio_latest.setVisible(False)
                self.radio_manual.setVisible(False)
                
            is_manual = self.radio_manual.isChecked()
            
            if hasattr(self, "input_manual"):
                self.input_manual.setVisible((is_nx or is_cafe or is_ctr) and is_manual)
            if hasattr(self, "lbl_manual_hint"):
                self.lbl_manual_hint.setVisible(False)

        if hasattr(self, "radio_list"):
            show_list = bool(is_nx and is_adv)
            self.radio_list.setVisible(show_list)
            if not show_list:
                if hasattr(self, "list_input_container"):
                    self.list_input_container.setVisible(False)
                if self.radio_list.isChecked():
                    self.radio_latest.setChecked(True)
            else:
                if hasattr(self, "list_input_container"):
                    self.list_input_container.setVisible(self.radio_list.isChecked())
                
        if hasattr(self, "page_target_cafe"):
            self.page_target_cafe.setVisible(is_cafe)
            is_cafe_manual = (is_cafe and hasattr(self, "radio_manual") and self.radio_manual.isChecked())
            
            if hasattr(self, "lbl_manual_hint_cafe"): self.lbl_manual_hint_cafe.setVisible(False)
            if hasattr(self, "frame_warn_cafe"): self.frame_warn_cafe.setVisible(is_cafe_manual)
            
            show_reg = is_cafe and not is_cafe_manual
            if hasattr(self, "cafe_reg_container"): self.cafe_reg_container.setVisible(show_reg)
            
        if hasattr(self, "page_target_ctr"):
            self.page_target_ctr.setVisible(is_ctr)
            if hasattr(self, "ctr_reg_container"): self.ctr_reg_container.setVisible(is_ctr)
            
        nx_settings = ["hactool", "keys", "prodinfo", "cert"]
        for setting in nx_settings:
            if hasattr(self, "labels_config") and setting in self.labels_config: 
                self.labels_config[setting].setVisible(is_nx)
            if hasattr(self, f"input_{setting}"): 
                getattr(self, f"input_{setting}").setVisible(is_nx)
            if hasattr(self, f"btn_browse_{setting}"): 
                getattr(self, f"btn_browse_{setting}").setVisible(is_nx)
            
        if hasattr(self, "lbl_otp"): self.lbl_otp.setVisible(is_cafe)
        if hasattr(self, "input_otp"): self.input_otp.setVisible(is_cafe)
        if hasattr(self, "btn_browse_otp"): self.btn_browse_otp.setVisible(is_cafe)
        
        if hasattr(self, "lbl_boot9"): self.lbl_boot9.setVisible(is_ctr)
        if hasattr(self, "input_boot9"): self.input_boot9.setVisible(is_ctr)
        if hasattr(self, "btn_browse_boot9"): self.btn_browse_boot9.setVisible(is_ctr)
        
        if hasattr(self, "btn_update"):
            self.btn_update.setText(self.T("btn_update"))
            
        self.refresh_dynamic_icons()

        if hasattr(self, "chk_build_nsp"):
            show_nsp = bool(is_adv and is_nx)
            self.chk_build_nsp.setVisible(show_nsp)

            if not show_nsp:
                self.chk_build_nsp.blockSignals(True)
                self.chk_build_nsp.setChecked(False)
                self.chk_build_nsp.blockSignals(False)
                if hasattr(self, "config"):
                    self.config["build_nsp"] = False

    def set_ui_locked(self, locked):
        self.btn_tab_cfg.setEnabled(not locked)
        self.btn_tab_credits.setEnabled(not locked)
        self.btn_tab_restart.setEnabled(not locked)
        self.console_selector.setEnabled(not locked)
        
        if hasattr(self, "radio_latest"): self.radio_latest.setEnabled(not locked)
        if hasattr(self, "radio_list"): self.radio_list.setEnabled(not locked)
        if hasattr(self, "radio_manual"): self.radio_manual.setEnabled(not locked)
        if hasattr(self, "input_manual"): self.input_manual.setEnabled(not locked)
        if hasattr(self, "page_target_cafe"): self.page_target_cafe.setEnabled(not locked)
        if hasattr(self, "page_target_ctr"): self.page_target_ctr.setEnabled(not locked)
        if hasattr(self, "btn_clear_console"): self.btn_clear_console.setEnabled(not locked)
        if hasattr(self, "chk_unlimited_console"): self.chk_unlimited_console.setEnabled(not locked)
        if hasattr(self, "btn_update"): self.btn_update.setEnabled(not locked)

    def clear_console_output(self, *args):
        if getattr(self, "worker", None) is not None and self.worker.isRunning(): 
            return
            
        if hasattr(self, "console"): self.console.clear()
        if hasattr(self, "progress_bar"): self.progress_bar.setValue(0)
        if hasattr(self, "lbl_progress_pct"): self.lbl_progress_pct.setText("0%")
        if hasattr(self, "_last_rendered_pct"): self._last_rendered_pct = 0
        if hasattr(self, "spinner_timer"): self.spinner_timer.stop()
        if hasattr(self, "symbol_reset_timer"): self.symbol_reset_timer.stop()
        if hasattr(self, "update_dl_mode_label"):
            self.update_dl_mode_label()

    def switch_tab_animated(self, index):
        if self.tabs.currentIndex() == index: 
            return
        if getattr(self, "_is_switching_tab", False):
            return
        self._is_switching_tab = True
            
        self.btn_tab_dl.setEnabled(False)
        self.btn_tab_cfg.setEnabled(False)
        self.btn_tab_credits.setEnabled(False)
        
        if hasattr(self, "fade_overlay") and self.fade_overlay:
            try:
                self.fade_overlay.deleteLater()
            except Exception:
                pass
            self.fade_overlay = None
        
        self.fade_overlay = QWidget(self.tabs)
        self.fade_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.fade_overlay.resize(self.tabs.size())
        
        theme_pref = self.config.get("theme", "auto")
        bg_color = "#F8F9FA"
        if theme_pref == "oled": bg_color = "#000000"
        elif theme_pref == "dark" or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)()): bg_color = "#3C3C44"
        
        self.fade_overlay.setStyleSheet(f"background-color: {bg_color};")
        self.overlay_opacity = QGraphicsOpacityEffect(self.fade_overlay)
        self.fade_overlay.setGraphicsEffect(self.overlay_opacity)
        self.overlay_opacity.setOpacity(0.0)
        self.fade_overlay.show()
        
        self.anim_fade_in = QPropertyAnimation(self.overlay_opacity, b"opacity")
        self.anim_fade_in.setDuration(50)
        self.anim_fade_in.setStartValue(0.0)
        self.anim_fade_in.setEndValue(1.0)
        self.anim_fade_in.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        def on_fade_in_finished():
            self.tabs.setCurrentIndex(index)
            self.sync_nav_buttons(index)
            
            self.anim_fade_out = QPropertyAnimation(self.overlay_opacity, b"opacity")
            self.anim_fade_out.setDuration(60)
            self.anim_fade_out.setStartValue(1.0)
            self.anim_fade_out.setEndValue(0.0)
            self.anim_fade_out.setEasingCurve(QEasingCurve.Type.OutQuad)
            
            def on_fade_out_finished():
                if hasattr(self, "fade_overlay") and self.fade_overlay:
                    self.fade_overlay.deleteLater()
                    self.fade_overlay = None
                self._is_switching_tab = False
                if not (getattr(self, "worker", None) is not None and self.worker.isRunning()):
                    self.btn_tab_dl.setEnabled(True)
                    self.btn_tab_cfg.setEnabled(True)
                    self.btn_tab_credits.setEnabled(True)
                    
            self.anim_fade_out.finished.connect(on_fade_out_finished)
            self.anim_fade_out.start()
            
        self.anim_fade_in.finished.connect(on_fade_in_finished)
        self.anim_fade_in.start()

    def sync_nav_buttons(self, index):
        if index == 0: self.btn_tab_dl.setChecked(True)
        elif index == 1: self.btn_tab_cfg.setChecked(True)
        elif index == 2: self.btn_tab_credits.setChecked(True)

    def prompt_restart(self, *args):
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("restart_blocked_title"))
            msg_box.setText(self.T("restart_blocked_msg"))
            msg_box.exec()
            return
            
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("restart_title"))
        msg_box.setText(self.T("restart_msg"))
        
        btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
        msg_box.setDefaultButton(btn_no)
        msg_box.exec()
        
        if msg_box.clickedButton() == btn_yes: 
            self.execute_restart()

    def execute_restart(self, *args):
        self._is_restarting = True
        
        if hasattr(self, "save_timer") and self.save_timer.isActive():
            self.save_timer.stop()
        if hasattr(self, "rainbow_timer") and self.rainbow_timer.isActive():
            self.rainbow_timer.stop()
        if hasattr(self, "_sigint_timer") and self._sigint_timer.isActive():
            self._sigint_timer.stop()
        if hasattr(self, "updater_spinner_timer") and self.updater_spinner_timer.isActive():
            self.updater_spinner_timer.stop()

        if hasattr(self, "audio"):
            try:
                if hasattr(self.audio, "cleanup"):
                    self.audio.cleanup()
                elif hasattr(self.audio, "stop_all"):
                    self.audio.stop_all()
            except Exception:
                pass

        try:
            if hasattr(self, "commit_save_to_disk"):
                self.commit_save_to_disk()
            elif hasattr(self, "config"):
                save_config(self.config)
        except Exception:
            pass

        self.perform_security_cleanup()

        if hasattr(self, "app_lock") and self.app_lock.isLocked():
            try:
                self.app_lock.unlock()
            except Exception:
                pass

        script_path = os.path.abspath(sys.argv[0])
        args = [sys.executable, script_path] + sys.argv[1:]
        kwargs = {"cwd": os.path.dirname(script_path) or os.getcwd()}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True

        try:
            subprocess.Popen(args, **kwargs)
        except Exception as e:
            print(f"[RESTART ERROR] {e}")

        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def show_corruption_warning(self, *args):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("msg_corrupted_title"))
        msg_box.setText(self.T("msg_corrupted_desc"))
        msg_box.exec()

    def show_easter_egg(self, *args):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("msg_easter_egg_title"))
        msg_box.setText(self.T("msg_easter_egg_desc"))
        msg_box.exec()

    def show_eula_if_needed(self, *args):
        show_full_eula, dont_show_again = True, False
        if os.path.exists(EULA_FILE):
            try:
                with open(EULA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("accepted") is True: 
                        show_full_eula = False
                    if data.get("dont_show_again") is True: 
                        dont_show_again = True
            except Exception: 
                pass
                
        if dont_show_again:
            if self.current_console != "WELCOME":
                QTimer.singleShot(200, lambda: self.start_update_check(auto=True))
            return
            
        self._eula_active = True
        try:
            dialog = EulaDialog(self, show_full_eula, getattr(self, "T", lambda x: x))
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    os.makedirs(str(APPDATA_DIR), exist_ok=True)
                    with open(EULA_FILE, "w", encoding="utf-8") as f:
                        json.dump({"accepted": True, "dont_show_again": dialog.dont_show_again, "date": datetime.datetime.now().isoformat()}, f, indent=4)
                except Exception: 
                    pass
            else:
                sys.exit(0)
        finally:
            self._eula_active = False

        if self.current_console != "WELCOME":
            QTimer.singleShot(200, lambda: self.start_update_check(auto=True))

    def switch_console_mode(self, index):
        if index == 3: return
        if getattr(self, "_is_switching_console", False): return
        
        modes = ["NX", "CTR", "CAFE", "WELCOME"]
        if not (0 <= index < len(modes)):
            return
        new_mode = modes[index]
        if new_mode == getattr(self, "current_console", None):
            return
            
        self._is_switching_console = True
        self.current_console = new_mode
        self.config["console_mode"] = new_mode
        
        self.console_selector.setEnabled(False)
        if hasattr(self, "audio"):
            self.audio.fade_out_fast(duration=50)
        self.sync_nav_buttons(0)
        
        if hasattr(self, "console_fade_overlay") and self.console_fade_overlay:
            try:
                self.console_fade_overlay.deleteLater()
            except Exception:
                pass
            self.console_fade_overlay = None
            
        self.console_fade_overlay = QWidget(self.tabs)
        self.console_fade_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.console_fade_overlay.resize(self.tabs.size())
        
        theme_pref = self.config.get("theme", "auto")
        bg_color = "#F8F9FA"
        if theme_pref == "oled": bg_color = "#000000"
        elif theme_pref == "dark" or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)()): bg_color = "#3C3C44"
        
        self.console_fade_overlay.setStyleSheet(f"background-color: {bg_color};")
        self.console_overlay_opacity = QGraphicsOpacityEffect(self.console_fade_overlay)
        self.console_fade_overlay.setGraphicsEffect(self.console_overlay_opacity)
        self.console_overlay_opacity.setOpacity(0.0)
        self.console_fade_overlay.show()
        
        self.anim_console_fade_in = QPropertyAnimation(self.console_overlay_opacity, b"opacity")
        self.anim_console_fade_in.setDuration(50)
        self.anim_console_fade_in.setStartValue(0.0)
        self.anim_console_fade_in.setEndValue(1.0)
        self.anim_console_fade_in.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        def d_on_fade_in_finished():
            if hasattr(self, "input_output"): 
                self.input_output.blockSignals(True)
                
            self.clear_console_output()
            if hasattr(self, "audio"):
                self.audio.play_boot(new_mode)
            
            if hasattr(self, "get_current_accent_color"): 
                self.get_current_accent_color()
                
            if hasattr(self, "input_output"):
                new_out = self.config.get(f"output_dir_{new_mode.lower()}", "")
                self.input_output.setText(new_out)
                self.config["output_dir"] = new_out
                self.input_output.blockSignals(False)
                
            if hasattr(self, "apply_visual_settings"): self.apply_visual_settings()
            if hasattr(self, "apply_console_theme_colors"): self.apply_console_theme_colors()
            
            if hasattr(self, "retranslate_ui"):
                self.retranslate_ui()
            
            if hasattr(self, "btn_update"):
                self.btn_update.setText(self.T("btn_update"))
                
            self.update_dynamic_ui()
            
            if hasattr(self, "update_manual_input_context"):
                self.update_manual_input_context()
                        
            if hasattr(self, "_update_settings_ui"): 
                self._update_settings_ui()
                
            self.tabs.setCurrentIndex(0)
            
            self.anim_console_fade_out = QPropertyAnimation(self.console_overlay_opacity, b"opacity")
            self.anim_console_fade_out.setDuration(60)
            self.anim_console_fade_out.setStartValue(1.0)
            self.anim_console_fade_out.setEndValue(0.0)
            self.anim_console_fade_out.setEasingCurve(QEasingCurve.Type.OutQuad)
            
            def d_on_fade_out_finished():
                if hasattr(self, "console_fade_overlay") and self.console_fade_overlay:
                    self.console_fade_overlay.deleteLater()
                    self.console_fade_overlay = None
                self._is_switching_console = False
                if not (getattr(self, "worker", None) is not None and self.worker.isRunning()):
                    self.console_selector.setEnabled(True)
                    self.btn_tab_dl.setEnabled(True)
                    self.btn_tab_cfg.setEnabled(True)
                    self.btn_tab_credits.setEnabled(True)
                if hasattr(self, "trigger_auto_save"):
                    self.trigger_auto_save()
                else:
                    save_config(self.config)
                    
            self.anim_console_fade_out.finished.connect(d_on_fade_out_finished)
            self.anim_console_fade_out.start()
            
        self.anim_console_fade_in.finished.connect(d_on_fade_in_finished)
        self.anim_console_fade_in.start()

    def handle_fatal_crash(self, exc_type, exc_value, exc_traceback):
        self.perform_security_cleanup()
        sys.__excepthook__(exc_type, exc_value, exc_traceback)