import os
import sys
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QFrame, QCheckBox, QSizePolicy, QMessageBox, QStackedWidget)
from PyQt6.QtCore import Qt
from .custom_widgets import ClickableLineEdit

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"
HACTOOL_FILENAME = "hactool.exe" if IS_WINDOWS else "hactool"
ARIA2C_FILENAME = "aria2c.exe" if IS_WINDOWS else "aria2c"
OPENSSL_FILENAME = "openssl.exe" if IS_WINDOWS else "openssl"

class UiTabsSettingsPathsMixin:
    def setup_paths_section(self, layout):
        if not hasattr(self, "labels_config"):
            self.labels_config = {}
        if not hasattr(self, "browse_buttons"):
            self.browse_buttons = []
            
        self.grp_crypto, crypto_layout, self.lbl_grp_crypto = self.create_card(self.T("grp_crypto"))
        
        self.paths_stack = QStackedWidget()
        self.paths_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        
        self.page_nx = QWidget()
        grid_nx = QGridLayout(self.page_nx)
        grid_nx.setVerticalSpacing(16)
        grid_nx.setHorizontalSpacing(16)
        grid_nx.setColumnStretch(1, 1)
        grid_nx.setContentsMargins(0, 0, 0, 0)
        
        self.input_hactool = ClickableLineEdit(self.config.get("hactool", ""))
        self.input_keys = ClickableLineEdit(self.config.get("prod_keys", ""))
        self.input_prodinfo = ClickableLineEdit(self.config.get("prodinfo", ""))
        self.input_aria2c = ClickableLineEdit(self.config.get("aria2c_path", ""))
        self.input_openssl = ClickableLineEdit(self.config.get("openssl_path", ""))
        
        browse_hactool = lambda: self.browse_file(self.input_hactool, HACTOOL_FILENAME)
        browse_keys = lambda: self.browse_file(self.input_keys, "prod.keys")
        browse_prodinfo = lambda: self.browse_file(self.input_prodinfo, "PRODINFO.bin")
        browse_aria = lambda: self.browse_file(self.input_aria2c, ARIA2C_FILENAME)
        browse_ssl = lambda: self.browse_file(self.input_openssl, OPENSSL_FILENAME)
        
        self.input_hactool.clicked.connect(browse_hactool)
        self.input_keys.clicked.connect(browse_keys)
        self.input_prodinfo.clicked.connect(browse_prodinfo)
        self.input_aria2c.clicked.connect(browse_aria)
        self.input_openssl.clicked.connect(browse_ssl)
        
        for i_field in (self.input_hactool, self.input_keys, self.input_prodinfo, self.input_aria2c, self.input_openssl):
            i_field.textChanged.connect(self.trigger_auto_save)
            
        self.labels_config["hactool"], _ = self.add_grid_row_extended(grid_nx, 0, self.T("lbl_hactool"), self.input_hactool, browse_hactool, getattr(self, "show_help_hactool", None))
        self.labels_config["keys"], _ = self.add_grid_row_extended(grid_nx, 1, self.T("lbl_keys"), self.input_keys, browse_keys, getattr(self, "show_help_keys", None))
        self.labels_config["prodinfo"], _ = self.add_grid_row_extended(grid_nx, 2, self.T("lbl_prodinfo"), self.input_prodinfo, browse_prodinfo, getattr(self, "show_help_prodinfo", None))
        
        self.sep_nx = QFrame()
        self.sep_nx.setFrameShape(QFrame.Shape.HLine)
        self.sep_nx.setObjectName("SeparatorLine")
        grid_nx.addWidget(self.sep_nx, 3, 0, 1, 3)
        
        self.chk_use_aria2c = QCheckBox()
        self.cont_aria2c, _ = self.create_wrapped_checkbox(self.chk_use_aria2c, self.T("chk_use_aria2c"))
        self.chk_use_aria2c.setChecked(bool(self.config.get("use_aria2c", False)))
        if hasattr(self, "on_aria_toggle"):
            self.chk_use_aria2c.toggled.connect(self.on_aria_toggle)
        if hasattr(self, "show_aria_info_popup"):
            self.chk_use_aria2c.clicked.connect(self.show_aria_info_popup)
            
        self.btn_auto_detect_aria = QPushButton(self.T("btn_auto_detect"))
        self.btn_auto_detect_aria.setCursor(Qt.CursorShape.PointingHandCursor)
        if hasattr(self, "auto_detect_aria"):
            self.btn_auto_detect_aria.clicked.connect(self.auto_detect_aria)
            
        aria_header_layout = QHBoxLayout()
        aria_header_layout.addWidget(self.cont_aria2c)
        aria_header_layout.addStretch()
        grid_nx.addLayout(aria_header_layout, 4, 0, 1, 2)
        grid_nx.addWidget(self.btn_auto_detect_aria, 4, 2)
        
        self.lbl_aria2c, self.widget_aria2c_btns = self.add_grid_row_extended(grid_nx, 5, self.T("lbl_aria2c"), self.input_aria2c, browse_aria, getattr(self, "show_help_aria", None))
        self.input_aria2c.setPlaceholderText(self.T("lbl_aria2c"))
        
        self.lbl_openssl, self.widget_openssl_btns = self.add_grid_row_extended(grid_nx, 6, self.T("lbl_openssl"), self.input_openssl, browse_ssl, getattr(self, "show_help_aria", None))
        self.input_openssl.setPlaceholderText(self.T("lbl_openssl"))
        
        self.sep_nx_bot = QFrame()
        self.sep_nx_bot.setFrameShape(QFrame.Shape.HLine)
        self.sep_nx_bot.setObjectName("SeparatorLine")
        grid_nx.addWidget(self.sep_nx_bot, 7, 0, 1, 3)
        self.paths_stack.addWidget(self.page_nx)
        
        self.page_ctr = QWidget()
        grid_ctr = QGridLayout(self.page_ctr)
        grid_ctr.setVerticalSpacing(12)
        grid_ctr.setHorizontalSpacing(16)
        grid_ctr.setColumnStretch(1, 1)
        grid_ctr.setContentsMargins(0, 0, 0, 0)

        self.input_boot9 = ClickableLineEdit(self.config.get("boot9_path", ""))
        self.input_boot9.setPlaceholderText(self.T("ctr_hint_boot9"))
        browse_boot9 = lambda: self.browse_file(self.input_boot9, "boot9.bin")
        self.input_boot9.clicked.connect(browse_boot9)
        self.input_boot9.textChanged.connect(self.trigger_auto_save)
        
        help_boot9 = getattr(self, "show_help_boot9", lambda: QMessageBox.information(self, self.T("help_boot9_title"), self.T("help_boot9_msg")))

        self.labels_config["boot9"], _ = self.add_grid_row_extended(
            grid_ctr, 0, self.T("lbl_boot9"), self.input_boot9, browse_boot9, help_boot9
        )
        
        sep_ctr_bot = QFrame()
        sep_ctr_bot.setFrameShape(QFrame.Shape.HLine)
        sep_ctr_bot.setObjectName("SeparatorLine")
        grid_ctr.addWidget(sep_ctr_bot, 1, 0, 1, 3)
        self.paths_stack.addWidget(self.page_ctr)
        
        self.page_cafe = QWidget()
        grid_cafe = QGridLayout(self.page_cafe)
        grid_cafe.setVerticalSpacing(16)
        grid_cafe.setHorizontalSpacing(16)
        grid_cafe.setColumnStretch(1, 1)
        grid_cafe.setContentsMargins(0, 0, 0, 0)
        
        self.input_otp = ClickableLineEdit(self.config.get("otp_path", ""))
        browse_otp = lambda: self.browse_file(self.input_otp, "otp.bin")
        self.input_otp.clicked.connect(browse_otp)
        self.input_otp.textChanged.connect(self.trigger_auto_save)
        
        self.labels_config["otp"], _ = self.add_grid_row_extended(
            grid_cafe, 0, self.T("lbl_otp"), self.input_otp, browse_otp, getattr(self, "show_help_otp", None)
        )
        
        sep_cafe_bot = QFrame()
        sep_cafe_bot.setFrameShape(QFrame.Shape.HLine)
        sep_cafe_bot.setObjectName("SeparatorLine")
        grid_cafe.addWidget(sep_cafe_bot, 1, 0, 1, 3)
        self.paths_stack.addWidget(self.page_cafe)

        self.page_welcome = QWidget()
        grid_welcome = QGridLayout(self.page_welcome)
        grid_welcome.setContentsMargins(0, 0, 0, 0)
        grid_welcome.addWidget(QLabel(""), 0, 0)
        self.paths_stack.addWidget(self.page_welcome)
        
        crypto_layout.addWidget(self.paths_stack)
        
        out_layout = QGridLayout()
        out_layout.setVerticalSpacing(16)
        out_layout.setHorizontalSpacing(16)
        out_layout.setColumnStretch(1, 1)
        out_layout.setContentsMargins(0, 0, 0, 0)
        
        self.input_output = ClickableLineEdit(self.config.get("output_dir", ""))
        browse_out = lambda: self.browse_folder(self.input_output)
        self.input_output.clicked.connect(browse_out)
        self.input_output.textChanged.connect(self.trigger_auto_save)
        
        self.lbl_out = QLabel(self.T("lbl_out"))
        self.lbl_out.setMinimumWidth(150)
        
        btn_out_browse = QPushButton(self.T("btn_browse"))
        btn_out_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_out_browse.clicked.connect(browse_out)
        self.browse_buttons.append(btn_out_browse)
        
        self.btn_suggest = QPushButton(self.T("btn_suggest"))
        self.btn_suggest.setCursor(Qt.CursorShape.PointingHandCursor)
        if hasattr(self, "suggest_export_folder"):
            self.btn_suggest.clicked.connect(self.suggest_export_folder)
            
        out_btns_layout = QHBoxLayout()
        out_btns_layout.addWidget(btn_out_browse)
        out_btns_layout.addWidget(self.btn_suggest)
        out_btns_layout.setContentsMargins(0, 0, 0, 0)
        
        out_btns_widget = QWidget()
        out_btns_widget.setLayout(out_btns_layout)
        
        out_layout.addWidget(self.lbl_out, 0, 0)
        out_layout.addWidget(self.input_output, 0, 1)
        out_layout.addWidget(out_btns_widget, 0, 2)
        
        self.labels_config["out"] = self.lbl_out
        crypto_layout.addLayout(out_layout)
        layout.addWidget(self.grp_crypto)

    def show_help_hactool(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_hactool_title"))
        msg_box.setText(self.T("help_hactool_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        if hasattr(self, "get_app_icon"):
            msg_box.setWindowIcon(self.get_app_icon())
        msg_box.exec()
        
    def show_help_keys(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_keys_title"))
        msg_box.setText(self.T("help_keys_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        if hasattr(self, "get_app_icon"):
            msg_box.setWindowIcon(self.get_app_icon())
        msg_box.exec()
        
    def show_help_prodinfo(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_prodinfo_title"))
        msg_box.setText(self.T("help_prodinfo_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        if hasattr(self, "get_app_icon"):
            msg_box.setWindowIcon(self.get_app_icon())
        msg_box.exec()
        
    def show_help_otp(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_otp_title"))
        msg_box.setText(self.T("help_otp_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        if hasattr(self, "get_app_icon"):
            msg_box.setWindowIcon(self.get_app_icon())
        msg_box.exec()

    def show_help_boot9(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_boot9_title"))
        msg_box.setText(self.T("help_boot9_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        if hasattr(self, "get_app_icon"):
            msg_box.setWindowIcon(self.get_app_icon())
        msg_box.exec()
        
    def show_help_aria(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_aria_title"))
        msg_box.setText(self.T("help_aria_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        if hasattr(self, "get_app_icon"):
            msg_box.setWindowIcon(self.get_app_icon())
        msg_box.exec()