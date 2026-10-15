import os
import sys
import traceback
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QCheckBox, QPushButton, QMessageBox, QApplication
)
from PyQt6.QtCore import QObject, QEvent, Qt

try:
    from .config import APPDATA_DIR
except Exception:
    APPDATA_DIR = None


def exception_hook(exctype, value, tb):
    if issubclass(exctype, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exctype, value, tb)
        return

    tb_str = "".join(traceback.format_exception(exctype, value, tb))

    if APPDATA_DIR is not None:
        try:
            os.makedirs(str(APPDATA_DIR), exist_ok=True)
            with open(os.path.join(str(APPDATA_DIR), "crash.log"), "w", encoding="utf-8") as cf:
                cf.write(tb_str)
        except Exception:
            pass

    err_stream = sys.__stderr__ if sys.__stderr__ is not None else sys.stderr
    if err_stream is not None:
        try:
            print("\n" + "=" * 50, file=err_stream)
            print("FATAL CRASH DETECTED", file=err_stream)
            print("=" * 50, file=err_stream)
            print(tb_str, file=err_stream)
            print("=" * 50, file=err_stream)
        except Exception:
            pass

    try:
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Fatal Error")
            msg.setText(f"A fatal unhandled error occurred:\n{value}")
            msg.setDetailedText(tb_str)
            msg.exec()
    except Exception:
        pass

    if not getattr(sys, "frozen", False) and sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except Exception:
            pass
    os._exit(1)


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
        raw = self.input_key.text().strip().strip("\"'").replace(" ", "")
        return raw, self.chk_remember.isChecked()
