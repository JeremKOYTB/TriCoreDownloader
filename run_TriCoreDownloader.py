import sys
import os
import io
import shutil
import stat
from pathlib import Path

safe_cwd = os.environ.get("OWD")
if not safe_cwd or "/.mount_" in safe_cwd or not os.path.isdir(safe_cwd):
    safe_cwd = os.path.expanduser("~")

try:
    cur_cwd = os.getcwd()
    if "/.mount_" in cur_cwd or not os.path.exists(cur_cwd):
        os.chdir(safe_cwd)
except OSError:
    try:
        os.chdir(safe_cwd)
    except Exception:
        pass

os.environ.pop("_MEIPASS2", None)
if "OWD" in os.environ and "/.mount_" in os.environ["OWD"]:
    os.environ["OWD"] = safe_cwd

if getattr(sys, "frozen", False):
    real_exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    base_dir = getattr(sys, "_MEIPASS", real_exe_dir)
else:
    real_exe_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = real_exe_dir

appimage_path = os.environ.get("APPIMAGE")
if appimage_path and os.path.exists(appimage_path):
    sys.executable = appimage_path

os.environ["GIO_MODULE_DIR"] = ""
os.environ["GIO_EXTRA_MODULES"] = ""
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.*=false;qt.qpa.*=false"

if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if exe_dir not in sys.path:
        sys.path.insert(0, exe_dir)
    if real_exe_dir not in sys.path:
        sys.path.insert(0, real_exe_dir)

if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

try:
    os.chdir(base_dir)
except Exception:
    pass


def _resolve_pyqt6_environment():
    if getattr(sys, "frozen", False):
        return True

    try:
        import PyQt6
        return True
    except ImportError:
        pass

    search_dirs = [base_dir, os.path.dirname(base_dir)]
    venv_names = [".venv", "venv", "env", "ENV", ".env"]
    current_py_tag = f"python{sys.version_info.major}.{sys.version_info.minor}"

    for s_dir in search_dirs:
        for v_name in venv_names:
            v_path = os.path.join(s_dir, v_name)
            if os.path.isdir(v_path):
                if os.name == "nt":
                    sp_win = os.path.join(v_path, "Lib", "site-packages")
                    if os.path.isdir(sp_win) and sp_win not in sys.path:
                        sys.path.insert(0, sp_win)
                else:
                    sp_unix = os.path.join(v_path, "lib", current_py_tag, "site-packages")
                    if os.path.isdir(sp_unix) and sp_unix not in sys.path:
                        sys.path.insert(0, sp_unix)

    try:
        import PyQt6
        return True
    except ImportError:
        pass

    if not os.environ.get("_TCD_REEXEC"):
        candidate_pythons = []
        for s_dir in search_dirs:
            for v_name in venv_names:
                if os.name == "nt":
                    candidate_pythons.append(os.path.join(s_dir, v_name, "Scripts", "python.exe"))
                else:
                    candidate_pythons.append(os.path.join(s_dir, v_name, "bin", "python"))
                    candidate_pythons.append(os.path.join(s_dir, v_name, "bin", "python3"))

        for py_exe in candidate_pythons:
            if os.path.isfile(py_exe) and os.path.abspath(py_exe) != os.path.abspath(sys.executable):
                import subprocess
                env = os.environ.copy()
                env["_TCD_REEXEC"] = "1"
                res = subprocess.run([py_exe] + sys.argv, env=env)
                os._exit(res.returncode)

    return False


_resolve_pyqt6_environment()

import json
import warnings
import traceback
import logging
import locale
import platform
import ssl
import subprocess
import time

ssl._create_default_https_context = ssl._create_unverified_context


def _get_appdata_directory():
    try:
        from TriCoreDownloader.config import APPDATA_DIR
        return str(APPDATA_DIR)
    except Exception:
        pass

    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            user_prof = os.environ.get("USERPROFILE", os.path.expanduser("~"))
            base = os.path.join(user_prof, "AppData", "Roaming")
        primary = os.path.join(base, "TriCoreDownloader")
        if os.path.exists(primary):
            return primary
        if sys.executable and (
            "WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.executable
        ):
            legacy_store = os.path.join(os.path.expanduser("~"), ".TriCoreDownloader")
            if os.path.exists(legacy_store):
                return legacy_store
        return primary
    elif sys.platform == "darwin":
        legacy_mac = os.path.expanduser("~/.config/TriCoreDownloader")
        std_mac = os.path.expanduser("~/Library/Application Support/TriCoreDownloader")
        if os.path.exists(legacy_mac) and not os.path.exists(std_mac):
            return legacy_mac
        return std_mac
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return os.path.join(base, "TriCoreDownloader")


def _setup_logging_mode():
    if sys.stdout is None:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass
    if sys.stderr is None:
        try:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass

    is_maintenance = any(
        arg in sys.argv for arg in ["--clean-cache", "--clean-pycache", "--clean-save", "--clean-data"]
    )
    if is_maintenance:
        return

    advanced_logs = False
    appdata_dir = _get_appdata_directory()
    config_path = os.path.join(appdata_dir, "config.json")

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                advanced_logs = config.get("advanced_logs", False)
        except Exception:
            pass

    if not advanced_logs:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass
        warnings.filterwarnings("ignore")


_setup_logging_mode()

SYS_LANG = ""

try:
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleLanguages"],
                text=True,
                timeout=1,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                clean = line.strip().strip('",();')
                if clean:
                    SYS_LANG = clean[:2].upper()
                    break
        except Exception:
            pass

    if not SYS_LANG:
        if os.name == "nt":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            sys_lang_raw = locale.windows_locale.get(lang_id)
        else:
            sys_lang_raw, _ = locale.getlocale()
            if not sys_lang_raw or sys_lang_raw == "C":
                sys_lang_raw = os.environ.get("LANG")

        if sys_lang_raw:
            SYS_LANG = sys_lang_raw[:2].upper()
except Exception:
    pass

if not SYS_LANG or SYS_LANG not in ["FR", "EN"]:
    SYS_LANG = "EN"

STRINGS = {
    "FR": {
        "CRASH_TITLE": "CRASH DÉTECTÉ / ERREUR FATALE",
        "STARTING": "Démarrage de TriCoreDownloader...",
        "DEP_OK": "Vérification des dépendances réussie.",
        "WINDOW_INIT": "Initialisation de la fenêtre principale...",
        "MACOS_OLD_TITLE": "Version de macOS non supportée",
        "MACOS_OLD_DESC": "Cette version de macOS n'est pas prise en charge et ne pourra pas l'être (macOS 13 Ventura minimum requis pour les dépendances et PyQt6).\nVeuillez mettre à jour votre système.",
        "MACOS_QUIT": "Quitter",
        "CRASH_PAUSE": "Un crash est survenu. Appuyez sur Entrée pour quitter...",
        "GUI_ERR_FAIL": "Impossible d'afficher la fenêtre d'erreur GUI : {err}",
        "ADVICE_DOUBLE_CLICK": (
            "[CONSEIL] Pour lancer l'application sous Windows :\n"
            "  1. Si une version compilée (.exe) existe, utilisez-la directement (elle inclut déjà toutes les dépendances sans aucune installation).\n"
            "  2. Sinon, exécutez le fichier 'start.bat' qui s'occupera d'installer et de configurer automatiquement toutes les dépendances nécessaires.\n"
            "  3. Ou installez manuellement les dépendances nécessaires dans votre environnement Python."
        ),
        "ADVICE_GENERAL": (
            "[CONSEIL] Le module 'PyQt6' n'est pas installé dans cet environnement Python.\n"
            "- Si une version compilée (.exe, .dmg, .AppImage) existe, lancez-la directement (aucun prérequis nécessaire).\n"
            "- Sinon, lancez le script 'start.bat' (Windows), 'start.command' (macOS) ou 'start.sh' (Linux) qui installera automatiquement toutes les dépendances."
        ),
        "CACHE_TITLE": "NETTOYAGE DES DOSSIERS __pycache__",
        "CACHE_DESC": "Ce script va supprimer tous les dossiers '__pycache__' dans le dossier de l'application et ses sous-dossiers.",
        "CACHE_USE_CASE": "À utiliser en cas de problème avec le cache Python ou simplement pour garder un projet propre.",
        "CACHE_FROZEN_INFO": "[INFO] Version compilée détectée : les fichiers de cache Python ne sont actifs qu'en exécution depuis le code source.",
        "CACHE_SEARCHING": "Recherche en cours...",
        "CACHE_FOUND": "Trouvé :",
        "CACHE_NOT_FOUND": "Aucun dossier '__pycache__' trouvé.",
        "CACHE_TOTAL": "Nombre total trouvé :",
        "CACHE_CONFIRM": "Confirmer la suppression ? (O/N) : ",
        "CACHE_CANCELLED": "Opération annulée.",
        "CACHE_DELETING": "Suppression en cours...",
        "CACHE_DELETE_ITEM": "Suppression de :",
        "CACHE_ERR_DELETE": "[ERREUR] Impossible de supprimer :",
        "CACHE_SUMMARY": "Résumé :",
        "CACHE_DELETED": "Supprimés :",
        "CACHE_FAILED": "Échecs    :",
        "SAVE_TITLE": "RÉINITIALISATION COMPLÈTE DES DONNÉES DE SAUVEGARDE",
        "SAVE_INTRO": "NOTE : Ce script sert uniquement si l'application rencontre un souci, n'arrive pas à se lancer ou s'il est impossible d'effacer la sauvegarde.",
        "SAVE_DESC": "Ce script va supprimer INTÉGRALEMENT le dossier de configuration et de sauvegarde :",
        "SAVE_WARN": "ATTENTION : Cela va remettre l'application dans son état d'origine sans sauvegarde.",
        "SAVE_NOT_FOUND": "[INFO] Le dossier n'existe pas ou a déjà été supprimé.",
        "SAVE_CONFIRM": "Voulez-vous vraiment supprimer ce dossier et tout son contenu ? (O/N) : ",
        "SAVE_CANCELLED": "Opération annulée. Rien n'a été modifié.",
        "SAVE_DELETING": "Suppression du dossier en cours...",
        "SAVE_SUCCESS": "[OK] Le dossier de configuration a été supprimé avec succès.",
        "SAVE_ERROR": "[ERREUR] Impossible de supprimer le dossier :",
        "PRESS_ENTER": "Appuyez sur Entrée pour quitter...",
    },
    "EN": {
        "CRASH_TITLE": "CRASH DETECTED / FATAL ERROR",
        "STARTING": "Starting TriCoreDownloader...",
        "DEP_OK": "Dependencies check successful.",
        "WINDOW_INIT": "Initializing main window...",
        "MACOS_OLD_TITLE": "Unsupported macOS Version",
        "MACOS_OLD_DESC": "This macOS version is not supported (macOS 13 Ventura minimum is required for dependencies and PyQt6).\nPlease upgrade your system.",
        "MACOS_QUIT": "Quit",
        "CRASH_PAUSE": "A crash occurred. Press Enter to exit...",
        "GUI_ERR_FAIL": "Could not display GUI error window: {err}",
        "ADVICE_DOUBLE_CLICK": (
            "[ADVICE] To run the application on Windows:\n"
            "  1. If a compiled executable (.exe) exists, run it directly (it already bundles all dependencies with no installation required).\n"
            "  2. Otherwise, run the 'start.bat' script which will automatically install and configure all required dependencies for you.\n"
            "  3. Or install the required dependencies manually in your Python environment."
        ),
        "ADVICE_GENERAL": (
            "[ADVICE] The 'PyQt6' module is not installed in this Python environment.\n"
            "- If a compiled executable (.exe, .dmg, .AppImage) exists, run it directly (no prerequisites needed).\n"
            "- Otherwise, run 'start.bat' (Windows), 'start.command' (macOS), or 'start.sh' (Linux) to install dependencies automatically."
        ),
        "CACHE_TITLE": "CLEANING __pycache__ DIRECTORIES",
        "CACHE_DESC": "This script will delete all '__pycache__' folders in the application directory and subdirectories.",
        "CACHE_USE_CASE": "Use if you have issues with Python cache or simply to keep your project clean.",
        "CACHE_FROZEN_INFO": "[INFO] Compiled build detected: Python bytecode cache is only active when running directly from source.",
        "CACHE_SEARCHING": "Searching...",
        "CACHE_FOUND": "Found:",
        "CACHE_NOT_FOUND": "No '__pycache__' folders found.",
        "CACHE_TOTAL": "Total found:",
        "CACHE_CONFIRM": "Confirm deletion? (Y/N): ",
        "CACHE_CANCELLED": "Operation cancelled.",
        "CACHE_DELETING": "Deleting...",
        "CACHE_DELETE_ITEM": "Deleting:",
        "CACHE_ERR_DELETE": "[ERROR] Failed to delete:",
        "CACHE_SUMMARY": "Summary:",
        "CACHE_DELETED": "Deleted:",
        "CACHE_FAILED": "Failed :",
        "SAVE_TITLE": "COMPLETE SAVE DATA RESET",
        "SAVE_INTRO": "NOTE: This script is intended for use if the application encounters an issue, fails to launch, or if it is impossible to delete save data.",
        "SAVE_DESC": "This script will COMPLETELY delete the data and configuration directory:",
        "SAVE_WARN": "WARNING: This will reset the application to its original state without any save data.",
        "SAVE_NOT_FOUND": "[INFO] The directory does not exist or has already been deleted.",
        "SAVE_CONFIRM": "Are you absolutely sure you want to delete this folder and all its contents? (Y/N): ",
        "SAVE_CANCELLED": "Operation cancelled. Nothing was changed.",
        "SAVE_DELETING": "Deleting directory...",
        "SAVE_SUCCESS": "[OK] The configuration directory has been successfully deleted.",
        "SAVE_ERROR": "[ERROR] Failed to delete the directory:",
        "PRESS_ENTER": "Press Enter to exit...",
    },
}

try:
    from TriCoreDownloader.Languages.locales import get_locale_dict
    lang_dict = get_locale_dict(SYS_LANG.lower())
    for k, v in STRINGS.get(SYS_LANG, STRINGS["EN"]).items():
        if k not in lang_dict:
            lang_dict[k] = v
except Exception:
    lang_dict = STRINGS.get(SYS_LANG, STRINGS["EN"])

log_stream = sys.__stderr__ if sys.__stderr__ is not None else sys.stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(log_stream)] if log_stream else [],
)
logger = logging.getLogger("TriCoreBoot")


def check_macos_compatibility():
    if sys.platform != "darwin":
        return

    try:
        mac_ver = platform.mac_ver()[0]
        major = None
        if mac_ver:
            try:
                major = int(mac_ver.split(".")[0])
            except (ValueError, IndexError):
                major = None

        if major is None:
            try:
                darwin_major = int(platform.release().split(".")[0])
                major = 12 if darwin_major < 22 else 13
            except Exception:
                pass

        if major is not None and major < 13:
            title = lang_dict.get("MACOS_OLD_TITLE", "Unsupported macOS Version")
            desc = lang_dict.get("MACOS_OLD_DESC", "macOS 13 Ventura minimum required.")
            btn = lang_dict.get("MACOS_QUIT", "Quit")

            script = (
                f'display dialog "{desc}" '
                f'with title "{title}" buttons {{"{btn}"}} default button "{btn}" with icon stop'
            )
            subprocess.run(["osascript", "-e", script], check=False)
            os._exit(1)
    except Exception as e:
        logger.debug(f"macOS check: {e}")


def set_console_visibility(show=False):
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 5 if show else 0)
        except Exception:
            pass


def _attach_console_for_cli():
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            if not k32.GetConsoleWindow():
                if not k32.AttachConsole(-1):
                    k32.AllocConsole()
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        except Exception:
            pass
    else:
        if sys.__stdout__ is not None:
            sys.stdout = sys.__stdout__
        if sys.__stderr__ is not None:
            sys.stderr = sys.__stderr__


def _force_rm_readonly(action, name, exc):
    try:
        os.chmod(name, stat.S_IWRITE)
        os.remove(name)
    except Exception:
        pass


def execute_clean_pycache_cli():
    _attach_console_for_cli()
    set_console_visibility(show=True)

    t = lang_dict
    print("\n" + "=" * 60)
    print(f"    {t.get('CACHE_TITLE')}")
    print("=" * 60 + "\n")
    print(t.get("CACHE_DESC"))
    print(t.get("CACHE_USE_CASE") + "\n")

    if getattr(sys, "frozen", False):
        print(t.get("CACHE_FROZEN_INFO") + "\n")

    print(t.get("CACHE_SEARCHING") + "\n")

    root_search = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else base_dir
    found_dirs = []
    for dirpath, dirnames, _ in os.walk(root_search, topdown=False):
        for d in dirnames:
            if d == "__pycache__":
                full_path = os.path.join(dirpath, d)
                found_dirs.append(full_path)
                print(f"{t.get('CACHE_FOUND')} {full_path}")

    if not found_dirs:
        print("\n" + t.get("CACHE_NOT_FOUND"))
        try:
            input(f"\n{t.get('PRESS_ENTER')}")
        except Exception:
            pass
        os._exit(0)

    print(f"\n{t.get('CACHE_TOTAL')} {len(found_dirs)}\n")
    try:
        confirm = input(t.get("CACHE_CONFIRM")).strip().upper()
    except Exception:
        confirm = "N"

    if confirm not in ["O", "Y"]:
        print("\n" + t.get("CACHE_CANCELLED"))
        try:
            input(f"\n{t.get('PRESS_ENTER')}")
        except Exception:
            pass
        os._exit(0)

    print("\n" + t.get("CACHE_DELETING") + "\n")
    deleted = 0
    failed = 0

    for path in found_dirs:
        if os.path.exists(path):
            print(f"{t.get('CACHE_DELETE_ITEM')} {path}")
            try:
                shutil.rmtree(path, onerror=_force_rm_readonly)
                if os.path.exists(path):
                    print(f"{t.get('CACHE_ERR_DELETE')} {path}")
                    failed += 1
                else:
                    deleted += 1
            except Exception as e:
                print(f"{t.get('CACHE_ERR_DELETE')} {path} ({e})")
                failed += 1

    print("\n" + "=" * 60)
    print(t.get("CACHE_SUMMARY"))
    print(f"    {t.get('CACHE_DELETED')} {deleted}")
    print(f"    {t.get('CACHE_FAILED')} {failed}")
    print("=" * 60 + "\n")

    try:
        input(t.get("PRESS_ENTER"))
    except Exception:
        pass
    os._exit(0)


def execute_clean_save_cli():
    _attach_console_for_cli()
    set_console_visibility(show=True)

    t = lang_dict
    target_dir = _get_appdata_directory()

    print("\n" + "=" * 60)
    print(f"    {t.get('SAVE_TITLE')}")
    print("=" * 60 + "\n")
    print(t.get("SAVE_INTRO") + "\n")
    print(t.get("SAVE_DESC"))
    print(f"    [Path] : \"{target_dir}\"\n")
    print(t.get("SAVE_WARN"))

    if not os.path.exists(target_dir):
        print("\n" + t.get("SAVE_NOT_FOUND"))
        try:
            input(f"\n{t.get('PRESS_ENTER')}")
        except Exception:
            pass
        os._exit(0)

    print()
    try:
        confirm = input(t.get("SAVE_CONFIRM")).strip().upper()
    except Exception:
        confirm = "N"

    if confirm not in ["O", "Y"]:
        print("\n" + t.get("SAVE_CANCELLED"))
        try:
            input(f"\n{t.get('PRESS_ENTER')}")
        except Exception:
            pass
        os._exit(0)

    print("\n" + t.get("SAVE_DELETING"))
    try:
        shutil.rmtree(target_dir, onerror=_force_rm_readonly)
        if not os.path.exists(target_dir):
            print("\n" + t.get("SAVE_SUCCESS"))
        else:
            print("\n" + t.get("SAVE_ERROR") + f" {target_dir}")
    except Exception as e:
        print("\n" + t.get("SAVE_ERROR") + f" {e}")

    try:
        input(f"\n{t.get('PRESS_ENTER')}")
    except Exception:
        pass
    os._exit(0)


def crash_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    try:
        appdata_dir = _get_appdata_directory()
        os.makedirs(appdata_dir, exist_ok=True)
        with open(os.path.join(appdata_dir, "crash.log"), "w", encoding="utf-8") as cf:
            cf.write(tb_text)
    except Exception:
        pass

    if not getattr(sys, "frozen", False):
        _attach_console_for_cli()
        set_console_visibility(show=True)

    err_out = sys.__stderr__ if sys.__stderr__ is not None else sys.stderr
    if err_out:
        try:
            print("\n" + "=" * 70, file=err_out)
            print(lang_dict.get("CRASH_TITLE", "FATAL ERROR"), file=err_out)
            print("=" * 70, file=err_out)
            print(tb_text, file=err_out)
            print("=" * 70, file=err_out)
        except Exception:
            pass

    gui_shown = False
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(lang_dict.get("CRASH_TITLE", "Fatal Error"))
        msg.setText(f"Fatal Error:\n{exc_value}")
        msg.setDetailedText(tb_text)
        msg.exec()
        gui_shown = True
    except Exception as e:
        if not getattr(sys, "frozen", False):
            _attach_console_for_cli()
            set_console_visibility(show=True)
        err_out = sys.stderr if sys.stderr is not None else sys.__stderr__
        err_msg = lang_dict.get("GUI_ERR_FAIL", "Impossible d'afficher la fenêtre d'erreur GUI : {err}").format(err=e)
        if err_out:
            try:
                print(f"{err_msg}", file=err_out)
            except Exception:
                pass

        if issubclass(exc_type, ImportError) and "PyQt6" in str(exc_value):
            is_win = os.name == "nt"
            is_source = not getattr(sys, "frozen", False)

            if is_win and is_source:
                advice = lang_dict.get("ADVICE_DOUBLE_CLICK", "")
            else:
                advice = lang_dict.get("ADVICE_GENERAL", "")

            if advice and err_out:
                try:
                    print(f"\n{advice}", file=err_out)
                except Exception:
                    pass

    if not gui_shown or not getattr(sys, "frozen", False):
        pause_msg = lang_dict.get("CRASH_PAUSE", "Un crash est survenu. Appuyez sur Entrée pour quitter...")
        try:
            input(f"\n{pause_msg}")
        except Exception:
            pass

    os._exit(1)


sys.excepthook = crash_handler


def cleanup_temp_updater():
    appdata = _get_appdata_directory()
    targets = [
        os.path.join(appdata, "TempUpdater.app"),
        os.path.join(appdata, "TempUpdater.exe"),
        os.path.join(appdata, "TempUpdater.exe.tmp"),
        os.path.join(appdata, "TempUpdater"),
        os.path.join(appdata, "TempUpdater.tmp"),
        os.path.join(appdata, "TempUpdater.py"),
        os.path.join(appdata, "TempUpdater.py.tmp"),
        os.path.join(appdata, "TCD_Download_Temp.bin"),
        os.path.join(appdata, "TCD_Extract_Temp"),
    ]
    for t in targets:
        if os.path.exists(t):
            for _ in range(3):
                try:
                    if os.path.isdir(t):
                        shutil.rmtree(t, onerror=_force_rm_readonly)
                    else:
                        os.remove(t)
                    break
                except PermissionError:
                    time.sleep(0.15)
                except Exception:
                    break


def _svg_bytes_to_qpixmap(svg_bytes, width=256, height=256, scale_ratio=1.0):
    from PyQt6.QtGui import QPixmap, QPainter
    from PyQt6.QtCore import QByteArray, Qt, QRectF

    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)

    scale_ratio = max(0.1, min(1.0, float(scale_ratio)))
    target_w = width * scale_ratio
    target_h = height * scale_ratio
    offset_x = (width - target_w) / 2.0
    offset_y = (height - target_h) / 2.0
    render_rect = QRectF(offset_x, offset_y, target_w, target_h)

    try:
        from PyQt6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(svg_bytes))
        if renderer.isValid():
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            renderer.render(painter, render_rect)
            painter.end()
            return pix
    except Exception:
        pass

    raw_pix = QPixmap()
    if raw_pix.loadFromData(QByteArray(svg_bytes), "SVG") or raw_pix.loadFromData(QByteArray(svg_bytes)):
        scaled_raw = raw_pix.scaled(
            int(target_w), int(target_h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        draw_x = int((width - scaled_raw.width()) / 2)
        draw_y = int((height - scaled_raw.height()) / 2)
        painter.drawPixmap(draw_x, draw_y, scaled_raw)
        painter.end()
        return pix

    return pix


def install_desktop_integration():
    if platform.system() != "Linux":
        return

    if "--updater" in sys.argv:
        return

    try:
        appimage_bin = os.environ.get("APPIMAGE")
        if appimage_bin and os.path.exists(appimage_bin):
            if "tempupdater" in os.path.basename(appimage_bin).lower():
                return
            exec_cmd = f'"{appimage_bin}"'
        elif getattr(sys, "frozen", False):
            exe_abs = os.path.abspath(sys.executable)
            if "tempupdater" in os.path.basename(exe_abs).lower():
                return
            exec_cmd = f'"{exe_abs}"'
        else:
            main_script = os.path.abspath(sys.argv[0])
            if "tempupdater" in os.path.basename(main_script).lower():
                return
            exec_cmd = f'"{sys.executable}" "{main_script}"'

        home = Path.home()
        apps_dir = home / ".local" / "share" / "applications"
        icons_dir = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        scalable_dir = home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
        pixmaps_dir = home / ".local" / "share" / "pixmaps"

        for d in [apps_dir, icons_dir, scalable_dir, pixmaps_dir]:
            d.mkdir(parents=True, exist_ok=True)

        from TriCoreDownloader.logos import TCD_MAIN_LOGO

        logo_updated = False
        svg_target = scalable_dir / "TriCoreDownloader.svg"
        
        if not svg_target.exists() or svg_target.read_bytes() != TCD_MAIN_LOGO:
            svg_target.write_bytes(TCD_MAIN_LOGO)
            logo_updated = True

        png_target = icons_dir / "TriCoreDownloader.png"
        pixmap_target = pixmaps_dir / "TriCoreDownloader.png"

        if logo_updated or not png_target.exists() or not pixmap_target.exists():
            pm = _svg_bytes_to_qpixmap(TCD_MAIN_LOGO, 256, 256)
            if not pm.isNull():
                for target in [png_target, pixmap_target]:
                    pm.save(str(target), "PNG")
                logo_updated = True

        desktop_target = apps_dir / "TriCoreDownloader.desktop"
        desktop_content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=TriCoreDownloader\n"
            f"Exec={exec_cmd}\n"
            "Icon=TriCoreDownloader\n"
            "Categories=Utility;\n"
            "Terminal=false\n"
            "StartupWMClass=TriCoreDownloader\n"
        )

        desktop_updated = False
        if not desktop_target.exists() or desktop_target.read_text(encoding="utf-8") != desktop_content:
            desktop_target.write_text(desktop_content, encoding="utf-8")
            desktop_target.chmod(0o755)
            desktop_updated = True

        if logo_updated or desktop_updated:
            try:
                subprocess.run(
                    ["gtk-update-icon-cache", "-f", "-t", str(home / ".local" / "share" / "icons" / "hicolor")],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass

            try:
                subprocess.run(
                    ["update-desktop-database", str(apps_dir)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Desktop integration: {e}")


def _get_mac_bundle_from_path(path):
    abs_path = os.path.abspath(path)
    parts = abs_path.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep.join(parts[:i + 1])
    return abs_path


def _launch_updater_mode(app, app_version):
    from Updater import UpdaterWindow, get_app_dir

    is_frozen = getattr(sys, "frozen", False)
    appdata_dir = get_app_dir()

    if is_frozen:
        if sys.platform == "darwin":
            exe_abs = os.path.abspath(sys.executable)
            app_bundle = _get_mac_bundle_from_path(exe_abs)
            if app_bundle.endswith(".app"):
                temp_bundle = os.path.join(appdata_dir, "TempUpdater.app")
                if os.path.normcase(app_bundle) != os.path.normcase(temp_bundle):
                    try:
                        os.makedirs(appdata_dir, exist_ok=True)
                        if os.path.exists(temp_bundle):
                            shutil.rmtree(temp_bundle, ignore_errors=True)
                        subprocess.run(["ditto", app_bundle, temp_bundle], check=True)

                        exe_name = os.path.basename(exe_abs)
                        temp_exe = os.path.join(temp_bundle, "Contents", "MacOS", exe_name)
                        if not os.path.exists(temp_exe):
                            temp_exe = os.path.join(temp_bundle, "Contents", "MacOS", "TriCoreDownloader")

                        args = [temp_exe, "--updater"]
                        passed_args = [a for a in sys.argv[1:] if a != "--updater"]
                        if "--install-dir" not in passed_args:
                            args.extend(["--install-dir", app_bundle])
                        if "--original-target" not in passed_args:
                            args.extend(["--original-target", app_bundle])
                        args.extend(passed_args)

                        clean_env = os.environ.copy()
                        clean_env.pop("_MEIPASS2", None)
                        clean_env.pop("_MEIPASS", None)

                        subprocess.Popen(
                            args,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            env=clean_env,
                            cwd=os.path.expanduser("~"),
                            start_new_session=True,
                        )
                        os._exit(0)
                    except Exception as e:
                        logger.error(f"macOS updater: {e}")
        else:
            exe_ext = ".exe" if sys.platform == "win32" else ""
            temp_updater_exe = os.path.join(appdata_dir, f"TempUpdater{exe_ext}")

            appimage_env = os.environ.get("ORIGINAL_APPIMAGE") or os.environ.get("APPIMAGE")
            if appimage_env and os.path.exists(appimage_env) and "tempupdater" not in os.path.basename(appimage_env).lower():
                src_exe = os.path.abspath(appimage_env)
            else:
                src_exe = os.path.abspath(sys.executable)

            actual_install_dir = os.path.dirname(src_exe)

            if os.path.normcase(src_exe) != os.path.normcase(temp_updater_exe):
                try:
                    os.makedirs(appdata_dir, exist_ok=True)
                    tmp_copy = temp_updater_exe + ".tmp"
                    shutil.copy2(src_exe, tmp_copy)
                    if sys.platform != "win32":
                        st = os.stat(tmp_copy)
                        os.chmod(tmp_copy, st.st_mode | stat.S_IEXEC | 0o755)
                    os.replace(tmp_copy, temp_updater_exe)

                    args = [temp_updater_exe, "--updater"]
                    passed_args = [a for a in sys.argv[1:] if a != "--updater"]
                    if "--install-dir" not in passed_args:
                        args.extend(["--install-dir", actual_install_dir])
                    if "--original-target" not in passed_args:
                        args.extend(["--original-target", src_exe])
                    args.extend(passed_args)

                    clean_env = os.environ.copy()
                    clean_env.pop("_MEIPASS2", None)
                    clean_env.pop("_MEIPASS", None)
                    clean_env.pop("APPDIR", None)
                    if sys.platform.startswith("linux") and "tempupdater" not in os.path.basename(src_exe).lower():
                        clean_env["ORIGINAL_APPIMAGE"] = src_exe

                    kwargs = {
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                        "env": clean_env,
                        "cwd": os.path.expanduser("~"),
                    }
                    if os.name == "nt":
                        kwargs["creationflags"] = 0x00000008 | 0x00000200
                    else:
                        kwargs["start_new_session"] = True

                    subprocess.Popen(args, **kwargs)
                    os._exit(0)
                except Exception as e:
                    logger.error(f"Updater: {e}")
    else:
        if "--install-dir" not in sys.argv:
            sys.argv.extend(["--install-dir", base_dir])
        if "--original-target" not in sys.argv:
            sys.argv.extend(["--original-target", os.path.abspath(__file__)])

    window = UpdaterWindow(app_version)
    window.show()
    os._exit(app.exec())


def main():
    if any(arg in sys.argv for arg in ["--clean-cache", "--clean-pycache"]):
        execute_clean_pycache_cli()

    if any(arg in sys.argv for arg in ["--clean-save", "--clean-data"]):
        execute_clean_save_cli()

    check_macos_compatibility()

    logger.info(lang_dict.get("STARTING", "Starting..."))

    try:
        import netifaces2 as netifaces
        sys.modules["netifaces"] = netifaces
    except Exception:
        pass

    warnings.filterwarnings("ignore", category=DeprecationWarning)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from TriCoreDownloader.config import load_config, APP_VERSION

    if os.name == "nt":
        try:
            import ctypes
            myappid = f"tricoredownloader.app.{APP_VERSION}"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("TriCoreDownloader")
    app.setDesktopFileName("TriCoreDownloader")

    from TriCoreDownloader.logos import TCD_MAIN_LOGO
    try:
        from TriCoreDownloader.logos import TCD_MAIN_LOGO_APPLE
    except ImportError:
        TCD_MAIN_LOGO_APPLE = TCD_MAIN_LOGO

    if sys.platform == "darwin":
        active_logo = TCD_MAIN_LOGO_APPLE
        pix = _svg_bytes_to_qpixmap(active_logo, 512, 512, scale_ratio=0.82)
        if not pix.isNull():
            app.setWindowIcon(QIcon(pix))
    else:
        pix = _svg_bytes_to_qpixmap(TCD_MAIN_LOGO, 256, 256)
        if not pix.isNull():
            app.setWindowIcon(QIcon(pix))

    if "--updater" in sys.argv:
        _launch_updater_mode(app, APP_VERSION)

    if platform.system() in ["Darwin", "Linux"]:
        try:
            from TriCoreDownloader.dependencies import check_dependencies
            try:
                check_dependencies(auto_install=True)
            except TypeError:
                check_dependencies()
            logger.info(lang_dict.get("DEP_OK", "Dependencies OK"))
        except Exception as e:
            logger.error(f"Dependencies: {e}")

    if platform.system() == "Linux":
        install_desktop_integration()

    cleanup_temp_updater()

    from TriCoreDownloader.styles import update_app_theme
    from TriCoreDownloader.app_main_logic import FirmwareApp

    initial_config, is_corrupted, tampered_rainbow = load_config()
    update_app_theme(app, initial_config.get("theme", "auto"), initial_config.get("accent_color", ""))

    logger.info(lang_dict.get("WINDOW_INIT", "Initializing window..."))
    window = FirmwareApp(initial_config, is_corrupted, tampered_rainbow)

    set_console_visibility(show=False)
    os._exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        crash_handler(*sys.exc_info())
