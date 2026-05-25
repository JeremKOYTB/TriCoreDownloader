import os
import json
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit
from PyQt6.QtCore import QTimer, pyqtSignal, Qt
from .config import APPDATA_DIR, EULA_FILE, save_config

class AutoCloseDialog(QDialog):
    def __init__(self, title, message, timeout_sec, btn_template_text, parent=None):
        super().__init__(parent)
        print(f"[WIDGETS] Initializing AutoCloseDialog for {timeout_sec}s.")
        self.timeout = timeout_sec
        self.btn_template = btn_template_text
        
        self.setWindowTitle(title)
        self.setMinimumSize(400, 200)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        lbl = QLabel(message)
        lbl.setObjectName("DialogText")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        
        layout.addStretch()
        
        self.btn = QPushButton(self.btn_template.format(self.timeout))
        self.btn.setObjectName("btnActionDialog")
        self.btn.clicked.connect(self.accept)
        self.btn.setMinimumWidth(120)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        self.timeout -= 1
        self.btn.setText(self.btn_template.format(self.timeout))
        if self.timeout <= 0:
            print("[WIDGETS] AutoCloseDialog timed out. Accepting automatically.")
            self.timer.stop()
            self.accept()

class EulaDialog(QDialog):
    def __init__(self, parent, is_first_time, translation_func):
        super().__init__(parent)
        print(f"[WIDGETS] Initializing EULA Dialog. First time: {is_first_time}")
        self.parent_app = parent
        self.T = translation_func
        self.is_first_time = is_first_time
        self.dont_show_again = False
        
        self.setWindowTitle(self.T("eula_title"))
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

        lang_layout = QHBoxLayout()
        lang_layout.addStretch()
        self.combo_lang = QComboBox()
        self.combo_lang.addItems([self.T("lang_en"), self.T("lang_fr")])
        
        current_lang = self.parent_app.config.get("lang", "en")
        self.combo_lang.setCurrentIndex(1 if current_lang == "fr" else 0)
        self.combo_lang.currentIndexChanged.connect(self.change_language)
        
        lang_layout.addWidget(self.combo_lang)
        layout.addLayout(lang_layout)

        msg = self.T("eula_first") if is_first_time else self.T("eula_return")
        
        self.lbl_msg = QLabel(msg)
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setObjectName("DialogText")
        layout.addWidget(self.lbl_msg)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        if is_first_time:
            self.btn_no = QPushButton(self.T("btn_no_quit"))
            self.btn_no.setObjectName("btnStop")
            self.btn_no.clicked.connect(self.reject)
            
            self.btn_ok = QPushButton(self.T("btn_ok_cont"))
            self.btn_ok.setObjectName("btnDownload")
            self.btn_ok.clicked.connect(self.accept)
            
            btn_layout.addWidget(self.btn_ok)
            btn_layout.addSpacing(16)
            btn_layout.addWidget(self.btn_no)
        else:
            self.btn_ok = QPushButton(self.T("btn_ok_only"))
            self.btn_ok.setObjectName("btnDownload")
            self.btn_ok.clicked.connect(self.accept)
            
            self.btn_never = QPushButton(self.T("btn_never_again"))
            self.btn_never.clicked.connect(self.accept_never_again)
            
            btn_layout.addWidget(self.btn_ok)
            btn_layout.addSpacing(16)
            btn_layout.addWidget(self.btn_never)

        layout.addLayout(btn_layout)

    def accept_never_again(self):
        print("[WIDGETS] User chose to never see the EULA again.")
        self.dont_show_again = True
        self.accept()

    def change_language(self, index):
        new_lang = "fr" if index == 1 else "en"
        print(f"[WIDGETS] EULA language changed to: {new_lang}")
        
        self.parent_app.config["lang"] = new_lang
        save_config(self.parent_app.config)
        
        self.setWindowTitle(self.T("eula_title"))
        msg = self.T("eula_first") if self.is_first_time else self.T("eula_return")
        self.lbl_msg.setText(msg)
        
        if self.is_first_time:
            self.btn_ok.setText(self.T("btn_ok_cont"))
            self.btn_no.setText(self.T("btn_no_quit"))
        else:
            self.btn_ok.setText(self.T("btn_ok_only"))
            self.btn_never.setText(self.T("btn_never_again"))
            
        if hasattr(self.parent_app, "retranslate_ui"):
            self.parent_app.retranslate_ui()
            
        if hasattr(self.parent_app, "combo_lang"):
            self.parent_app.combo_lang.blockSignals(True)
            self.parent_app.combo_lang.setCurrentIndex(index)
            self.parent_app.combo_lang.blockSignals(False)

class ClickableLineEdit(QLineEdit):
    clicked = pyqtSignal()
    
    def __init__(self, text=""):
        super().__init__(text)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36) 

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)