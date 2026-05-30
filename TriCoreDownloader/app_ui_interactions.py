import os
import sys
import datetime
import subprocess
import json
from PyQt6.QtWidgets import (QMessageBox, QWidget, QGraphicsOpacityEffect, QDialog, 
                             QComboBox, QTextBrowser, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QCheckBox, QApplication)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QByteArray
from PyQt6.QtGui import QIcon, QCursor, QPixmap

from .config import EULA_FILE, CONFIG_FILE, APPDATA_DIR, save_config
from .custom_widgets import EulaDialog
from .logos import (NX_LOGO_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_BLACK_SVG, 
                    CTR_LOGO_CLEAN_SVG, CAFE_LOGO_SVG, VOL_MUTE_SVG, 
                    VOL_LOW_SVG, VOL_HIGH_SVG, RESTART_SVG, TCD_MAIN_LOGO)

class UiInteractionsMixin:
    def verify_application_version(self):
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
                pm = QPixmap()
                pm.loadFromData(QByteArray(TCD_MAIN_LOGO), "SVG")
                if not pm.isNull():
                    dialog.setWindowIcon(QIcon(pm))
            except:
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
                    if CONFIG_FILE.exists(): CONFIG_FILE.unlink()
                    if EULA_FILE.exists(): EULA_FILE.unlink()
                except:
                    pass
                subprocess.Popen([sys.executable] + sys.argv)
                QApplication.quit()
                sys.exit(0)
            else:
                self.config.pop("_version_status", None)
                self.config.pop("_old_version", None)

        elif status == "upgrade":
            dialog = QDialog(self)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
            
            dialog.setWindowTitle(self.T("msg_upgrade_title"))
            try:
                pm = QPixmap()
                pm.loadFromData(QByteArray(TCD_MAIN_LOGO), "SVG")
                if not pm.isNull():
                    dialog.setWindowIcon(QIcon(pm))
            except:
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
        self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_frames)
        self.lbl_update_spinner.setText(self.spinner_frames[self.spinner_idx])

    def manual_check_updates(self, *args):
        self.start_update_check(auto=False)

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
        color = b"#FFFFFF" if is_dark else b"#333333"
        colored_svg = svg_bytes.replace(b"currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(colored_svg))
        return pixmap

    def refresh_dynamic_icons(self):
        self._update_combo_box_icons()
        
        modes = ["NX", "CTR", "CAFE", "WELCOME"]
        idx = self.console_selector.currentIndex() if hasattr(self, "console_selector") else -1
        active_console = modes[idx] if idx >= 0 and idx < len(modes) else self.config.get("console_mode", "WELCOME")
        
        if active_console == "NX":
            self.setWindowIcon(QIcon(self.get_svg_icon(NX_LOGO_SVG)))
        elif active_console == "CAFE":
            self.setWindowIcon(QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))
        elif active_console == "CTR":
            theme_pref = self.config.get("theme", "auto")
            is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
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
            pixmap = self.get_svg_icon(svg).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.lbl_welcome_vol_icon.setPixmap(pixmap)
            
        if hasattr(self, "btn_tab_restart"):
            pm_restart = self.get_svg_icon(RESTART_SVG)
            self.btn_tab_restart.setIcon(QIcon(pm_restart))
            
        if hasattr(self, "btn_welcome_ctr"):
            theme_pref = self.config.get("theme", "auto")
            is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG
            self.btn_welcome_ctr.setIcon(QIcon(self.get_svg_icon(ctr_svg)))

    def _update_combo_box_icons(self):
        if hasattr(self, "console_selector"):
            theme_pref = self.config.get("theme", "auto")
            is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_CLEAN_SVG
            self.console_selector.setItemIcon(0, QIcon(self.get_svg_icon(NX_LOGO_SVG)))
            self.console_selector.setItemIcon(1, QIcon(self.get_svg_icon(ctr_svg)))
            self.console_selector.setItemIcon(2, QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))
            self.console_selector.setIconSize(QSize(18, 18))

    def _update_vol_icon(self, value):
        if value == 0: svg = VOL_MUTE_SVG
        elif value < 50: svg = VOL_LOW_SVG
        else: svg = VOL_HIGH_SVG
        pixmap = self.get_svg_icon(svg).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
        adv = self.chk_welcome_adv.isChecked()
        logs = self.chk_welcome_logs.isChecked()
        
        self.config["advanced_mode"] = adv
        self.config["advanced_logs"] = logs
        self.config["first_launch"] = False
        save_config(self.config)
        
        if hasattr(self, "chk_adv_mode"): 
            self.chk_adv_mode.blockSignals(True)
            self.chk_adv_mode.setChecked(adv)
            self.chk_adv_mode.blockSignals(False)
        if hasattr(self, "chk_adv_logs"): 
            self.chk_adv_logs.blockSignals(True)
            self.chk_adv_logs.setChecked(logs)
            self.chk_adv_logs.blockSignals(False)
            
        console_names = ["NX", "CTR", "CAFE"]
        chosen_console = console_names[console_index]
        self.audio.stop_all()
        self.audio.play_console_click(chosen_console)
        
        self.welcome_fade = QPropertyAnimation(self, b"windowOpacity")
        self.welcome_fade.setDuration(200)
        self.welcome_fade.setStartValue(1.0)
        self.welcome_fade.setEndValue(0.0)
        self.welcome_fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        def on_fade_out_finished():
            self.header_widget.setVisible(True)
            self.nav_wrapper.setVisible(False if console_index == 3 else True)
            self.bottom_widget.setVisible(True)
            self.console_selector.setCurrentIndex(console_index)
            
            self.welcome_fade_in = QPropertyAnimation(self, b"windowOpacity")
            self.welcome_fade_in.setDuration(300)
            self.welcome_fade_in.setStartValue(0.0)
            self.welcome_fade_in.setEndValue(1.0)
            self.welcome_fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
            self.welcome_fade_in.start()
            
        self.welcome_fade.finished.connect(on_fade_out_finished)
        self.welcome_fade.start()

    def update_color_button(self):
        if not hasattr(self, "btn_color"): 
            return
        color = self.config.get("accent_color", "").strip()
        default_colors = ["#c6a1fa", "#bc181a", "#4ebcff", ""]
        if color.lower() in default_colors or not color:
            self.btn_color.setText(self.T("btn_color_auto"))
            self.btn_color.setStyleSheet("")
        else:
            self.btn_color.setText(color.upper())
            self.btn_color.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;")

    def _step_spinner(self):
        if hasattr(self, "lbl_dl_mode"):
            frame = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
            self.lbl_dl_mode.setText(f" {frame} ")
            self.spinner_idx += 1

    def on_cafe_options_changed(self):
        if hasattr(self, "radio_mlc"):
            if self.radio_mlc.isChecked(): parts = ["MLC"]
            elif self.radio_slc.isChecked(): parts = ["SLC"]
            else: parts = ["MLC", "SLC"]
            
            if self.radio_usa.isChecked(): reg = "USA"
            elif self.radio_jpn.isChecked(): reg = "JPN"
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
                self.chk_build_nsp.blockSignals(True)
                self.chk_build_nsp.setChecked(False)
                self.chk_build_nsp.blockSignals(False)
                if hasattr(self, "config"):
                    self.config["build_nsp"] = False
                return
                
        if hasattr(self, "config"):
            self.config["build_nsp"] = checked

    def update_dynamic_ui(self):
        is_nx = self.current_console == "NX"
        is_ctr = self.current_console == "CTR"
        is_cafe = self.current_console == "CAFE"
        is_welcome = self.current_console == "WELCOME"
        is_adv = False
        
        if hasattr(self, "chk_adv_mode"):
            is_adv = self.chk_adv_mode.isChecked()
            
        if hasattr(self, "btn_tab_credits"):
            self.btn_tab_credits.setVisible(not is_welcome)
        if hasattr(self, "volume_slider") and self.volume_slider.parentWidget():
            self.volume_slider.parentWidget().setVisible(not is_welcome)
            
        if hasattr(self, "chk_unlimited_console"):
            self.chk_unlimited_console.setVisible(is_adv and not is_welcome)
            
        if hasattr(self, "radio_latest") and hasattr(self, "radio_manual"):
            if is_cafe or is_ctr:
                self.radio_latest.setVisible(True)
                self.radio_manual.setVisible(is_adv)
                if not is_adv and self.radio_manual.isChecked(): 
                    self.radio_latest.setChecked(True)
            elif is_nx:
                self.radio_latest.setVisible(True)
                self.radio_manual.setVisible(is_adv)
                if not is_adv and self.radio_manual.isChecked():
                    self.radio_latest.setChecked(True)
            else:
                self.radio_latest.setVisible(False)
                self.radio_manual.setVisible(False)
                
            is_manual = self.radio_manual.isChecked()
            
            if is_nx and is_manual:
                self.input_manual.setVisible(True)
                if hasattr(self, "lbl_manual_hint"): self.lbl_manual_hint.setVisible(False)
            elif (is_cafe or is_ctr) and is_manual:
                self.input_manual.setVisible(True)
                if hasattr(self, "lbl_manual_hint"): self.lbl_manual_hint.setVisible(False)
            else:
                self.input_manual.setVisible(False)
                if hasattr(self, "lbl_manual_hint"): self.lbl_manual_hint.setVisible(False)
                
        if hasattr(self, "page_target_cafe"):
            self.page_target_cafe.setVisible(is_cafe)
            is_cafe_manual = (is_cafe and hasattr(self, "radio_manual") and self.radio_manual.isChecked())
            
            if hasattr(self, "lbl_manual_hint_cafe"): self.lbl_manual_hint_cafe.setVisible(False)
            if hasattr(self, "frame_warn_cafe"): self.frame_warn_cafe.setVisible(is_cafe_manual)
            
            show_reg = is_cafe and not is_cafe_manual
            if hasattr(self, "cafe_reg_container"): self.cafe_reg_container.setVisible(show_reg)
            
        if hasattr(self, "page_target_ctr"):
            self.page_target_ctr.setVisible(is_ctr)
            show_ctr_reg = is_ctr 
            
            if hasattr(self, "ctr_reg_container"): self.ctr_reg_container.setVisible(show_ctr_reg)
            
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

        # --- GESTION DU BOUTON NSP EXACTEMENT AU BON MOMENT ---
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
        if hasattr(self, "spinner_timer"): self.spinner_timer.stop()
        if hasattr(self, "symbol_reset_timer"): self.symbol_reset_timer.stop()
        self.update_dl_mode_label()

    def switch_tab_animated(self, index):
        if self.tabs.currentIndex() == index: 
            return
            
        self.btn_tab_dl.setEnabled(False)
        self.btn_tab_cfg.setEnabled(False)
        self.btn_tab_credits.setEnabled(False)
        
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
        self.anim_fade_in.setDuration(120)
        self.anim_fade_in.setStartValue(0.0)
        self.anim_fade_in.setEndValue(1.0)
        self.anim_fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        def on_fade_in_finished():
            self.tabs.setCurrentIndex(index)
            self.sync_nav_buttons(index)
            
            self.anim_fade_out = QPropertyAnimation(self.overlay_opacity, b"opacity")
            self.anim_fade_out.setDuration(120)
            self.anim_fade_out.setStartValue(1.0)
            self.anim_fade_out.setEndValue(0.0)
            self.anim_fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
            
            def on_fade_out_finished():
                self.fade_overlay.deleteLater()
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
        self.perform_security_cleanup()
        subprocess.Popen([sys.executable] + sys.argv)
        QApplication.quit()
        sys.exit(0)

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
            except: 
                pass
                
        if dont_show_again: 
            return
            
        dialog = EulaDialog(self, show_full_eula, getattr(self, "T", lambda x: x))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                os.makedirs(APPDATA_DIR, exist_ok=True)
                with open(EULA_FILE, "w", encoding="utf-8") as f:
                    json.dump({"accepted": True, "dont_show_again": dialog.dont_show_again, "date": datetime.datetime.now().isoformat()}, f, indent=4)
            except Exception: 
                pass
        else:
            sys.exit(0)

    def switch_console_mode(self, index):
        if index == 3: return
        
        self.console_selector.setEnabled(False)
        self.audio.fade_out_fast(duration=120)
        self.sync_nav_buttons(0)
        
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
        self.anim_console_fade_in.setDuration(120)
        self.anim_console_fade_in.setStartValue(0.0)
        self.anim_console_fade_in.setEndValue(1.0)
        self.anim_console_fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        def d_on_fade_in_finished():
            if hasattr(self, "input_output"): 
                self.input_output.blockSignals(True)
                
            self.clear_console_output()
            modes = ["NX", "CTR", "CAFE", "WELCOME"]
            new_mode = modes[index]
            
            self.audio.play_boot(new_mode)
            self.current_console = new_mode
            self.config["console_mode"] = new_mode
            
            if hasattr(self, "get_current_accent_color"): 
                self.get_current_accent_color()
                
            if hasattr(self, "input_output"):
                new_out = self.config.get(f"output_dir_{new_mode.lower()}", "")
                self.input_output.setText(new_out)
                self.config["output_dir"] = new_out
                self.input_output.blockSignals(False)
                
            save_config(self.config)
            
            if hasattr(self, "apply_visual_settings"): self.apply_visual_settings()
            self.apply_console_theme_colors()
            self.refresh_dynamic_icons()
            
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
            self.anim_console_fade_out.setDuration(120)
            self.anim_console_fade_out.setStartValue(1.0)
            self.anim_console_fade_out.setEndValue(0.0)
            self.anim_console_fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
            
            def d_on_fade_out_finished():
                self.console_fade_overlay.deleteLater()
                if not (getattr(self, "worker", None) is not None and self.worker.isRunning()):
                    self.console_selector.setEnabled(True)
                    self.btn_tab_dl.setEnabled(True)
                    self.btn_tab_cfg.setEnabled(True)
                    self.btn_tab_credits.setEnabled(True)
                    
            self.anim_console_fade_out.finished.connect(d_on_fade_out_finished)
            self.anim_console_fade_out.start()
            
        self.anim_console_fade_in.finished.connect(d_on_fade_in_finished)
        self.anim_console_fade_in.start()

    def handle_fatal_crash(self, exc_type, exc_value, exc_traceback):
        self.perform_security_cleanup()
        sys.__excepthook__(exc_type, exc_value, exc_traceback)