import os
import sys
import datetime
import subprocess
import json
import stat
from pathlib import Path
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QGraphicsOpacityEffect, QDialog,
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QColor

from .config import EULA_FILE, CONFIG_FILE, APPDATA_DIR, APP_VERSION, save_config
from .custom_widgets import EulaDialog
from .logos import (
    NX_LOGO_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_BLACK_SVG, CTR_LOGO_CLEAN_SVG,
    CAFE_LOGO_SVG, VOL_MUTE_SVG, VOL_LOW_SVG, VOL_HIGH_SVG,
    RESTART_SVG, TCD_MAIN_LOGO
)

_SVG_CACHE = {}
_VOL_CACHE = {}


def get_mac_app_bundle_path(path):
    abs_path = os.path.abspath(path)
    parts = abs_path.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep.join(parts[:i + 1])
    return abs_path


def check_path_permissions(target_path, check_writable=True):
    try:
        p = os.path.abspath(target_path)
        while not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent

        mode = os.R_OK | (os.W_OK if check_writable else 0)
        return os.access(p, mode)
    except Exception:
        return False


class UiInteractionsMixin:
    def _is_dark_theme(self):
        theme_pref = self.config.get("theme", "auto")
        return theme_pref in ("dark", "oled") or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())

    def verify_application_version(self):
        if getattr(self, "_eula_active", False):
            QTimer.singleShot(300, self.verify_application_version)
            return

        status = self.config.get("_version_status")
        saved_version = self.config.get("_old_version", "0.0.0")

        if not status:
            return

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

            for b in (btn_force, btn_reset, btn_exit):
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet("padding: 6px 16px; font-weight: bold;")
                btn_layout.addWidget(b)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)
            layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

            choice = {"action": "exit"}
            btn_force.clicked.connect(lambda: (choice.update({"action": "launch"}), dialog.accept()))
            btn_reset.clicked.connect(lambda: (choice.update({"action": "reset"}), dialog.accept()))
            btn_exit.clicked.connect(lambda: (choice.update({"action": "exit"}), dialog.reject()))

            dialog.exec()

            if choice["action"] == "exit":
                sys.exit(0)
            elif choice["action"] == "reset":
                try:
                    if os.path.exists(CONFIG_FILE) and os.access(CONFIG_FILE, os.W_OK):
                        os.remove(CONFIG_FILE)
                    if os.path.exists(EULA_FILE) and os.access(EULA_FILE, os.W_OK):
                        os.remove(EULA_FILE)
                except Exception:
                    pass
                self.execute_restart()
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

            self.config.pop("_version_status", None)
            self.config.pop("_old_version", None)

    def update_update_spinner(self):
        if hasattr(self, "lbl_update_spinner") and getattr(self, "spinner_frames", None):
            self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_frames)
            self.lbl_update_spinner.setText(self.spinner_frames[self.spinner_idx])

    def manual_check_updates(self, *args, **kwargs):
        try:
            from .custom_widgets import launch_updater
            try:
                launch_updater(self, getattr(self, "T", None))
            except TypeError:
                try:
                    launch_updater(self)
                except TypeError:
                    launch_updater()
        except Exception as e:
            if hasattr(self, "console_write"):
                self.console_write(f"[ERROR] Unable to launch the updater : {e}\n")

    def on_unlimited_console_toggled(self, checked):
        if getattr(self, "_is_loading_ui", False):
            return
        self.config["unlimited_console"] = bool(checked)
        if hasattr(self, "console"):
            self.console.setMaximumBlockCount(0 if checked else 1000)
        self.trigger_auto_save()

    def get_svg_icon(self, svg_bytes):
        if not svg_bytes:
            svg_bytes = TCD_MAIN_LOGO

        is_dark = self._is_dark_theme()
        cache_key = (svg_bytes, is_dark)
        if cache_key in _SVG_CACHE:
            return _SVG_CACHE[cache_key]

        if hasattr(self, "_get_cached_icon"):
            _, pm = self._get_cached_icon(svg_bytes, is_dark)
            if not pm.isNull():
                _SVG_CACHE[cache_key] = pm
                return pm

        color = b"#FFFFFF" if is_dark else b"#333333"
        colored_svg = svg_bytes.replace(b"currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(colored_svg), "SVG")
        _SVG_CACHE[cache_key] = pixmap
        return pixmap

    def refresh_dynamic_icons(self):
        self._update_combo_box_icons()

        modes = ("NX", "CTR", "CAFE", "WELCOME")
        idx = self.console_selector.currentIndex() if hasattr(self, "console_selector") else -1
        active_console = modes[idx] if 0 <= idx < len(modes) else self.config.get("console_mode", "WELCOME")

        is_dark = self._is_dark_theme()

        if sys.platform != "darwin":
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
            svg = VOL_MUTE_SVG if val == 0 else (VOL_LOW_SVG if val < 50 else VOL_HIGH_SVG)
            cache_key = (svg, is_dark, 20, 20)
            if cache_key in _VOL_CACHE:
                pixmap = _VOL_CACHE[cache_key]
            else:
                pixmap = self.get_svg_icon(svg).scaled(
                    20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                _VOL_CACHE[cache_key] = pixmap
            self.lbl_welcome_vol_icon.setPixmap(pixmap)

        if hasattr(self, "btn_tab_restart"):
            self.btn_tab_restart.setIcon(QIcon(self.get_svg_icon(RESTART_SVG)))

        if hasattr(self, "btn_welcome_ctr"):
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG
            self.btn_welcome_ctr.setIcon(QIcon(self.get_svg_icon(ctr_svg)))

    def _update_combo_box_icons(self):
        if hasattr(self, "console_selector"):
            is_dark = self._is_dark_theme()
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_CLEAN_SVG
            self.console_selector.blockSignals(True)
            if hasattr(self, "_set_selector_item_icon"):
                self._set_selector_item_icon(0, QIcon(self.get_svg_icon(NX_LOGO_SVG)))
                self._set_selector_item_icon(1, QIcon(self.get_svg_icon(ctr_svg)))
                self._set_selector_item_icon(2, QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))
            elif hasattr(self.console_selector, "setItemIcon"):
                self.console_selector.setItemIcon(0, QIcon(self.get_svg_icon(NX_LOGO_SVG)))
                self.console_selector.setItemIcon(1, QIcon(self.get_svg_icon(ctr_svg)))
                self.console_selector.setItemIcon(2, QIcon(self.get_svg_icon(CAFE_LOGO_SVG)))
            self.console_selector.blockSignals(False)

    def _update_vol_icon(self, value=None):
        if not hasattr(self, "lbl_vol_icon"):
            return
        if value is None:
            value = self.volume_slider.value() if hasattr(self, "volume_slider") else int(self.config.get("volume", 50))
        svg = VOL_MUTE_SVG if value == 0 else (VOL_LOW_SVG if value < 50 else VOL_HIGH_SVG)
        is_dark = self._is_dark_theme()

        cache_key = (svg, is_dark, 18, 18)
        if cache_key in _VOL_CACHE:
            pixmap = _VOL_CACHE[cache_key]
        else:
            pixmap = self.get_svg_icon(svg).scaled(
                18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            _VOL_CACHE[cache_key] = pixmap

        self.lbl_vol_icon.setPixmap(pixmap)

    def on_volume_changed(self, value):
        if hasattr(self, "audio"):
            self.audio.set_global_volume(value)
        self._update_vol_icon(value)
        self.config["volume"] = value

        if getattr(self, "_is_loading_ui", False):
            return

        if not hasattr(self, "_vol_save_timer"):
            self._vol_save_timer = QTimer(self)
            self._vol_save_timer.setSingleShot(True)
            self._vol_save_timer.timeout.connect(lambda: save_config(self.config))

        self._vol_save_timer.start(1500)

    def _play_volume_test_sound(self):
        if hasattr(self, "audio") and hasattr(self.audio, "play_test_sound"):
            if hasattr(self, "volume_slider") and self.volume_slider.value() > 0:
                self.audio.play_test_sound()

    def finish_welcome_setup(self, console_index):
        if getattr(self, "_is_finishing_welcome", False):
            return
        self._is_finishing_welcome = True

        console_names = ("NX", "CTR", "CAFE")
        if not (0 <= console_index < len(console_names)):
            self._is_finishing_welcome = False
            return
        chosen_console = console_names[console_index]

        if hasattr(self, "audio"):
            self.audio.stop_all()
            self.audio.play_console_click(chosen_console)

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

        welcome_buttons = (
            getattr(self, "btn_welcome_nx", None),
            getattr(self, "btn_welcome_ctr", None),
            getattr(self, "btn_welcome_cafe", None)
        )
        for btn in welcome_buttons:
            if btn:
                btn.setEnabled(False)

        theme_pref = self.config.get("theme", "auto")
        bg_color = "#F8F9FA"
        if theme_pref == "oled":
            bg_color = "#000000"
        elif theme_pref == "dark" or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)()):
            bg_color = "#3C3C44"

        central = self.centralWidget() if hasattr(self, "centralWidget") and self.centralWidget() else self
        overlay = QWidget(central)
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overlay.setStyleSheet(f"background-color: {bg_color};")
        overlay.setGeometry(central.rect())
        overlay.raise_()

        overlay_opacity = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(overlay_opacity)
        overlay_opacity.setOpacity(0.0)
        overlay.show()

        self._welcome_anims = []

        anim_in = QPropertyAnimation(overlay_opacity, b"opacity", self)
        anim_in.setDuration(220)
        anim_in.setStartValue(0.0)
        anim_in.setEndValue(1.0)
        anim_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._welcome_anims.append((overlay_opacity, anim_in))

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

            if hasattr(self, "sync_nav_buttons"):
                self.sync_nav_buttons(0)

            if hasattr(self, "input_output"):
                self.input_output.blockSignals(True)
                new_out = self.config.get(f"output_dir_{chosen_console.lower()}", "")
                self.input_output.setText(new_out)
                self.config["output_dir"] = new_out
                self.input_output.blockSignals(False)

            save_config(self.config)

            self.tabs.setCurrentIndex(0)
            if hasattr(self, "clear_console_output"):
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
            anim_out.setDuration(220)
            anim_out.setStartValue(1.0)
            anim_out.setEndValue(0.0)
            anim_out.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._welcome_anims.append((overlay_opacity, anim_out))

            def on_fade_out_complete():
                overlay.deleteLater()
                self._welcome_anims.clear()
                self._is_finishing_welcome = False

                for btn in welcome_buttons:
                    if btn:
                        btn.setEnabled(True)

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
        default_colors = ("#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", "")

        if not raw_color or raw_color in default_colors:
            text_auto = self.T("btn_color_auto", "Auto")
            self.btn_color.setText(text_auto)
            self.btn_color.setStyleSheet("")
        else:
            display_hex = raw_color.upper()
            c = QColor(display_hex)
            luma = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255 if c.isValid() else 0
            text_color = "#000000" if luma > 0.5 else "#FFFFFF"
            self.btn_color.setText(display_hex)
            self.btn_color.setStyleSheet(
                f"background-color: {display_hex}; color: {text_color}; font-weight: bold; border: 1px solid #CED4DA; border-radius: 6px; padding: 6px 16px;"
            )

    def _step_spinner(self):
        if hasattr(self, "lbl_dl_mode") and getattr(self, "spinner_frames", None):
            frame = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
            self.lbl_dl_mode.setText(f" {frame} ")
            self.spinner_idx += 1

    def on_cafe_options_changed(self):
        if getattr(self, "_is_loading_ui", False):
            return
        if hasattr(self, "radio_mlc"):
            if self.radio_mlc.isChecked():
                parts = ["MLC"]
            elif self.radio_slc.isChecked():
                parts = ["SLC"]
            else:
                parts = ["MLC", "SLC"]

            if hasattr(self, "radio_usa") and self.radio_usa.isChecked():
                reg = "USA"
            elif hasattr(self, "radio_jpn") and self.radio_jpn.isChecked():
                reg = "JPN"
            else:
                reg = "EUR"

            self.config["cafe_partitions"] = parts
            self.config["cafe_region"] = reg
            self.trigger_auto_save()

    def on_ctr_options_changed(self):
        if getattr(self, "_is_loading_ui", False):
            return
        if hasattr(self, "radio_ctr_usa") and self.radio_ctr_usa.isChecked():
            reg = "USA"
        elif hasattr(self, "radio_ctr_jpn") and self.radio_ctr_jpn.isChecked():
            reg = "JPN"
        elif hasattr(self, "radio_ctr_aus") and self.radio_ctr_aus.isChecked():
            reg = "AUS"
        elif hasattr(self, "radio_ctr_kor") and self.radio_ctr_kor.isChecked():
            reg = "KOR"
        elif hasattr(self, "radio_ctr_chn") and self.radio_ctr_chn.isChecked():
            reg = "CHN"
        elif hasattr(self, "radio_ctr_twn") and self.radio_ctr_twn.isChecked():
            reg = "TWN"
        else:
            reg = "EUR"

        model = "NEW" if (hasattr(self, "radio_new_3ds") and self.radio_new_3ds.isChecked()) else "OLD"

        self.config["ctr_region"] = reg
        self.config["ctr_model"] = model
        self.trigger_auto_save()

    def _handle_nsp_toggle(self, checked):
        if checked:
            title = self.T("nsp_warning_title", "Avertissement !")
            msg = self.T("nsp_warning_msg", "")

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(title)
            msg_box.setText(msg)
            msg_box.setIcon(QMessageBox.Icon.Warning)

            btn_yes = msg_box.addButton(self.T("btn_yes", "Oui"), QMessageBox.ButtonRole.YesRole)
            btn_no = msg_box.addButton(self.T("btn_no", "Non"), QMessageBox.ButtonRole.NoRole)
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
            self.config["build_nsp"] = bool(checked)
        self.trigger_auto_save()

    def update_dynamic_ui(self, *args):
        mode = getattr(self, "current_console", "NX")
        is_nx = (mode == "NX")
        is_ctr = (mode == "CTR")
        is_cafe = (mode == "CAFE")
        is_welcome = (mode == "WELCOME")
        is_adv = self.chk_adv_mode.isChecked() if hasattr(self, "chk_adv_mode") else bool(self.config.get("advanced_mode", False))

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

            is_manual = self.radio_manual.isChecked() and is_adv

            if hasattr(self, "manual_input_container"):
                self.manual_input_container.setVisible((is_nx or is_cafe or is_ctr) and is_manual)
            if hasattr(self, "input_manual"):
                self.input_manual.setVisible((is_nx or is_cafe or is_ctr) and is_manual)
            if hasattr(self, "lbl_manual_hint"):
                self.lbl_manual_hint.setVisible((is_nx or is_cafe or is_ctr) and is_manual)
            if hasattr(self, "lbl_datfile_link"):
                self.lbl_datfile_link.setVisible((is_nx or is_cafe or is_ctr) and is_manual)

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
            is_cafe_manual = (is_cafe and hasattr(self, "radio_manual") and self.radio_manual.isChecked() and is_adv)

            if hasattr(self, "lbl_manual_hint_cafe"):
                self.lbl_manual_hint_cafe.setVisible(False)
            if hasattr(self, "frame_warn_cafe"):
                was_warn_vis = self.frame_warn_cafe.isVisible()
                self.frame_warn_cafe.setVisible(is_cafe_manual)
                if is_cafe_manual and not was_warn_vis and hasattr(self, "animate_widget_fade"):
                    self.animate_widget_fade(self.frame_warn_cafe)

            show_reg = is_cafe and not is_cafe_manual
            if hasattr(self, "cafe_reg_container"):
                was_reg_vis = self.cafe_reg_container.isVisible()
                self.cafe_reg_container.setVisible(show_reg)
                if show_reg and not was_reg_vis and hasattr(self, "animate_widget_fade"):
                    self.animate_widget_fade(self.cafe_reg_container)

        if hasattr(self, "page_target_ctr"):
            self.page_target_ctr.setVisible(is_ctr)
            if hasattr(self, "ctr_reg_container"):
                self.ctr_reg_container.setVisible(is_ctr)

        for setting in ("hactool", "keys", "prodinfo"):
            if hasattr(self, "labels_config") and setting in self.labels_config:
                self.labels_config[setting].setVisible(is_nx)
            if hasattr(self, f"input_{setting}"):
                getattr(self, f"input_{setting}").setVisible(is_nx)
            if hasattr(self, f"btn_browse_{setting}"):
                getattr(self, f"btn_browse_{setting}").setVisible(is_nx)

        if hasattr(self, "btn_auto_hactool"):
            self.btn_auto_hactool.setVisible(is_nx)

        if hasattr(self, "lbl_otp"):
            self.lbl_otp.setVisible(is_cafe)
        if hasattr(self, "input_otp"):
            self.input_otp.setVisible(is_cafe)
        if hasattr(self, "btn_browse_otp"):
            self.btn_browse_otp.setVisible(is_cafe)

        if hasattr(self, "lbl_boot9"):
            self.lbl_boot9.setVisible(is_ctr)
        if hasattr(self, "input_boot9"):
            self.input_boot9.setVisible(is_ctr)
        if hasattr(self, "btn_browse_boot9"):
            self.btn_browse_boot9.setVisible(is_ctr)

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

        for attr in (
            "radio_latest", "radio_list", "radio_manual", "input_manual",
            "combo_nx_fw", "chk_build_nsp", "page_target_cafe", "page_target_ctr",
            "btn_clear_console", "chk_unlimited_console", "btn_update"
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(not locked)

    def clear_console_output(self, *args):
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            return

        if hasattr(self, "console"):
            self.console.clear()
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(0)
        if hasattr(self, "lbl_progress_pct"):
            self.lbl_progress_pct.setText("0%")
        if hasattr(self, "_last_rendered_pct"):
            self._last_rendered_pct = 0
        if hasattr(self, "spinner_timer"):
            self.spinner_timer.stop()
        if hasattr(self, "symbol_reset_timer"):
            self.symbol_reset_timer.stop()
        if hasattr(self, "update_dl_mode_label"):
            self.update_dl_mode_label()

    def switch_tab_animated(self, index):
        if self.tabs.currentIndex() == index or getattr(self, "_is_switching_tab", False):
            return
        self._is_switching_tab = True

        if getattr(self, "_settings_dirty", False):
            if hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()
            else:
                save_config(self.config)
            self._settings_dirty = False

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
        if theme_pref == "oled":
            bg_color = "#000000"
        elif theme_pref == "dark" or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)()):
            bg_color = "#3C3C44"

        self.fade_overlay.setStyleSheet(f"background-color: {bg_color};")
        self.overlay_opacity = QGraphicsOpacityEffect(self.fade_overlay)
        self.fade_overlay.setGraphicsEffect(self.overlay_opacity)
        self.overlay_opacity.setOpacity(0.0)
        self.fade_overlay.show()

        self.anim_fade_in = QPropertyAnimation(self.overlay_opacity, b"opacity")
        self.anim_fade_in.setDuration(55)
        self.anim_fade_in.setStartValue(0.0)
        self.anim_fade_in.setEndValue(1.0)
        self.anim_fade_in.setEasingCurve(QEasingCurve.Type.OutQuad)

        def on_fade_in_finished():
            self.tabs.setCurrentIndex(index)
            self.sync_nav_buttons(index)
            if index == 1:
                if hasattr(self, "_update_settings_ui"):
                    self._update_settings_ui()
                if hasattr(self, "_update_cafe_adv_ui"):
                    self._update_cafe_adv_ui()

            self.anim_fade_out = QPropertyAnimation(self.overlay_opacity, b"opacity")
            self.anim_fade_out.setDuration(85)
            self.anim_fade_out.setStartValue(1.0)
            self.anim_fade_out.setEndValue(0.0)
            self.anim_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

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
        buttons = (self.btn_tab_dl, self.btn_tab_cfg, self.btn_tab_credits)
        if 0 <= index < len(buttons) and hasattr(self, "btn_tab_dl"):
            buttons[index].setChecked(True)

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

    def restart_app(self, *args):
        self.execute_restart(*args)

    def execute_restart(self, *args):
        self._is_restarting = True

        for timer_attr in ("save_timer", "rainbow_timer", "_sigint_timer", "updater_spinner_timer", "_vol_save_timer"):
            timer = getattr(self, timer_attr, None)
            if timer and hasattr(timer, "isActive") and timer.isActive():
                timer.stop()

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

        is_frozen = getattr(sys, "frozen", False)

        if sys.platform == "darwin":
            if is_frozen:
                mac_app = get_mac_app_bundle_path(sys.executable)
                if mac_app.endswith(".app") and os.path.exists(mac_app):
                    args_list = ["open", "-n", mac_app]
                    work_dir = os.path.dirname(mac_app)
                else:
                    exe_target = os.path.abspath(sys.executable)
                    work_dir = os.path.dirname(exe_target)
                    args_list = [exe_target] + [a for a in sys.argv[1:] if a != "--updater"]
            else:
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path) or os.getcwd()
                args_list = [sys.executable, script_path] + [a for a in sys.argv[1:] if a != "--updater"]

        elif sys.platform == "win32":
            if is_frozen:
                exe_target = os.path.abspath(sys.executable)
                work_dir = os.path.dirname(exe_target)
                args_list = [exe_target] + [a for a in sys.argv[1:] if a != "--updater"]
            else:
                py_exec = sys.executable
                if py_exec.lower().endswith("python.exe"):
                    pyw = os.path.join(os.path.dirname(py_exec), "pythonw.exe")
                    if os.path.exists(pyw):
                        py_exec = pyw
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path) or os.getcwd()
                args_list = [py_exec, script_path] + [a for a in sys.argv[1:] if a != "--updater"]

        else:
            if is_frozen:
                appimage_env = os.environ.get("ORIGINAL_APPIMAGE") or os.environ.get("APPIMAGE")
                if appimage_env and os.path.exists(appimage_env):
                    exe_target = appimage_env
                    work_dir = os.path.dirname(appimage_env)
                else:
                    exe_target = os.path.abspath(sys.executable)
                    work_dir = os.path.dirname(exe_target)

                try:
                    st = os.stat(exe_target)
                    os.chmod(exe_target, st.st_mode | stat.S_IEXEC | 0o755)
                except Exception:
                    pass
                args_list = [exe_target] + [a for a in sys.argv[1:] if a != "--updater"]
            else:
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path) or os.getcwd()
                args_list = [sys.executable, script_path] + [a for a in sys.argv[1:] if a != "--updater"]

        kwargs = {
            "cwd": work_dir,
            "env": clean_env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True
        }

        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True

        try:
            subprocess.Popen(args_list, **kwargs)
        except Exception as e:
            if hasattr(self, "console_write"):
                self.console_write(f"[ERROR] Échec du redémarrage : {e}\n")

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
                        json.dump({
                            "accepted": True,
                            "dont_show_again": dialog.dont_show_again,
                            "date": datetime.datetime.now().isoformat()
                        }, f, indent=4)
                except PermissionError:
                    if hasattr(self, "console_write"):
                        self.console_write(f"[WARN] Droits insuffisants pour écrire l'EULA dans {APPDATA_DIR}\n")
                except Exception:
                    pass
            else:
                sys.exit(0)
        finally:
            self._eula_active = False

        if self.current_console != "WELCOME":
            QTimer.singleShot(200, lambda: self.start_update_check(auto=True))

    def switch_console_mode(self, index):
        if index == 3 or getattr(self, "_is_switching_console", False):
            return

        modes = ("NX", "CTR", "CAFE", "WELCOME")
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
        if theme_pref == "oled":
            bg_color = "#000000"
        elif theme_pref == "dark" or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)()):
            bg_color = "#3C3C44"

        self.console_fade_overlay.setStyleSheet(f"background-color: {bg_color};")
        self.console_overlay_opacity = QGraphicsOpacityEffect(self.console_fade_overlay)
        self.console_fade_overlay.setGraphicsEffect(self.console_overlay_opacity)
        self.console_overlay_opacity.setOpacity(0.0)
        self.console_fade_overlay.show()

        self.anim_console_fade_in = QPropertyAnimation(self.console_overlay_opacity, b"opacity")
        self.anim_console_fade_in.setDuration(55)
        self.anim_console_fade_in.setStartValue(0.0)
        self.anim_console_fade_in.setEndValue(1.0)
        self.anim_console_fade_in.setEasingCurve(QEasingCurve.Type.OutQuad)

        def d_on_fade_in_finished():
            if hasattr(self, "input_output"):
                self.input_output.blockSignals(True)

            self.clear_console_output()
            if hasattr(self, "audio"):
                self.audio.play_boot(new_mode)

            if hasattr(self, "input_output"):
                new_out = self.config.get(f"output_dir_{new_mode.lower()}", "")
                self.input_output.setText(new_out)
                self.config["output_dir"] = new_out
                self.input_output.blockSignals(False)

            if hasattr(self, "apply_visual_settings"):
                self.apply_visual_settings()
            if hasattr(self, "apply_console_theme_colors"):
                self.apply_console_theme_colors()

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
            self.anim_console_fade_out.setDuration(85)
            self.anim_console_fade_out.setStartValue(1.0)
            self.anim_console_fade_out.setEndValue(0.0)
            self.anim_console_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

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

                if getattr(self, "_settings_dirty", False):
                    self._settings_dirty = False
                    if hasattr(self, "trigger_auto_save"):
                        self.trigger_auto_save()
                    else:
                        save_config(self.config)
                elif hasattr(self, "trigger_auto_save"):
                    self.trigger_auto_save()
                else:
                    save_config(self.config)

            self.anim_console_fade_out.finished.connect(d_on_fade_out_finished)
            self.anim_console_fade_out.start()

        self.anim_console_fade_in.finished.connect(d_on_fade_in_finished)
        self.anim_console_fade_in.start()

    def handle_fatal_crash(self, exc_type, exc_value, exc_traceback):
        if hasattr(self, "perform_security_cleanup"):
            self.perform_security_cleanup()
        exception_hook(exc_type, exc_value, exc_traceback)
