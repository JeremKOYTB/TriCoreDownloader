import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QLabel, QPushButton, QComboBox, QFrame, 
                             QCheckBox, QSizePolicy, QSlider, QStyle)
from PyQt6.QtCore import Qt, QSize

class UiTabsSettingsAppMixin:
    def setup_app_section(self, layout):
        self.grp_app, app_layout, self.lbl_grp_app = self.create_card(self.T("grp_app"))
        app_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        row1 = QHBoxLayout()
        row1.addStretch() 
        
        self.lbl_lang = QLabel(self.T("lbl_lang"))
        self.combo_lang = QComboBox()
        
        try:
            from .Languages.locales import STRINGS
            self.combo_lang.blockSignals(True)
            
            for lang_code, lang_dict in STRINGS.items():
                display_name = lang_dict.get("LanguageName", lang_code.upper())
                self.combo_lang.addItem(display_name, userData=lang_code)
                
            saved_lang = self.config.get("lang", "en")
            index = self.combo_lang.findData(saved_lang)
            if index >= 0:
                self.combo_lang.setCurrentIndex(index)
                
            self.combo_lang.blockSignals(False)
        except ImportError:
            self.combo_lang.addItem(self.T("msg_no_lang"), userData="en")
            
        self.combo_lang.currentIndexChanged.connect(self._on_lang_changed)
        
        row1.addWidget(self.lbl_lang)
        row1.addWidget(self.combo_lang)
        row1.addSpacing(24) 
        
        self.lbl_theme = QLabel(self.T("lbl_theme"))
        self.combo_theme = QComboBox()
        theme_items = [self.T("theme_auto"), self.T("theme_light"), self.T("theme_dark"), self.T("theme_oled")]
        self.combo_theme.addItems(theme_items)
        theme_map = {"auto": 0, "light": 1, "dark": 2, "oled": 3}
        self.combo_theme.setCurrentIndex(theme_map.get(self.config.get("theme", "auto"), 0))
        self.combo_theme.currentIndexChanged.connect(self.trigger_auto_save)
        
        row1.addWidget(self.lbl_theme)
        row1.addWidget(self.combo_theme)
        row1.addSpacing(24)
        
        self.lbl_color = QLabel(self.T("lbl_color"))
        self.btn_color = QPushButton()
        self.btn_color.setCursor(Qt.CursorShape.PointingHandCursor)
        if hasattr(self, "pick_color"): 
            self.btn_color.clicked.connect(self.pick_color)
            
        self.btn_reset_color = QPushButton()
        self.btn_reset_color.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_reset_color.setIconSize(QSize(18, 18))
        self.btn_reset_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_color.setFixedSize(36, 36)
        if hasattr(self, "reset_color"): 
            self.btn_reset_color.clicked.connect(self.reset_color)
            
        if hasattr(self, "update_color_button"): 
            self.update_color_button()
            
        row1.addWidget(self.lbl_color)
        row1.addWidget(self.btn_color)
        row1.addWidget(self.btn_reset_color)
        row1.addStretch()
        
        app_layout.addLayout(row1)
        app_layout.addSpacing(24)
        
        self.chk_rainbow = QCheckBox()
        self.cont_rainbow, _ = self.create_wrapped_checkbox(self.chk_rainbow, self.T("chk_rainbow"))
        self.chk_rainbow.setChecked(self.config.get("rainbow_mode", False))
        if hasattr(self, "on_rainbow_toggle"):
            self.chk_rainbow.toggled.connect(self.on_rainbow_toggle)

        self.chk_adv_mode = QCheckBox()
        self.cont_adv_mode, _ = self.create_wrapped_checkbox(self.chk_adv_mode, self.T("chk_adv_mode"))
        self.chk_adv_mode.setChecked(self.config.get("advanced_mode", False))
        if hasattr(self, "on_adv_mode_toggle"):
            self.chk_adv_mode.toggled.connect(self.on_adv_mode_toggle)

        self.chk_resize = QCheckBox()
        self.cont_resize, _ = self.create_wrapped_checkbox(self.chk_resize, self.T("chk_resize"))
        self.chk_resize.setChecked(self.config.get("allow_resize", False)) 
        self.chk_resize.toggled.connect(self.trigger_auto_save)
        
        self.chk_adv_logs = QCheckBox()
        self.cont_adv_logs, _ = self.create_wrapped_checkbox(self.chk_adv_logs, self.T("chk_adv_logs"))
        self.chk_adv_logs.setChecked(self.config.get("advanced_logs", False))
        if hasattr(self, "on_adv_logs_toggle"):
            self.chk_adv_logs.toggled.connect(self.on_adv_logs_toggle)
            
        self.chk_exfat = QCheckBox()
        self.cont_exfat, _ = self.create_wrapped_checkbox(self.chk_exfat, self.T("chk_exfat"))
        self.chk_exfat.setChecked(self.config.get("exclude_exfat", False))
        if hasattr(self, "on_exfat_toggle"):
            self.chk_exfat.toggled.connect(self.on_exfat_toggle)
        self.chk_exfat.toggled.connect(self.trigger_auto_save)
        
        self.chk_hide_warn = QCheckBox()
        self.cont_hide_warn, _ = self.create_wrapped_checkbox(self.chk_hide_warn, self.T("chk_hide_warn"))
        self.chk_hide_warn.setChecked(self.config.get("hide_privacy_warning", False))
        if hasattr(self, "on_hide_warn_toggle"):
            self.chk_hide_warn.toggled.connect(self.on_hide_warn_toggle)

        for container in [self.cont_rainbow, self.cont_adv_mode, self.cont_resize, self.cont_adv_logs, self.cont_exfat, self.cont_hide_warn]:
            container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

        TOTAL_BLOCK_WIDTH = 680
        MAIN_COL_WIDTH = 300
        RB_COL_WIDTH = 215
        
        MAIN_SHIFT = 110  
        RAINBOW_SHIFT = 30

        core_vbox = QVBoxLayout()
        core_vbox.setContentsMargins(0, 0, 0, 0)
        core_vbox.setSpacing(16)

        toggles_wrapper = QWidget()
        toggles_wrapper.setFixedWidth(TOTAL_BLOCK_WIDTH)
        
        self.toggles_grid = QGridLayout(toggles_wrapper)
        self.toggles_grid.setContentsMargins(0, 0, 0, 0)
        self.toggles_grid.setHorizontalSpacing(40)
        self.toggles_grid.setVerticalSpacing(16)
        self.toggles_grid.setColumnMinimumWidth(0, MAIN_COL_WIDTH)
        self.toggles_grid.setColumnMinimumWidth(1, MAIN_COL_WIDTH)
        
        self.toggles_grid.addWidget(self.cont_rainbow, 0, 0)
        self.toggles_grid.addWidget(self.cont_adv_mode, 0, 1)
        
        toggles_center = QHBoxLayout()
        toggles_center.addStretch()
        toggles_center.addSpacing(MAIN_SHIFT)
        toggles_center.addWidget(toggles_wrapper)
        toggles_center.addStretch()
        core_vbox.addLayout(toggles_center)

        self.rainbow_options_widget = QWidget()
        rainbow_layout = QVBoxLayout(self.rainbow_options_widget)
        rainbow_layout.setContentsMargins(0, 0, 0, 24)
        
        self.lbl_rainbow_hint = QLabel(self.T("lbl_rainbow_hint"))
        self.lbl_rainbow_hint.setObjectName("HintText")
        
        hint_center = QHBoxLayout()
        hint_center.addStretch()
        hint_center.addSpacing(RAINBOW_SHIFT)
        hint_center.addWidget(self.lbl_rainbow_hint)
        hint_center.addStretch()
        rainbow_layout.addLayout(hint_center)
        
        rainbow_wrapper = QWidget()
        rainbow_wrapper.setFixedWidth(TOTAL_BLOCK_WIDTH)
        
        rainbow_grid = QGridLayout(rainbow_wrapper)
        rainbow_grid.setContentsMargins(0, 8, 0, 0)
        rainbow_grid.setHorizontalSpacing(16)
        rainbow_grid.setVerticalSpacing(12)
        rainbow_grid.setColumnMinimumWidth(0, RB_COL_WIDTH)
        rainbow_grid.setColumnMinimumWidth(1, RB_COL_WIDTH)
        rainbow_grid.setColumnMinimumWidth(2, RB_COL_WIDTH)
        
        self.rainbow_target_cbs = {}
        targets_def = {
            "title": self.T("rb_title"), "tabs": self.T("rb_tabs"), "buttons": self.T("rb_btns"),
            "progress": self.T("rb_progress"), "indicators": self.T("rb_indicators"),
            "text": self.T("rb_text"), "inputs": self.T("rb_inputs"), "console": self.T("rb_console") 
        }
        rt_cfg = self.config.get("rainbow_targets", {"title": True, "tabs": True, "buttons": True})
        
        r, c = 0, 0
        for key, label in targets_def.items():
            cb = QCheckBox(label)
            cb.setStyleSheet("color: #8A8A95; font-size: 9pt;") 
            cb.setChecked(rt_cfg.get(key, True if key not in ["text", "inputs", "console"] else False))
            
            if hasattr(self, "on_rainbow_target_toggled"): 
                cb.toggled.connect(self.on_rainbow_target_toggled)
                
            self.rainbow_target_cbs[key] = cb
            rainbow_grid.addWidget(cb, r, c, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            
            c += 1
            if c > 2:
                c = 0
                r += 1
                
        self.speed_widget = QWidget()
        speed_layout = QHBoxLayout(self.speed_widget)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.setSpacing(8)
        
        self.lbl_speed_text = QLabel(self.T("lbl_rb_speed"))
        self.lbl_speed_text.setStyleSheet("color: #8A8A95; font-size: 9pt;") 
        
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(1, 6) 
        self.slider_speed.setValue(self.config.get("rainbow_speed", 2))
        
        self.lbl_speed_pct = QLabel()
        self.lbl_speed_pct.setStyleSheet("color: #8A8A95; font-weight: bold; font-size: 9pt;") 
        self.lbl_speed_pct.setFixedWidth(40)
        self.lbl_speed_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        def update_speed_label(val):
            pct = int((val / 6.0) * 100)
            self.lbl_speed_pct.setText(f"{pct}%")
            
        self.slider_speed.valueChanged.connect(update_speed_label)
        update_speed_label(self.slider_speed.value())
        self.slider_speed.valueChanged.connect(self.trigger_auto_save)
        
        speed_layout.addWidget(self.lbl_speed_text)
        speed_layout.addWidget(self.slider_speed)
        speed_layout.addWidget(self.lbl_speed_pct)
        
        rainbow_grid.addWidget(self.speed_widget, 2, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        rainbow_grid_center = QHBoxLayout()
        rainbow_grid_center.addStretch()
        rainbow_grid_center.addSpacing(RAINBOW_SHIFT)
        rainbow_grid_center.addWidget(rainbow_wrapper)
        rainbow_grid_center.addStretch()
        rainbow_layout.addLayout(rainbow_grid_center)
        
        self.rainbow_options_widget.setVisible(self.chk_rainbow.isChecked())
        self.chk_rainbow.toggled.connect(self.rainbow_options_widget.setVisible)
        core_vbox.addWidget(self.rainbow_options_widget)

        self.adv_drawer = QWidget()
        adv_layout = QVBoxLayout(self.adv_drawer)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        
        adv_wrapper = QWidget()
        adv_wrapper.setFixedWidth(TOTAL_BLOCK_WIDTH)
        
        self.adv_grid = QGridLayout(adv_wrapper)
        self.adv_grid.setContentsMargins(0, 0, 0, 0)
        self.adv_grid.setHorizontalSpacing(40)
        self.adv_grid.setVerticalSpacing(16)
        self.adv_grid.setColumnMinimumWidth(0, MAIN_COL_WIDTH)
        self.adv_grid.setColumnMinimumWidth(1, MAIN_COL_WIDTH)
        
        self.adv_grid.addWidget(self.cont_resize, 0, 0)
        self.adv_grid.addWidget(self.cont_adv_logs, 0, 1)
        self.adv_grid.addWidget(self.cont_exfat, 1, 0)
        self.adv_grid.addWidget(self.cont_hide_warn, 1, 1)
        
        adv_center = QHBoxLayout()
        adv_center.addStretch()
        adv_center.addSpacing(MAIN_SHIFT)
        adv_center.addWidget(adv_wrapper)
        adv_center.addStretch()
        adv_layout.addLayout(adv_center)
        
        core_vbox.addWidget(self.adv_drawer)
        app_layout.addLayout(core_vbox)

        self.btn_reset_center = QPushButton(self.T("btn_reset"))
        self.btn_reset_center.setObjectName("btnReset")
        self.btn_reset_center.setMinimumWidth(250)
        if hasattr(self, "reset_config"): 
            self.btn_reset_center.clicked.connect(self.reset_config)

        reset_layout = QHBoxLayout()
        reset_layout.setContentsMargins(0, 32, 0, 0)
        reset_layout.addStretch(1)
        reset_layout.addWidget(self.btn_reset_center)
        reset_layout.addStretch(1)
        app_layout.addLayout(reset_layout)
        
        layout.addWidget(self.grp_app)
        
        self.chk_adv_mode.toggled.connect(self._update_settings_ui)
        self.chk_adv_mode.toggled.connect(self._update_cafe_adv_ui)
        self.chk_adv_logs.toggled.connect(self._update_settings_ui)
        if hasattr(self, 'chk_use_aria2c'):
            self.chk_use_aria2c.toggled.connect(self._update_settings_ui)

    def _update_cafe_adv_ui(self, *args):
        adv_on = getattr(self, "chk_adv_mode", None)
        adv_checked = adv_on.isChecked() if adv_on else self.config.get("advanced_mode", False)
        saved_adv = self.config.get("advanced_mode", False)
        
        auto_save_on = getattr(self, "chk_auto_save", None)
        is_auto_save = auto_save_on.isChecked() if auto_save_on else self.config.get("auto_save", False)
        
        effective_adv = adv_checked if is_auto_save else saved_adv
            
        if hasattr(self, "radio_manual") and hasattr(self, "radio_latest"):
            if hasattr(self, "current_console") and self.current_console == "NX":
                self.radio_manual.setVisible(effective_adv)
                if not effective_adv and self.radio_manual.isChecked():
                    self.radio_latest.setChecked(True)
                    if hasattr(self, "input_manual"):
                        self.input_manual.setVisible(False)

        if hasattr(self, "cont_cafe_extract"): 
            self.cont_cafe_extract.setVisible(effective_adv)
            
        if hasattr(self, "cont_cemu_layout"):
            extract_checked = getattr(self, "chk_cafe_extract", None)
            is_extract = extract_checked.isChecked() if extract_checked else False
            
            if not is_extract and hasattr(self, "chk_cemu_layout") and self.chk_cemu_layout.isChecked():
                self.chk_cemu_layout.blockSignals(True)
                self.chk_cemu_layout.setChecked(False)
                self.config["cafe_cemu_layout"] = False
                self.chk_cemu_layout.blockSignals(False)
                
            self.cont_cemu_layout.setVisible(effective_adv and is_extract)
            
        if not effective_adv:
            if hasattr(self, "chk_cafe_extract") and is_auto_save: 
                self.chk_cafe_extract.setChecked(False)
            if hasattr(self, "chk_cemu_layout") and is_auto_save: 
                self.chk_cemu_layout.setChecked(False)

    def _on_lang_changed(self, index):
        new_lang = self.combo_lang.itemData(index)
        if new_lang:
            self.config["lang"] = new_lang
            self.trigger_auto_save()
            if hasattr(self, "retranslate_ui"):
                self.retranslate_ui()