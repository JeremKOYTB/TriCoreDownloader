from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

BASE_FONT = "\"Segoe UI Variable\", \"Segoe UI\", \"Roboto\", sans-serif"

STYLESHEET_LIGHT = f"""
QMainWindow, QDialog {{ background-color: #F8F9FA; }}
QWidget {{ color: #212529; font-family: {BASE_FONT}; font-size: 10pt; }}
QLabel {{ color: #212529; }}
QFrame#NavLine {{ border: none; border-top: 1px solid #DEE2E6; margin: 0px; padding: 0px; }}
QPushButton#NavTab {{ background-color: transparent; color: #6C757D; padding: 8px 24px; font-weight: 600; font-size: 10pt; border: none; border-bottom: 3px solid transparent; border-radius: 0px; outline: none; }}
QPushButton#NavTab:checked {{ color: #7E57C2; border-bottom: 3px solid #7E57C2; }}
QPushButton#NavTab:hover:!checked {{ color: #495057; }}
QPushButton#BtnCredits {{ background-color: transparent; color: #6C757D; padding: 4px 8px; font-weight: 600; font-size: 9pt; border: none; outline: none; }}
QPushButton#BtnCredits:checked {{ color: #7E57C2; }}
QPushButton#BtnCredits:hover:!checked {{ color: #495057; }}
QFrame#Card {{ background-color: #FFFFFF; border-radius: 8px; border: 1px solid #DEE2E6; }}
QLabel#CardTitle {{ color: #212529; font-size: 12pt; font-weight: 700; padding-bottom: 4px; }}
QLabel#DialogText {{ font-size: 10pt; color: #212529; line-height: 1.5; }}
QLabel#HintText {{ font-size: 9pt; color: #6C757D; }}
QFrame#SeparatorLine {{ border: none; border-top: 1px solid #CED4DA; margin: 4px 0px; }}
QRadioButton, QCheckBox {{ font-size: 10pt; color: #212529; padding: 2px; }}
QRadioButton:checked {{ color: #7E57C2; font-weight: 600; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 2px solid #ADB5BD; background-color: transparent; }}
QRadioButton::indicator:unchecked:hover {{ border: 2px solid #7E57C2; }}
QRadioButton::indicator:checked {{ border: 2px solid #ADB5BD; background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #7E57C2, stop:0.55 #7E57C2, stop:0.65 transparent); }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 2px solid #ADB5BD; background-color: transparent; }}
QCheckBox::indicator:checked {{ background-color: #7E57C2; border: 2px solid #7E57C2; image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23FFFFFF' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E"); }}
QLineEdit, QComboBox {{ background-color: #F8F9FA; border: 1px solid #CED4DA; border-radius: 6px; padding: 8px 12px; color: #212529; font-size: 10pt; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid #7E57C2; background-color: #FFFFFF; }}
QLineEdit:read-only {{ background-color: #E9ECEF; color: #495057; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QListView {{ background-color: #FFFFFF; color: #212529; selection-background-color: #E9ECEF; selection-color: #212529; border: 1px solid #CED4DA; outline: none; }}
QComboBox QListView::item {{ padding: 6px; }}
QPushButton {{ background-color: #E9ECEF; color: #212529; border-radius: 6px; padding: 8px 16px; font-weight: 600; border: 1px solid #CED4DA; min-height: 20px; }}
QPushButton:hover {{ background-color: #DEE2E6; }}
QPushButton:pressed {{ background-color: #7E57C2; color: #FFFFFF; border: 1px solid #7E57C2; }}
#btnDownload {{ background-color: #7E57C2; color: #FFFFFF; font-size: 11pt; padding: 12px 24px; border-radius: 8px; border: none; }}
#btnDownload:hover {{ background-color: #512DA8; }}
#btnDownload:disabled {{ background-color: #E9ECEF; color: #ADB5BD; border: none; }}
#btnStop {{ background-color: #DC3545; color: #FFFFFF; font-size: 11pt; padding: 12px 24px; border-radius: 8px; border: none; }}
#btnStop:hover {{ background-color: #C82333; }}
#btnReset {{ background-color: transparent; color: #DC3545; border: 1px solid #DC3545; border-radius: 6px; padding: 8px 16px; font-size: 10pt; outline: none; }}
#btnReset:hover {{ background-color: #F8D7DA; }}
#btnReset:disabled {{ color: #ADB5BD; border-color: #ADB5BD; background-color: transparent; }}
#btnActionDialog {{ background-color: #7E57C2; color: #FFFFFF; border-radius: 6px; font-weight: 600; font-size: 10pt; padding: 8px 16px; border: none; }}
QTextEdit, QTextEdit:focus, QTextEdit:read-only, QTextEdit:disabled {{ background-color: #FFFFFF; border: 1px solid #CED4DA; color: #495057; font-family: Consolas, monospace; font-size: 9pt; border-radius: 6px; padding: 8px; }}
QScrollBar:vertical {{ background-color: transparent; width: 10px; margin: 0px; }}
QScrollBar::handle:vertical {{ background-color: #CED4DA; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background-color: #ADB5BD; }}
QHorizontalLayout, QVerticalLayout {{ background-color: transparent; }}
QScrollArea {{ border: none; background-color: transparent; }}
QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
QProgressBar {{ background-color: #E9ECEF; border: none; border-radius: 4px; text-align: center; max-height: 8px; }}
QProgressBar::chunk {{ background-color: #7E57C2; border-radius: 4px; }}
QToolTip {{ color: #ffffff; background-color: #2a2a2a; border: 1px solid #555555; border-radius: 4px; padding: 4px; }}
QFrame#WelcomeInfoBox {{ background-color: #E9ECEF; border: 1px solid #CED4DA; border-radius: 12px; }}
QLabel#WelcomeInfoTitle {{ font-size: 18px; font-weight: bold; color: #212529; border: none; background-color: transparent; }}
QLabel#WelcomeInfoDesc {{ font-size: 14px; color: #212529; border: none; background-color: transparent; }}
QLabel#WelcomeInfoRisk {{ font-size: 13px; color: #D32F2F; font-weight: bold; border: none; background-color: transparent; }}
QPushButton#BtnWelcomeHelp {{ border-radius: 12px; background-color: #E9ECEF; color: #212529; padding: 0px; font-weight: bold; border: 1px solid #CED4DA; }}
QPushButton#BtnWelcomeHelp:hover {{ background-color: #DEE2E6; }}
QPushButton#BtnWelcomeNX, QPushButton#BtnWelcomeCTR, QPushButton#BtnWelcomeCAFE {{ font-size: 20px; font-weight: bold; border-radius: 12px; background-color: #FFFFFF; color: #212529; border: 1px solid #CED4DA; }}
QPushButton#BtnWelcomeNX:hover {{ background-color: #F8F9FA; border-top: 2px solid #00c3e3; border-left: 2px solid #00c3e3; border-bottom: 2px solid #ff4554; border-right: 2px solid #ff4554; color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00c3e3, stop:0.60 #00c3e3, stop:0.60 #ff4554, stop:1 #ff4554); }}
QPushButton#BtnWelcomeCTR:hover {{ background-color: #F8F9FA; border-top: 2px solid #CE181E; border-left: 2px solid #CE181E; border-bottom: 2px solid #CE181E; border-right: 2px solid #CE181E; color: #CE181E; }}
QPushButton#BtnWelcomeCAFE:hover {{ background-color: #F8F9FA; border-top: 2px solid #009AC7; border-left: 2px solid #009AC7; border-bottom: 2px solid #009AC7; border-right: 2px solid #009AC7; color: #009AC7; }}
QSlider::groove:horizontal {{ border: 1px solid #CED4DA; height: 6px; background: #E9ECEF; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #7E57C2; border: none; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #512DA8; }}
QSlider::sub-page:horizontal {{ background: #7E57C2; border-radius: 3px; }}
QSlider::add-page:horizontal {{ background: #E9ECEF; border-radius: 3px; }}
"""

STYLESHEET_DARK = f"""
QMainWindow, QDialog {{ background-color: #3C3C44; }}
QWidget {{ color: #E8E8E8; font-family: {BASE_FONT}; font-size: 10pt; }}
QLabel {{ color: #E8E8E8; }}
QFrame#NavLine {{ border: none; border-top: 1px solid #555560; margin: 0px; padding: 0px; }}
QPushButton#NavTab {{ background-color: transparent; color: #B0B0B8; padding: 8px 24px; font-weight: 600; font-size: 10pt; border: none; border-bottom: 3px solid transparent; border-radius: 0px; outline: none; }}
QPushButton#NavTab:checked {{ color: #C4A1FF; border-bottom: 3px solid #C4A1FF; }}
QPushButton#NavTab:hover:!checked {{ color: #FFFFFF; }}
QPushButton#BtnCredits {{ background-color: transparent; color: #B0B0B8; padding: 4px 8px; font-weight: 600; font-size: 9pt; border: none; outline: none; }}
QPushButton#BtnCredits:checked {{ color: #C4A1FF; }}
QPushButton#BtnCredits:hover:!checked {{ color: #FFFFFF; }}
QFrame#Card {{ background-color: #4A4A54; border-radius: 8px; border: 1px solid #555560; }}
QLabel#CardTitle {{ color: #FFFFFF; font-size: 12pt; font-weight: 700; padding-bottom: 4px; }}
QLabel#DialogText {{ font-size: 10pt; color: #E8E8E8; line-height: 1.5; }}
QLabel#HintText {{ font-size: 9pt; color: #C0C0C8; }}
QFrame#SeparatorLine {{ border: none; border-top: 1px solid #555560; margin: 4px 0px; }}
QRadioButton, QCheckBox {{ font-size: 10pt; color: #E8E8E8; padding: 2px; }}
QRadioButton:checked {{ color: #C4A1FF; font-weight: 600; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 2px solid #8A8A95; background-color: transparent; }}
QRadioButton::indicator:unchecked:hover {{ border: 2px solid #C4A1FF; }}
QRadioButton::indicator:checked {{ border: 2px solid #8A8A95; background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #C4A1FF, stop:0.55 #C4A1FF, stop:0.65 transparent); }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 2px solid #8A8A95; background-color: transparent; }}
QCheckBox::indicator:checked {{ background-color: #C4A1FF; border: 2px solid #C4A1FF; image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233C3C44' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E"); }}
QLineEdit, QComboBox {{ background-color: #32323A; border: 1px solid #555560; border-radius: 6px; padding: 8px 12px; color: #E8E8E8; font-size: 10pt; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid #C4A1FF; background-color: #3C3C44; }}
QLineEdit:read-only {{ background-color: #42424C; color: #C0C0C8; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QListView {{ background-color: #4A4A54; color: #E8E8E8; selection-background-color: #5A5A66; selection-color: #FFFFFF; border: 1px solid #555560; outline: none; }}
QComboBox QListView::item {{ padding: 6px; }}
QPushButton {{ background-color: #555560; color: #E8E8E8; border-radius: 6px; padding: 8px 16px; font-weight: 600; border: 1px solid #626270; min-height: 20px; }}
QPushButton:hover {{ background-color: #626270; }}
QPushButton:pressed {{ background-color: #C4A1FF; color: #3C3C44; border: 1px solid #C4A1FF; }}
#btnDownload {{ background-color: #C4A1FF; color: #2B2B30; font-size: 11pt; padding: 12px 24px; border-radius: 8px; border: none; }}
#btnDownload:hover {{ background-color: #8C54FF; }}
#btnDownload:disabled {{ background-color: #555560; color: #8A8A95; border: none; }}
#btnStop {{ background-color: #EF5350; color: #FFFFFF; font-size: 11pt; padding: 12px 24px; border-radius: 8px; border: none; }}
#btnStop:hover {{ background-color: #E53935; }}
#btnReset {{ background-color: transparent; color: #EF5350; border: 1px solid #EF5350; border-radius: 6px; padding: 8px 16px; font-size: 10pt; outline: none; }}
#btnReset:hover {{ background-color: #4A1C1C; }}
#btnReset:disabled {{ color: #8A8A95; border-color: #8A8A95; background-color: transparent; }}
#btnActionDialog {{ background-color: #C4A1FF; color: #2B2B30; border-radius: 6px; font-weight: 600; font-size: 10pt; padding: 8px 16px; border: none; }}
QTextEdit, QTextEdit:focus, QTextEdit:read-only, QTextEdit:disabled {{ background-color: #32323A; border: 1px solid #555560; color: #D0D0D5; font-family: Consolas, monospace; font-size: 9pt; border-radius: 6px; padding: 8px; }}
QScrollBar:vertical {{ background-color: transparent; width: 10px; margin: 0px; }}
QScrollBar::handle:vertical {{ background-color: #5A5A66; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background-color: #70707D; }}
QScrollArea {{ border: none; background-color: transparent; }}
QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
QProgressBar {{ background-color: #32323A; border: none; border-radius: 4px; text-align: center; max-height: 8px; }}
QProgressBar::chunk {{ background-color: #C4A1FF; border-radius: 4px; }}
QToolTip {{ color: #ffffff; background-color: #2a2a2a; border: 1px solid #555555; border-radius: 4px; padding: 4px; }}
QFrame#WelcomeInfoBox {{ background-color: #4A4A54; border: 1px solid #555560; border-radius: 12px; }}
QLabel#WelcomeInfoTitle {{ font-size: 18px; font-weight: bold; color: #FFFFFF; border: none; background-color: transparent; }}
QLabel#WelcomeInfoDesc {{ font-size: 14px; color: #E8E8E8; border: none; background-color: transparent; }}
QLabel#WelcomeInfoRisk {{ font-size: 13px; color: #FF6B6B; font-weight: bold; border: none; background-color: transparent; }}
QPushButton#BtnWelcomeHelp {{ border-radius: 12px; background-color: #555560; color: #E8E8E8; padding: 0px; font-weight: bold; border: 1px solid #626270; }}
QPushButton#BtnWelcomeHelp:hover {{ background-color: #626270; }}
QPushButton#BtnWelcomeNX, QPushButton#BtnWelcomeCTR, QPushButton#BtnWelcomeCAFE {{ font-size: 20px; font-weight: bold; border-radius: 12px; background-color: #32323A; color: #FFFFFF; border: 1px solid #555560; }}
QPushButton#BtnWelcomeNX:hover {{ background-color: #3C3C44; border-top: 2px solid #00c3e3; border-left: 2px solid #00c3e3; border-bottom: 2px solid #ff4554; border-right: 2px solid #ff4554; color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00c3e3, stop:0.60 #00c3e3, stop:0.60 #ff4554, stop:1 #ff4554); }}
QPushButton#BtnWelcomeCTR:hover {{ background-color: #3C3C44; border-top: 2px solid #CE181E; border-left: 2px solid #CE181E; border-bottom: 2px solid #CE181E; border-right: 2px solid #CE181E; color: #CE181E; }}
QPushButton#BtnWelcomeCAFE:hover {{ background-color: #3C3C44; border-top: 2px solid #009AC7; border-left: 2px solid #009AC7; border-bottom: 2px solid #009AC7; border-right: 2px solid #009AC7; color: #009AC7; }}
QSlider::groove:horizontal {{ border: 1px solid #555560; height: 6px; background: #32323A; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #C4A1FF; border: none; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #8C54FF; }}
QSlider::sub-page:horizontal {{ background: #C4A1FF; border-radius: 3px; }}
QSlider::add-page:horizontal {{ background: #32323A; border-radius: 3px; }}
"""

STYLESHEET_OLED = f"""
QMainWindow, QDialog {{ background-color: #000000; }}
QWidget {{ color: #E0E0E0; font-family: {BASE_FONT}; font-size: 10pt; }}
QLabel {{ color: #E0E0E0; }}
QFrame#NavLine {{ border: none; border-top: 1px solid #212121; margin: 0px; padding: 0px; }}
QPushButton#NavTab {{ background-color: transparent; color: #757575; padding: 8px 24px; font-weight: 600; font-size: 10pt; border: none; border-bottom: 3px solid transparent; border-radius: 0px; outline: none; }}
QPushButton#NavTab:checked {{ color: #C4A1FF; border-bottom: 3px solid #C4A1FF; }}
QPushButton#NavTab:hover:!checked {{ color: #E0E0E0; }}
QPushButton#BtnCredits {{ background-color: transparent; color: #757575; padding: 4px 8px; font-weight: 600; font-size: 9pt; border: none; outline: none; }}
QPushButton#BtnCredits:checked {{ color: #C4A1FF; }}
QPushButton#BtnCredits:hover:!checked {{ color: #E0E0E0; }}
QFrame#Card {{ background-color: #0A0A0A; border-radius: 8px; border: 1px solid #212121; }}
QLabel#CardTitle {{ color: #FFFFFF; font-size: 12pt; font-weight: 700; padding-bottom: 4px; }}
QLabel#DialogText {{ font-size: 10pt; color: #E0E0E0; line-height: 1.5; }}
QLabel#HintText {{ font-size: 9pt; color: #757575; }}
QFrame#SeparatorLine {{ border: none; border-top: 1px solid #333333; margin: 4px 0px; }}
QRadioButton, QCheckBox {{ font-size: 10pt; color: #E0E0E0; padding: 2px; }}
QRadioButton:checked {{ color: #C4A1FF; font-weight: 600; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 2px solid #616161; background-color: transparent; }}
QRadioButton::indicator:unchecked:hover {{ border: 2px solid #C4A1FF; }}
QRadioButton::indicator:checked {{ border: 2px solid #616161; background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #C4A1FF, stop:0.55 #C4A1FF, stop:0.65 transparent); }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 2px solid #616161; background-color: transparent; }}
QCheckBox::indicator:checked {{ background-color: #C4A1FF; border: 2px solid #616161; image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000000' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E"); }}
QLineEdit, QComboBox {{ background-color: #000000; border: 1px solid #333333; border-radius: 6px; padding: 8px 12px; color: #E0E0E0; font-size: 10pt; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid #C4A1FF; background-color: #111111; }}
QComboBox:hover {{ background-color: #111111; border: 1px solid #555555; }}
QLineEdit:read-only {{ background-color: #111111; color: #757575; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QListView {{ background-color: #000000; color: #E0E0E0; selection-background-color: #111111; selection-color: #FFFFFF; border: 1px solid #333333; outline: none; }}
QComboBox QListView::item {{ padding: 6px; }}
QPushButton {{ background-color: #111111; color: #E0E0E0; border-radius: 6px; padding: 8px 16px; font-weight: 600; border: 1px solid #333333; min-height: 20px; }}
QPushButton:hover {{ background-color: #212121; }}
QPushButton:pressed {{ background-color: #C4A1FF; color: #000000; border: 1px solid #C4A1FF; }}
#btnDownload {{ background-color: #C4A1FF; color: #000000; font-size: 11pt; padding: 12px 24px; border-radius: 8px; border: none; }}
#btnDownload:hover {{ background-color: #8C54FF; }}
#btnDownload:disabled {{ background-color: #111111; color: #424242; border: none; }}
#btnStop {{ background-color: #EF5350; color: #000000; font-size: 11pt; padding: 12px 24px; border-radius: 8px; border: none; }}
#btnStop:hover {{ background-color: #E53935; }}
#btnReset {{ background-color: transparent; color: #EF5350; border: 1px solid #EF5350; border-radius: 6px; padding: 8px 16px; font-size: 10pt; outline: none; }}
#btnReset:hover {{ background-color: #1F0D0D; }}
#btnReset:disabled {{ color: #424242; border-color: #424242; background-color: transparent; }}
#btnActionDialog {{ background-color: #C4A1FF; color: #000000; border-radius: 6px; font-weight: 600; font-size: 10pt; padding: 8px 16px; border: none; }}
QTextEdit, QTextEdit:focus, QTextEdit:read-only, QTextEdit:disabled {{ background-color: #000000; border: 1px solid #212121; color: #9E9E9E; font-family: Consolas, monospace; font-size: 9pt; border-radius: 6px; padding: 8px; }}
QScrollBar:vertical {{ background-color: transparent; width: 10px; margin: 0px; }}
QScrollBar::handle:vertical {{ background-color: #333333; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background-color: #424242; }}
QScrollArea {{ border: none; background-color: transparent; }}
QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
QProgressBar {{ background-color: #111111; border: none; border-radius: 4px; text-align: center; max-height: 8px; }}
QProgressBar::chunk {{ background-color: #C4A1FF; border-radius: 4px; }}
QToolTip {{ color: #ffffff; background-color: #2a2a2a; border: 1px solid #555555; border-radius: 4px; padding: 4px; }}
QFrame#WelcomeInfoBox {{ background-color: #0A0A0A; border: 1px solid #212121; border-radius: 12px; }}
QLabel#WelcomeInfoTitle {{ font-size: 18px; font-weight: bold; color: #FFFFFF; border: none; background-color: transparent; }}
QLabel#WelcomeInfoDesc {{ font-size: 14px; color: #E0E0E0; border: none; background-color: transparent; }}
QLabel#WelcomeInfoRisk {{ font-size: 13px; color: #FF6B6B; font-weight: bold; border: none; background-color: transparent; }}
QPushButton#BtnWelcomeHelp {{ border-radius: 12px; background-color: #111111; color: #E0E0E0; padding: 0px; font-weight: bold; border: 1px solid #333333; }}
QPushButton#BtnWelcomeHelp:hover {{ background-color: #212121; }}
QPushButton#BtnWelcomeNX, QPushButton#BtnWelcomeCTR, QPushButton#BtnWelcomeCAFE {{ font-size: 20px; font-weight: bold; border-radius: 12px; background-color: #000000; color: #FFFFFF; border: 1px solid #333333; }}
QPushButton#BtnWelcomeNX:hover {{ background-color: #111111; border-top: 2px solid #00c3e3; border-left: 2px solid #00c3e3; border-bottom: 2px solid #ff4554; border-right: 2px solid #ff4554; color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00c3e3, stop:0.60 #00c3e3, stop:0.60 #ff4554, stop:1 #ff4554); }}
QPushButton#BtnWelcomeCTR:hover {{ background-color: #111111; border-top: 2px solid #CE181E; border-left: 2px solid #CE181E; border-bottom: 2px solid #CE181E; border-right: 2px solid #CE181E; color: #CE181E; }}
QPushButton#BtnWelcomeCAFE:hover {{ background-color: #111111; border-top: 2px solid #009AC7; border-left: 2px solid #009AC7; border-bottom: 2px solid #009AC7; border-right: 2px solid #009AC7; color: #009AC7; }}
QSlider::groove:horizontal {{ border: 1px solid #333333; height: 6px; background: #111111; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #C4A1FF; border: none; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #8C54FF; }}
QSlider::sub-page:horizontal {{ background: #C4A1FF; border-radius: 3px; }}
QSlider::add-page:horizontal {{ background: #111111; border-radius: 3px; }}
"""

def update_app_theme(app, theme_pref, custom_accent="", console_mode="NX"):
    console_defaults = {
        "NX":    ("#7E57C2", "#C4A1FF"), 
        "CTR":  ("#E60012", "#E60012"), 
        "CAFE": ("#009AC7", "#009AC7")  
    }

    if custom_accent and QColor(custom_accent).isValid():
        light_accent = custom_accent
        dark_accent = custom_accent
    else:
        light_accent, dark_accent = console_defaults.get(console_mode, console_defaults["NX"])
    
    c_light = QColor(light_accent)
    light_hover = c_light.darker(120).name() if c_light.isValid() else light_accent
    
    c_dark = QColor(dark_accent)
    dark_hover = c_dark.darker(120).name() if c_dark.isValid() else dark_accent

    light_style = STYLESHEET_LIGHT.replace("#7E57C2", light_accent).replace("#512DA8", light_hover)
    dark_style = STYLESHEET_DARK.replace("#C4A1FF", dark_accent).replace("#8C54FF", dark_hover)
    oled_style = STYLESHEET_OLED.replace("#C4A1FF", dark_accent).replace("#8C54FF", dark_hover)

    print(f"LOG_THEME_APPLIED_MODE_{console_mode}_ACCENT_{light_accent}")

    if theme_pref == "light":
        app.setStyleSheet(light_style)
    elif theme_pref == "dark":
        app.setStyleSheet(dark_style)
    elif theme_pref == "oled":
        app.setStyleSheet(oled_style)
    else:
        is_dark = True
        try:
            scheme = app.styleHints().colorScheme()
            is_dark = (scheme == Qt.ColorScheme.Dark)
        except AttributeError:
            palette = app.palette()
            is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
            
        app.setStyleSheet(dark_style if is_dark else light_style)