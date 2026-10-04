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
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if "--install-dir" in sys.argv:
    try:
        idx = sys.argv.index("--install-dir")
        install_dir_path = sys.argv[idx + 1]
        sys.path.insert(0, os.path.abspath(install_dir_path))
    except IndexError:
        pass

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QFrame, 
                             QMessageBox, QCheckBox, QLayout, QSizePolicy,
                             QGraphicsOpacityEffect, QTextEdit, QProgressBar, QMenu)
from PyQt6.QtCore import (Qt, QTimer, QThread, pyqtSignal, QByteArray, 
                          QPropertyAnimation, QAbstractAnimation, QPoint, QSize, 
                          QEasingCurve, QParallelAnimationGroup)
from PyQt6.QtGui import QIcon, QPixmap, QTextOption, QAction

RE_MARKDOWN_NL = re.compile(r'(?<!\n)\n(?!\n)')
RE_APP_VERSION = re.compile(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']')

def ensure_dependencies():
    if importlib.util.find_spec("darkdetect") is None:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "darkdetect", "--no-warn-script-location"], 
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

ensure_dependencies()
try:
    import darkdetect
except ImportError:
    darkdetect = None

try:
    from TriCoreDownloader.config import APP_VERSION
except ImportError:
    APP_VERSION = "0.9.0.5"

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

def get_app_dir():
    try:
        from TriCoreDownloader.config import APPDATA_DIR
        return str(APPDATA_DIR)
    except Exception:
        pass

    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "TriCoreDownloader")

def load_tricore_config():
    config_path = os.path.join(get_app_dir(), 'config.json')
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
            
    raw_color = str(cfg.get("accent_color", "")).strip().lower()
    default_colors = ["#c6a1fa", "#bc181a", "#4ebcff", "#7e57c2", "#c4a1ff", "#e60012", "#009ac7", "auto", ""]
    if not raw_color or raw_color in default_colors:
        defaults = {"NX": "#c6a1fa", "CTR": "#bc181a", "CAFE": "#009ac7"}
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
    
    QPushButton#ConsoleSelector {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 14px;
        color: {c['text']};
        text-align: left;
        font-weight: 600;
        font-size: 10pt;
        min-height: 32px;
    }}
    QPushButton#ConsoleSelector:hover {{
        background-color: {c['border_hover']};
        border: 1px solid {accent_color};
    }}
    
    QMenu#ConsoleCustomMenu {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu#ConsoleCustomMenu::item {{
        padding: 8px 16px;
        color: {c['text']};
        border-radius: 6px;
        font-size: 10pt;
        font-weight: 500;
        min-height: 24px;
    }}
    QMenu#ConsoleCustomMenu::item:selected {{
        background-color: {c['card']};
        color: {c['text_title']};
    }}
    
    QCheckBox {{ color: {c['text']}; outline: none; font-size: 10pt; padding: 2px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 2px solid {c['border']}; background-color: transparent; }}
    QCheckBox::indicator:hover {{ border: 2px solid {accent_color}; }}
    QCheckBox::indicator:checked {{ background-color: {accent_color}; border: 2px solid {accent_color}; image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23FFFFFF' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E"); }}
    
    QProgressBar {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        text-align: center;
        max-height: 8px;
    }}
    QProgressBar::chunk {{
        background-color: {accent_color};
        border-radius: 3px;
    }}

    QPushButton {{
        background-color: {c['border']};
        color: {c['text']};
        border-radius: 6px;
        padding: 6px 14px;
        font-weight: 600;
        border: 1px solid {c['border_hover']};
        min-height: 20px;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {c['border_hover']};
    }}
    QPushButton:pressed {{
        background-color: {accent_color};
        color: {c['btn_text']};
        border: 1px solid {accent_color};
    }}
    QPushButton#btnRefresh {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        min-width: 34px;
        max-width: 34px;
        min-height: 32px;
        padding: 0px;
    }}
    QPushButton#btnRefresh:hover {{
        background-color: {c['border_hover']};
        border: 1px solid {accent_color};
    }}
    #btnExecute {{
        background-color: {accent_color};
        color: {c['btn_text']};
        font-size: 11pt;
        font-weight: bold;
        padding: 10px 24px;
        border-radius: 6px;
        border: none;
        min-width: 200px;
    }}
    #btnExecute:hover {{
        opacity: 0.85;
        color: {c['btn_hover_text']};
    }}
    #btnExecute:disabled {{
        background-color: {c['border']};
        color: {c['text_dim']};
    }}
    """

class CustomConsoleSelector(QPushButton):
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConsoleSelector")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(20, 20))
        
        self.menu = QMenu(self)
        self.menu.setObjectName("ConsoleCustomMenu")
        
        self.items = []
        self._current_index = 0
        self._signals_blocked = False
        self._active_anim_group = None
        
        self.clicked.connect(self._show_menu)

    def blockSignals(self, b):
        self._signals_blocked = b
        return super().blockSignals(b)

    def _update_minimum_width(self):
        if not self.items:
            return
        
        font_metrics = self.fontMetrics()
        max_w = max(
            (font_metrics.horizontalAdvance(" " + str(item['text'])) + 
             (28 if (item['icon'] and not item['icon'].isNull()) else 0) + 56)
            for item in self.items
        )
        if max_w > 0:
            self.setMinimumWidth(max_w)

    def addItem(self, icon_or_text, text_or_data=None, user_data=None):
        if isinstance(icon_or_text, QIcon):
            icon = icon_or_text
            text = str(text_or_data or "")
            data = user_data
        else:
            icon = QIcon()
            text = str(icon_or_text or "")
            data = text_or_data

        idx = len(self.items)
        action = QAction(text, self.menu)
        action.setData(idx)
        
        if not icon.isNull():
            action.setIcon(icon)

        self.menu.addAction(action)
        self.items.append({'text': text, 'icon': icon, 'action': action, 'data': data})
        self._update_minimum_width()

        if len(self.items) == 1:
            self.setCurrentIndex(0)

    def insertItem(self, index, icon_or_text, text_or_data=None, user_data=None):
        if isinstance(icon_or_text, QIcon):
            icon = icon_or_text
            text = str(text_or_data or "")
            data = user_data
        else:
            icon = QIcon()
            text = str(icon_or_text or "")
            data = text_or_data

        action = QAction(text, self.menu)
        if not icon.isNull():
            action.setIcon(icon)

        if index >= len(self.items):
            self.menu.addAction(action)
            self.items.append({'text': text, 'icon': icon, 'action': action, 'data': data})
        else:
            before_action = self.items[index]['action']
            self.menu.insertAction(before_action, action)
            self.items.insert(index, {'text': text, 'icon': icon, 'action': action, 'data': data})

        for i, itm in enumerate(self.items):
            itm['action'].setData(i)

        self._update_minimum_width()

    def currentData(self, role=None):
        return self.itemData(self._current_index)

    def currentText(self):
        return self.itemText(self._current_index)

    def itemData(self, index):
        if 0 <= index < len(self.items):
            return self.items[index].get('data')
        return None

    def setItemData(self, index, data):
        if 0 <= index < len(self.items):
            self.items[index]['data'] = data

    def itemText(self, index):
        if 0 <= index < len(self.items):
            return self.items[index].get('text', "")
        return ""

    def findData(self, data):
        for idx, item in enumerate(self.items):
            if item.get('data') == data:
                return idx
        return -1

    def findText(self, text):
        for idx, item in enumerate(self.items):
            if item.get('text') == text:
                return idx
        return -1

    def clear(self):
        self.menu.clear()
        self.items = []
        self._current_index = 0
        self.setText("")
        self.setIcon(QIcon())

    def setCurrentIndex(self, index):
        if 0 <= index < len(self.items):
            old_idx = self._current_index
            self._current_index = index
            item = self.items[index]
            self.setText(" " + item['text'])
            if item['icon'] and not item['icon'].isNull():
                self.setIcon(item['icon'])
            else:
                self.setIcon(QIcon())
            
            self._update_minimum_width()

            if not self._signals_blocked and old_idx != index:
                self.currentIndexChanged.emit(index)

    def currentIndex(self):
        return self._current_index

    def count(self):
        return len(self.items)

    def _play_transition_animation(self, new_index, action, on_finished=None):
        try:
            top_win = self.window()
            if not top_win or not self.isVisible():
                if on_finished:
                    on_finished()
                return

            if hasattr(self, "_active_anim_group") and self._active_anim_group:
                self._active_anim_group.stop()
                self._active_anim_group = None

            action_rect = self.menu.actionGeometry(action)
            global_start = self.menu.mapToGlobal(action_rect.topLeft())
            start_pt = top_win.mapFromGlobal(global_start)
            end_pt = top_win.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))

            new_item = self.items[new_index]

            anim_card = QWidget(top_win)
            anim_card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            anim_card.setObjectName("ConsoleSelector")
            anim_card.setStyleSheet(self.styleSheet())

            lay = QHBoxLayout(anim_card)
            lay.setContentsMargins(12, 0, 12, 0)
            lay.setSpacing(8)

            if new_item['icon'] and not new_item['icon'].isNull():
                lbl_icon = QLabel()
                lbl_icon.setPixmap(new_item['icon'].pixmap(QSize(20, 20)))
                lay.addWidget(lbl_icon)

            lbl_text = QLabel(new_item['text'])
            lbl_text.setStyleSheet("font-size: 10pt; font-weight: 600;")
            lay.addWidget(lbl_text)
            lay.addStretch()

            anim_card.setGeometry(start_pt.x(), start_pt.y(), self.width(), self.height())
            anim_card.show()

            opacity = QGraphicsOpacityEffect(anim_card)
            anim_card.setGraphicsEffect(opacity)

            anim_pos = QPropertyAnimation(anim_card, b"pos", self)
            anim_pos.setDuration(150)
            anim_pos.setStartValue(start_pt)
            anim_pos.setEndValue(end_pt)
            anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

            anim_fade = QPropertyAnimation(opacity, b"opacity", self)
            anim_fade.setDuration(150)
            anim_fade.setStartValue(0.3)
            anim_fade.setEndValue(1.0)

            anim_group = QParallelAnimationGroup(self)
            anim_group.addAnimation(anim_pos)
            anim_group.addAnimation(anim_fade)
            self._active_anim_group = anim_group

            def cleanup():
                self._active_anim_group = None
                anim_card.deleteLater()
                if on_finished:
                    on_finished()

            anim_group.finished.connect(cleanup)
            anim_group.start()
        except Exception:
            if on_finished:
                on_finished()

    def _show_menu(self):
        if not self.isEnabled() or not self.menu or self.menu.isEmpty():
            return
        
        self.menu.setMinimumWidth(max(self.width(), self.menu.sizeHint().width()))
        pos = self.mapToGlobal(QPoint(0, self.height() + 4))
        
        selected_action = self.menu.exec(pos)
        if selected_action is not None:
            idx = selected_action.data()
            if idx is not None and 0 <= idx < len(self.items):
                if self._current_index != idx:
                    self._play_transition_animation(idx, selected_action, on_finished=lambda: self.setCurrentIndex(idx))

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
    progress_val = pyqtSignal(int)
    completed = pyqtSignal(bool, str)

    def __init__(self, download_url, install_dir, target_version):
        super().__init__()
        self.download_url = download_url
        self.install_dir = os.path.abspath(install_dir)
        self.target_version = target_version
        self.is_7z = download_url.lower().endswith(".7z")
        self.skip_updater = self.target_version in ["0.9.0", "0.9.0.1", "0.9.0.2", "0.9.0.3", "0.9.0.4", "0.9.0.5"]

    def run(self):
        temp_archive_path = os.path.join(self.install_dir, "TCD_Update_Temp." + ("7z" if self.is_7z else "zip"))
        temp_extract_dir = os.path.join(self.install_dir, "TCD_Extract_Temp")
        
        try:
            if self.is_7z:
                self.progress.emit("Loading 7z extraction modules...")
                if importlib.util.find_spec("py7zr") is None:
                    try:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "py7zr", "--no-warn-script-location"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except subprocess.CalledProcessError:
                        raise Exception("Failed to install py7zr required for 7z extraction.")
            
            self.progress.emit("Downloading archive...")
            self.progress_val.emit(0)
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urllib.request.urlopen(req, timeout=30) as response:
                total_length = response.headers.get('content-length')
                total_size = int(total_length) if total_length and total_length.isdigit() else 0
                downloaded = 0
                chunk_size = 131072
                last_pct = -1
                with open(temp_archive_path, 'wb') as out_file:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            if pct != last_pct:
                                last_pct = pct
                                self.progress_val.emit(pct)
                                self.progress.emit(f"Downloading archive... ({pct}%)")
                        else:
                            mb_downloaded = downloaded // 1048576
                            if mb_downloaded != last_pct:
                                last_pct = mb_downloaded
                                self.progress.emit(f"Downloading archive... ({downloaded // 1024} KB)")

            self.progress_val.emit(100)
            self.progress.emit("Extracting files...")
            os.makedirs(temp_extract_dir, exist_ok=True)
            
            if self.is_7z:
                import py7zr
                with py7zr.SevenZipFile(temp_archive_path, mode='r') as z:
                    z.extractall(path=temp_extract_dir)
            else:
                with zipfile.ZipFile(temp_archive_path, 'r') as z:
                    z.extractall(temp_extract_dir)

            self.progress.emit("Analyzing architecture...")
            base_target = temp_extract_dir
            contents = os.listdir(temp_extract_dir)
            if len(contents) == 1:
                possible_dir = os.path.join(temp_extract_dir, contents[0])
                if os.path.isdir(possible_dir):
                    base_target = possible_dir

            main_script_target = os.path.join(base_target, "run_TriCoreDownloader.py")
            if not os.path.exists(main_script_target):
                raise Exception("Security: The vital file 'run_TriCoreDownloader.py' is missing from the downloaded archive. The update is cancelled to protect your current installation.")

            self.progress.emit("Cleaning up old files...")
            extracted_files = set()
            for root, _, files in os.walk(base_target):
                for f in files:
                    if self.skip_updater and f == "Updater.py":
                        continue
                    rel_path = os.path.relpath(os.path.join(root, f), base_target)
                    extracted_files.add(os.path.normcase(os.path.abspath(os.path.join(self.install_dir, rel_path))))

            ALLOWED_FOLDERS = ["TriCoreDownloader", "CAFE", "CTR", "NX", "Languages", "Songs"]
            ALLOWED_ROOT_FILES = [
                "clean_pycache.bat", "run_TriCoreDownloader.py", "start.bat", 
                "run_TriCoreDownloader.command", "run_TriCoreDownloader.sh",
                "start.sh", "start.command",
                "Updater.py", "clean_save.bat", "LICENSE", "README.md"
            ]

            for folder in ALLOWED_FOLDERS:
                folder_path = os.path.abspath(os.path.join(self.install_dir, folder))
                if not os.path.exists(folder_path):
                    continue
                for dirpath, _, filenames in os.walk(folder_path, topdown=False):
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
                if self.skip_updater and root_file == "Updater.py":
                    continue
                file_path = os.path.abspath(os.path.join(self.install_dir, root_file))
                file_norm = os.path.normcase(file_path)
                if os.path.exists(file_path) and file_norm not in extracted_files:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

            self.progress.emit("Installing new files...")
            for root, _, files in os.walk(base_target):
                for f in files:
                    if self.skip_updater and f == "Updater.py":
                        continue
                    src_file = os.path.join(root, f)
                    rel_path = os.path.relpath(src_file, base_target)
                    dst_file = os.path.join(self.install_dir, rel_path)
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    if sys.platform != "win32":
                        if dst_file.endswith((".sh", ".command", ".py")):
                            try:
                                st = os.stat(dst_file)
                                os.chmod(dst_file, st.st_mode | 0o111)
                            except Exception:
                                pass

            self.completed.emit(True, "Update installed successfully.")
        except Exception as e:
            self.completed.emit(False, str(e))
        finally:
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            if os.path.exists(temp_archive_path):
                try:
                    os.remove(temp_archive_path)
                except Exception:
                    pass

class UpdaterWindow(QMainWindow):
    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        self._is_closing = False
        self._in_cancel_prompt = False
        
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
        self.theme_name = self.app_cfg.get("theme", "auto").lower()
        if self.theme_name not in THEMES or self.theme_name == "auto":
            is_dark = True
            try:
                if darkdetect is not None:
                    is_dark = bool(darkdetect.isDark())
                else:
                    scheme = QApplication.styleHints().colorScheme()
                    is_dark = (scheme == Qt.ColorScheme.Dark)
            except Exception:
                pass
            self.theme_name = "dark" if is_dark else "light"
            
        self.accent_color = self.app_cfg.get("accent_color", "#C4A1FF")
        self.rainbow_mode = bool(self.app_cfg.get("rainbow_mode", False))
        self.rainbow_speed = max(1, min(6, int(self.app_cfg.get("rainbow_speed", 2))))
        self.current_hue = 0.0
        
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.spinner_timer = QTimer(self)
        self.spinner_timer.timeout.connect(self.update_spinner_ui)
        
        self.commit_thread = None
        self.fetch_thread = None
        self.worker = None

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
        return RE_MARKDOWN_NL.sub('\n\n', text_normalized)

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
        
        title_lbl = QLabel("TriCoreDownloader Updater 1.2.0", card_frame)
        title_lbl.setObjectName("CardTitle")
        card_layout.addWidget(title_lbl)
        
        self.version_lbl = QLabel(f"Current version of your TriCoreDownloader: {self.current_version}", card_frame)
        self.version_lbl.setObjectName("CardVersion")
        card_layout.addWidget(self.version_lbl)
        
        self.beta_checkbox = QCheckBox("Include main branch [not recommended]", card_frame)
        self.beta_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.beta_checkbox.stateChanged.connect(self.toggle_beta_mode)
        card_layout.addWidget(self.beta_checkbox)
        
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_lbl = QLabel("Checking available TriCoreDownloader versions...", card_frame)
        status_layout.addWidget(self.status_lbl)
        
        self.status_icon_lbl = QLabel("", card_frame)
        self.status_icon_lbl.setFixedWidth(20)
        status_layout.addWidget(self.status_icon_lbl)
        
        status_layout.addStretch()
        card_layout.addLayout(status_layout)
        
        self.progress_bar = QProgressBar(card_frame)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        card_layout.addWidget(self.progress_bar)
        
        combo_layout = QHBoxLayout()
        combo_layout.setContentsMargins(0, 0, 0, 0)
        combo_layout.setSpacing(8)
        
        self.version_combo = CustomConsoleSelector(card_frame)
        self.version_combo.setEnabled(False)
        self.version_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo_layout.addWidget(self.version_combo, 1)
        
        self.btn_refresh = QPushButton("🔄", card_frame)
        self.btn_refresh.setObjectName("btnRefresh")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.btn_execute.setCursor(Qt.CursorShape.PointingHandCursor)
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
        
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.handle_cancel)
        
        btn_layout.addWidget(self.btn_execute)
        btn_layout.addWidget(self.lbl_warning_symbol)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_cancel)
        
        main_layout.addLayout(btn_layout)
        
        self.setFixedWidth(520)
        if sys.platform == "win32":
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
        new_accent = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        if new_accent != self.accent_color:
            self.accent_color = new_accent
            self.apply_style()

    def update_spinner_ui(self):
        self.status_icon_lbl.setText(self.spinner_chars[self.spinner_idx])
        self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_chars)

    def update_scrollbar_stylesheet(self):
        up_idle = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238A8A95' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='18 15 12 9 6 15'/></svg>"
        up_hover = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23FFFFFF' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='18 15 12 9 6 15'/></svg>"
        down_idle = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238A8A95' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>"
        down_hover = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23FFFFFF' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>"

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
                width: 18px;
                margin: 0px;
                padding-top: 20px;
                padding-bottom: 20px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {self.accent_color};
                width: 18px;
                min-height: 40px;
                border-radius: 6px;
            }}
            QScrollBar::add-line:vertical {{
                border: none;
                background: #3A3A45;
                width: 18px;
                height: 20px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
                border-radius: 6px;
            }}
            QScrollBar::sub-line:vertical {{
                border: none;
                background: #3A3A45;
                width: 18px;
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
                width: 12px;
                height: 12px;
            }}
            QScrollBar::down-arrow:vertical {{
                image: url("{down_idle}");
                width: 12px;
                height: 12px;
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
        self.status_icon_lbl.setText("")
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
            
        if state == 2 or state == Qt.CheckState.Checked:
            self.btn_execute.setEnabled(False)
            QTimer.singleShot(100, self.fetch_beta_source)
        else:
            self.btn_execute.setEnabled(self.version_combo.count() > 0)
        self.adjustSize()

    def fetch_all_releases(self):
        self.fetch_thread = ReleasesFetchThread()
        self.fetch_thread.finished.connect(self.process_releases)
        self.fetch_thread.start()

    def process_releases(self, data, error_str):
        if error_str:
            self.status_icon_lbl.setText("❌")
            self.status_lbl.setText(f"API Connection Error: {error_str}")
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.setEnabled(True)
            return
            
        self.releases_data = data
        self.cached_releases = []
        self.version_combo.clear()
        self.browser.clear()
        self.status_icon_lbl.setText("")
        
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
                self.status_lbl.setText("Automatic reinstallation triggered...")
                QTimer.singleShot(300, self.start_installation)
            elif self.force_prerelease_mode and prerelease_idx != -1:
                self.version_combo.setCurrentIndex(prerelease_idx)
                self.status_lbl.setText("Automatic reinstallation (beta) triggered...")
                QTimer.singleShot(300, self.start_installation)
            elif self.force_view_all_mode:
                self.version_combo.setCurrentIndex(0)
            else:
                if data and data[0].get("prerelease", False) and first_stable_idx != -1:
                    self.version_combo.setCurrentIndex(first_stable_idx)
                else:
                    self.version_combo.setCurrentIndex(0)
                    
            if self.beta_checkbox.isChecked():
                self.toggle_beta_mode(2)
        else:
            self.status_lbl.setText("No public release distributions found?")
            
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(True)
        self.adjustSize()

    def fetch_beta_source(self):
        url = f"https://raw.githubusercontent.com/JeremKOYTB/TriCoreDownloader/refs/heads/main/TriCoreDownloader/config.py?t={int(time.time())}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urllib.request.urlopen(req, timeout=5) as response:
                code = response.read().decode('utf-8', errors='ignore')
            
            match = RE_APP_VERSION.search(code)
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
            self.set_warning(f"Failed to fetch main branch metadata: {e}")
            self.btn_execute.setEnabled(False)
            
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(True)
        self.adjustSize()

    def on_version_changed_index(self, index):
        if index < 0 or index >= self.version_combo.count():
            return
        current_data = self.version_combo.currentData()
        self.browser.clear()
        
        self.check_version_warnings(index)
        
        if isinstance(current_data, dict) and current_data.get("is_main_branch_node", False):
            self.browser.setHtml("<div style='color: #8A8A95; font-style: italic;'>Fetching latest commit data from GitHub...</div>")
            if self.commit_thread and self.commit_thread.isRunning():
                try:
                    self.commit_thread.finished.disconnect()
                except Exception:
                    pass
                self.commit_thread.terminate()
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
        base_version = current_text.split(" ")[0]
        
        if base_version == "0.9.0":
            self.set_warning("⚠️ WARNING: The structure of the 0.9.0 archive is incompatible with this updater. Installing it may corrupt the folder. Proceed with extreme caution.")
        elif "main branch" in current_text:
            self.set_warning("WARNING: These versions are actively under development. Reliability might be lower. Install only if you accept the risks and dangers! 👍")
        else:
            current_data = self.version_combo.currentData()
            if isinstance(current_data, dict) and current_data.get("prerelease", False):
                self.set_warning("WARNING: This pre-release build is nearly complete, but remains actively under evaluation. Reliability might be reduced.")
            else:
                self.set_warning("")

    def handle_progress_val(self, val):
        if val >= 100:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(val)

    def start_installation(self, *args):
        current_data = self.version_combo.currentData()
        if not current_data: return
        
        current_text = self.version_combo.currentText()
        base_version = current_text.split(" ")[0]
        
        download_url = None
        is_main_branch = current_data.get("is_main_branch_node", False)
        
        if is_main_branch:
            download_url = current_data.get("zipball_url")
        else:
            assets = current_data.get("assets", [])
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".zip") or name.endswith(".7z"):
                    download_url = asset.get("browser_download_url")
                    break
                    
        if not download_url:
            self.status_icon_lbl.setText("❌")
            self.status_lbl.setText("Select a release:")
            err_box = QMessageBox(self)
            err_box.setWindowIcon(self.get_app_icon())
            err_box.setIcon(QMessageBox.Icon.Critical)
            err_box.setWindowTitle("Asset Missing")
            err_box.setText("Security: No valid compiled asset (.zip or .7z) was found in this release. Source code download is explicitly forbidden for official releases.")
            err_box.exec()
            return
            
        self.version_combo.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.beta_checkbox.setEnabled(False)
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(False)
            
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.spinner_timer.start(100)
        
        self.worker = DownloadWorkerThread(download_url, self.install_dir, base_version)
        self.worker.progress.connect(self.status_lbl.setText)
        self.worker.progress_val.connect(self.handle_progress_val)
        self.worker.completed.connect(self.installation_finished)
        self.worker.start()

    def installation_finished(self, success, message):
        self.spinner_timer.stop()
        if success:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self.status_icon_lbl.setText("✅")
            self.status_lbl.setText("Complete.")
            success_box = QMessageBox(self)
            success_box.setWindowIcon(self.get_app_icon())
            success_box.setIcon(QMessageBox.Icon.Information)
            success_box.setWindowTitle("Success:")
            success_box.setText("TriCoreDownloader has been updated successfully.\n\nPress OK to reload TriCoreDownloader.")
            success_box.exec()
            
            self._is_closing = True
            main_script = os.path.join(self.install_dir, "run_TriCoreDownloader.py")
            if os.path.exists(main_script):
                kwargs = {'cwd': self.install_dir, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
                if sys.platform == "win32":
                    kwargs['creationflags'] = 0x00000008 | 0x00000200
                else:
                    kwargs['start_new_session'] = True
                subprocess.Popen([sys.executable, main_script], **kwargs)
            self.close()
            QApplication.quit()
            sys.exit(0)
        else:
            self.progress_bar.hide()
            self.status_icon_lbl.setText("❌")
            self.status_lbl.setText("Select a release:")
            fail_box = QMessageBox(self)
            fail_box.setWindowIcon(self.get_app_icon())
            fail_box.setIcon(QMessageBox.Icon.Critical)
            fail_box.setWindowTitle("Installation Failed...")
            fail_box.setText(f"Critical execution error:\n{message}")
            fail_box.exec()
            
            self.version_combo.setEnabled(True)
            self.btn_execute.setEnabled(True)
            self.btn_cancel.setEnabled(True)
            self.beta_checkbox.setEnabled(True)
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.setEnabled(True)

    def closeEvent(self, event):
        if self._is_closing:
            event.accept()
            return

        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            event.ignore()
            return

        event.ignore()
        self.handle_cancel()

    def handle_cancel(self, *args):
        if self._is_closing or self._in_cancel_prompt:
            return

        self._in_cancel_prompt = True
        try:
            box = QMessageBox(self)
            box.setWindowIcon(self.get_app_icon())
            box.setWindowTitle("Cancel Update")
            box.setText(f"Do you want to return to TriCoreDownloader ({self.current_version}) or exit completely?")
            box.setIcon(QMessageBox.Icon.Question)
            
            btn_return = box.addButton("Return to TriCoreDownloader", QMessageBox.ButtonRole.YesRole)
            btn_exit = box.addButton("Exit", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Stay here", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_return)
            box.exec()
            
            clicked = box.clickedButton()
            if clicked == btn_return:
                self._is_closing = True
                main_script = os.path.join(self.install_dir, "run_TriCoreDownloader.py")
                if os.path.exists(main_script):
                    kwargs = {'cwd': self.install_dir, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
                    if sys.platform == "win32":
                        kwargs['creationflags'] = 0x00000008 | 0x00000200
                    else:
                        kwargs['start_new_session'] = True
                    subprocess.Popen([sys.executable, main_script], **kwargs)
                self.close()
                QApplication.quit()
                sys.exit(0)
            elif clicked == btn_exit:
                self._is_closing = True
                self.close()
                QApplication.quit()
                sys.exit(0)
            else:
                self.status_icon_lbl.setText("❌")
                self.status_lbl.setText("Select a release:")
        finally:
            self._in_cancel_prompt = False

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
    window_instance.handle_cancel()

if __name__ == "__main__":
    current_script = os.path.abspath(__file__)
    appdata_dir = get_app_dir()
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
            
            log_file_path = os.path.join(appdata_dir, "updater_debug.log")
            debug_log = open(log_file_path, "w", encoding="utf-8")
            kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": debug_log,
                "stderr": subprocess.STDOUT
            }
            if sys.platform == "win32":
                kwargs['creationflags'] = 0x00000008 | 0x00000200
            else:
                kwargs['start_new_session'] = True
                
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