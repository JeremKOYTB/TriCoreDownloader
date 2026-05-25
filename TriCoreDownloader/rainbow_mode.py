import random
from PyQt6.QtWidgets import QApplication, QColorDialog, QToolTip, QCheckBox, QRadioButton, QMessageBox, QLineEdit, QSlider
from PyQt6.QtGui import QColor, QCursor, QPalette
from PyQt6.QtCore import Qt
from .styles import update_app_theme
from .config import save_config

class RainbowModeMixin:
    def get_console_style(self, hex_color=None):
        theme = self.config.get("theme", "auto")
        if theme == "auto":
            theme = "dark" if self.get_effective_is_dark() else "light"
            
        if theme == "oled":
            bg, fg, border = "#000000", "#F8F9FA", "#333333"
        elif theme == "dark":
            bg, fg, border = "#1E1E22", "#F8F9FA", "#3A3A40"
        else:
            bg, fg, border = "#F8F9FA", "#2B2B30", "#DEE2E6"
            
        border_css = f"2px solid {hex_color}" if hex_color else f"1px solid {border}"
        
        return f"""
            QPlainTextEdit {{
                background-color: {bg};
                color: {fg};
                border: {border_css};
                border-radius: 6px;
                padding: 8px;
            }}
        """

    def tick_rainbow(self):
        if not self.isVisible() or self.isMinimized(): return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton: return
            
        speed = self.config.get("rainbow_speed", 2)
        increment = speed * 0.8
        self.rainbow_hue = (getattr(self, "rainbow_hue", 0.0) + increment) % 360.0
        
        is_dark = self.get_effective_is_dark()
        sat_f = 200.0 / 255.0 if is_dark else 240.0 / 255.0
        val_f = 255.0 / 255.0 if is_dark else 180.0 / 255.0
        
        c = QColor.fromHsvF(self.rainbow_hue / 360.0, sat_f, val_f)
        hex_color = c.name()
        
        if hasattr(self, "last_rainbow_hex") and self.last_rainbow_hex == hex_color:
            return
        self.last_rainbow_hex = hex_color
        
        indicator_border = "#8A8A95" if is_dark else "#ADB5BD"
        btn_txt = "#2B2B30" if is_dark else "#FFFFFF"
        
        targets = self.config.get("rainbow_targets", {"title": True, "tabs": True, "buttons": True, "progress": True, "indicators": True, "text": False, "inputs": False, "console": False})

        if targets.get("title", True) and hasattr(self, "lbl_title"):
            self.lbl_title.setText(self.get_formatted_title(hex_color))
            
        if targets.get("buttons", True):
            if hasattr(self, "btn_action"):
                self.btn_action.setStyleSheet(f"QPushButton {{ background-color: {hex_color}; color: {btn_txt}; border: none; border-radius: 6px; }}")
            if hasattr(self, "btn_update"):
                self.btn_update.setStyleSheet(f"QPushButton#btnHeader {{ background-color: {hex_color}; color: {btn_txt}; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: none; }}")
            
        if targets.get("tabs", True):
            if hasattr(self, "btn_tab_dl"):
                nav_tab_css = f"QPushButton:checked {{ color: {hex_color}; border-bottom: 3px solid {hex_color}; }}"
                self.btn_tab_dl.setStyleSheet(nav_tab_css)
                if hasattr(self, "btn_tab_cfg"): self.btn_tab_cfg.setStyleSheet(nav_tab_css)
                if hasattr(self, "btn_tab_credits"): self.btn_tab_credits.setStyleSheet(f"QPushButton:checked {{ color: {hex_color}; }}")
            
            if hasattr(self, "console_selector"):
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
                
        if targets.get("progress", True) and hasattr(self, "progress_bar"):
            self.progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {hex_color}; border-radius: 4px; }}")

        if targets.get("console", False) and hasattr(self, "console"):
            self.console.setStyleSheet(self.get_console_style(hex_color))
        elif hasattr(self, "console"):
            self.console.setStyleSheet(self.get_console_style())

        do_indicators = targets.get("indicators", True)
        do_text = targets.get("text", False)
        
        if do_indicators or do_text:
            chk_css, rad_css = "", ""
            
            indicator_color = hex_color
            if not do_indicators:
                indicator_color = self.config.get("accent_color")
                if not indicator_color:
                    defaults = {"NX": "#c6a1fa", "CTR": "#bc181a", "CAFE": "#4ebcff"}
                    indicator_color = defaults.get(self.config.get("console_mode", "NX"), "#c6a1fa")

            chk_css += f"QCheckBox::indicator:checked {{ background-color: {indicator_color}; border: 2px solid {indicator_color}; }} QCheckBox::indicator:hover {{ border: 2px solid {indicator_color}; }} "
            rad_css += f"QRadioButton::indicator:checked {{ background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {indicator_color}, stop:0.55 {indicator_color}, stop:0.65 transparent); border: 2px solid {indicator_border}; }} QRadioButton::indicator:hover {{ border: 2px solid {indicator_color}; }} "
            
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

            if hasattr(self, "volume_slider"): self.volume_slider.setStyleSheet(slider_css)
            if hasattr(self, "slider_welcome_vol"): self.slider_welcome_vol.setStyleSheet(slider_css)
            for chk in self.findChildren(QCheckBox): chk.setStyleSheet(chk_css)
            for rad in self.findChildren(QRadioButton): rad.setStyleSheet(rad_css)
            for slider in self.findChildren(QSlider): slider.setStyleSheet(slider_css)
                
        if targets.get("inputs", False):
            input_css = f"QLineEdit:focus {{ border: 2px solid {hex_color}; }}"
            for inp in self.findChildren(QLineEdit): inp.setStyleSheet(input_css)

    def apply_visual_settings(self):
        print("[RAINBOW] Applying static visual settings.")
        self.centralWidget().setStyleSheet("")
        
        accent = self.config.get("accent_color")
        if not accent:
            defaults = {"NX": "#c6a1fa", "CTR": "#bc181a", "CAFE": "#4ebcff"}
            console = self.config.get("console_mode", "NX")
            accent = defaults.get(console, "#c6a1fa")

        is_dark = self.get_effective_is_dark()
        indicator_border = "#8A8A95" if is_dark else "#ADB5BD"
        btn_txt = "#2B2B30" if is_dark else "#FFFFFF"

        if hasattr(self, "lbl_title"):
            self.lbl_title.setText(self.get_formatted_title(accent))
            
        if hasattr(self, "btn_action"):
            self.btn_action.setStyleSheet(f"QPushButton {{ background-color: {accent}; color: {btn_txt}; border: none; border-radius: 6px; }}")
            
        if hasattr(self, "btn_update"):
            self.btn_update.setStyleSheet(f"QPushButton#btnHeader {{ background-color: {accent}; color: {btn_txt}; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: none; }}")
            
        if hasattr(self, "btn_tab_dl"):
            nav_tab_css = f"QPushButton:checked {{ color: {accent}; border-bottom: 3px solid {accent}; }}"
            self.btn_tab_dl.setStyleSheet(nav_tab_css)
            if hasattr(self, "btn_tab_cfg"): self.btn_tab_cfg.setStyleSheet(nav_tab_css)
            if hasattr(self, "btn_tab_credits"): self.btn_tab_credits.setStyleSheet(f"QPushButton:checked {{ color: {accent}; }}")
            
        if hasattr(self, "console_selector"):
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
                    border: 1px solid {accent}; 
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
            
        if hasattr(self, "progress_bar"):
            self.progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {accent}; border-radius: 4px; }}")

        if hasattr(self, "console"):
            self.console.setStyleSheet(self.get_console_style())

        chk_css = f"QCheckBox::indicator:checked {{ background-color: {accent}; border: 2px solid {accent}; }} QCheckBox::indicator:hover {{ border: 2px solid {accent}; }} "
        rad_css = f"QRadioButton::indicator:checked {{ background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {accent}, stop:0.55 {accent}, stop:0.65 transparent); border: 2px solid {indicator_border}; }} QRadioButton::indicator:hover {{ border: 2px solid {accent}; }} "
        
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
                background: {accent}; 
                border-radius: 3px; 
            }}
            QSlider::handle:horizontal {{ 
                background: {accent}; 
                width: 16px; 
                height: 16px; 
                margin: -5px 0; 
                border-radius: 8px; 
            }}
        """

        if hasattr(self, "volume_slider"): self.volume_slider.setStyleSheet(slider_css)
        if hasattr(self, "slider_welcome_vol"): self.slider_welcome_vol.setStyleSheet(slider_css)
        for chk in self.findChildren(QCheckBox): chk.setStyleSheet(chk_css)
        for rad in self.findChildren(QRadioButton): rad.setStyleSheet(rad_css)
        for slider in self.findChildren(QSlider): slider.setStyleSheet(slider_css)

        input_css = f"QLineEdit:focus {{ border: 2px solid {accent}; }}"
        for inp in self.findChildren(QLineEdit): inp.setStyleSheet(input_css)
            
        self.update_app_colors(self.config.get("accent_color", ""))
        
        self.last_rainbow_hex = ""
        
        if self.config.get("rainbow_mode", False):
            print("[RAINBOW] Enabling high-precision color loop.")
            if not self.rainbow_timer.isActive():
                self.rainbow_timer.setTimerType(Qt.TimerType.PreciseTimer)
                self.rainbow_timer.start(33) 
        else:
            print("[RAINBOW] Disabling color loop.")
            self.rainbow_timer.stop()

    def update_app_colors(self, custom_color):
        theme_pref = self.config.get("theme", "auto")
        console = self.config.get("console_mode", "NX")
        update_app_theme(QApplication.instance(), theme_pref, custom_color, console)
        
        if hasattr(self, "btn_color"): 
            self.update_color_button()

    def get_effective_is_dark(self):
        actual_theme = self.config.get("theme", "auto")
        if actual_theme == "light": return False
        if actual_theme in ["dark", "oled"]: return True
        try:
            scheme = QApplication.instance().styleHints().colorScheme()
            return (scheme == Qt.ColorScheme.Dark)
        except AttributeError:
            palette = QApplication.instance().palette()
            return palette.color(QPalette.ColorRole.Window).lightness() < 128

    def refresh_title_color(self):
        if not hasattr(self, "lbl_title"): return
        if self.config.get("rainbow_mode", False): return
        
        accent = self.config.get("accent_color")
        if not accent:
            defaults = {"NX": "#c6a1fa", "CTR": "#bc181a", "CAFE": "#4ebcff"}
            console = self.config.get("console_mode", "NX")
            accent = defaults.get(console, "#c6a1fa")
            
        self.lbl_title.setText(self.get_formatted_title(accent))

    def on_rainbow_toggle(self, checked):
        print(f"[RAINBOW] Rainbow mode toggled: {checked}")
        if hasattr(self, "rainbow_options_widget"):
            self.rainbow_options_widget.setVisible(checked)
            
        if hasattr(self, "speed_widget"):
            self.speed_widget.setVisible(checked)
            
        self.trigger_auto_save()

    def on_rainbow_target_toggled(self):
        if getattr(self, "_is_loading_ui", True): return
        
        any_checked = any(cb.isChecked() for cb in getattr(self, "rainbow_target_cbs", {}).values())
        if not any_checked:
            print("[RAINBOW] All targets disabled. Auto-deactivating rainbow mode.")
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
            self.trigger_auto_save()

    def pick_color(self):
        if hasattr(self, "chk_rainbow") and self.chk_rainbow.isChecked():
            msg = f"<span style='font-size: 10pt; font-family: sans-serif;'>{self.T('tooltip_color_disabled') if hasattr(self, 'T') else 'Disabled in Rainbow Mode'}</span>"
            QToolTip.showText(QCursor.pos(), msg, self.btn_color, self.btn_color.rect(), 5000)
            return

        print("[RAINBOW] Opening color picker dialog.")
        custom_colors = self.config.get("custom_colors", [])
        for i, hex_col in enumerate(custom_colors):
            if i < QColorDialog.customCount(): QColorDialog.setCustomColor(i, QColor(hex_col))
                
        current_col = QColor(self.pending_color if getattr(self, "pending_color", None) else ("#C4A1FF" if self.get_effective_is_dark() else "#9D00FF"))
        color = QColorDialog.getColor(current_col, self, self.T("lbl_color") if hasattr(self, "T") else "Select Color")
        
        if color.isValid():
            print(f"[RAINBOW] User selected new accent color: {color.name().upper()}")
            self.pending_color = color.name().upper()
            self.update_color_button()
            new_customs = [QColorDialog.customColor(i).name() for i in range(QColorDialog.customCount()) if QColorDialog.customColor(i).isValid()]
            self.config["custom_colors"] = new_customs
            self.trigger_auto_save()

    def reset_color(self):
        if hasattr(self, "chk_rainbow") and self.chk_rainbow.isChecked():
            msg = f"<span style='font-size: 10pt; font-family: sans-serif;'>{self.T('tooltip_color_disabled') if hasattr(self, 'T') else 'Disabled in Rainbow Mode'}</span>"
            QToolTip.showText(QCursor.pos(), msg, self.btn_reset_color, self.btn_reset_color.rect(), 5000)
            return
            
        print("[RAINBOW] Resetting custom color to console default.")
        self.pending_color = ""
        self.update_color_button()
        self.trigger_auto_save()

    def update_color_button(self):
        if not hasattr(self, "btn_color"): return
        hex_color = getattr(self, "pending_color", "")
        is_default = False
        if not hex_color:
            defaults = {"NX": "#c6a1fa", "CTR": "#bc181a", "CAFE": "#4ebcff"}
            console = self.config.get("console_mode", "NX")
            hex_color = defaults.get(console, "#c6a1fa")
            is_default = True
        
        c = QColor(hex_color)
        luma = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255
        text_color = "#000000" if luma > 0.5 else "#FFFFFF"
        
        self.btn_color.setText(self.T("btn_color_auto") if is_default and hasattr(self, "T") else hex_color.upper())
        self.btn_color.setStyleSheet(f"background-color: {hex_color}; color: {text_color}; font-weight: bold; border: 1px solid #CED4DA; border-radius: 6px; padding: 6px 16px;")