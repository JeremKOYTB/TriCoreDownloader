import os
import sys
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QFrame, 
                             QSizePolicy, QStackedWidget)
from PyQt6.QtCore import Qt

from .ui_tabs_settings_paths import UiTabsSettingsPathsMixin
from .ui_tabs_settings_app import UiTabsSettingsAppMixin

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
        
        self.settings_scroll.setStyleSheet("""
            QScrollBar:vertical { border: none; background-color: transparent; width: 8px; margin: 0px; }
            QScrollBar::handle:vertical { background-color: #888888; min-height: 30px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background-color: #AAAAAA; }
            QScrollBar::handle:vertical:pressed { background-color: #CCCCCC; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background-color: transparent; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background-color: transparent; }
        """)

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
        
        if mode == "NX": target_idx = 0
        elif mode == "CTR": target_idx = 1
        elif mode == "CAFE": target_idx = 2
        else: target_idx = 3
        
        if hasattr(self, "paths_stack") and target_idx < self.paths_stack.count():
            for i in range(self.paths_stack.count()):
                page = self.paths_stack.widget(i)
                if i == target_idx:
                    page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
                else:
                    page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            self.paths_stack.setCurrentIndex(target_idx)
            
        effective_adv = self.chk_adv_mode.isChecked() if hasattr(self, 'chk_adv_mode') else False
        is_nx = (mode == "NX")
        
        if hasattr(self, "adv_options_widget"):
            self.adv_options_widget.setVisible(effective_adv)
        
        if hasattr(self, "cont_resize"): self.cont_resize.setVisible(effective_adv)
        if hasattr(self, "cont_exfat"): self.cont_exfat.setVisible(effective_adv and is_nx)
        if hasattr(self, "cont_adv_logs"): self.cont_adv_logs.setVisible(effective_adv)
        
        if effective_adv and hasattr(self, 'chk_adv_logs') and self.chk_adv_logs.isChecked() and is_nx:
            if hasattr(self, "cont_hide_warn"): self.cont_hide_warn.setVisible(True)
        else:
            if hasattr(self, "cont_hide_warn"): self.cont_hide_warn.setVisible(False)
            
        show_aria = effective_adv and is_nx
        show_aria_options = show_aria and hasattr(self, 'chk_use_aria2c') and self.chk_use_aria2c.isChecked()
        
        if hasattr(self, 'sep_nx'):
            self.sep_nx.setVisible(show_aria)
            self.cont_aria2c.setVisible(show_aria)
            self.btn_auto_detect_aria.setVisible(show_aria_options)
            self.lbl_aria2c.setVisible(show_aria_options)
            self.input_aria2c.setVisible(show_aria_options)
            self.widget_aria2c_btns.setVisible(show_aria_options)
            self.lbl_openssl.setVisible(show_aria_options)
            self.input_openssl.setVisible(show_aria_options)
            self.widget_openssl_btns.setVisible(show_aria_options)
            self.sep_nx_bot.setVisible(show_aria)
            
        if hasattr(self, "paths_stack"):
            self.paths_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

    def update_sys_info_label(self):
        py_ver = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        try:
            from .config import CONFIG_FILE
            config_path = os.path.abspath(CONFIG_FILE)
        except ImportError:
            config_path = os.path.abspath("config.json")
            
        save_dir = os.path.dirname(config_path)
        
        edition_str = self.T("sys_standard_edition", "Standard Edition")
        save_loc_str = self.T("sys_save_location", "Save location")
        
        text = f"{py_ver} ( [{edition_str}] )\n{save_loc_str} : {save_dir}"
        
        if hasattr(self, 'lbl_sys_info'):
            self.lbl_sys_info.setText(text)