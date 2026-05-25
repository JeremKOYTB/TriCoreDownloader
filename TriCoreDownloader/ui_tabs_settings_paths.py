import os
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QGridLayout, 
                             QPushButton, QFrame, QCheckBox, QSizePolicy, QMessageBox, QStackedWidget)
from PyQt6.QtCore import Qt
from .custom_widgets import ClickableLineEdit

class UiTabsSettingsPathsMixin:
    def setup_paths_section(self, layout):
        print("[UI] Building Paths and Crypto Settings section...")
        self.grp_crypto, crypto_layout, self.lbl_grp_crypto = self.create_card(self.T("grp_crypto"))
        
        self.paths_stack = QStackedWidget()
        self.paths_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        
        print("[UI] Assembling NX crypto fields...")
        self.page_nx = QWidget()
        grid_nx = QGridLayout(self.page_nx)
        grid_nx.setVerticalSpacing(16)
        grid_nx.setHorizontalSpacing(16)
        grid_nx.setColumnStretch(1, 1)
        grid_nx.setContentsMargins(0, 0, 0, 0)
        
        self.input_hactool = ClickableLineEdit(self.config.get("hactool", ""))
        self.input_keys = ClickableLineEdit(self.config.get("prod_keys", ""))
        self.input_prodinfo = ClickableLineEdit(self.config.get("prodinfo", ""))
        self.input_cert = ClickableLineEdit(self.config.get("cert_pem", ""))
        self.input_aria2c = ClickableLineEdit(self.config.get("aria2c_path", ""))
        self.input_openssl = ClickableLineEdit(self.config.get("openssl_path", ""))
        
        browse_hactool = lambda: self.browse_file(self.input_hactool, "hactool.exe" if os.name == "nt" else "hactool")
        browse_keys = lambda: self.browse_file(self.input_keys, "prod.keys")
        browse_prodinfo = lambda: self.browse_file(self.input_prodinfo, "PRODINFO.bin")
        browse_cert = lambda: self.browse_file(self.input_cert, "certificat.pem")
        browse_aria = lambda: self.browse_file(self.input_aria2c, "aria2c.exe" if os.name == "nt" else "aria2c")
        browse_ssl = lambda: self.browse_file(self.input_openssl, "openssl.exe" if os.name == "nt" else "openssl")
        
        self.input_hactool.clicked.connect(browse_hactool)
        self.input_keys.clicked.connect(browse_keys)
        self.input_prodinfo.clicked.connect(browse_prodinfo)
        self.input_cert.clicked.connect(browse_cert)
        self.input_aria2c.clicked.connect(browse_aria)
        self.input_openssl.clicked.connect(browse_ssl)
        
        for i_field in [self.input_hactool, self.input_keys, self.input_prodinfo, self.input_cert, self.input_aria2c, self.input_openssl]:
            i_field.textChanged.connect(self.trigger_auto_save)
            
        self.labels_config["hactool"], _ = self.add_grid_row_extended(grid_nx, 0, self.T("lbl_hactool"), self.input_hactool, browse_hactool, getattr(self, "show_help_hactool", None))
        self.labels_config["keys"], _ = self.add_grid_row_extended(grid_nx, 1, self.T("lbl_keys"), self.input_keys, browse_keys, getattr(self, "show_help_keys", None))
        self.labels_config["prodinfo"], _ = self.add_grid_row_extended(grid_nx, 2, self.T("lbl_prodinfo"), self.input_prodinfo, browse_prodinfo, getattr(self, "show_help_prodinfo", None))
        self.labels_config["cert"], _ = self.add_grid_row_extended(grid_nx, 3, self.T("lbl_cert"), self.input_cert, browse_cert, getattr(self, "show_help_cert", None))
        
        self.sep_nx = QFrame()
        self.sep_nx.setFrameShape(QFrame.Shape.HLine)
        self.sep_nx.setObjectName("SeparatorLine")
        grid_nx.addWidget(self.sep_nx, 4, 0, 1, 3)
        
        self.chk_use_aria2c = QCheckBox()
        self.cont_aria2c, _ = self.create_wrapped_checkbox(self.chk_use_aria2c, self.T("chk_use_aria2c"))
        self.chk_use_aria2c.setChecked(self.config.get("use_aria2c", False))
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
        grid_nx.addLayout(aria_header_layout, 5, 0, 1, 2)
        grid_nx.addWidget(self.btn_auto_detect_aria, 5, 2)
        
        self.lbl_aria2c, self.widget_aria2c_btns = self.add_grid_row_extended(grid_nx, 6, self.T("lbl_aria2c"), self.input_aria2c, browse_aria, getattr(self, "show_help_aria", None))
        self.input_aria2c.setPlaceholderText(self.T("lbl_aria2c"))
        
        self.lbl_openssl, self.widget_openssl_btns = self.add_grid_row_extended(grid_nx, 7, self.T("lbl_openssl"), self.input_openssl, browse_ssl, getattr(self, "show_help_aria", None))
        self.input_openssl.setPlaceholderText(self.T("lbl_openssl"))
        
        self.sep_nx_bot = QFrame()
        self.sep_nx_bot.setFrameShape(QFrame.Shape.HLine)
        self.sep_nx_bot.setObjectName("SeparatorLine")
        grid_nx.addWidget(self.sep_nx_bot, 8, 0, 1, 3)
        self.paths_stack.addWidget(self.page_nx)
        
        print("[UI] Assembling CTR crypto fields...")
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
        
        help_boot9 = lambda: QMessageBox.information(
            self, 
            self.T("help_boot9_title"), 
            self.T("help_boot9_msg")
        )

        self.labels_config["boot9"], _ = self.add_grid_row_extended(
            grid_ctr, 0, self.T("lbl_boot9"), self.input_boot9, browse_boot9, help_boot9
        )
        
        sep_ctr_bot = QFrame()
        sep_ctr_bot.setFrameShape(QFrame.Shape.HLine)
        sep_ctr_bot.setObjectName("SeparatorLine")
        grid_ctr.addWidget(sep_ctr_bot, 1, 0, 1, 3)
        self.paths_stack.addWidget(self.page_ctr)
        
        print("[UI] Assembling CAFE crypto fields...")
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

        from PyQt6.QtWidgets import QLabel
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
        print("[UI] Displaying help dialog: hactool")
        QMessageBox.information(self, self.T("help_hactool_title"), self.T("help_hactool_msg"))
        
    def show_help_keys(self):
        print("[UI] Displaying help dialog: keys")
        QMessageBox.information(self, self.T("help_keys_title"), self.T("help_keys_msg"))
        
    def show_help_prodinfo(self):
        print("[UI] Displaying help dialog: prodinfo")
        QMessageBox.information(self, self.T("help_prodinfo_title"), self.T("help_prodinfo_msg"))
        
    def show_help_cert(self):
        print("[UI] Displaying help dialog: cert")
        QMessageBox.information(self, self.T("help_cert_title"), self.T("help_cert_msg"))
        
    def show_help_otp(self):
        print("[UI] Displaying help dialog: otp")
        QMessageBox.information(self, self.T("help_otp_title"), self.T("help_otp_msg"))
        
    def show_help_aria(self):
        print("[UI] Displaying help dialog: aria2c/openssl dependencies")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("help_aria_title"))
        msg_box.setText(self.T("help_aria_msg"))
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        msg_box.exec()