import random
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QPushButton, QStackedWidget, QMessageBox,
    QFrame, QButtonGroup, QCheckBox, QComboBox, QRadioButton, 
    QApplication, QSizePolicy, QScrollArea, QSlider, QLineEdit, QDialog
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QByteArray, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QCursor, QDesktopServices, QPainter, QColor

from .config import save_config
from .custom_widgets import CustomConsoleSelector
from .ui_tabs import UiTabsMixin
from .ui_tabs_settings import UiTabsSettingsMixin
from .rainbow_mode import RainbowModeMixin
from .settings_logic import SettingsMixin

from .logos import (
    NX_LOGO_SVG, CTR_LOGO_BLACK_SVG, CTR_LOGO_WHITE_SVG, CAFE_LOGO_SVG, 
    CTR_LOGO_CLEAN_SVG, VOL_HIGH_SVG, VOL_LOW_SVG, VOL_MUTE_SVG, 
    RESTART_SVG, WARNING_SVG, TCD_MAIN_LOGO
)
from .ui_theme_locale import UiThemeLocaleMixin

SCROLLBAR_CSS = """
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #80888888;
    min-height: 30px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #CC888888;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0px;
    background: transparent;
}
"""

class FirmwareAppUI(QMainWindow, UiTabsMixin, UiTabsSettingsMixin, RainbowModeMixin, SettingsMixin, UiThemeLocaleMixin):
    def __init__(self, config_data):
        super().__init__()
        
        self._is_loading_ui = True
        self.config = config_data  
        
        try:
            from .Languages.locales import STRINGS
        except Exception:
            STRINGS = None

        if not STRINGS:
            msg = QDialog()
            msg.setWindowTitle("TriCoreDownloader (!ERROR!)")
            
            window_container = QVBoxLayout(msg)
            window_container.setContentsMargins(32, 28, 32, 24)
            window_container.setSpacing(24)

            try:
                pm_main = QPixmap()
                pm_main.loadFromData(QByteArray(TCD_MAIN_LOGO), "SVG")
                if not pm_main.isNull():
                    msg.setWindowIcon(QIcon(pm_main))
            except Exception:
                pass

            lbl_text = QLabel(
                "No language files could be detected in\n '\\TriCoreDownloader\\Languages'.\n\n"
                "• Did you extract the application archive correctly?\nMake sure all folders are present.\n\n"
                "• If the files are there and you believe this is a bug,\nplease submit an issue report on GitHub.\n\n"
                "Would you like to force launch anyway?\n(All UI text will be broken or raw)."
            )
            lbl_text.setTextFormat(Qt.TextFormat.PlainText)
            lbl_text.setStyleSheet("font-size: 10.5pt; line-height: 1.4;")
            lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            window_container.addWidget(lbl_text)

            btn_layout = QHBoxLayout()
            btn_layout.setSpacing(12)
            btn_layout.addStretch()  

            btn_yes = QPushButton("Force Launch")
            btn_no = QPushButton("Exit")
            btn_issue = QPushButton("Report Issue (GitHub)")
            
            for btn in [btn_yes, btn_no, btn_issue]:
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet("padding: 6px 16px; font-weight: bold;")
                btn_layout.addWidget(btn)
                
            btn_layout.addStretch()  
            window_container.addLayout(btn_layout)

            window_container.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

            user_choice = {"action": "exit"}

            def accept_force():
                user_choice["action"] = "launch"
                msg.accept()

            def reject_exit():
                user_choice["action"] = "exit"
                msg.reject()

            def open_github_issues():
                QDesktopServices.openUrl(QUrl("https://github.com/JeremKOYTB/TriCoreDownloader/issues"))

            btn_yes.clicked.connect(accept_force)
            btn_no.clicked.connect(reject_exit)
            btn_issue.clicked.connect(open_github_issues)

            msg.exec()
            
            if user_choice["action"] == "exit":
                sys.exit(0)
        
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        QTimer.singleShot(800, self._remove_top_hint)
        
        if "output_dir" in self.config and "output_dir_nx" not in self.config:
            self.config["output_dir_nx"] = self.config["output_dir"]
            
        for m in ["nx", "cafe", "ctr"]:
            if f"output_dir_{m}" not in self.config: 
                self.config[f"output_dir_{m}"] = ""
            if f"ask_open_folder_{m}" not in self.config: 
                self.config[f"ask_open_folder_{m}"] = self.config.get("ask_open_folder", True)
            if f"auto_open_folder_{m}" not in self.config: 
                self.config[f"auto_open_folder_{m}"] = self.config.get("auto_open_folder", False)
                
        self.init_language()
        
        self.rainbow_hue = float(random.randint(0, 359))
        self.rainbow_interval = 33 
        self.rainbow_timer = QTimer(self)
        self.rainbow_timer.timeout.connect(self.tick_rainbow)
        if self.config.get("rainbow_mode", False):
            self.rainbow_timer.start(self.rainbow_interval)

        if self.config.get("first_launch", True): 
            self.current_console = "WELCOME"
        else: 
            self.current_console = self.config.get("console_mode", "NX")
            if self.current_console not in ["NX", "CTR", "CAFE"]:
                self.current_console = "NX"

        raw_color = str(self.config.get("accent_color", "")).strip().lower()
        default_tokens = ["#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""]
        self.pending_color = "" if (not raw_color or raw_color in default_tokens) else self.config.get("accent_color", "")

        self.setWindowOpacity(0.0)
        self.startup_anim = QPropertyAnimation(self, b"windowOpacity")
        self.startup_anim.setDuration(300)
        self.startup_anim.setStartValue(0.0)
        self.startup_anim.setEndValue(1.0)
        self.startup_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        self.header_widget = QWidget()
        header_grid = QGridLayout(self.header_widget)
        header_grid.setContentsMargins(0, 0, 0, 0)
        
        header_grid.setColumnMinimumWidth(0, 200)
        header_grid.setColumnMinimumWidth(2, 200)
        
        header_grid.setColumnStretch(0, 1)
        header_grid.setColumnStretch(1, 0)
        header_grid.setColumnStretch(2, 1)
        
        self.console_selector = CustomConsoleSelector()
        self.console_selector.setMinimumHeight(42)
        self.console_selector.setFixedWidth(200)
        
        self.refresh_all_static_icons()
        
        self.console_selector.addItem(self.icon_nx, self.T("console_nx"))
        self.console_selector.addItem(self.icon_ctr_selector, self.T("console_ctr"))
        self.console_selector.addItem(self.icon_cafe, self.T("console_cafe"))
        
        if self.current_console == "WELCOME":
            mode_idx = 0
        else:
            mode_idx = {"NX": 0, "CTR": 1, "CAFE": 2}.get(self.current_console, 0)
            
        self.console_selector.blockSignals(True)
        self.console_selector.setCurrentIndex(mode_idx)
        self.console_selector.blockSignals(False)
        
        combo_layout = QVBoxLayout()
        combo_layout.setContentsMargins(0, 0, 0, 16) 
        combo_layout.addWidget(self.console_selector, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_grid.addLayout(combo_layout, 0, 0)
        
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel()
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 35px; font-weight: bold; font-family: 'Segoe UI', sans-serif;")
        self.refresh_title_color()
        title_box.addWidget(self.lbl_title)
        
        self.lbl_sub = QLabel(self.T("subtitle"))
        self.lbl_sub.setObjectName("HintText")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_box.addWidget(self.lbl_sub)
        
        header_grid.addLayout(title_box, 0, 1, Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.header_widget)

        self.nav_wrapper = QWidget()
        self.nav_wrapper_layout = QVBoxLayout(self.nav_wrapper)
        self.nav_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_wrapper_layout.setSpacing(0)
        
        self.nav_container = QWidget()
        self.nav_layout = QHBoxLayout(self.nav_container)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_tab_dl = QPushButton(self.T("tab_dl"))
        self.btn_tab_dl.setObjectName("NavTab")
        self.btn_tab_dl.setCheckable(True)
        self.btn_tab_dl.setChecked(True)
        self.btn_tab_dl.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_tab_restart = QPushButton(self.T("btn_restart_app"))
        self.btn_tab_restart.setObjectName("btnReset")
        self.btn_tab_restart.setStyleSheet("padding: 6px 16px;")
        self.btn_tab_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_tab_cfg = QPushButton(self.T("tab_cfg"))
        self.btn_tab_cfg.setObjectName("NavTab")
        self.btn_tab_cfg.setCheckable(True)
        self.btn_tab_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.nav_layout.addWidget(self.btn_tab_dl)
        self.nav_layout.addStretch()
        self.nav_layout.addWidget(self.btn_tab_restart)
        self.nav_layout.addStretch()
        self.nav_layout.addWidget(self.btn_tab_cfg)
        
        self.nav_line = QFrame()
        self.nav_line.setObjectName("NavLine")
        self.nav_line.setFrameShape(QFrame.Shape.HLine)
        
        self.nav_wrapper_layout.addWidget(self.nav_container)
        self.nav_wrapper_layout.addWidget(self.nav_line)
        main_layout.addWidget(self.nav_wrapper)

        self.tabs = QStackedWidget()
        self.tab_main = QWidget()
        self.tab_settings = QWidget()
        self.tab_credits = QWidget()
        self.tab_welcome = QWidget()
        
        self.tabs.addWidget(self.tab_main)     
        self.tabs.addWidget(self.tab_settings) 
        self.tabs.addWidget(self.tab_credits)  
        self.tabs.addWidget(self.tab_welcome)  
        
        main_layout.addWidget(self.tabs)

        self.bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_sys_info = QLabel()
        self.lbl_sys_info.setObjectName("HintText")
        self.lbl_sys_info.setStyleSheet("font-size: 8pt; color: #6C757D;")
        self.lbl_sys_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.update_sys_info_label()
        self.lbl_sys_info.setVisible(self.config.get("advanced_logs", False))
        
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.lbl_sys_info)
        bottom_layout.addStretch(1)
        
        self.btn_tab_credits = QPushButton(self.T("tab_credits"))
        self.btn_tab_credits.setObjectName("BtnCredits")
        self.btn_tab_credits.setCheckable(True)
        self.btn_tab_credits.setCursor(Qt.CursorShape.PointingHandCursor)
        
        bottom_layout.addWidget(self.btn_tab_credits)
        main_layout.addWidget(self.bottom_widget)

        if self.current_console == "WELCOME":
            self.header_widget.setVisible(False)
            self.nav_wrapper.setVisible(False)
            self.btn_tab_credits.setVisible(False)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.addButton(self.btn_tab_dl, 0)
        self.nav_group.addButton(self.btn_tab_cfg, 1)
        self.nav_group.addButton(self.btn_tab_credits, 2)
        
        self.worker = None
        self.setup_main_tab()
        
        if hasattr(self, "init_nx_firmware_list"):
            self.init_nx_firmware_list()
        
        self.page_target_cafe = QWidget()
        layout_cafe = QVBoxLayout(self.page_target_cafe)
        layout_cafe.setContentsMargins(0, 0, 0, 0)
        layout_cafe.setSpacing(6)
        
        self.lbl_manual_hint_cafe = QLabel()
        self.lbl_manual_hint_cafe.setObjectName("HintText")
        self.lbl_manual_hint_cafe.setWordWrap(True)
        self.lbl_manual_hint_cafe.setVisible(False)
        layout_cafe.addWidget(self.lbl_manual_hint_cafe)

        self.frame_warn_cafe = QFrame()
        self.frame_warn_cafe.setStyleSheet("border: 1px solid #FF4444; border-radius: 5px; background-color: rgba(255, 68, 68, 0.1);")
        self.frame_warn_cafe.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        warn_layout = QVBoxLayout(self.frame_warn_cafe)
        warn_layout.setContentsMargins(12, 12, 12, 12)
        warn_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        
        self.lbl_warn_cafe_downgrade = QLabel()
        self.lbl_warn_cafe_downgrade.setWordWrap(True)
        f_warn = self.lbl_warn_cafe_downgrade.font()
        f_warn.setBold(True)
        self.lbl_warn_cafe_downgrade.setFont(f_warn)
        self.lbl_warn_cafe_downgrade.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_warn_cafe_downgrade.setStyleSheet("color: #FF4444; border: none; background-color: transparent;")
        
        warn_layout.addWidget(self.lbl_warn_cafe_downgrade)
        self.frame_warn_cafe.setVisible(False)
        layout_cafe.addWidget(self.frame_warn_cafe)

        self.lbl_cafe_part = QLabel(self.T("cafe_lbl_part"))
        self.lbl_cafe_part.setStyleSheet("font-weight: bold;")
        layout_cafe.addWidget(self.lbl_cafe_part)

        self.radio_mlc = QRadioButton(self.T("cafe_part_mlc"))
        self.radio_slc = QRadioButton(self.T("cafe_part_slc"))
        self.radio_both = QRadioButton(self.T("cafe_part_both"))
        
        saved_parts = self.config.get("cafe_partitions", ["MLC", "SLC"])
        if saved_parts == ["MLC"]: 
            self.radio_mlc.setChecked(True)
        elif saved_parts == ["SLC"]: 
            self.radio_slc.setChecked(True)
        else: 
            self.radio_both.setChecked(True)
            
        self.grp_cafe_part = QButtonGroup(self)
        self.grp_cafe_part.addButton(self.radio_mlc)
        self.grp_cafe_part.addButton(self.radio_slc)
        self.grp_cafe_part.addButton(self.radio_both)
        layout_cafe.addWidget(self.radio_mlc)
        layout_cafe.addWidget(self.radio_slc)
        layout_cafe.addWidget(self.radio_both)
        layout_cafe.addSpacing(6)

        self.cafe_reg_container = QWidget()
        cafe_reg_layout = QVBoxLayout(self.cafe_reg_container)
        cafe_reg_layout.setContentsMargins(0, 0, 0, 0)
        cafe_reg_layout.setSpacing(6)

        self.lbl_cafe_reg = QLabel(self.T("cafe_lbl_reg"))
        self.lbl_cafe_reg.setStyleSheet("font-weight: bold;")
        cafe_reg_layout.addWidget(self.lbl_cafe_reg)

        self.radio_eur = QRadioButton(self.T("cafe_reg_eur"))
        self.radio_usa = QRadioButton(self.T("cafe_reg_usa"))
        self.radio_jpn = QRadioButton(self.T("cafe_reg_jpn"))
        
        saved_region = self.config.get("cafe_region", "EUR")
        if saved_region == "USA": self.radio_usa.setChecked(True)
        elif saved_region == "JPN": self.radio_jpn.setChecked(True)
        else: self.radio_eur.setChecked(True)
            
        self.grp_cafe_reg = QButtonGroup(self)
        self.grp_cafe_reg.addButton(self.radio_eur)
        self.grp_cafe_reg.addButton(self.radio_usa)
        self.grp_cafe_reg.addButton(self.radio_jpn)
        
        cafe_reg_layout.addWidget(self.radio_eur)
        cafe_reg_layout.addWidget(self.radio_usa)
        cafe_reg_layout.addWidget(self.radio_jpn)
        
        layout_cafe.addWidget(self.cafe_reg_container)

        self.chk_cafe_extract = QCheckBox()
        self.cont_cafe_extract, self.lbl_cafe_extract = self.create_wrapped_checkbox(self.chk_cafe_extract, self.T("chk_cafe_extract"))
        self.chk_cafe_extract.setChecked(self.config.get("cafe_extract", False))
        
        layout_cafe.addSpacing(10)
        layout_cafe.addWidget(self.cont_cafe_extract)

        self.chk_cemu_layout = QCheckBox()
        self.cont_cemu_layout, self.lbl_cemu_layout = self.create_wrapped_checkbox(self.chk_cemu_layout, self.T("chk_cemu_layout"))
        self.chk_cemu_layout.setChecked(self.config.get("cafe_cemu_layout", False))
        
        layout_cafe.addSpacing(4)
        layout_cafe.addWidget(self.cont_cemu_layout)
            
        def on_cafe_extract_toggled(checked):
            if not checked:
                self.chk_cemu_layout.setChecked(False)
            self._update_cafe_adv_ui()

        self.chk_cafe_extract.toggled.connect(on_cafe_extract_toggled)

        def save_cafe_extract_options():
            self.config["cafe_extract"] = self.chk_cafe_extract.isChecked()
            self.config["cafe_cemu_layout"] = self.chk_cemu_layout.isChecked()
            if hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()
                
        self.chk_cafe_extract.toggled.connect(save_cafe_extract_options)
        self.chk_cemu_layout.toggled.connect(save_cafe_extract_options)

        layout_cafe.addStretch()

        if hasattr(self, 'scroll_layout'):
            self.scroll_layout.addWidget(self.page_target_cafe)
        self.page_target_cafe.setVisible(False)

        self.page_target_ctr = QWidget()
        layout_ctr = QVBoxLayout(self.page_target_ctr)
        layout_ctr.setContentsMargins(0, 0, 0, 0)
        layout_ctr.setSpacing(6)
        
        self.lbl_ctr_model = QLabel(self.T("ctr_lbl_model"))
        self.lbl_ctr_model.setStyleSheet("font-weight: bold;")
        layout_ctr.addWidget(self.lbl_ctr_model)

        self.radio_old_3ds = QRadioButton(self.T("ctr_model_old"))
        self.radio_new_3ds = QRadioButton(self.T("ctr_model_new"))

        saved_ctr_model = self.config.get("ctr_model", "OLD")
        if saved_ctr_model == "NEW": self.radio_new_3ds.setChecked(True)
        else: self.radio_old_3ds.setChecked(True)

        self.grp_ctr_model = QButtonGroup(self)
        self.grp_ctr_model.addButton(self.radio_old_3ds)
        self.grp_ctr_model.addButton(self.radio_new_3ds)
        layout_ctr.addWidget(self.radio_old_3ds)
        layout_ctr.addWidget(self.radio_new_3ds)
        layout_ctr.addSpacing(6)

        self.ctr_reg_container = QWidget()
        ctr_reg_layout = QVBoxLayout(self.ctr_reg_container)
        ctr_reg_layout.setContentsMargins(0, 0, 0, 0)
        ctr_reg_layout.setSpacing(6)

        self.lbl_ctr_reg = QLabel(self.T("ctr_lbl_reg"))
        self.lbl_ctr_reg.setStyleSheet("font-weight: bold;")
        ctr_reg_layout.addWidget(self.lbl_ctr_reg)

        self.radio_ctr_eur = QRadioButton(self.T("ctr_reg_eur"))
        self.radio_ctr_usa = QRadioButton(self.T("ctr_reg_usa"))
        self.radio_ctr_jpn = QRadioButton(self.T("ctr_reg_jpn"))
        self.radio_ctr_aus = QRadioButton(self.T("ctr_reg_aus"))
        self.radio_ctr_kor = QRadioButton(self.T("ctr_reg_kor"))
        self.radio_ctr_chn = QRadioButton(self.T("ctr_reg_chn"))
        self.radio_ctr_twn = QRadioButton(self.T("ctr_reg_twn"))

        saved_ctr_region = self.config.get("ctr_region", "EUR")
        if saved_ctr_region == "USA": self.radio_ctr_usa.setChecked(True)
        elif saved_ctr_region == "JPN": self.radio_ctr_jpn.setChecked(True)
        elif saved_ctr_region == "AUS": self.radio_ctr_aus.setChecked(True)
        elif saved_ctr_region == "KOR": self.radio_ctr_kor.setChecked(True)
        elif saved_ctr_region == "CHN": self.radio_ctr_chn.setChecked(True)
        elif saved_ctr_region == "TWN": self.radio_ctr_twn.setChecked(True)
        else: self.radio_ctr_eur.setChecked(True)

        self.grp_ctr_reg = QButtonGroup(self)
        self.grp_ctr_reg.addButton(self.radio_ctr_eur)
        self.grp_ctr_reg.addButton(self.radio_ctr_usa)
        self.grp_ctr_reg.addButton(self.radio_ctr_jpn)
        self.grp_ctr_reg.addButton(self.radio_ctr_aus)
        self.grp_ctr_reg.addButton(self.radio_ctr_kor)
        self.grp_ctr_reg.addButton(self.radio_ctr_chn)
        self.grp_ctr_reg.addButton(self.radio_ctr_twn)
        
        ctr_reg_layout.addWidget(self.radio_ctr_eur)
        ctr_reg_layout.addWidget(self.radio_ctr_usa)
        ctr_reg_layout.addWidget(self.radio_ctr_jpn)
        ctr_reg_layout.addWidget(self.radio_ctr_aus)
        ctr_reg_layout.addWidget(self.radio_ctr_kor)
        ctr_reg_layout.addWidget(self.radio_ctr_chn)
        ctr_reg_layout.addWidget(self.radio_ctr_twn)

        layout_ctr.addWidget(self.ctr_reg_container)

        self.chk_ctr_decrypt = QCheckBox()
        self.cont_ctr_decrypt, self.lbl_ctr_decrypt = self.create_wrapped_checkbox(self.chk_ctr_decrypt, self.T("chk_ctr_decrypt"))
        self.chk_ctr_decrypt.setChecked(self.config.get("decrypt_cia", False))

        def save_ctr_options():
            self.config["decrypt_cia"] = self.chk_ctr_decrypt.isChecked()
            if hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()

        self.chk_ctr_decrypt.toggled.connect(save_ctr_options)
        
        layout_ctr.addSpacing(10)
        layout_ctr.addWidget(self.cont_ctr_decrypt)

        layout_ctr.addStretch()

        if hasattr(self, 'scroll_layout'):
            self.scroll_layout.addWidget(self.page_target_ctr)
        self.page_target_ctr.setVisible(False)

        self.setup_credits_tab()
        self.setup_settings_tab()
        self.setup_welcome_tab() 
        self.refresh_all_static_icons()
        
        if hasattr(self, "btn_save"): 
            self.btn_save.clicked.connect(self._update_cafe_adv_ui)
        if hasattr(self, "chk_adv_mode"): 
            self.chk_adv_mode.toggled.connect(self._update_cafe_adv_ui)
        if hasattr(self, "chk_auto_save"): 
            self.chk_auto_save.toggled.connect(self._update_cafe_adv_ui)
            
        self._update_cafe_adv_ui()
        self.apply_window_constraints()
        self.retranslate_ui()
        
        app = QApplication.instance()
        if app:
            style_hints = app.styleHints()
            if hasattr(style_hints, 'colorSchemeChanged'):
                style_hints.colorSchemeChanged.connect(self._on_os_theme_changed)

    def setup_welcome_tab(self):
        layout = QVBoxLayout(self.tab_welcome)
        layout.setContentsMargins(0, 0, 0, 0)
        
        scroll_area = QScrollArea()
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: transparent;\n" + SCROLLBAR_CSS)
        
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: transparent;")
        container_layout = QVBoxLayout(scroll_widget)
        container_layout.setContentsMargins(40, 60, 40, 60)
        container_layout.setSpacing(20)
        
        self.lbl_welcome_title = QLabel(self.T("welcome_title"))
        self.lbl_welcome_title.setStyleSheet("font-size: 36px; font-weight: bold;")
        self.lbl_welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.lbl_welcome_title)
        
        self.lbl_welcome_intro = QLabel(self.T("welcome_subtitle"))
        self.lbl_welcome_intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_welcome_intro.setStyleSheet("font-size: 16px; margin-bottom: 30px; color: #888888;")
        self.lbl_welcome_intro.setObjectName("HintText") 
        container_layout.addWidget(self.lbl_welcome_intro)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(25)
        
        self.btn_welcome_cafe = QPushButton(" " + self.T("console_cafe"))
        self.btn_welcome_cafe.setObjectName("BtnWelcomeCAFE")
        
        self.btn_welcome_nx = QPushButton(" " + self.T("console_nx"))
        self.btn_welcome_nx.setObjectName("BtnWelcomeNX")
        
        self.btn_welcome_ctr = QPushButton(" " + self.T("console_ctr"))
        self.btn_welcome_ctr.setObjectName("BtnWelcomeCTR")
        
        for btn in [self.btn_welcome_cafe, self.btn_welcome_nx, self.btn_welcome_ctr]:
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setMinimumHeight(180)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            btn_layout.addWidget(btn)
            
        container_layout.addLayout(btn_layout)
        container_layout.addSpacing(20)

        frame_info = QFrame()
        frame_info.setObjectName("WelcomeInfoBox")
        
        info_layout = QVBoxLayout(frame_info)
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(15)
        
        self.lbl_welcome_info_title = QLabel(self.T("welcome_info_title"))
        self.lbl_welcome_info_title.setObjectName("WelcomeInfoTitle")
        self.lbl_welcome_info_title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.lbl_welcome_info_desc = QLabel(self.T("welcome_info_desc"))
        self.lbl_welcome_info_desc.setObjectName("WelcomeInfoDesc")
        self.lbl_welcome_info_desc.setWordWrap(True)
        
        self.lbl_welcome_info_risk = QLabel(self.T("welcome_info_risk"))
        self.lbl_welcome_info_risk.setObjectName("WelcomeInfoRisk")
        self.lbl_welcome_info_risk.setWordWrap(True)
        
        info_layout.addWidget(self.lbl_welcome_info_title)
        info_layout.addWidget(self.lbl_welcome_info_desc)
        info_layout.addWidget(self.lbl_welcome_info_risk)
        
        container_layout.addWidget(frame_info)
        container_layout.addSpacing(20)
        
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(20)
        
        adv_layout = QHBoxLayout()
        self.chk_welcome_adv = QCheckBox(self.T("chk_welcome_adv"))
        self.chk_welcome_adv.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.chk_welcome_adv.setStyleSheet("font-size: 14px; font-weight: bold;")
        
        self.btn_welcome_help = QPushButton("?")
        self.btn_welcome_help.setObjectName("BtnWelcomeHelp")
        self.btn_welcome_help.setFixedSize(24, 24)
        self.btn_welcome_help.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_welcome_help.setToolTip(self.T("tooltip_welcome_adv"))
        
        def show_adv_warning():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("msg_adv_warning_title"))
            msg_box.setText(self.T("msg_adv_warning_desc"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.exec()

        self.btn_welcome_help.clicked.connect(show_adv_warning)
        
        adv_layout.addWidget(self.chk_welcome_adv)
        adv_layout.addWidget(self.btn_welcome_help)
        
        self.chk_welcome_logs = QCheckBox(self.T("chk_welcome_logs"))
        self.chk_welcome_logs.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        sp = self.chk_welcome_logs.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.chk_welcome_logs.setSizePolicy(sp)
        self.chk_welcome_logs.setVisible(False) 
        
        def on_welcome_adv_toggled(checked):
            self.chk_welcome_logs.setVisible(checked)
            if not checked:
                self.chk_welcome_logs.setChecked(False)
                
        self.chk_welcome_adv.toggled.connect(on_welcome_adv_toggled)
        adv_layout.addWidget(self.chk_welcome_logs)
        
        vol_layout = QHBoxLayout()
        self.lbl_welcome_vol_icon = QLabel()
        self.lbl_welcome_vol_icon.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        self.slider_welcome_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_welcome_vol.setRange(0, 100)
        current_vol = self.config.get("volume", 50)
        self.slider_welcome_vol.setValue(current_vol)
        self.slider_welcome_vol.setFixedWidth(150)
        self.slider_welcome_vol.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        self.lbl_welcome_vol_val = QLabel(f"{current_vol}%")
        self.lbl_welcome_vol_val.setStyleSheet("font-size: 14px; font-weight: bold;")
        
        def _update_vol_icon(val=None):
            if val is None: val = self.slider_welcome_vol.value()
            theme_pref = self.config.get("theme", "auto")
            
            is_dark = False
            if theme_pref in ["dark", "oled"]:
                is_dark = True
            elif theme_pref == "auto":
                if hasattr(self, "get_effective_is_dark"):
                    is_dark = self.get_effective_is_dark()
                    
            text_color = "#FFFFFF" if is_dark else "#333333"
            
            if val == 0: 
                svg_data = VOL_MUTE_SVG
            elif val < 50: 
                svg_data = VOL_LOW_SVG
            else: 
                svg_data = VOL_HIGH_SVG
                
            pm_vol = QPixmap()
            pm_vol.loadFromData(QByteArray(svg_data), "SVG")
            
            if not pm_vol.isNull():
                painter = QPainter(pm_vol)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pm_vol.rect(), QColor(text_color))
                painter.end()
                self.lbl_welcome_vol_icon.setPixmap(pm_vol.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        self.update_welcome_vol_icon = _update_vol_icon
        self.update_welcome_vol_icon(current_vol)

        self._pre_mute_welcome_vol = current_vol if current_vol > 0 else 50
        def toggle_welcome_mute(event):
            if event.button() == Qt.MouseButton.LeftButton:
                if self.slider_welcome_vol.value() > 0:
                    self._pre_mute_welcome_vol = self.slider_welcome_vol.value()
                    self.slider_welcome_vol.setValue(0)
                else:
                    restored_vol = self._pre_mute_welcome_vol if self._pre_mute_welcome_vol > 0 else 50
                    self.slider_welcome_vol.setValue(restored_vol)
                event.accept()
                
        self.lbl_welcome_vol_icon.mousePressEvent = toggle_welcome_mute

        def on_vol_changed(val):
            self.lbl_welcome_vol_val.setText(f"{val}%")
            self.config["volume"] = val
            self.update_welcome_vol_icon(val)
            if hasattr(self, "audio"):
                self.audio.set_global_volume(val)
                
        self.slider_welcome_vol.valueChanged.connect(on_vol_changed)
        
        self.slider_welcome_vol.sliderReleased.connect(
            lambda: self.audio.play_test_sound() if hasattr(self, "audio") and hasattr(self.audio, "play_test_sound") and self.slider_welcome_vol.value() > 0 else None
        )
        
        vol_layout.addWidget(self.lbl_welcome_vol_icon)
        vol_layout.addWidget(self.slider_welcome_vol)
        vol_layout.addWidget(self.lbl_welcome_vol_val)
        
        bottom_layout.addLayout(adv_layout)
        bottom_layout.addStretch()
        bottom_layout.addLayout(vol_layout)
        
        container_layout.addLayout(bottom_layout)
        
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

    def _remove_top_hint(self):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.show()

    def refresh_all_static_icons(self):
        theme_pref = self.config.get("theme", "auto")
        is_dark = False
        if theme_pref in ["dark", "oled"]:
            is_dark = True
        elif theme_pref == "auto":
            if hasattr(self, "get_effective_is_dark"):
                is_dark = self.get_effective_is_dark()

        try:
            pm_nx = QPixmap()
            pm_nx.loadFromData(QByteArray(NX_LOGO_SVG), "SVG")
            if not pm_nx.isNull(): self.icon_nx = QIcon(pm_nx)
        except Exception: pass
        
        try:
            pm_cafe = QPixmap()
            pm_cafe.loadFromData(QByteArray(CAFE_LOGO_SVG), "SVG")
            if not pm_cafe.isNull(): self.icon_cafe = QIcon(pm_cafe)
        except Exception: pass
        
        try:
            self.pm_ctr_clean = QPixmap()
            self.pm_ctr_clean.loadFromData(QByteArray(CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_CLEAN_SVG), "SVG")
            if not self.pm_ctr_clean.isNull(): self.icon_ctr_selector = QIcon(self.pm_ctr_clean)
        except Exception: pass

        if hasattr(self, "console_selector") and self.console_selector.count() >= 3:
            self.console_selector.blockSignals(True)
            if hasattr(self, "icon_nx"): self.console_selector.setItemIcon(0, self.icon_nx)
            if hasattr(self, "icon_ctr_selector"): self.console_selector.setItemIcon(1, self.icon_ctr_selector)
            if hasattr(self, "icon_cafe"): self.console_selector.setItemIcon(2, self.icon_cafe)
            self.console_selector.blockSignals(False)

        if hasattr(self, "btn_tab_restart"):
            try:
                pm_restart = QPixmap()
                pm_restart.loadFromData(QByteArray(RESTART_SVG), "SVG")
                if not pm_restart.isNull():
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
                if not pm_info.isNull():
                    color_info = "#FFFFFF" if is_dark else "#888888"
                    painter = QPainter(pm_info)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    painter.fillRect(pm_info.rect(), QColor(color_info))
                    painter.end()
                    info_icon = QIcon(pm_info)
                    info_icon.addPixmap(pm_info, QIcon.Mode.Disabled)
                    self.btn_tab_credits.setIcon(info_icon)
            except Exception: pass

        if hasattr(self, "btn_welcome_ctr"):
            ctr_svg = CTR_LOGO_WHITE_SVG if is_dark else CTR_LOGO_BLACK_SVG
            try:
                if hasattr(self, "get_svg_icon"):
                    self.btn_welcome_ctr.setIcon(QIcon(self.get_svg_icon(ctr_svg)))
            except Exception: pass
            
        if hasattr(self, "_update_vol_icon"):
            try: self._update_vol_icon()
            except Exception: pass
            
        if hasattr(self, "update_welcome_vol_icon"):
            try: self.update_welcome_vol_icon()
            except Exception: pass

    def _update_cafe_adv_ui(self, *args):
        adv_on = getattr(self, "chk_adv_mode", None)
        adv_checked = adv_on.isChecked() if adv_on else self.config.get("advanced_mode", False)
        saved_adv = self.config.get("advanced_mode", False)
        
        auto_save_on = getattr(self, "chk_auto_save", None)
        is_auto_save = auto_save_on.isChecked() if auto_save_on else self.config.get("auto_save", False)
        
        effective_adv = adv_checked if is_auto_save else saved_adv
            
        if hasattr(self, "radio_manual") and hasattr(self, "radio_latest"):
            if hasattr(self, "current_console") and self.current_console == "NX":
                if hasattr(self, "radio_list"):
                    self.radio_list.setVisible(effective_adv)
                    if hasattr(self, "list_input_container"):
                        self.list_input_container.setVisible(effective_adv and self.radio_list.isChecked())
                    if not effective_adv and self.radio_list.isChecked():
                        self.radio_latest.setChecked(True)
                self.radio_manual.setVisible(effective_adv)
                if not effective_adv and self.radio_manual.isChecked():
                    self.radio_latest.setChecked(True)
                    if hasattr(self, "input_manual"):
                        self.input_manual.setVisible(False)
            else:
                if hasattr(self, "radio_list"):
                    self.radio_list.setVisible(False)
                    if hasattr(self, "list_input_container"):
                        self.list_input_container.setVisible(False)
                    if self.radio_list.isChecked():
                        self.radio_latest.setChecked(True)
                if hasattr(self, "radio_manual"):
                    self.radio_manual.setVisible(effective_adv)
                    if not effective_adv and self.radio_manual.isChecked():
                        self.radio_latest.setChecked(True)

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
        new_lang = None
        if hasattr(self, "combo_lang"):
            new_lang = self.combo_lang.itemData(index)
        if not new_lang and hasattr(self, "lang_codes") and 0 <= index < len(self.lang_codes):
            new_lang = self.lang_codes[index]
            
        if new_lang:
            self.config["lang"] = str(new_lang).strip().upper()
            save_config(self.config)
            
            if hasattr(self, "reload_locales"):
                self.reload_locales()
                
            if hasattr(self, "trigger_auto_save"):
                self.trigger_auto_save()
                
            if hasattr(self, "retranslate_ui"):
                QTimer.singleShot(170, self.retranslate_ui)

    def retranslate_ui(self):
        try:
            mode_titles = {"NX": self.T("title_nx"), "CTR": self.T("title_ctr"), "CAFE": self.T("title_cafe")}
            self.setWindowTitle(mode_titles.get(self.current_console, self.T("title")))
        except Exception: pass
        
        try:
            if hasattr(self, "lbl_title"): self.refresh_title_color()
            if hasattr(self, "lbl_sub"): self.lbl_sub.setText(self.T("subtitle"))
        except Exception: pass
        
        try:
            if hasattr(self, "btn_tab_dl"): self.btn_tab_dl.setText(self.T("tab_dl"))
            if hasattr(self, "btn_tab_cfg"): self.btn_tab_cfg.setText(self.T("tab_cfg"))
            if hasattr(self, "btn_tab_credits"): self.btn_tab_credits.setText(self.T("tab_credits"))
            if hasattr(self, "btn_tab_restart"): self.btn_tab_restart.setText(" " + self.T("btn_restart_app"))
        except Exception: pass
        
        try:
            self.update_sys_info_label()
        except Exception: pass
        
        try:
            if hasattr(self, "lbl_grp_target"): self.lbl_grp_target.setText(self.T("grp_target"))
            if hasattr(self, "radio_latest"): self.radio_latest.setText(self.T("opt_latest"))
            if hasattr(self, "radio_list"): self.radio_list.setText(self.T("opt_list"))
            if hasattr(self, "radio_manual"): self.radio_manual.setText(self.T("opt_manual"))
            if hasattr(self, "lbl_list_hint"): self.lbl_list_hint.setText(self.T("lbl_list_hint"))
            if hasattr(self, "lbl_manual_hint"): self.lbl_manual_hint.setText(self.T("lbl_manual_hint"))
            if hasattr(self, "lbl_manual_hint_cafe"): self.lbl_manual_hint_cafe.setText(self.T("lbl_manual_hint_cafe"))
            if hasattr(self, "lbl_warn_cafe_downgrade"): self.lbl_warn_cafe_downgrade.setText(self.T("warn_cafe_downgrade"))
            if hasattr(self, "lbl_grp_live"): self.lbl_grp_live.setText(self.T("grp_live"))
            if hasattr(self, "btn_clear_console"): self.btn_clear_console.setText(self.T("btn_clear_console"))
        except Exception: pass

        try:
            if hasattr(self, "chk_build_nsp"):
                self.chk_build_nsp.setText(self.T("build_nsp_checkbox"))
                self.chk_build_nsp.setToolTip(self.T("tt_build_nsp"))

            if hasattr(self, "btn_action"):
                if getattr(self, "worker", None) and self.worker.isRunning(): 
                    self.btn_action.setText(self.T("btn_stop"))
                else: 
                    self.btn_action.setText(self.T("btn_start"))
        except Exception: pass
                
        try:
            if hasattr(self, "lbl_grp_crypto"): self.lbl_grp_crypto.setText(self.T("grp_crypto"))
            if hasattr(self, "grp_crypto") and hasattr(self.grp_crypto, "setTitle"): self.grp_crypto.setTitle(self.T("grp_crypto"))
            if hasattr(self, "lbl_grp_app"): self.lbl_grp_app.setText(self.T("grp_app"))
            if hasattr(self, "grp_app") and hasattr(self.grp_app, "setTitle"): self.grp_app.setTitle(self.T("grp_app"))
            if hasattr(self, "lbl_lang"): self.lbl_lang.setText(self.T("lbl_lang"))
            if hasattr(self, "lbl_color"): self.lbl_color.setText(self.T("lbl_color"))
            if hasattr(self, "lbl_theme"): self.lbl_theme.setText(self.T("lbl_theme"))
        except Exception: pass
        
        try:
            if hasattr(self, "combo_theme"):
                self.combo_theme.blockSignals(True)
                self.combo_theme.setItemText(0, self.T("theme_auto"))
                self.combo_theme.setItemText(1, self.T("theme_light"))
                self.combo_theme.setItemText(2, self.T("theme_dark"))
                self.combo_theme.setItemText(3, self.T("theme_oled"))
                cur_th = self.combo_theme.currentIndex()
                if 0 <= cur_th < self.combo_theme.count():
                    self.combo_theme.setCurrentIndex(cur_th)
                self.combo_theme.blockSignals(False)
        except Exception: pass
        
        try:
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
        except Exception: pass
            
        chk_labels_map = {
            "lbl_chk_rainbow": "chk_rainbow",
            "lbl_chk_adv_mode": "chk_adv_mode",
            "lbl_chk_resize": "chk_resize",
            "lbl_chk_adv_logs": "chk_adv_logs",
            "lbl_chk_exfat": "chk_exfat",
            "lbl_chk_hide_warn": "chk_hide_warn",
            "chk_rainbow": "chk_rainbow",
            "chk_resize": "chk_resize",
            "chk_adv_mode": "chk_adv_mode",
            "chk_adv_logs": "chk_adv_logs",
            "chk_auto_save": "chk_auto_save",
            "chk_hide_warn": "chk_hide_warn",
            "chk_exfat": "chk_exfat",
            "chk_use_aria2c": "chk_use_aria2c",
            "chk_unlimited_console": "chk_unlimited_console",
            "lbl_chk_unlimited_console": "chk_unlimited_console",
            "lbl_chk_aria2c": "chk_use_aria2c"
        }
        for attr, key in chk_labels_map.items():
            try:
                if hasattr(self, attr): 
                    getattr(self, attr).setText(self.T(key))
            except Exception: pass
        
        try:
            if hasattr(self, "rainbow_target_cbs"):
                rb_keys = { "title": "rb_title", "tabs": "rb_tabs", "buttons": "rb_btns", "progress": "rb_progress", "indicators": "rb_indicators", "text": "rb_text", "inputs": "rb_inputs", "console": "rb_console" }
                for k, cb in self.rainbow_target_cbs.items():
                    cb.setText(self.T(rb_keys.get(k, f"rb_{k}")))
            
            if hasattr(self, "lbl_save_hint"): self.lbl_save_hint.setText(self.T("lbl_save_hint"))
            if hasattr(self, "lbl_speed_text"): self.lbl_speed_text.setText(self.T("lbl_rb_speed"))
        except Exception: pass

        try:
            if hasattr(self, "labels_config"):
                keys_map = { "hactool": "lbl_hactool", "keys": "lbl_keys", "prodinfo": "lbl_prodinfo", "otp": "lbl_otp", "out": "lbl_out", "boot9": "lbl_boot9" }
                for key, label in self.labels_config.items():
                    label.setText(self.T(keys_map.get(key, key)))

            if hasattr(self, "input_boot9"):
                self.input_boot9.setPlaceholderText(self.T("ctr_hint_boot9"))

            if hasattr(self, "btn_auto_detect_aria"): self.btn_auto_detect_aria.setText(self.T("btn_auto_detect"))
            if hasattr(self, "lbl_aria2c"): self.lbl_aria2c.setText(self.T("lbl_aria2c"))
            if hasattr(self, "lbl_openssl"): self.lbl_openssl.setText(self.T("lbl_openssl"))
            if hasattr(self, "btn_suggest"): self.btn_suggest.setText(self.T("btn_suggest"))
            if hasattr(self, "btn_save"): self.btn_save.setText(self.T("btn_save"))
            
            for btn in getattr(self, "browse_buttons", []):
                btn.setText(self.T("btn_browse"))
                btn.setMinimumWidth(85)
                
            if hasattr(self, "btn_reset_center"): self.btn_reset_center.setText(self.T("btn_reset"))
            if hasattr(self, "btn_reset_right"): self.btn_reset_right.setText(self.T("btn_reset"))
            if hasattr(self, "lbl_credits_title"): self.lbl_credits_title.setText(self.T("credits_header"))
            if hasattr(self, "lbl_credits_text"): self.lbl_credits_text.setText(self.T("credits_text"))
        except Exception: pass
        
        try:
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
        except Exception: pass

        try:
            if hasattr(self, "console_selector"):
                self.console_selector.setItemText(0, self.T("console_nx"))
                self.console_selector.setItemText(1, self.T("console_ctr"))
                self.console_selector.setItemText(2, self.T("console_cafe"))

            if hasattr(self, "btn_update"):
                self.btn_update.setText(self.T("btn_update"))
        except Exception: pass

        try:
            self.refresh_all_icons()
            self.update_dl_mode_label()
            if hasattr(self, "update_manual_input_context"):
                self.update_manual_input_context()
        except Exception: pass

        self.update()