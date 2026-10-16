import random
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QToolTip, QCheckBox, 
    QRadioButton, QMessageBox, QLineEdit, QSlider, QComboBox
)
from PyQt6.QtGui import QColor, QCursor, QPalette
from PyQt6.QtCore import Qt
from .styles import update_app_theme, MONO_FONT, FS_MONO
from .config import save_config

_DEFAULT_COLORS = {"#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""}


class RainbowModeMixin:
    def _refresh_rainbow_widget_cache(self):
        self._cached_chk = self.findChildren(QCheckBox)
        self._cached_rad = self.findChildren(QRadioButton)
        self._cached_sliders = self.findChildren(QSlider)
        self._cached_inputs = self.findChildren(QLineEdit)

    def get_console_style(self, hex_color=None):
        theme = str(self.config.get("theme", "auto")).lower()
        if theme == "auto":
            theme = "dark" if self.get_effective_is_dark() else "light"

        if theme == "oled":
            bg, fg, border = "#000000", "#9E9E9E", "#212121"
        elif theme == "dark":
            bg, fg, border = "#32323A", "#D0D0D5", "#555560"
        else:
            bg, fg, border = "#FFFFFF", "#495057", "#CED4DA"

        border_css = f"2px solid {hex_color}" if hex_color else f"1px solid {border}"

        return f"""
            QPlainTextEdit, QPlainTextEdit:focus, QPlainTextEdit:read-only, QPlainTextEdit:disabled {{
                background-color: {bg};
                color: {fg};
                border: {border_css};
                font-family: {MONO_FONT};
                font-size: {FS_MONO};
                border-radius: 6px;
                padding: 8px;
            }}
        """

    def _apply_console_widget_style(self, hex_color=None):
        if not hasattr(self, "console") or self.console is None:
            return
        target_console = self.get_console_style(hex_color)
        if self.console.styleSheet() != target_console:
            self.console.setStyleSheet(target_console)
        self.console.style().unpolish(self.console)
        self.console.style().polish(self.console)
        if self.console.viewport() is not None:
            self.console.viewport().style().unpolish(self.console.viewport())
            self.console.viewport().style().polish(self.console.viewport())
            self.console.viewport().update()
        self.console.update()

    def tick_rainbow(self):
        if not self.isVisible() or self.isMinimized():
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return

        speed = max(1, min(6, int(self.config.get("rainbow_speed", 2))))
        increment = speed * 0.8
        self.rainbow_hue = (getattr(self, "rainbow_hue", 0.0) + increment) % 360.0

        is_dark = self.get_effective_is_dark()
        current_theme_key = (str(self.config.get("theme", "auto")).lower(), is_dark)
        theme_changed = getattr(self, "_last_rainbow_theme_key", None) != current_theme_key
        self._last_rainbow_theme_key = current_theme_key

        sat_f = 200.0 / 255.0 if is_dark else 240.0 / 255.0
        val_f = 255.0 / 255.0 if is_dark else 180.0 / 255.0

        c = QColor.fromHsvF(self.rainbow_hue / 360.0, sat_f, val_f)
        hex_color = c.name()

        if getattr(self, "last_rainbow_hex", None) == hex_color and not theme_changed:
            return
        self.last_rainbow_hex = hex_color

        indicator_border = "#8A8A95" if is_dark else "#ADB5BD"
        btn_txt = "#2B2B30" if is_dark else "#FFFFFF"

        targets = self.config.get("rainbow_targets", {
            "title": True, "tabs": True, "buttons": True, 
            "progress": True, "indicators": True, "text": False, 
            "inputs": False, "console": False
        })

        if targets.get("title", True) and hasattr(self, "lbl_title"):
            self.lbl_title.setText(self.get_formatted_title(hex_color))

        if targets.get("buttons", True):
            if hasattr(self, "btn_action"):
                self.btn_action.setStyleSheet(f"QPushButton {{ background-color: {hex_color}; color: {btn_txt}; border: none; border-radius: 6px; }}")
            if hasattr(self, "btn_update"):
                self.btn_update.setStyleSheet(f"QPushButton#btnHeader {{ background-color: {hex_color}; color: {btn_txt}; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: none; }}")

        if targets.get("tabs", True):
            nav_tab_css = f"QPushButton:checked {{ color: {hex_color}; border-bottom: 3px solid {hex_color}; }}"
            if hasattr(self, "btn_tab_dl"):
                self.btn_tab_dl.setStyleSheet(nav_tab_css)
            if hasattr(self, "btn_tab_cfg"):
                self.btn_tab_cfg.setStyleSheet(nav_tab_css)
            if hasattr(self, "btn_tab_credits"):
                self.btn_tab_credits.setStyleSheet(f"QPushButton:checked {{ color: {hex_color}; }}")

            if hasattr(self, "console_selector"):
                if isinstance(self.console_selector, QComboBox):
                    theme_pref = self.config.get("theme", "auto")
                    if theme_pref == "oled":
                        combo_bg, combo_text, combo_border_idle, arrow_color, hover_bg = "#000000", "#E0E0E0", "#333333", "%23E0E0E0", "#111111"
                    elif is_dark:
                        combo_bg, combo_text, combo_border_idle, arrow_color, hover_bg = "#32323A", "#E8E8E8", "#555560", "%23E8E8E8", "#3C3C44"
                    else:
                        combo_bg, combo_text, combo_border_idle, arrow_color, hover_bg = "#F8F9FA", "#212529", "#CED4DA", "%23212529", "#FFFFFF"

                    arrow_svg = f"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='{arrow_color}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>"

                    self.console_selector.setStyleSheet(f"""
                        QComboBox {{ 
                            background-color: {combo_bg}; 
                            color: {combo_text}; 
                            border: 1px solid {combo_border_idle}; 
                            border-radius: 6px; 
                            padding: 4px 10px; 
                            min-height: 24px; 
                        }}
                        QComboBox:hover, QComboBox:focus, QComboBox:on {{ 
                            background-color: {hover_bg};
                            border: 1px solid {hex_color}; 
                        }}
                        QComboBox::drop-down {{ 
                            subcontrol-origin: padding; 
                            subcontrol-position: top right; 
                            width: 24px; 
                            border: none; 
                            background-color: transparent; 
                        }}
                        QComboBox::down-arrow {{ 
                            image: url("{arrow_svg}"); 
                            width: 14px; 
                            height: 14px; 
                            margin-right: 5px; 
                        }}
                        QComboBox QListView {{ 
                            background-color: {combo_bg}; 
                            color: {combo_text}; 
                            selection-background-color: {hover_bg}; 
                            selection-color: #FFFFFF; 
                            border: 1px solid {combo_border_idle}; 
                            outline: none; 
                        }}
                        QComboBox QListView::item {{ 
                            padding: 6px; 
                        }}
                    """)
                else:
                    self.console_selector.setStyleSheet(f"QPushButton#ConsoleSelector:hover {{ border: 1px solid {hex_color}; }}")

        if targets.get("progress", True) and hasattr(self, "progress_bar"):
            self.progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {hex_color}; border-radius: 4px; }}")

        if targets.get("console", False):
            self._apply_console_widget_style(hex_color)
            self._last_rainbow_console_styled = True
        elif getattr(self, "_last_rainbow_console_styled", False) or theme_changed:
            self._apply_console_widget_style(None)
            self._last_rainbow_console_styled = False

        do_indicators = targets.get("indicators", True)
        do_text = targets.get("text", False)

        if do_indicators or do_text:
            if not hasattr(self, "_cached_chk"):
                self._refresh_rainbow_widget_cache()

            indicator_color = hex_color if do_indicators else self.get_current_accent_color()

            chk_css = f"QCheckBox::indicator:checked {{ background-color: {indicator_color}; border: 2px solid {indicator_color}; }} QCheckBox::indicator:hover {{ border: 2px solid {indicator_color}; }} "
            rad_css = f"QRadioButton::indicator:checked {{ background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {indicator_color}, stop:0.55 {indicator_color}, stop:0.65 transparent); border: 2px solid {indicator_border}; }} QRadioButton::indicator:hover {{ border: 2px solid {indicator_color}; }} "

            slider_bg = "#3A3A40" if is_dark else "#D1D1D6"
            slider_css = f"""
                QSlider {{ 
                    min-height: 24px; 
                    background: transparent; 
                }}
                QSlider::groove:horizontal {{ 
                    height: 6px; 
                    background: {slider_bg}; 
                    border-radius: 3px; 
                    border: none; 
                }}
                QSlider::sub-page:horizontal {{ 
                    background: {indicator_color}; 
                    border-radius: 3px; 
                }}
                QSlider::handle:horizontal {{ 
                    background: {indicator_color}; 
                    width: 16px; 
                    height: 16px; 
                    margin: -5px 0; 
                    border-radius: 8px; 
                }}
            """

            if do_text:
                chk_css += f"QCheckBox:checked, QCheckBox:hover {{ color: {hex_color}; }} "
                rad_css += f"QRadioButton:checked, QRadioButton:hover {{ color: {hex_color}; }} "

            if hasattr(self, "volume_slider"):
                self.volume_slider.setStyleSheet(slider_css)
            if hasattr(self, "slider_welcome_vol"):
                self.slider_welcome_vol.setStyleSheet(slider_css)

            for chk in getattr(self, "_cached_chk", []):
                try:
                    chk.setStyleSheet(chk_css)
                except RuntimeError:
                    pass
            for rad in getattr(self, "_cached_rad", []):
                try:
                    rad.setStyleSheet(rad_css)
                except RuntimeError:
                    pass
            for slider in getattr(self, "_cached_sliders", []):
                try:
                    slider.setStyleSheet(slider_css)
                except RuntimeError:
                    pass
            self._last_rainbow_indicators_styled = True
        elif getattr(self, "_last_rainbow_indicators_styled", False):
            for chk in getattr(self, "_cached_chk", []):
                try:
                    if chk.styleSheet():
                        chk.setStyleSheet("")
                except RuntimeError:
                    pass
            for rad in getattr(self, "_cached_rad", []):
                try:
                    if rad.styleSheet():
                        rad.setStyleSheet("")
                except RuntimeError:
                    pass
            for slider in getattr(self, "_cached_sliders", []):
                try:
                    if slider.styleSheet():
                        slider.setStyleSheet("")
                except RuntimeError:
                    pass
            if hasattr(self, "volume_slider") and self.volume_slider.styleSheet():
                self.volume_slider.setStyleSheet("")
            if hasattr(self, "slider_welcome_vol") and self.slider_welcome_vol.styleSheet():
                self.slider_welcome_vol.setStyleSheet("")
            self._last_rainbow_indicators_styled = False

        if targets.get("inputs", False):
            if not hasattr(self, "_cached_inputs"):
                self._refresh_rainbow_widget_cache()
            input_css = f"QLineEdit:focus {{ border: 2px solid {hex_color}; }}"
            for inp in getattr(self, "_cached_inputs", []):
                try:
                    inp.setStyleSheet(input_css)
                except RuntimeError:
                    pass
            self._last_rainbow_inputs_styled = True
        elif getattr(self, "_last_rainbow_inputs_styled", False):
            for inp in getattr(self, "_cached_inputs", []):
                try:
                    if inp.styleSheet():
                        inp.setStyleSheet("")
                except RuntimeError:
                    pass
            self._last_rainbow_inputs_styled = False

    def apply_visual_settings(self):
        if getattr(self, "_in_apply_visual_settings", False):
            return
        self._in_apply_visual_settings = True
        self.setUpdatesEnabled(False)
        try:
            if hasattr(self, "centralWidget") and self.centralWidget():
                if self.centralWidget().styleSheet():
                    self.centralWidget().setStyleSheet("")
            accent = self.get_current_accent_color()

            if hasattr(self, "lbl_title"):
                self.lbl_title.setText(self.get_formatted_title(accent))

            if hasattr(self, "btn_action") and self.btn_action.styleSheet():
                self.btn_action.setStyleSheet("")
                self.btn_action.style().unpolish(self.btn_action)
                self.btn_action.style().polish(self.btn_action)

            if hasattr(self, "btn_update") and self.btn_update.styleSheet():
                self.btn_update.setStyleSheet("")
                self.btn_update.style().unpolish(self.btn_update)
                self.btn_update.style().polish(self.btn_update)

            if hasattr(self, "btn_tab_dl") and self.btn_tab_dl.styleSheet():
                self.btn_tab_dl.setStyleSheet("")
            if hasattr(self, "btn_tab_cfg") and self.btn_tab_cfg.styleSheet():
                self.btn_tab_cfg.setStyleSheet("")
            if hasattr(self, "btn_tab_credits") and self.btn_tab_credits.styleSheet():
                self.btn_tab_credits.setStyleSheet("")

            if hasattr(self, "console_selector") and self.console_selector.styleSheet():
                self.console_selector.setStyleSheet("")

            if hasattr(self, "progress_bar"):
                if self.progress_bar.styleSheet():
                    self.progress_bar.setStyleSheet("")
                self.progress_bar.style().unpolish(self.progress_bar)
                self.progress_bar.style().polish(self.progress_bar)

            if getattr(self, "_last_rainbow_indicators_styled", False) or getattr(self, "_last_rainbow_inputs_styled", False):
                for cache_attr in ("_cached_chk", "_cached_rad", "_cached_sliders", "_cached_inputs"):
                    for w in getattr(self, cache_attr, []):
                        try:
                            if w.styleSheet():
                                w.setStyleSheet("")
                        except RuntimeError:
                            pass
                if hasattr(self, "volume_slider") and self.volume_slider.styleSheet():
                    self.volume_slider.setStyleSheet("")
                if hasattr(self, "slider_welcome_vol") and self.slider_welcome_vol.styleSheet():
                    self.slider_welcome_vol.setStyleSheet("")

            self.update_app_colors(self.config.get("accent_color", ""))
            self._apply_console_widget_style(None)

            self.last_rainbow_hex = ""
            self._last_rainbow_console_styled = False
            self._last_rainbow_indicators_styled = False
            self._last_rainbow_inputs_styled = False

            if self.config.get("rainbow_mode", False):
                if hasattr(self, "rainbow_timer") and not self.rainbow_timer.isActive():
                    self.rainbow_timer.setTimerType(Qt.TimerType.PreciseTimer)
                    self.rainbow_timer.start(33)
                self.tick_rainbow()
            elif hasattr(self, "rainbow_timer"):
                self.rainbow_timer.stop()
        finally:
            self.setUpdatesEnabled(True)
            self._in_apply_visual_settings = False

    def update_app_colors(self, custom_color):
        theme_pref = self.config.get("theme", "auto")
        console = self.config.get("console_mode", "NX")

        color_param = "" if (not custom_color or str(custom_color).lower() in _DEFAULT_COLORS) else custom_color
        update_app_theme(QApplication.instance(), theme_pref, color_param, console)

        if hasattr(self, "btn_color"):
            self.update_color_button()

    def get_effective_is_dark(self):
        actual_theme = str(self.config.get("theme", "auto")).lower()
        if actual_theme == "light":
            return False
        if actual_theme in ("dark", "oled"):
            return True
        app = QApplication.instance()
        if app:
            try:
                scheme = app.styleHints().colorScheme()
                if scheme == Qt.ColorScheme.Dark:
                    return True
                if scheme == Qt.ColorScheme.Light:
                    return False
            except AttributeError:
                pass
            try:
                import darkdetect
                return bool(darkdetect.isDark())
            except Exception:
                try:
                    palette = app.palette()
                    return palette.color(QPalette.ColorRole.Window).lightness() < 128
                except Exception:
                    return True
        return True

    def refresh_title_color(self):
        if not hasattr(self, "lbl_title"):
            return
        if self.config.get("rainbow_mode", False):
            return
        self.lbl_title.setText(self.get_formatted_title(self.get_current_accent_color()))

    def on_rainbow_toggle(self, checked):
        if hasattr(self, "rainbow_options_widget"):
            self.rainbow_options_widget.setVisible(checked)

        if hasattr(self, "speed_widget"):
            self.speed_widget.setVisible(checked)

        self.config["rainbow_mode"] = checked
        if checked:
            if hasattr(self, "rainbow_timer") and not self.rainbow_timer.isActive():
                self.rainbow_timer.setTimerType(Qt.TimerType.PreciseTimer)
                self.rainbow_timer.start(33)
        else:
            if hasattr(self, "rainbow_timer"):
                self.rainbow_timer.stop()
            self.apply_visual_settings()

        self.trigger_auto_save()

    def on_rainbow_target_toggled(self):
        if getattr(self, "_is_loading_ui", True):
            return

        any_checked = any(cb.isChecked() for cb in getattr(self, "rainbow_target_cbs", {}).values())
        if not any_checked:
            self._is_loading_ui = True

            if hasattr(self, "chk_rainbow"):
                self.chk_rainbow.setChecked(False)

            self.config["rainbow_mode"] = False

            if hasattr(self, "rainbow_target_cbs") and "indicators" in self.rainbow_target_cbs:
                self.rainbow_target_cbs["indicators"].setChecked(True)

            self._is_loading_ui = False

            if hasattr(self, "rainbow_options_widget"):
                self.rainbow_options_widget.setVisible(False)

            self.apply_visual_settings()

            if hasattr(self, "save_settings"):
                self.save_settings(silent=True)
            else:
                save_config(self.config)

            msg_title = self.T("rb_disabled_title") if hasattr(self, "T") else "Rainbow Mode Disabled"
            msg_desc = self.T("rb_disabled_msg") if hasattr(self, "T") else "All targets deselected. Mode disabled."
            QMessageBox.information(self, msg_title, msg_desc)
        else:
            self.last_rainbow_hex = ""
            if self.config.get("rainbow_mode", False):
                self.tick_rainbow()
            self.trigger_auto_save()

    def pick_color(self):
        if hasattr(self, "chk_rainbow") and self.chk_rainbow.isChecked():
            msg = f"<span style='font-size: 10pt; font-family: sans-serif;'>{self.T('tooltip_color_disabled') if hasattr(self, 'T') else 'Disabled in Rainbow Mode'}</span>"
            QToolTip.showText(QCursor.pos(), msg, self.btn_color, self.btn_color.rect(), 5000)
            return

        custom_colors = self.config.get("custom_colors", [])
        for i, hex_col in enumerate(custom_colors):
            if i < QColorDialog.customCount():
                QColorDialog.setCustomColor(i, QColor(hex_col))

        current_col = QColor(self.pending_color if getattr(self, "pending_color", None) else ("#C4A1FF" if self.get_effective_is_dark() else "#9D00FF"))
        color = QColorDialog.getColor(current_col, self, self.T("lbl_color") if hasattr(self, "T") else "Select Color")

        if color.isValid():
            new_hex = color.name().upper()
            if self.config.get("accent_color", "") == new_hex:
                return
            self.setUpdatesEnabled(False)
            try:
                self.pending_color = new_hex
                self.config["accent_color"] = new_hex
                if hasattr(self, "apply_console_theme_colors"):
                    self.apply_console_theme_colors()
                self.apply_visual_settings()
                new_customs = [QColorDialog.customColor(i).name() for i in range(QColorDialog.customCount()) if QColorDialog.customColor(i).isValid()]
                self.config["custom_colors"] = new_customs
                self.trigger_auto_save()
            finally:
                self.setUpdatesEnabled(True)

    def reset_color(self):
        if hasattr(self, "chk_rainbow") and self.chk_rainbow.isChecked():
            msg = f"<span style='font-size: 10pt; font-family: sans-serif;'>{self.T('tooltip_color_disabled') if hasattr(self, 'T') else 'Disabled in Rainbow Mode'}</span>"
            QToolTip.showText(QCursor.pos(), msg, self.btn_reset_color, self.btn_reset_color.rect(), 5000)
            return

        if not self.config.get("accent_color", "") and not getattr(self, "pending_color", ""):
            return

        self.setUpdatesEnabled(False)
        try:
            self.pending_color = ""
            self.config["accent_color"] = ""
            if hasattr(self, "apply_console_theme_colors"):
                self.apply_console_theme_colors()
            self.apply_visual_settings()
            self.trigger_auto_save()
        finally:
            self.setUpdatesEnabled(True)

    def update_color_button(self):
        if not hasattr(self, "btn_color"):
            return
        raw_color = str(self.config.get("accent_color", "")).strip().lower()

        if not raw_color or raw_color in _DEFAULT_COLORS:
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
