import sys
import traceback
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QPushButton
from PyQt6.QtCore import QObject, QEvent

def exception_hook(exctype, value, tb):
    print("\n" + "="*50)
    print("FATAL CRASH DETECTED")
    print("="*50)
    traceback.print_exception(exctype, value, tb)
    print("="*50)
    print("No language detected. / Aucune langue n'était détectée.")
    input("\nPress Enter to close this window...")
    sys.exit(1)

class ComboScrollFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            return True
        return False

class OtpInputDialog(QDialog):
    def __init__(self, parent, title, message, chk_text, btn_ok_text, btn_cancel_text, saved_key=""):
        super().__init__(parent)
        print("[UTILS] Initializing OTP Input Dialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        self.lbl_msg = QLabel(message)
        self.lbl_msg.setWordWrap(True)
        layout.addWidget(self.lbl_msg)
        
        self.input_key = QLineEdit(self)
        if saved_key:
            self.input_key.setText(saved_key)
        layout.addWidget(self.input_key)
        
        self.chk_remember = QCheckBox(chk_text)
        if saved_key:
            self.chk_remember.setChecked(True)
        layout.addWidget(self.chk_remember)
        
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(btn_ok_text)
        self.btn_cancel = QPushButton(btn_cancel_text)
        
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)

    def get_data(self):
        print(f"[UTILS] OTP Dialog closed. Remember key: {self.chk_remember.isChecked()}")
        return self.input_key.text().strip(), self.chk_remember.isChecked()