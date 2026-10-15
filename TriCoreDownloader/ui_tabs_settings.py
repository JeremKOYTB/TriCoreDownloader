import os
import sys
import platform
import subprocess
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QFrame,
    QSizePolicy
)
from PyQt6.QtCore import Qt

from .ui_tabs_settings_paths import UiTabsSettingsPathsMixin
from .ui_tabs_settings_app import UiTabsSettingsAppMixin
from .config import IS_STORE_PYTHON

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


def _detect_os_and_arch(unknown_label="Unknown"):
    if sys.platform == "win32":
        os_name = "Windows"
    elif sys.platform == "darwin":
        os_name = "macOS"
    elif sys.platform.startswith("linux"):
        os_name = "Linux"
    else:
        os_name = unknown_label

    raw_mach = (platform.machine() or "").strip().lower()
    arch_name = unknown_label

    if sys.platform == "darwin":
        is_arm = raw_mach.startswith("arm64") or raw_mach.startswith("aarch64")
        if not is_arm and hasattr(os, "uname"):
            try:
                u_m = (os.uname().machine or "").strip().lower()
                if u_m.startswith("arm64") or u_m.startswith("aarch64"):
                    is_arm = True
            except Exception:
                pass
        if not is_arm:
            for sysctl_key in ("hw.optional.arm64", "sysctl.proc_translated"):
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", sysctl_key],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=1,
                    )
                    if res.stdout.strip() == "1":
                        is_arm = True
                        break
                except Exception:
                    pass
        if is_arm:
            arch_name = "arm64 / Apple Silicon"
        elif raw_mach in ("x86_64", "amd64", "x64"):
            arch_name = "x64 / Intel"
        elif raw_mach:
            arch_name = raw_mach
    elif sys.platform == "win32":
        proc_arch = os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
        if raw_mach in ("amd64", "x86_64", "x64") or proc_arch in ("amd64", "x64"):
            arch_name = "x64"
        elif raw_mach.startswith("arm64") or raw_mach.startswith("aarch64") or proc_arch == "arm64":
            arch_name = "arm64"
        elif raw_mach in ("x86", "i386", "i686") or proc_arch == "x86":
            arch_name = "x86"
        elif raw_mach:
            arch_name = raw_mach
    elif sys.platform.startswith("linux"):
        if raw_mach in ("x86_64", "amd64", "x64"):
            arch_name = "x86_64"
        elif raw_mach.startswith("arm64") or raw_mach.startswith("aarch64"):
            arch_name = "arm64"
        elif raw_mach:
            arch_name = raw_mach
    elif raw_mach:
        arch_name = raw_mach

    return os_name, arch_name


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

        self._load_settings_into_ui()

    def _load_settings_into_ui(self):
        self._is_loading_ui = True

        if hasattr(self, "input_hactool"):
            self.input_hactool.setText(self.config.get("hactool", ""))
        if hasattr(self, "input_keys"):
            self.input_keys.setText(self.config.get("prod_keys", ""))
        if hasattr(self, "input_prodinfo"):
            self.input_prodinfo.setText(self.config.get("prodinfo", ""))
        if hasattr(self, "input_boot9"):
            self.input_boot9.setText(self.config.get("boot9_path", ""))
        if hasattr(self, "input_otp"):
            self.input_otp.setText(self.config.get("otp_path", ""))
        if hasattr(self, "input_aria2c"):
            self.input_aria2c.setText(self.config.get("aria2c_path", ""))
        if hasattr(self, "input_openssl"):
            self.input_openssl.setText(self.config.get("openssl_path", ""))

        if hasattr(self, "chk_adv_mode"):
            self.chk_adv_mode.setChecked(bool(self.config.get("advanced_mode", False)))
        if hasattr(self, "chk_adv_logs"):
            self.chk_adv_logs.setChecked(bool(self.config.get("advanced_logs", False)))
        if hasattr(self, "chk_hide_warn"):
            self.chk_hide_warn.setChecked(bool(self.config.get("hide_privacy_warning", False)))
        if hasattr(self, "chk_exfat"):
            self.chk_exfat.setChecked(bool(self.config.get("exclude_exfat", False)))
        if hasattr(self, "chk_resize"):
            self.chk_resize.setChecked(bool(self.config.get("allow_resize", False)))
        if hasattr(self, "chk_auto_save"):
            self.chk_auto_save.setChecked(bool(self.config.get("auto_save", False)))
        if hasattr(self, "chk_use_aria2c"):
            self.chk_use_aria2c.setChecked(bool(self.config.get("use_aria2c", False)))

        lang = str(self.config.get("lang") or "EN").upper()
        if hasattr(self, "combo_lang"):
            idx_lang = self.combo_lang.findData(lang)
            if idx_lang >= 0:
                self.combo_lang.blockSignals(True)
                self.combo_lang.setCurrentIndex(idx_lang)
                self.combo_lang.blockSignals(False)

        theme = str(self.config.get("theme", "auto")).lower()
        theme_map = {"auto": 0, "light": 1, "dark": 2, "oled": 3}
        if hasattr(self, "combo_theme"):
            self.combo_theme.blockSignals(True)
            self.combo_theme.setCurrentIndex(theme_map.get(theme, 0))
            self.combo_theme.blockSignals(False)

        self._is_loading_ui = False
        self._settings_dirty = False
        self._update_settings_ui()

    def _update_settings_ui(self, *args):
        mode = getattr(self, "current_console", "NX")
        target_idx = TARGET_MODES.get(mode, 0)

        if hasattr(self, "paths_stack") and 0 <= target_idx < self.paths_stack.count():
            if getattr(self, "_last_settings_target_idx", None) != target_idx:
                self._last_settings_target_idx = target_idx
                for i in range(self.paths_stack.count()):
                    page = self.paths_stack.widget(i)
                    policy = QSizePolicy.Policy.Preferred if i == target_idx else QSizePolicy.Policy.Ignored
                    page.setSizePolicy(policy, policy)
                self.paths_stack.setCurrentIndex(target_idx)

        nx_widgets = [
            "lbl_hactool", "input_hactool", "btn_browse_hactool", "btn_auto_hactool", "btn_help_hactool",
            "lbl_keys", "input_keys", "btn_browse_keys", "btn_help_keys",
            "lbl_prodinfo", "input_prodinfo", "btn_browse_prodinfo", "btn_help_prodinfo"
        ]
        for attr in nx_widgets:
            if hasattr(self, attr):
                _set_vis(getattr(self, attr), mode == "NX")

        ctr_widgets = ["lbl_boot9", "input_boot9", "btn_browse_boot9", "btn_help_boot9"]
        for attr in ctr_widgets:
            if hasattr(self, attr):
                _set_vis(getattr(self, attr), mode == "CTR")

        cafe_widgets = ["lbl_otp", "input_otp", "btn_browse_otp", "btn_help_otp"]
        for attr in cafe_widgets:
            if hasattr(self, attr):
                _set_vis(getattr(self, attr), mode == "CAFE")

        effective_adv = bool(self.chk_adv_mode.isChecked()) if hasattr(self, "chk_adv_mode") else False
        is_nx = (mode == "NX")

        _set_vis(getattr(self, "adv_options_widget", None), effective_adv)
        _set_vis(getattr(self, "cont_resize", None), effective_adv)
        _set_vis(getattr(self, "cont_exfat", None), effective_adv and is_nx)
        _set_vis(getattr(self, "cont_adv_logs", None), effective_adv)

        show_hide_warn = bool(effective_adv and is_nx and hasattr(self, "chk_adv_logs") and self.chk_adv_logs.isChecked())
        _set_vis(getattr(self, "cont_hide_warn", None), show_hide_warn)

        show_aria = bool(effective_adv and is_nx)
        show_aria_options = bool(show_aria and hasattr(self, "chk_use_aria2c") and self.chk_use_aria2c.isChecked())

        _set_vis(getattr(self, "sep_nx", None), show_aria)
        _set_vis(getattr(self, "cont_aria2c", None), show_aria)
        _set_vis(getattr(self, "btn_auto_detect_aria", None), show_aria_options)
        _set_vis(getattr(self, "lbl_aria2c", None), show_aria_options)
        _set_vis(getattr(self, "input_aria2c", None), show_aria_options)
        _set_vis(getattr(self, "widget_aria2c_btns", None), show_aria_options)
        _set_vis(getattr(self, "lbl_openssl", None), show_aria_options)
        _set_vis(getattr(self, "input_openssl", None), show_aria_options)
        _set_vis(getattr(self, "widget_openssl_btns", None), show_aria_options)
        _set_vis(getattr(self, "sep_nx_bot", None), show_aria)

        if hasattr(self, "paths_stack"):
            self.paths_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

        out_key = f"output_dir_{mode.lower()}"
        current_out = self.config.get(out_key, self.config.get("output_dir", ""))
        if hasattr(self, "input_output"):
            self.input_output.blockSignals(True)
            self.input_output.setText(current_out)
            self.input_output.blockSignals(False)

    def get_runtime_env_summary(self):
        unknown_val = self.T("sys_unknown_val", "Unknown")
        os_name, arch_name = _detect_os_and_arch(unknown_val)

        is_frozen = bool(getattr(sys, "frozen", False))
        if is_frozen:
            build_edition = self.T("sys_compiled_edition", "Compiled Edition")
        else:
            build_edition = self.T("sys_source_edition", "Source Code Edition")

        py_edition = (
            self.T("sys_store_edition", "Microsoft Store Edition")
            if IS_STORE_PYTHON
            else self.T("sys_standard_edition", "Standard Edition")
        )
        return os_name, arch_name, build_edition, py_edition

    def update_sys_info_label(self):
        if not hasattr(self, "lbl_sys_info"):
            return

        if not hasattr(self, "_cached_save_dir"):
            try:
                from .config import CONFIG_FILE
                config_path = str(CONFIG_FILE.resolve() if isinstance(CONFIG_FILE, Path) else os.path.abspath(CONFIG_FILE))
            except Exception:
                config_path = os.path.abspath("config.json")
            self._cached_save_dir = os.path.dirname(config_path)

        os_name, arch_name, build_edition, py_edition = self.get_runtime_env_summary()
        save_loc_str = self.T("sys_save_location", "Emplacement de sauvegarde")

        line1 = f"{os_name} ({arch_name}) • [{build_edition}] | {PY_VER_STR} ([{py_edition}])"
        line2 = f"{save_loc_str} : {self._cached_save_dir}"
        self.lbl_sys_info.setText(f"{line1}\n{line2}")

    def retranslate_settings_tab(self):
        if hasattr(self, "retranslate_paths_section"):
            self.retranslate_paths_section()
        if hasattr(self, "retranslate_app_section"):
            self.retranslate_app_section()
        self.update_sys_info_label()
