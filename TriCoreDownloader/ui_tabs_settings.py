import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QFrame, 
                             QSizePolicy, QStackedWidget)
from PyQt6.QtCore import Qt

from .ui_tabs_settings_paths import UiTabsSettingsPathsMixin
from .ui_tabs_settings_app import UiTabsSettingsAppMixin

TARGET_MODES = {"NX": 0, "CTR": 1, "CAFE": 2}
PY_VER_STR = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

SCROLL_STYLE = """
    QScrollBar:vertical { border: none; background-color: transparent; width: 8px; margin: 0px; }
    QScrollBar::handle:vertical { background-color: #888888; min-height: 30px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background-color: #AAAAAA; }
    QScrollBar::handle:vertical:pressed { background-color: #CCCCCC; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background-color: transparent; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background-color: transparent; }
"""

def _set_vis(widget, state):
    if widget is not None and (not widget.isHidden()) != state:
        widget.setVisible(state)

class UiTabsSettingsMixin(UiTabsSettingsPathsMixin, UiTabsSettingsAppMixin):
    def setup_settings_tab(self):
        main_tab_layout = QVBoxLayout(self.tab_settings)
        main_tab_layout.setContentsMargins(24, 16, 16, 16)
        main_tab_layout.setSpacing(16)
        
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.settings_scroll.setStyleSheet(SCROLL_STYLE)

        self.settings_content = QWidget()
        layout = QVBoxLayout(self.settings_content)
        layout.setContentsMargins(0, 0, 28, 0)
        layout.setSpacing(16)
        
        self.browse_buttons = []
        self.labels_config = {}
        
        self.setup_paths_section(layout)
        self.setup_app_section(layout)
        
        layout.addStretch()
        
        self.settings_scroll.setWidget(self.settings_content)
        main_tab_layout.addWidget(self.settings_scroll)
        
        self._update_settings_ui()

    def _update_settings_ui(self, *args):
        mode = getattr(self, "current_console", "NX")
        target_idx = TARGET_MODES.get(mode, 3)
        
        if hasattr(self, "paths_stack") and 0 <= target_idx < self.paths_stack.count():
            if getattr(self, "_last_settings_target_idx", None) != target_idx:
                self._last_settings_target_idx = target_idx
                for i in range(self.paths_stack.count()):
                    page = self.paths_stack.widget(i)
                    policy = QSizePolicy.Policy.Preferred if i == target_idx else QSizePolicy.Policy.Ignored
                    page.setSizePolicy(policy, policy)
                self.paths_stack.setCurrentIndex(target_idx)
            
        effective_adv = bool(self.chk_adv_mode.isChecked()) if hasattr(self, 'chk_adv_mode') else False
        is_nx = (mode == "NX")
        
        _set_vis(getattr(self, "adv_options_widget", None), effective_adv)
        _set_vis(getattr(self, "cont_resize", None), effective_adv)
        _set_vis(getattr(self, "cont_exfat", None), effective_adv and is_nx)
        _set_vis(getattr(self, "cont_adv_logs", None), effective_adv)
        
        show_hide_warn = bool(effective_adv and is_nx and hasattr(self, 'chk_adv_logs') and self.chk_adv_logs.isChecked())
        _set_vis(getattr(self, "cont_hide_warn", None), show_hide_warn)
            
        show_aria = bool(effective_adv and is_nx)
        show_aria_options = bool(show_aria and hasattr(self, 'chk_use_aria2c') and self.chk_use_aria2c.isChecked())
        
        _set_vis(getattr(self, 'sep_nx', None), show_aria)
        _set_vis(getattr(self, 'cont_aria2c', None), show_aria)
        _set_vis(getattr(self, 'btn_auto_detect_aria', None), show_aria_options)
        _set_vis(getattr(self, 'lbl_aria2c', None), show_aria_options)
        _set_vis(getattr(self, 'input_aria2c', None), show_aria_options)
        _set_vis(getattr(self, 'widget_aria2c_btns', None), show_aria_options)
        _set_vis(getattr(self, 'lbl_openssl', None), show_aria_options)
        _set_vis(getattr(self, 'input_openssl', None), show_aria_options)
        _set_vis(getattr(self, 'widget_openssl_btns', None), show_aria_options)
        _set_vis(getattr(self, 'sep_nx_bot', None), show_aria)
            
        if hasattr(self, "paths_stack"):
            self.paths_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

    def update_sys_info_label(self):
        if not hasattr(self, 'lbl_sys_info'):
            return
            
        if not hasattr(self, "_cached_save_dir"):
            try:
                from .config import CONFIG_FILE
                config_path = str(CONFIG_FILE.resolve() if isinstance(CONFIG_FILE, Path) else os.path.abspath(CONFIG_FILE))
            except Exception:
                config_path = os.path.abspath("config.json")
            self._cached_save_dir = os.path.dirname(config_path)
        
        edition_str = self.T("sys_standard_edition", "Standard Edition")
        save_loc_str = self.T("sys_save_location", "Save location")
        
        self.lbl_sys_info.setText(f"{PY_VER_STR} ( [{edition_str}] )\n{save_loc_str} : {self._cached_save_dir}")