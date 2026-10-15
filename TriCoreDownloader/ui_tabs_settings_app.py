from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QSizePolicy, QSlider, QStyle
)
from PyQt6.QtCore import Qt, QSize
from .custom_widgets import CustomConsoleSelector
from .config import save_config


class UiTabsSettingsAppMixin:
    def setup_app_section(self, layout):
        self.grp_app, app_layout, self.lbl_grp_app = self.create_card(self.T("grp_app"))
        app_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        row1 = QHBoxLayout()
        row1.addStretch()

        self.lbl_lang = QLabel(self.T("lbl_lang"))
        self.combo_lang = CustomConsoleSelector()
        self.combo_lang.setFixedWidth(160)
        self.lang_codes = []

        try:
            from .Languages.locales import STRINGS
            self.combo_lang.blockSignals(True)

            if isinstance(STRINGS, dict):
                for lang_code, lang_dict in STRINGS.items():
                    display_name = lang_dict.get("LanguageName", str(lang_code).upper()) if isinstance(lang_dict, dict) else str(lang_code).upper()
                    code_str = str(lang_code).strip().upper()
                    self.combo_lang.addItem(display_name, code_str)
                    self.lang_codes.append(code_str)

            saved_lang = str(self.config.get("lang") or "EN").strip().upper()
            matching_idx = self.lang_codes.index(saved_lang) if saved_lang in self.lang_codes else 0
            self.combo_lang.setCurrentIndex(matching_idx)
            self.combo_lang.blockSignals(False)
        except Exception:
            self.combo_lang.addItem(self.T("msg_no_lang"), "EN")
            self.lang_codes = ["EN"]

        self.combo_lang.currentIndexChanged.connect(self._on_lang_changed)

        row1.addWidget(self.lbl_lang)
        row1.addWidget(self.combo_lang)
        row1.addSpacing(24)

        self.lbl_theme = QLabel(self.T("lbl_theme"))
        self.combo_theme = CustomConsoleSelector()
        self.combo_theme.setFixedWidth(160)

        self.combo_theme.blockSignals(True)
        theme_items = [self.T("theme_auto"), self.T("theme_light"), self.T("theme_dark"), self.T("theme_oled")]
        for item in theme_items:
            self.combo_theme.addItem(item)
        theme_map = {"auto": 0, "light": 1, "dark": 2, "oled": 3}
        self.combo_theme.setCurrentIndex(theme_map.get(str(self.config.get("theme", "auto")).lower(), 0))
        self.combo_theme.blockSignals(False)

        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)

        row1.addWidget(self.lbl_theme)
        row1.addWidget(self.combo_theme)
        row1.addSpacing(24)

        self.lbl_color = QLabel(self.T("lbl_color"))
        self.btn_color = QPushButton()
        self.btn_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_color.setMinimumHeight(34)
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
        self.cont_rainbow, self.lbl_chk_rainbow = self.create_wrapped_checkbox(self.chk_rainbow, self.T("chk_rainbow"))
        self.chk_rainbow.setChecked(bool(self.config.get("rainbow_mode", False)))
        if hasattr(self, "on_rainbow_toggle"):
            self.chk_rainbow.toggled.connect(self.on_rainbow_toggle)
        self.chk_rainbow.toggled.connect(lambda v: self._on_bool_setting_changed("rainbow_mode", v))

        self.chk_adv_mode = QCheckBox()
        self.cont_adv_mode, self.lbl_chk_adv_mode = self.create_wrapped_checkbox(self.chk_adv_mode, self.T("chk_adv_mode"))
        self.chk_adv_mode.setChecked(bool(self.config.get("advanced_mode", False)))
        if hasattr(self, "on_adv_mode_toggle"):
            self.chk_adv_mode.toggled.connect(self.on_adv_mode_toggle)
        self.chk_adv_mode.toggled.connect(lambda v: self._on_bool_setting_changed("advanced_mode", v))

        self.chk_resize = QCheckBox()
        self.cont_resize, self.lbl_chk_resize = self.create_wrapped_checkbox(self.chk_resize, self.T("chk_resize"))
        self.chk_resize.setChecked(bool(self.config.get("allow_resize", False)))
        self.chk_resize.toggled.connect(lambda v: self._on_bool_setting_changed("allow_resize", v))
        if hasattr(self, "apply_window_constraints"):
            self.chk_resize.toggled.connect(self.apply_window_constraints)

        self.chk_adv_logs = QCheckBox()
        self.cont_adv_logs, self.lbl_chk_adv_logs = self.create_wrapped_checkbox(self.chk_adv_logs, self.T("chk_adv_logs"))
        self.chk_adv_logs.setChecked(bool(self.config.get("advanced_logs", False)))
        if hasattr(self, "on_adv_logs_toggle"):
            self.chk_adv_logs.toggled.connect(self.on_adv_logs_toggle)
        self.chk_adv_logs.toggled.connect(lambda v: self._on_bool_setting_changed("advanced_logs", v))

        self.chk_exfat = QCheckBox()
        self.cont_exfat, self.lbl_chk_exfat = self.create_wrapped_checkbox(self.chk_exfat, self.T("chk_exfat"))
        self.chk_exfat.setChecked(bool(self.config.get("exclude_exfat", False)))
        if hasattr(self, "on_exfat_toggle"):
            self.chk_exfat.toggled.connect(self.on_exfat_toggle)
        self.chk_exfat.toggled.connect(lambda v: self._on_bool_setting_changed("exclude_exfat", v))

        self.chk_hide_warn = QCheckBox()
        self.cont_hide_warn, self.lbl_chk_hide_warn = self.create_wrapped_checkbox(self.chk_hide_warn, self.T("chk_hide_warn"))
        self.chk_hide_warn.setChecked(bool(self.config.get("hide_privacy_warning", False)))
        if hasattr(self, "on_hide_warn_toggle"):
            self.chk_hide_warn.toggled.connect(self.on_hide_warn_toggle)
        self.chk_hide_warn.toggled.connect(lambda v: self._on_bool_setting_changed("hide_privacy_warning", v))

        for container in [self.cont_rainbow, self.cont_adv_mode, self.cont_resize, self.cont_adv_logs, self.cont_exfat, self.cont_hide_warn]:
            container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
            sp = container.sizePolicy()
            sp.setRetainSizeWhenHidden(True)
            container.setSizePolicy(sp)

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
        self.toggles_grid.setRowMinimumHeight(0, 42)

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
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.slider_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider_speed.setRange(1, 6)
        self.slider_speed.setValue(int(self.config.get("rainbow_speed", 2)))

        self.lbl_speed_pct = QLabel()
        self.lbl_speed_pct.setStyleSheet("color: #8A8A95; font-weight: bold; font-size: 9pt;")
        self.lbl_speed_pct.setFixedWidth(40)
        self.lbl_speed_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def update_speed_label(val):
            pct = int((val / 6.0) * 100)
            self.lbl_speed_pct.setText(f"{pct}%")
            self.config["rainbow_speed"] = val
            if not getattr(self, "_is_loading_ui", False) and hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()

        self.slider_speed.valueChanged.connect(update_speed_label)
        update_speed_label(self.slider_speed.value())

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

        def on_rainbow_drawer_toggled(checked):
            self.rainbow_options_widget.setVisible(checked)
            if checked and hasattr(self, "animate_widget_fade"):
                self.animate_widget_fade(self.rainbow_options_widget)

        self.chk_rainbow.toggled.connect(on_rainbow_drawer_toggled)
        core_vbox.addWidget(self.rainbow_options_widget)

        self.adv_drawer = QWidget()
        self.adv_options_widget = self.adv_drawer
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
        self.adv_grid.setRowMinimumHeight(0, 42)
        self.adv_grid.setRowMinimumHeight(1, 42)

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

        self.adv_drawer.setVisible(self.chk_adv_mode.isChecked())

        def on_adv_drawer_toggled(checked):
            self.adv_drawer.setVisible(checked)
            if checked and hasattr(self, "animate_widget_fade"):
                self.animate_widget_fade(self.adv_drawer)

        self.chk_adv_mode.toggled.connect(on_adv_drawer_toggled)

        def on_adv_logs_anim_toggled(checked):
            if checked and getattr(self, "current_console", "NX") == "NX" and hasattr(self, "animate_widget_fade"):
                self.animate_widget_fade(self.cont_hide_warn)

        self.chk_adv_logs.toggled.connect(on_adv_logs_anim_toggled)

        core_vbox.addWidget(self.adv_drawer)
        app_layout.addLayout(core_vbox)

        self.btn_reset_center = QPushButton(self.T("btn_reset"))
        self.btn_reset_center.setObjectName("btnReset")
        self.btn_reset_center.setCursor(Qt.CursorShape.PointingHandCursor)
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

        if hasattr(self, "_update_settings_ui"):
            self.chk_adv_mode.toggled.connect(self._update_settings_ui)
            self.chk_adv_logs.toggled.connect(self._update_settings_ui)
            if hasattr(self, "chk_use_aria2c"):
                self.chk_use_aria2c.toggled.connect(self._update_settings_ui)
        if hasattr(self, "_update_cafe_adv_ui"):
            self.chk_adv_mode.toggled.connect(self._update_cafe_adv_ui)

    def _on_bool_setting_changed(self, key, value):
        if getattr(self, "_is_loading_ui", False):
            return
        if hasattr(self, "config"):
            self.config[key] = bool(value)
            if hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()

    def _on_theme_changed(self, index):
        if getattr(self, "_is_loading_ui", False):
            return
        theme_list = ["auto", "light", "dark", "oled"]
        if 0 <= index < len(theme_list):
            self.config["theme"] = theme_list[index]
            save_config(self.config)
            if hasattr(self, "apply_console_theme_colors"):
                self.apply_console_theme_colors()

    def retranslate_app_section(self):
        if hasattr(self, "lbl_grp_app"):
            self.lbl_grp_app.setText(self.T("grp_app"))
        if hasattr(self, "lbl_lang"):
            self.lbl_lang.setText(self.T("lbl_lang"))
        if hasattr(self, "lbl_theme"):
            self.lbl_theme.setText(self.T("lbl_theme"))
        if hasattr(self, "lbl_color"):
            self.lbl_color.setText(self.T("lbl_color"))
        if hasattr(self, "update_color_button"):
            self.update_color_button()
        if hasattr(self, "lbl_chk_rainbow"):
            self.lbl_chk_rainbow.setText(self.T("chk_rainbow"))
        if hasattr(self, "lbl_chk_adv_mode"):
            self.lbl_chk_adv_mode.setText(self.T("chk_adv_mode"))
        if hasattr(self, "lbl_chk_resize"):
            self.lbl_chk_resize.setText(self.T("chk_resize"))
        if hasattr(self, "lbl_chk_adv_logs"):
            self.lbl_chk_adv_logs.setText(self.T("chk_adv_logs"))
        if hasattr(self, "lbl_chk_exfat"):
            self.lbl_chk_exfat.setText(self.T("chk_exfat"))
        if hasattr(self, "lbl_chk_hide_warn"):
            self.lbl_chk_hide_warn.setText(self.T("chk_hide_warn"))
        if hasattr(self, "lbl_rainbow_hint"):
            self.lbl_rainbow_hint.setText(self.T("lbl_rainbow_hint"))
        if hasattr(self, "lbl_speed_text"):
            self.lbl_speed_text.setText(self.T("lbl_rb_speed"))
        if hasattr(self, "btn_reset_center"):
            self.btn_reset_center.setText(self.T("btn_reset"))

        if hasattr(self, "combo_theme"):
            cur_idx = self.combo_theme.currentIndex()
            self.combo_theme.blockSignals(True)
            self.combo_theme.clear()
            for key in ["theme_auto", "theme_light", "theme_dark", "theme_oled"]:
                self.combo_theme.addItem(self.T(key))
            self.combo_theme.setCurrentIndex(cur_idx if cur_idx >= 0 else 0)
            self.combo_theme.blockSignals(False)

        if hasattr(self, "rainbow_target_cbs"):
            mapping = {
                "title": "rb_title", "tabs": "rb_tabs", "buttons": "rb_btns",
                "progress": "rb_progress", "indicators": "rb_indicators",
                "text": "rb_text", "inputs": "rb_inputs", "console": "rb_console"
            }
            for k, cb in self.rainbow_target_cbs.items():
                if k in mapping:
                    cb.setText(self.T(mapping[k]))
