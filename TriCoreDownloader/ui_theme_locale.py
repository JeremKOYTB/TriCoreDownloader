import os
import sys
import platform
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPalette, QPainter, QColor

from .config import CONFIG_FILE, IS_STORE_PYTHON, save_config
from .logos import (
    CTR_LOGO_BLACK_SVG, CTR_LOGO_WHITE_SVG, CTR_LOGO_CLEAN_SVG, 
    NX_LOGO_SVG, CAFE_LOGO_SVG, RESTART_SVG
)

_DEFAULT_COLORS = {"#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""}
_ICON_CACHE = {}
_INFO_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#888888" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>'

class UiThemeLocaleMixin:
    _missing_keys_log = set()
    _cached_strings = None
    _active_lang_cache = None
    _active_lang_key = None
    
    def init_language(self):
        if not self.config.get("lang"):
            sys_lang = "EN"
            try:
                import locale
                sys_lang_tuple = locale.getlocale()
                sys_lang = sys_lang_tuple[0] if sys_lang_tuple else None
                
                if not sys_lang:
                    if os.name == "nt": 
                        import ctypes
                        sys_lang = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "EN")
                    else: 
                        sys_lang = os.environ.get("LANG", "EN")
            except Exception: 
                sys_lang = "EN"
                
            self.config["lang"] = "FR" if sys_lang and str(sys_lang).lower().startswith("fr") else "EN"
            save_config(self.config)

    def reload_locales(self):
        try:
            from .Languages import locales
            import importlib
            importlib.reload(locales)
            self._cached_strings = locales.STRINGS
            self._active_lang_cache = None
            self._active_lang_key = None
        except Exception:
            pass

    def T(self, key, default=None):
        try:
            if self._cached_strings is None:
                from .Languages import locales
                self._cached_strings = locales.STRINGS

            strings = self._cached_strings
            if not strings:
                return default or key
            
            target_lang = str(self.config.get("lang", "EN")).strip().upper()
            
            if self._active_lang_key != target_lang or self._active_lang_cache is None:
                lang_dict = strings.get(target_lang) or strings.get(target_lang.lower())
                
                if not lang_dict:
                    for code, d in strings.items():
                        if str(code).strip().upper() == target_lang:
                            lang_dict = d
                            break
                
                if not lang_dict:
                    lang_dict = strings.get("EN") or strings.get("en")
                            
                if not lang_dict and strings:
                    lang_dict = next(iter(strings.values()), {})
                
                self._active_lang_cache = lang_dict
                self._active_lang_key = target_lang
            else:
                lang_dict = self._active_lang_cache
            
            if lang_dict and key in lang_dict:
                return lang_dict[key]
            return default or key
        except Exception: 
            return default or key

    def get_current_accent_color(self):
        accent = str(self.config.get("accent_color", "")).strip()
        if accent and accent.lower() not in _DEFAULT_COLORS:
            return accent
            
        mode = getattr(self, "current_console", "WELCOME")
        if mode == "CTR": 
            return "#bc181a"
        elif mode == "CAFE": 
            return "#009ac7"
        return "#c6a1fa"

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
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            cp = screen.availableGeometry().center()
            qr = self.frameGeometry()
            qr.moveCenter(cp)
            self.move(qr.topLeft())

    def apply_console_theme_colors(self):
        theme_pref = self.config.get("theme", "auto")
        mode = getattr(self, "current_console", "WELCOME")
        
        raw_color = str(self.config.get("accent_color", "")).strip()
        user_accent = "" if (not raw_color or raw_color.lower() in _DEFAULT_COLORS) else raw_color
        self.pending_color = user_accent
        
        try:
            from .styles import update_app_theme
            update_app_theme(QApplication.instance(), theme_pref, user_accent, mode)
        except Exception:
            pass

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
            
        self.refresh_title_color()
        
        if hasattr(self, "refresh_all_icons"):
            self.refresh_all_icons()
            
        if hasattr(self, "update_color_button"): 
            self.update_color_button()

    def get_formatted_title(self, accent_hex):
        mode = getattr(self, "current_console", "WELCOME")
        if mode == "NX": 
            prefix = '<span style="color:#00c3e3">N</span><span style="color:#ff4554">X</span>'
        elif mode == "CAFE": 
            prefix = '<span style="color:#4ebcff">CAFE</span>'
        elif mode == "CTR": 
            prefix = '<span style="color:#bc181a">CTR</span>'
        else: 
            prefix = '<span style="color:#c6a1fa">TriCore</span>'
        return f'<div style="font-size: 35px; font-weight: bold; font-family: Segoe UI, sans-serif;">{prefix} <span style="color:{accent_hex}">{self.T("firmware_downloader")}</span></div>'
        
    def refresh_title_color(self):
        if not self.config.get("rainbow_mode", False) and hasattr(self, "lbl_title"):
            self.lbl_title.setText(self.get_formatted_title(self.get_current_accent_color()))

    def update_sys_info_label(self):
        if not hasattr(self, "lbl_sys_info"): 
            return
        try:
            store_str = self.T("sys_store") if IS_STORE_PYTHON else self.T("sys_standard")
            found_status = self.T("file_found") if os.path.exists(CONFIG_FILE) else self.T("file_not_found")
            config_name = CONFIG_FILE.name if hasattr(CONFIG_FILE, "name") else str(CONFIG_FILE)
            format_string = self.T("sys_info_format")
            self.lbl_sys_info.setText(format_string.format(platform.python_version(), store_str, config_name, found_status))
        except Exception:
            pass

    def update_dl_mode_label(self):
        if not hasattr(self, "lbl_dl_mode"): 
            return
        self.lbl_dl_mode.setText(self.T("lbl_mode_aria") if self.config.get("use_aria2c", False) else self.T("lbl_mode_normal"))

    def _get_cached_icon(self, svg_data, is_dark, tint_color=None):
        cache_key = (svg_data, is_dark, tint_color)
        if cache_key in _ICON_CACHE:
            return _ICON_CACHE[cache_key]

        pm = QPixmap()
        if tint_color is not None:
            pm.loadFromData(QByteArray(svg_data), "SVG")
            if not pm.isNull():
                painter = QPainter(pm)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pm.rect(), QColor(tint_color))
                painter.end()
        else:
            color = b"#FFFFFF" if is_dark else b"#333333"
            pm.loadFromData(QByteArray(svg_data.replace(b"currentColor", color)), "SVG")

        icon = QIcon(pm)
        _ICON_CACHE[cache_key] = (icon, pm)
        return icon, pm

    def refresh_all_icons(self):
        theme_pref = self.config.get("theme", "auto")
        is_dark = theme_pref in ["dark", "oled"] or (theme_pref == "auto" and getattr(self, "get_effective_is_dark", lambda: False)())

        icon_nx, _ = self._get_cached_icon(NX_LOGO_SVG, is_dark)
        self.icon_nx = icon_nx

        ctr_logo_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG
        icon_ctr, self.pm_ctr = self._get_cached_icon(ctr_logo_svg, is_dark)
        self.icon_ctr = icon_ctr

        ctr_selector_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_CLEAN_SVG
        icon_ctr_selector, self.pm_ctr_clean = self._get_cached_icon(ctr_selector_svg, is_dark)
        self.icon_ctr_selector = icon_ctr_selector

        icon_cafe, _ = self._get_cached_icon(CAFE_LOGO_SVG, is_dark)
        self.icon_cafe = icon_cafe

        if hasattr(self, "console_selector") and self.console_selector.count() >= 3:
            self.console_selector.blockSignals(True)
            self.console_selector.setItemIcon(0, self.icon_nx)
            self.console_selector.setItemIcon(1, self.icon_ctr_selector)
            self.console_selector.setItemIcon(2, self.icon_cafe)
            self.console_selector.blockSignals(False)

        if hasattr(self, "btn_tab_restart"):
            color_restart = "#FFFFFF" if is_dark else "#333333"
            icon_restart, _ = self._get_cached_icon(RESTART_SVG, is_dark, color_restart)
            self.btn_tab_restart.setIcon(icon_restart)

        if hasattr(self, "btn_tab_credits"):
            color_info = "#FFFFFF" if is_dark else "#888888"
            icon_info, pm_info = self._get_cached_icon(_INFO_SVG, is_dark, color_info)
            if not pm_info.isNull():
                icon_info.addPixmap(pm_info, QIcon.Mode.Disabled)
            self.btn_tab_credits.setIcon(icon_info)

        if hasattr(self, "btn_welcome_ctr"):
            self.btn_welcome_ctr.setIcon(self.icon_ctr)

        if hasattr(self, "update_welcome_vol_icon"):
            self.update_welcome_vol_icon()
            
        if hasattr(self, "_update_vol_icon") and hasattr(self, "volume_slider"):
            self._update_vol_icon(self.volume_slider.value())

        current = getattr(self, "current_console", "WELCOME")
        if current == "NX": 
            self.setWindowIcon(self.icon_nx)
        elif current == "CAFE": 
            self.setWindowIcon(self.icon_cafe)
        elif current == "CTR": 
            self.setWindowIcon(self.icon_ctr)