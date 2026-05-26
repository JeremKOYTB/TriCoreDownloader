import os
import sys
import json
import re
import zipfile
import io
import urllib.request
import urllib.error
import subprocess
import importlib.util
import signal
import colorsys
import shutil
import time

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QFrame, 
                             QMessageBox, QComboBox, QCheckBox, QLayout, QSizePolicy,
                             QGraphicsOpacityEffect, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QByteArray, QPropertyAnimation, QAbstractAnimation, QDir
from PyQt6.QtGui import QIcon, QPixmap, QTextOption

def ensure_dependencies():
    if importlib.util.find_spec("darkdetect") is None:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "darkdetect"], 
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            sys.exit(1)

ensure_dependencies()
import darkdetect

from TriCoreDownloader.config import APP_VERSION

BASE_FONT = "\"Segoe UI Variable\", \"Segoe UI\", \"Roboto\", sans-serif"

TCD_MAIN_LOGO = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128"><rect width="128" height="128" rx="28" fill="#32323A" stroke="#4A4A54" stroke-width="4"/><path d="M64 14 L64 42" stroke="#FF3E3E" stroke-width="16" stroke-linecap="round"/><path d="M64 42 L64 66" stroke="#00A2E8" stroke-width="16" stroke-linecap="round"/><path d="M64 66 L64 88 M38 64 L64 90 L90 64" fill="none" stroke="#C4A1FF" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/><path d="M24 82 L24 98 A 8 8 0 0 0 32 106 L96 106 A 8 8 0 0 0 104 98 L104 82" fill="none" stroke="#555560" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg>"""

THEMES = {
    "dark": {
        "bg": "#3C3C44", "bg_input": "#32323A", "text": "#E8E8E8", "text_title": "#FFFFFF", 
        "text_dim": "#B0B0B8", "card": "#4A4A54", "border": "#555560", "border_hover": "#626270",
        "btn_text": "#2B2B30", "btn_hover_text": "#FFFFFF", "warn": "#EF5350"
    },
    "light": {
        "bg": "#F0F0F5", "bg_input": "#F9F9FB", "text": "#1D1D1F", "text_title": "#000000", 
        "text_dim": "#8E8E93", "card": "#FFFFFF", "border": "#D1D1D6", "border_hover": "#E5E5EA",
        "btn_text": "#FFFFFF", "btn_hover_text": "#FFFFFF", "warn": "#EF5350"
    },
    "oled": {
        "bg": "#000000", "bg_input": "#121212", "text": "#E8E8E8", "text_title": "#FFFFFF", 
        "text_dim": "#888888", "card": "#0A0A0A", "border": "#333333", "border_hover": "#555555",
        "btn_text": "#000000", "btn_hover_text": "#FFFFFF", "warn": "#EF5350"
    }
}

def load_tricore_config():
    config_path = os.path.join(os.environ.get('APPDATA', ''), 'TriCoreDownloader', 'config.json')
    cfg = {
        "theme": "dark",
        "console_mode": "NX",
        "accent_color": "",
        "rainbow_mode": False,
        "rainbow_speed": 2
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k in cfg:
                    if k in data:
                        cfg[k] = data[k]
        except Exception:
            pass
            
    if not cfg["accent_color"]:
        defaults = {"NX": "#c6a1fa", "CTR": "#bc181a", "CAFE": "#4ebcff"}
        cfg["accent_color"] = defaults.get(cfg.get("console_mode", "NX"), "#c6a1fa")
        
    return cfg

def get_stylesheet(theme_name, accent_color):
    c = THEMES.get(theme_name, THEMES["dark"])
    return f"""
    QMainWindow, QDialog, QMessageBox {{ background-color: {c['bg']}; color: {c['text']}; }}
    QWidget {{ font-family: {BASE_FONT}; font-size: 10pt; }}
    QLabel {{ color: {c['text']}; }}
    QFrame#Card {{ background-color: {c['card']}; border-radius: 8px; border: 1px solid {c['border']}; }}
    QLabel#CardTitle {{ color: {c['text_title']}; font-size: 13pt; font-weight: 700; }}
    QLabel#CardVersion {{ color: {c['text_dim']}; font-size: 9pt; font-weight: 500; }}
    QComboBox {{ background-color: {c['bg_input']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px; color: {c['text']}; min-height: 28px; outline: none; }}
    QCheckBox {{ color: {c['text']}; outline: none; }}
    QPushButton {{ background-color: {c['border']}; color: {c['text']}; border-radius: 6px; padding: 6px 14px; font-weight: 600; border: 1px solid {c['border_hover']}; min-height: 20px; outline: none; }}
    QPushButton:hover {{ background-color: {c['border_hover']}; }}
    QPushButton:pressed {{ background-color: {accent_color}; color: {c['btn_text']}; border: 1px solid {accent_color}; }}
    #btnExecute {{ background-color: {accent_color}; color: {c['btn_text']}; font-size: 11pt; font-weight: bold; padding: 10px 24px; border-radius: 6px; border: none; min-width: 200px; }}
    #btnExecute:hover {{ opacity: 0.8; color: {c['btn_hover_text']}; }}
    """

class ReleasesFetchThread(QThread):
    finished = pyqtSignal(list, str)

    def run(self):
        url = f"https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/releases?t={int(time.time())}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            self.finished.emit(data, "")
        except Exception as e:
            self.finished.emit([], str(e))

class DownloadWorkerThread(QThread):
    progress = pyqtSignal(str)
    completed = pyqtSignal(bool, str)

    def __init__(self, download_url, install_dir):
        super().__init__()
        self.download_url = download_url
        self.install_dir = os.path.abspath(install_dir)

    def run(self):
        try:
            self.progress.emit("Downloading update payload...")
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urllib.request.urlopen(req, timeout=30) as response:
                zip_bytes = response.read()

            self.progress.emit("Extracting files and replacing old data...")
            extracted_files = set()
            
            install_dir_norm = os.path.normcase(self.install_dir)
            
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                namelist = z.namelist()
                common_prefix = None
                
                for name in namelist:
                    if not name.endswith('/'):
                        parts = name.split('/')
                        if len(parts) > 1:
                            if common_prefix is None:
                                common_prefix = parts[0] + '/'
                            elif not name.startswith(common_prefix):
                                common_prefix = ""
                                break
                        else:
                            common_prefix = ""
                            break
                            
                for member in z.infolist():
                    filename = member.filename
                    
                    if common_prefix and filename.startswith(common_prefix):
                        filename = filename[len(common_prefix):]
                        
                    if not filename or filename.endswith('/'):
                        continue 

                    target_path = os.path.abspath(os.path.join(self.install_dir, filename))
                    target_norm = os.path.normcase(target_path)
                    
                    if not target_norm.startswith(install_dir_norm):
                        continue

                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as f_out:
                        f_out.write(z.read(member))
                        
                    extracted_files.add(target_norm)

            self.progress.emit("Cleaning up orphaned core files...")
            
            ALLOWED_FOLDERS = ["TriCoreDownloader", "CAFE", "CTR", "NX", "Languages", "Songs"]
            ALLOWED_ROOT_FILES = ["clean_pycache.bat", "run_TriCoreDownloader.py", "start.bat", "Updater.py", "clean_save.bat", "LICENSE", "README.md"]
            
            for folder in ALLOWED_FOLDERS:
                folder_path = os.path.abspath(os.path.join(self.install_dir, folder))
                if not os.path.exists(folder_path):
                    continue
                    
                for dirpath, dirnames, filenames in os.walk(folder_path, topdown=False):
                    for f in filenames:
                        file_path = os.path.abspath(os.path.join(dirpath, f))
                        file_norm = os.path.normcase(file_path)
                        if file_norm not in extracted_files:
                            try:
                                os.remove(file_path)
                            except Exception:
                                pass
                    
                    try:
                        if not os.listdir(dirpath):
                            os.rmdir(dirpath)
                    except Exception:
                        pass
                        
            for root_file in ALLOWED_ROOT_FILES:
                file_path = os.path.abspath(os.path.join(self.install_dir, root_file))
                file_norm = os.path.normcase(file_path)
                if os.path.exists(file_path) and file_norm not in extracted_files:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

            self.completed.emit(True, "Update installed successfully.")
        except Exception as e:
            self.completed.emit(False, str(e))

class UpdaterWindow(QMainWindow):
    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        
        self.install_dir = os.getcwd()
        if "--install-dir" in sys.argv:
            try:
                idx = sys.argv.index("--install-dir")
                self.install_dir = sys.argv[idx + 1]
            except IndexError:
                pass
                
        self.setWindowTitle("TriCoreDownloader (Updater)")
        self.setWindowIcon(self.get_app_icon())
        self.releases_data = []
        self.cached_releases = []
        
        self.force_reinstall_mode = "--reinstall" in sys.argv
        self.force_prerelease_mode = "--prerelease" in sys.argv
        self.force_view_all_mode = "--view-all" in sys.argv

        self.app_cfg = load_tricore_config()
        self.theme_name = self.app_cfg["theme"].lower()
        if self.theme_name not in THEMES:
            self.theme_name = "dark" if darkdetect.isDark() else "light"
            
        self.accent_color = self.app_cfg.get("accent_color", "#C4A1FF")
        self.rainbow_mode = self.app_cfg.get("rainbow_mode", False)
        self.rainbow_speed = self.app_cfg.get("rainbow_speed", 2)
        self.current_hue = 0.0
        
        self.init_ui()
        self.apply_style()
        
        if self.rainbow_mode:
            self.rainbow_timer = QTimer(self)
            self.rainbow_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.rainbow_timer.timeout.connect(self.update_rainbow_tick)
            self.rainbow_timer.start(33)
        
        self.fetch_all_releases()

    def get_app_icon(self):
        pix = QPixmap()
        if pix.loadFromData(QByteArray(TCD_MAIN_LOGO)):
            return QIcon(pix)
        return QIcon()

    def _convert_markdown_to_html(self, text):
        if not text:
            return ""
        text_normalized = text.replace("\r\n", "\n")
        return re.sub(r'(?<!\n)\n(?!\n)', '\n\n', text_normalized)

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        card_frame = QFrame(self)
        card_frame.setObjectName("Card")
        card_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(12)
        
        title_lbl = QLabel("TriCoreDownloader Updater 1.0.1", card_frame)
        title_lbl.setObjectName("CardTitle")
        card_layout.addWidget(title_lbl)
        
        self.version_lbl = QLabel(f"Current version of your TriCoreDownloader: {self.current_version}", card_frame)
        self.version_lbl.setObjectName("CardVersion")
        card_layout.addWidget(self.version_lbl)
        
        self.beta_checkbox = QCheckBox("Include main branch [not recommended]", card_frame)
        self.beta_checkbox.stateChanged.connect(self.toggle_beta_mode)
        card_layout.addWidget(self.beta_checkbox)
        
        self.status_lbl = QLabel("Checking available system versions...", card_frame)
        card_layout.addWidget(self.status_lbl)
        
        combo_layout = QHBoxLayout()
        combo_layout.setContentsMargins(0, 0, 0, 0)
        
        self.version_combo = QComboBox(card_frame)
        self.version_combo.setEnabled(False)
        self.version_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo_layout.addWidget(self.version_combo)
        
        self.btn_refresh = QPushButton("🔄", card_frame)
        self.btn_refresh.clicked.connect(self.refresh_data)
        combo_layout.addWidget(self.btn_refresh)
        
        card_layout.addLayout(combo_layout)
        
        self.warn_lbl = QLabel("", card_frame)
        self.warn_lbl.setWordWrap(True)
        self.warn_lbl.setStyleSheet("color: #EF5350; font-size: 9pt;")
        self.warn_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.warn_lbl.hide()
        card_layout.addWidget(self.warn_lbl)
        
        self.browser = QTextEdit(card_frame)
        self.browser.setReadOnly(True)
        self.browser.setMinimumHeight(150)
        self.browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        card_layout.addWidget(self.browser)
        
        self.version_combo.currentIndexChanged.connect(self.on_version_changed_index)
        
        main_layout.addWidget(card_frame)
        
        btn_layout = QHBoxLayout()
        
        btn_text = "Install"
        if self.force_reinstall_mode:
            btn_text = "Reinstall Current Version"
        elif self.force_prerelease_mode:
            btn_text = "Install Beta Build"
        
        self.btn_execute = QPushButton(btn_text, self)
        self.btn_execute.setObjectName("btnExecute")
        self.btn_execute.setEnabled(False)
        self.btn_execute.clicked.connect(self.start_installation)
        
        self.lbl_warning_symbol = QLabel("", self)
        self.lbl_warning_symbol.setMinimumWidth(15)
        self.lbl_warning_symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.opacity_effect = QGraphicsOpacityEffect(self.lbl_warning_symbol)
        self.lbl_warning_symbol.setGraphicsEffect(self.opacity_effect)
        
        self.pulse_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.pulse_anim.setStartValue(1.0)
        self.pulse_anim.setKeyValueAt(0.5, 0.3)
        self.pulse_anim.setEndValue(1.0)
        self.pulse_anim.setLoopCount(-1)
        self.pulse_anim.setDuration(2000)
        
        # --- MODIFICATION ICI ---
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.handle_cancel)
        
        btn_layout.addWidget(self.btn_execute)
        btn_layout.addWidget(self.lbl_warning_symbol)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_cancel)
        # ------------------------
        
        main_layout.addLayout(btn_layout)
        
        self.setFixedWidth(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.MSWindowsFixedSizeDialogHint)
        QTimer.singleShot(10, self.adjustSize)

    def apply_style(self):
        self.setStyleSheet(get_stylesheet(self.theme_name, self.accent_color))
        self.update_scrollbar_stylesheet()

    def update_rainbow_tick(self):
        increment = self.rainbow_speed * 0.8
        self.current_hue = (self.current_hue + increment) % 360.0
        is_dark = self.theme_name in ["dark", "oled"]
        sat_f = 200.0 / 255.0 if is_dark else 240.0 / 255.0
        val_f = 255.0 / 255.0 if is_dark else 180.0 / 255.0
        r, g, b = colorsys.hsv_to_rgb(self.current_hue / 360.0, sat_f, val_f)
        self.accent_color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        self.apply_style()

    def update_scrollbar_stylesheet(self):
        tmp_dir = QDir.tempPath() + "/TriCore_SVGs"
        QDir().mkpath(tmp_dir)
        
        def create_svg_file(name, color, is_up):
            path = tmp_dir + "/" + name
            pts = "18 15 12 9 6 15" if is_up else "6 9 12 15 18 9"
            content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="{pts}"/></svg>"""
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return path

        up_idle = create_svg_file("up_idle.svg", "#8A8A95", True)
        up_hover = create_svg_file("up_hover.svg", "#FFFFFF", True)
        down_idle = create_svg_file("down_idle.svg", "#8A8A95", False)
        down_hover = create_svg_file("down_hover.svg", "#FFFFFF", False)

        self.browser.setStyleSheet(f"""
            QTextEdit {{
                background-color: #1E1E24;
                color: #E8E8E8;
                border: 1px solid #4A4A55;
                border-radius: 8px;
                padding: 8px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: #2D2D36;
                width: 20px;
                margin: 0px 0 0px 0;
                padding-top: 20px;
                padding-bottom: 20px;
            }}
            QScrollBar::handle:vertical {{
                background: {self.accent_color};
                width: 20px;
                min-height: 40px;
                border-radius: 6px;
            }}
            QScrollBar::add-line:vertical {{
                border: none;
                background: #3A3A45;
                width: 20px;
                height: 20px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
                border-radius: 6px;
            }}
            QScrollBar::sub-line:vertical {{
                border: none;
                background: #3A3A45;
                width: 20px;
                height: 20px;
                subcontrol-position: top;
                subcontrol-origin: margin;
                border-radius: 6px;
            }}
            QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover,
            QScrollBar::add-line:vertical:pressed, QScrollBar::sub-line:vertical:pressed {{
                background: {self.accent_color};
            }}
            QScrollBar::up-arrow:vertical {{
                image: url("{up_idle}");
                width: 14px;
                height: 14px;
            }}
            QScrollBar::down-arrow:vertical {{
                image: url("{down_idle}");
                width: 14px;
                height: 14px;
            }}
            QScrollBar::up-arrow:vertical:hover, QScrollBar::up-arrow:vertical:pressed {{
                image: url("{up_hover}");
            }}
            QScrollBar::down-arrow:vertical:hover, QScrollBar::down-arrow:vertical:pressed {{
                image: url("{down_hover}");
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
                border: none;
            }}
        """)

    def set_warning(self, text):
        if text:
            self.warn_lbl.setText(text)
            self.warn_lbl.show()
            self.lbl_warning_symbol.setText("⚠️")
            if self.pulse_anim.state() != QAbstractAnimation.State.Running:
                self.pulse_anim.start()
        else:
            self.warn_lbl.setText("")
            self.warn_lbl.hide()
            self.pulse_anim.stop()
            self.opacity_effect.setOpacity(1.0)
            self.lbl_warning_symbol.setText("")
        QTimer.singleShot(10, self.adjustSize)

    def refresh_data(self):
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(False)
        self.status_lbl.setText("Refreshing data from GitHub...")
        self.version_combo.clear()
        self.version_combo.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.fetch_all_releases()

    def toggle_beta_mode(self, state):
        self.version_combo.clear()
        self.set_warning("")
        self.browser.clear()
        
        for text, data in self.cached_releases:
            self.version_combo.addItem(text, data)
            
        if state == Qt.CheckState.Checked.value:
            self.btn_execute.setEnabled(False)
            QTimer.singleShot(100, self.fetch_beta_source)
        else:
            self.btn_execute.setEnabled(self.version_combo.count() > 0)
        self.adjustSize()

    def merge_dicts(self, dict1, dict2):
        return {**dict1, **dict2}

    def fetch_all_releases(self):
        self.fetch_thread = ReleasesFetchThread()
        self.fetch_thread.finished.connect(self.process_releases)
        self.fetch_thread.start()

    def process_releases(self, data, error_str):
        if error_str:
            self.status_lbl.setText(f"API Connection Error: {error_str}")
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.setEnabled(True)
            return
            
        self.releases_data = data
        self.cached_releases = []
        self.version_combo.clear()
        self.browser.clear()
        
        first_stable_idx = -1
        prerelease_idx = -1
        
        for idx, release in enumerate(data):
            tag = release.get("tag_name", "").strip().lstrip('v')
            if tag:
                if release.get("prerelease", False):
                    display_name = f"{tag} [!Pre-release!]"
                    if prerelease_idx == -1:
                        prerelease_idx = idx
                else:
                    display_name = tag
                    if first_stable_idx == -1:
                        first_stable_idx = idx
                        
                self.cached_releases.append((display_name, release))
                self.version_combo.addItem(display_name, release)
                
        if self.version_combo.count() > 0:
            self.status_lbl.setText("Select a release:")
            self.version_combo.setEnabled(True)
            self.btn_execute.setEnabled(True)
            
            if self.force_reinstall_mode:
                self.status_lbl.setText("Automated structural reinstallation sequence triggered...")
                QTimer.singleShot(300, self.start_installation)
            elif self.force_prerelease_mode and prerelease_idx != -1:
                self.version_combo.setCurrentIndex(prerelease_idx)
                self.status_lbl.setText("Automated structural beta deployment sequence triggered...")
                QTimer.singleShot(300, self.start_installation)
            elif self.force_view_all_mode:
                self.version_combo.setCurrentIndex(0)
            else:
                if data[0].get("prerelease", False) and first_stable_idx != -1:
                    self.version_combo.setCurrentIndex(first_stable_idx)
                else:
                    self.version_combo.setCurrentIndex(0)
                    
            if self.beta_checkbox.isChecked():
                self.toggle_beta_mode(Qt.CheckState.Checked.value)
        else:
            self.status_lbl.setText("No public release distributions found.")
            
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(True)
        self.adjustSize()

    def fetch_beta_source(self):
        url = f"https://raw.githubusercontent.com/JeremKOYTB/TriCoreDownloader/refs/heads/main/TriCoreDownloader/config.py?t={int(time.time())}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
                
            with urllib.request.urlopen(req, timeout=5) as response:
                code = response.read().decode('utf-8', errors='ignore')
            
            match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', code)
            beta_version = match.group(1) if match else "Unknown"
            display_version = beta_version if beta_version.startswith("v") else f"v{beta_version}"
            
            target_zip = "https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/zipball/main"
            
            dummy_release = {
                "tag_name": f"main branch ({display_version})", 
                "zipball_url": target_zip, 
                "assets": [],
                "is_main_branch_node": True
            }
            
            self.version_combo.insertItem(0, f"main branch ({display_version})", dummy_release)
            self.version_combo.setCurrentIndex(0)
            self.set_warning("WARNING: These versions are actively under development. Reliability might be lower. Install only if you accept the risks and dangers! 👍")
            self.btn_execute.setEnabled(True)
        except Exception as e:
            self.set_warning(f"Failed to fetch main branch metadata matrix: {e}")
            self.btn_execute.setEnabled(False)
            
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(True)
        self.adjustSize()

    def on_version_changed_index(self, index):
        if index < 0:
            return
        current_data = self.version_combo.currentData()
        self.browser.clear()
        
        self.check_version_warnings(index)
        
        if isinstance(current_data, dict) and current_data.get("is_main_branch_node", False):
            self.browser.setHtml("<div style='color: #8A8A95; font-style: italic;'>Fetching latest commit data from GitHub...</div>")
            self.commit_thread = MainBranchCommitFetchThread()
            self.commit_thread.finished.connect(self.on_main_branch_commit_loaded)
            self.commit_thread.start()
        else:
            changelog_text = current_data.get("body", "No changelog provided.") if isinstance(current_data, dict) else ""
            self.browser.setMarkdown(self._convert_markdown_to_html(changelog_text))

    def on_main_branch_commit_loaded(self, commit_text):
        self.browser.setHtml(commit_text)

    def check_version_warnings(self, index):
        if index < 0: return
        current_text = self.version_combo.currentText()
        if "main branch" in current_text:
            self.set_warning("WARNING: These versions are actively under development. Reliability might be lower. Install only if you accept the risks and dangers! 👍")
        else:
            current_data = self.version_combo.currentData()
            if isinstance(current_data, dict) and current_data.get("prerelease", False):
                self.set_warning("WARNING: This pre-release build is nearly complete, but remains actively under evaluation. Reliability might be reduced.")
            else:
                self.set_warning("")

    def start_installation(self, *args):
        current_data = self.version_combo.currentData()
        if not current_data: return
        
        download_url = current_data.get("zipball_url")
        if not download_url:
            err_box = QMessageBox(self)
            err_box.setWindowIcon(self.get_app_icon())
            err_box.setIcon(QMessageBox.Icon.Critical)
            err_box.setWindowTitle("Asset Missing")
            err_box.setText("No installable binary distribution tree could be resolved for this variant.")
            err_box.exec()
            return
            
        self.version_combo.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.beta_checkbox.setEnabled(False)
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(False)
        
        self.worker = DownloadWorkerThread(download_url, self.install_dir)
        self.worker.progress.connect(self.status_lbl.setText)
        self.worker.completed.connect(self.installation_finished)
        self.worker.start()

    def installation_finished(self, success, message):
        if success:
            success_box = QMessageBox(self)
            success_box.setWindowIcon(self.get_app_icon())
            success_box.setIcon(QMessageBox.Icon.Information)
            success_box.setWindowTitle("Success")
            success_box.setText("The application structural assets have been updated successfully.\n\nPress OK to reload TriCoreDownloader.")
            success_box.exec()
            
            main_script = os.path.join(self.install_dir, "run_TriCoreDownloader.py")
            if os.path.exists(main_script):
                kwargs = {'cwd': self.install_dir, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
                if os.name == 'nt':
                    kwargs['creationflags'] = 0x00000008 | 0x00000200
                subprocess.Popen([sys.executable, main_script], **kwargs)
            sys.exit(0)
        else:
            fail_box = QMessageBox(self)
            fail_box.setWindowIcon(self.get_app_icon())
            fail_box.setIcon(QMessageBox.Icon.Critical)
            fail_box.setWindowTitle("Installation Failed")
            fail_box.setText(f"Critical execution error:\n{message}")
            fail_box.exec()
            
            self.version_combo.setEnabled(True)
            self.btn_execute.setEnabled(True)
            self.btn_cancel.setEnabled(True)
            self.beta_checkbox.setEnabled(True)
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.setEnabled(True)

    def handle_cancel(self, *args):
        box = QMessageBox(self)
        box.setWindowIcon(self.get_app_icon())
        box.setWindowTitle("Cancel Update")
        box.setText(f"Do you want to return to TriCoreDownloader ({self.current_version}) or exit completely?")
        box.setIcon(QMessageBox.Icon.Question)
        
        btn_return = box.addButton("Return to TriCoreDownloader", QMessageBox.ButtonRole.YesRole)
        btn_exit = box.addButton("Exit completely", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Stay here", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_return)
        box.exec()
        
        if box.clickedButton() == btn_return:
            main_script = os.path.join(self.install_dir, "run_TriCoreDownloader.py")
            if os.path.exists(main_script):
                kwargs = {'cwd': self.install_dir, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
                if os.name == 'nt':
                    kwargs['creationflags'] = 0x00000008 | 0x00000200
                subprocess.Popen([sys.executable, main_script], **kwargs)
            sys.exit(0)
        elif box.clickedButton() == btn_exit:
            sys.exit(0)

class MainBranchCommitFetchThread(QThread):
    finished = pyqtSignal(str)

    def run(self):
        url = f"https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/commits/main?t={int(time.time())}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
                
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            sha = data.get("sha", "")[:7]
            commit_info = data.get("commit", {})
            message = commit_info.get("message", "No description provided.")
            author_info = commit_info.get("author", {})
            date_str = author_info.get("date", "").replace("T", " ").replace("Z", "")
            
            html_output = (
                f"<div style='margin-bottom: 4px;'><b style='color: #C4A1FF;'>Latest Main Commit:</b> <code style='background-color: #2D2D36; padding: 2px 4px; border-radius: 4px; color: #FFFFFF;'>{sha}</code></div>"
                f"<div style='margin-bottom: 4px;'><b style='color: #8A8A95;'>Date:</b> <span style='color: #E8E8E8;'>{date_str}</span></div>"
                f"<hr style='border: none; border-top: 1px solid #4A4A55; margin: 6px 0;'>"
                f"<div><b style='color: #FFFFFF;'>Modification Notes:</b></div>"
                f"<div style='color: #E8E8E8; white-space: pre-wrap; margin-top: 4px;'>{message}</div>"
            )
            self.finished.emit(html_output)
        except Exception as e:
            self.finished.emit(f"<div style='color: #EF5350;'>Failed to reach main branch commit API endpoint: {e}</div>")

def handle_interrupt(window_instance):
    box = QMessageBox(window_instance)
    box.setWindowIcon(window_instance.get_app_icon())
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Exit?")
    box.setText("Ctrl+C was detected in the terminal.\n\nDo you want to close the updater?")
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    if box.exec() == QMessageBox.StandardButton.Yes:
        QApplication.quit()
        sys.exit(0)

if __name__ == "__main__":
    current_script = os.path.abspath(__file__)
    appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "TriCoreDownloader")
    temp_updater = os.path.join(appdata_dir, "TempUpdater.py")

    if os.path.normcase(current_script) != os.path.normcase(temp_updater):
        relocated_successfully = False
        try:
            os.makedirs(appdata_dir, exist_ok=True)
            shutil.copy2(current_script, temp_updater)
            
            for _ in range(10):
                if os.path.exists(temp_updater) and os.path.getsize(temp_updater) > 0:
                    break
                time.sleep(0.05)
                
            args = [sys.executable, temp_updater]
            passed_args = sys.argv[1:]
            if "--install-dir" not in passed_args:
                args.extend(["--install-dir", os.path.dirname(current_script)])
            args.extend(passed_args)
            
            kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL
            }
            if os.name == 'nt':
                kwargs['creationflags'] = 0x00000008 | 0x00000200
                
            proc = subprocess.Popen(args, **kwargs)
            time.sleep(0.4)
            if proc.poll() is None:
                relocated_successfully = True
        except Exception:
            pass 
            
        if relocated_successfully:
            sys.exit(0)

    app = QApplication(sys.argv)
    window = UpdaterWindow(APP_VERSION)
    window.show()
    
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)
    signal.signal(signal.SIGINT, lambda sig, frame: handle_interrupt(window))
    
    sys.exit(app.exec())
