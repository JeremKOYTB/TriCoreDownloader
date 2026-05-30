import os
import sys
import platform
import inspect
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPalette, QPainter, QColor

from .config import CONFIG_FILE, IS_STORE_PYTHON, save_config
from .logos import (CTR_LOGO_BLACK_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_CLEAN_SVG, 
                    NX_LOGO_SVG, CAFE_LOGO_SVG, RESTART_SVG)

class UiThemeLocaleMixin:
    
    _missing_keys_log = set()
    
    def init_language(self):
        if not self.config.get("lang"):
            sys_lang = "en"
            try:
                import locale
                sys_lang_tuple = locale.getlocale()
                sys_lang = sys_lang_tuple[0] if sys_lang_tuple else None
                
                if not sys_lang:
                    import ctypes
                    if os.name == "nt": 
                        sys_lang = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "en")
                    else: 
                        sys_lang = os.environ.get("LANG", "en")
            except Exception: 
                sys_lang = "en"
                
            self.config["lang"] = "fr" if sys_lang and str(sys_lang).lower().startswith("fr") else "en"
            save_config(self.config)
            
        try:
            from .Languages.locales import STRINGS
            target_lang = self.config.get("lang", "en")
            if STRINGS:
                if target_lang not in STRINGS:
                    pass
        except Exception:
            pass

    def T(self, key, default=None):
        try:
            from .Languages.locales import STRINGS
            if not STRINGS: return default or key
            
            lang = self.config.get("lang", "en")
            lang_dict = STRINGS.get(lang)
            
            if not lang_dict: lang_dict = STRINGS.get("en")
            if not lang_dict and STRINGS: lang_dict = list(STRINGS.values())[0]
            
            if lang_dict and key in lang_dict:
                return lang_dict[key]
            else:
                log_id = f"{lang}_{key}"
                if log_id not in self._missing_keys_log:
                    self._missing_keys_log.add(log_id)
                return default or key
        except Exception:
            return default or key

    def get_current_accent_color(self):
        accent = self.config.get("accent_color", "").strip().lower()
        default_colors = ["#c6a1fa", "#bc181a", "#4ebcff", ""]
        mode = getattr(self, "current_console", "WELCOME")
        
        if accent in default_colors:
            if mode == "CTR": target_color = "#bc181a"
            elif mode == "CAFE": target_color = "#4ebcff"
            else: target_color = "#c6a1fa"
            self.config["accent_color"] = target_color
            return target_color
        return accent

    def _on_os_theme_changed(self, *args):
        if self.config.get("theme", "auto") == "auto":
            if hasattr(self, "refresh_all_icons"):
                self.refresh_all_icons()
            self.apply_console_theme_colors()

    def apply_window_constraints(self):
        d_w, d_h = 1000, 800
        if self.config.get("allow_resize", False):
            self.setMinimumSize(d_w, d_h)
            self.setMaximumSize(16777215, 16777215)
        else:
            self.showNormal()
            self.setMinimumSize(d_w, d_h)
            self.setMaximumSize(d_w, d_h)
            self.resize(d_w, d_h)
            
    def center_on_screen(self):
        qr = self.frameGeometry()
        cp = self.screen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def apply_console_theme_colors(self):
        theme_pref = self.config.get("theme", "auto")
        mode = getattr(self, "current_console", "WELCOME")
        accent = self.get_current_accent_color()
        self.pending_color = accent
        
        try:
            from .styles import update_app_theme
            update_app_theme(QApplication.instance(), theme_pref, accent, mode)
        except Exception: 
            pass
            
        self.refresh_title_color()
        
        if hasattr(self, "refresh_all_icons"):
            self.refresh_all_icons()
            
        if hasattr(self, "update_color_button"): 
            self.update_color_button()

    def get_formatted_title(self, accent_hex):
        mode = getattr(self, "current_console", "WELCOME")
        if mode == "NX": prefix = '<span style="color:#00c3e3">N</span><span style="color:#ff4554">X</span>'
        elif mode == "CAFE": prefix = '<span style="color:#4ebcff">CAFE</span>'
        elif mode == "CTR": prefix = '<span style="color:#bc181a">CTR</span>'
        else: prefix = '<span style="color:#c6a1fa">TriCore</span>'
        return f'<div style="font-size: 35px; font-weight: bold; font-family: Segoe UI, sans-serif;">{prefix} <span style="color:{accent_hex}">{self.T("firmware_downloader")}</span></div>'
        
    def refresh_title_color(self):
        if not self.config.get("rainbow_mode", False) and hasattr(self, "lbl_title"):
            self.lbl_title.setText(self.get_formatted_title(self.get_current_accent_color()))

    def update_sys_info_label(self):
        if not hasattr(self, "lbl_sys_info"): return
        store_str = self.T("sys_store") if IS_STORE_PYTHON else self.T("sys_standard")
        found_status = self.T("file_found") if os.path.exists(CONFIG_FILE) else self.T("file_not_found")
        config_name = CONFIG_FILE.name if hasattr(CONFIG_FILE, "name") else str(CONFIG_FILE)
        format_string = self.T("sys_info_format")
        self.lbl_sys_info.setText(format_string.format(platform.python_version(), store_str, config_name, found_status))

    def update_dl_mode_label(self):
        if not hasattr(self, "lbl_dl_mode"): return
        self.lbl_dl_mode.setText(self.T("lbl_mode_aria") if self.config.get("use_aria2c", False) else self.T("lbl_mode_normal"))

    def refresh_all_icons(self):
        theme_pref = self.config.get("theme", "auto")
        
        is_dark = False
        if theme_pref in ["dark", "oled"]:
            is_dark = True
        elif theme_pref == "auto":
            if hasattr(self, "get_effective_is_dark"):
                is_dark = self.get_effective_is_dark()

        if hasattr(self, "console_selector"):
            try:
                pm_nx = QPixmap()
                pm_nx.loadFromData(QByteArray(NX_LOGO_SVG), "SVG")
                self.icon_nx = QIcon(pm_nx)
                self.console_selector.setItemIcon(0, self.icon_nx)
            except Exception: pass

            try:
                self.pm_ctr = QPixmap()
                self.pm_ctr.loadFromData(QByteArray(CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG), "SVG")
                self.icon_ctr = QIcon(self.pm_ctr)

                self.pm_ctr_clean = QPixmap()
                self.pm_ctr_clean.loadFromData(QByteArray(CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_CLEAN_SVG), "SVG")
                self.icon_ctr_selector = QIcon(self.pm_ctr_clean)

                self.console_selector.setItemIcon(1, self.icon_ctr_selector)
            except Exception: pass

            try:
                pm_cafe = QPixmap()
                pm_cafe.loadFromData(QByteArray(CAFE_LOGO_SVG), "SVG")
                self.icon_cafe = QIcon(pm_cafe)
                self.console_selector.setItemIcon(2, self.icon_cafe)
            except Exception: pass

        if hasattr(self, "btn_tab_restart"):
            try:
                pm_restart = QPixmap()
                pm_restart.loadFromData(QByteArray(RESTART_SVG), "SVG")
                color_restart = "#FFFFFF" if is_dark else "#333333"
                
                painter = QPainter(pm_restart)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pm_restart.rect(), QColor(color_restart))
                painter.end()
                
                self.btn_tab_restart.setIcon(QIcon(pm_restart))
            except Exception: pass

        if hasattr(self, "btn_tab_credits"):
            try:
                info_svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#888888" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>'
                pm_info = QPixmap()
                pm_info.loadFromData(QByteArray(info_svg), "SVG")
                color_info = "#FFFFFF" if is_dark else "#888888"
                
                painter = QPainter(pm_info)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pm_info.rect(), QColor(color_info))
                painter.end()
                
                info_icon = QIcon(pm_info)
                info_icon.addPixmap(pm_info, QIcon.Mode.Disabled)
                self.btn_tab_credits.setIcon(info_icon)
            except Exception: pass

        if hasattr(self, "update_welcome_vol_icon"):
            self.update_welcome_vol_icon()
            
        if hasattr(self, "_update_vol_icon") and hasattr(self, "volume_slider"):
            self._update_vol_icon(self.volume_slider.value())

        if self.current_console == "NX" and hasattr(self, 'icon_nx'): 
            self.setWindowIcon(self.icon_nx)
        elif self.current_console == "CAFE" and hasattr(self, 'icon_cafe'): 
            self.setWindowIcon(self.icon_cafe)
        elif self.current_console == "CTR" and hasattr(self, 'icon_ctr'): 
            self.setWindowIcon(self.icon_ctr)

    def retranslate_ui(self):
        mode_titles = {"NX": self.T("title_nx"), "CTR": self.T("title_ctr"), "CAFE": self.T("title_cafe")}
        self.setWindowTitle(mode_titles.get(self.current_console, self.T("title")))
        
        if hasattr(self, "lbl_title"): self.refresh_title_color()
        if hasattr(self, "lbl_sub"): self.lbl_sub.setText(self.T("subtitle"))
        
        if hasattr(self, "btn_tab_dl"): self.btn_tab_dl.setText(self.T("tab_dl"))
        if hasattr(self, "btn_tab_cfg"): self.btn_tab_cfg.setText(self.T("tab_cfg"))
        if hasattr(self, "btn_tab_credits"): self.btn_tab_credits.setText(self.T("tab_credits"))
        if hasattr(self, "btn_tab_restart"): self.btn_tab_restart.setText(" " + self.T("btn_restart_app"))
        
        self.update_sys_info_label()
        
        if hasattr(self, "lbl_grp_target"): self.lbl_grp_target.setText(self.T("grp_target"))
        if hasattr(self, "radio_latest"): self.radio_latest.setText(self.T("opt_latest"))
        if hasattr(self, "radio_manual"): self.radio_manual.setText(self.T("opt_manual"))
        if hasattr(self, "lbl_manual_hint"): self.lbl_manual_hint.setText(self.T("lbl_manual_hint"))
        if hasattr(self, "lbl_manual_hint_cafe"): self.lbl_manual_hint_cafe.setText(self.T("lbl_manual_hint_cafe"))
        if hasattr(self, "lbl_warn_cafe_downgrade"): self.lbl_warn_cafe_downgrade.setText(self.T("warn_cafe_downgrade"))
        if hasattr(self, "lbl_grp_live"): self.lbl_grp_live.setText(self.T("grp_live"))
        if hasattr(self, "btn_clear_console"): self.btn_clear_console.setText(self.T("btn_clear_console"))

        # TRADUCTION DYNAMIQUE DU BOUTON ICI
        if hasattr(self, "chk_build_nsp"):
            self.chk_build_nsp.setText(self.T("build_nsp_checkbox"))
            self.chk_build_nsp.setToolTip(self.T("tt_build_nsp"))

        if hasattr(self, "btn_action"):
            if getattr(self, "worker", None) and self.worker.isRunning(): 
                self.btn_action.setText(self.T("btn_stop"))
            else: 
                self.btn_action.setText(self.T("btn_start"))
                
        if hasattr(self, "lbl_grp_crypto"): self.lbl_grp_crypto.setText(self.T("grp_crypto"))
        if hasattr(self, "lbl_grp_app"): self.lbl_grp_app.setText(self.T("grp_app"))
        if hasattr(self, "lbl_lang"): self.lbl_lang.setText(self.T("lbl_lang"))
        if hasattr(self, "lbl_color"): self.lbl_color.setText(self.T("lbl_color"))
        if hasattr(self, "lbl_theme"): self.lbl_theme.setText(self.T("lbl_theme"))
        
        if hasattr(self, "lbl_cafe_part"): self.lbl_cafe_part.setText(self.T("cafe_lbl_part"))
        if hasattr(self, "radio_mlc"): self.radio_mlc.setText(self.T("cafe_part_mlc"))
        if hasattr(self, "radio_slc"): self.radio_slc.setText(self.T("cafe_part_slc"))
        if hasattr(self, "radio_both"): self.radio_both.setText(self.T("cafe_part_both"))
        if hasattr(self, "lbl_cafe_reg"): self.lbl_cafe_reg.setText(self.T("cafe_lbl_reg"))
        if hasattr(self, "radio_eur"): self.radio_eur.setText(self.T("cafe_reg_eur"))
        if hasattr(self, "radio_usa"): self.radio_usa.setText(self.T("cafe_reg_usa"))
        if hasattr(self, "radio_jpn"): self.radio_jpn.setText(self.T("cafe_reg_jpn"))
        if hasattr(self, "chk_cafe_extract"): self.chk_cafe_extract.setText(self.T("chk_cafe_extract"))
        if hasattr(self, "chk_cemu_layout"): self.chk_cemu_layout.setText(self.T("chk_cemu_layout"))

        if hasattr(self, "lbl_ctr_model"): self.lbl_ctr_model.setText(self.T("ctr_lbl_model"))
        if hasattr(self, "radio_old_3ds"): self.radio_old_3ds.setText(self.T("ctr_model_old"))
        if hasattr(self, "radio_new_3ds"): self.radio_new_3ds.setText(self.T("ctr_model_new"))
        if hasattr(self, "lbl_ctr_reg"): self.lbl_ctr_reg.setText(self.T("ctr_lbl_reg"))
        if hasattr(self, "radio_ctr_eur"): self.radio_ctr_eur.setText(self.T("ctr_reg_eur"))
        if hasattr(self, "radio_ctr_usa"): self.radio_ctr_usa.setText(self.T("ctr_reg_usa"))
        if hasattr(self, "radio_ctr_jpn"): self.radio_ctr_jpn.setText(self.T("ctr_reg_jpn"))
        if hasattr(self, "lbl_rainbow_hint"): self.lbl_rainbow_hint.setText(self.T("lbl_rainbow_hint"))
            
        for attr in ["chk_rainbow", "chk_resize", "chk_adv_mode", "chk_adv_logs", "chk_auto_save", "chk_hide_warn", "chk_exfat", "chk_use_aria2c", "chk_unlimited_console"]:
            if hasattr(self, attr): 
                getattr(self, attr).setText(self.T(attr))
        
        if hasattr(self, "rainbow_target_cbs"):
            rb_keys = { "title": "rb_title", "tabs": "rb_tabs", "buttons": "rb_btns", "progress": "rb_progress", "indicators": "rb_indicators", "text": "rb_text", "inputs": "rb_inputs", "console": "rb_console" }
            for k, cb in self.rainbow_target_cbs.items():
                cb.setText(self.T(rb_keys.get(k, f"rb_{k}")))
        
        if hasattr(self, "lbl_save_hint"): self.lbl_save_hint.setText(self.T("lbl_save_hint"))
        if hasattr(self, "lbl_speed_text"): self.lbl_speed_text.setText(self.T("lbl_rb_speed"))

        if hasattr(self, "labels_config"):
            keys_map = { "hactool": "lbl_hactool", "keys": "lbl_keys", "prodinfo": "lbl_prodinfo", "cert": "lbl_cert", "otp": "lbl_otp", "out": "lbl_out", "boot9": "lbl_boot9" }
            for key, label in self.labels_config.items():
                label.setText(self.T(keys_map.get(key, key)))

        if hasattr(self, "input_boot9"):
            self.input_boot9.setPlaceholderText(self.T("ctr_hint_boot9"))

        if hasattr(self, "btn_auto_detect_aria"): self.btn_auto_detect_aria.setText(self.T("btn_auto_detect"))
        if hasattr(self, "lbl_aria2c"): self.lbl_aria2c.setText(self.T("lbl_aria2c"))
        if hasattr(self, "lbl_openssl"): self.lbl_openssl.setText(self.T("lbl_openssl"))
        if hasattr(self, "btn_suggest"): self.btn_suggest.setText(self.T("btn_suggest"))
        if hasattr(self, "btn_save"): self.btn_save.setText(self.T("btn_save"))
        for btn in getattr(self, "browse_buttons", []): btn.setText(self.T("btn_browse"))
        if hasattr(self, "btn_reset_center"): self.btn_reset_center.setText(self.T("btn_reset"))
        if hasattr(self, "btn_reset_right"): self.btn_reset_right.setText(self.T("btn_reset"))
        if hasattr(self, "lbl_credits_title"): self.lbl_credits_title.setText(self.T("credits_header"))
        if hasattr(self, "lbl_credits_text"): self.lbl_credits_text.setText(self.T("credits_text"))
        
        if hasattr(self, "lbl_welcome_title"): self.lbl_welcome_title.setText(self.T("welcome_title"))
        if hasattr(self, "lbl_welcome_intro"): self.lbl_welcome_intro.setText(self.T("welcome_subtitle"))
        if hasattr(self, "lbl_welcome_info_title"): self.lbl_welcome_info_title.setText(self.T("welcome_info_title"))
        if hasattr(self, "lbl_welcome_info_desc"): self.lbl_welcome_info_desc.setText(self.T("welcome_info_desc"))
        if hasattr(self, "lbl_welcome_info_risk"): self.lbl_welcome_info_risk.setText(self.T("welcome_info_risk"))
        if hasattr(self, "chk_welcome_adv"): self.chk_welcome_adv.setText(self.T("chk_welcome_adv"))
        if hasattr(self, "chk_welcome_logs"): self.chk_welcome_logs.setText(self.T("chk_welcome_logs"))
        if hasattr(self, "btn_welcome_help"): self.btn_welcome_help.setToolTip(self.T("tooltip_welcome_adv"))
        if hasattr(self, "btn_welcome_cafe"): self.btn_welcome_cafe.setText(" " + self.T("console_cafe"))
        if hasattr(self, "btn_welcome_nx"): self.btn_welcome_nx.setText(" " + self.T("console_nx"))
        if hasattr(self, "btn_welcome_ctr"): self.btn_welcome_ctr.setText(" " + self.T("console_ctr"))

        if hasattr(self, "console_selector"):
            self.console_selector.setItemText(0, "\u00A0" + self.T("console_nx"))
            self.console_selector.setItemText(1, "\u00A0" + self.T("console_ctr"))
            self.console_selector.setItemText(2, "\u00A0" + self.T("console_cafe"))
            if self.console_selector.count() > 3:
                self.console_selector.setItemText(3, self.T("console_welcome"))

        if hasattr(self, "btn_update"):
            self.btn_update.setText(self.T("btn_update"))

        self.refresh_all_icons()
        self.update_dl_mode_label()