import sys
import traceback
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QPushButton
from PyQt6.QtCore import QObject, QEvent, Qt

def exception_hook(exctype, value, tb):
    print("\n" + "="*50)
    print("FATAL CRASH DETECTED")
    print("="*50)
    traceback.print_exception(exctype, value, tb)
    print("="*50)
    print("No language detected. / Aucune langue n'était détectée.")
    if sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except Exception:
            pass
    sys.exit(1)

class ComboScrollFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(obj, event)

class OtpInputDialog(QDialog):
    def __init__(self, parent, title, message, chk_text, btn_ok_text, btn_cancel_text, saved_key=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        self.lbl_msg = QLabel(message)
        self.lbl_msg.setWordWrap(True)
        layout.addWidget(self.lbl_msg)
        
        self.input_key = QLineEdit(self)
        if saved_key:
            self.input_key.setText(saved_key)
        layout.addWidget(self.input_key)
        
        self.chk_remember = QCheckBox(chk_text)
        self.chk_remember.setCursor(Qt.CursorShape.PointingHandCursor)
        if saved_key:
            self.chk_remember.setChecked(True)
        layout.addWidget(self.chk_remember)
        
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(btn_ok_text)
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel = QPushButton(btn_cancel_text)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)

    def get_data(self):
        return self.input_key.text().strip(), self.chk_remember.isChecked()