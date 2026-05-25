import sys
import os
import json
import warnings
from pathlib import Path
import traceback
import logging
import locale
from datetime import datetime

# =====================================================================
# SILENT LOGGING BOOTSTRAP
# =====================================================================
class NullStream:
    """Safely swallows all standard stream writes when logging is disabled."""
    def write(self, text): pass
    def flush(self): pass

def _setup_logging_mode():
    advanced_logs = False
    appdata_path = os.environ.get('APPDATA')
    
    if appdata_path:
        config_path = Path(appdata_path) / "TriCoreDownloader" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    advanced_logs = config.get("advanced_logs", False)
            except Exception:
                pass 

    if not advanced_logs:
        sys.stdout = NullStream()
        sys.stderr = NullStream()
        warnings.filterwarnings("ignore")

_setup_logging_mode()

# =====================================================================
# SYSTEM LOCALE DETECTION MATRIX
# =====================================================================
SYS_LANG = ""
try:
    # Safe multi-tiered locale fallback tracking strategy for Windows environments
    if os.name == 'nt':
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        sys_lang_raw = locale.windows_locale.get(lang_id)
    else:
        sys_lang_raw, _ = locale.getlocale()
        
    if not sys_lang_raw:
        sys_lang_raw = os.environ.get("LANG")
        
    if sys_lang_raw:
        SYS_LANG = sys_lang_raw[:2].upper()
except Exception:
    pass

if not SYS_LANG or SYS_LANG not in ["FR", "EN"]:
    SYS_LANG = "EN"

STRINGS = {
    "FR": {
        "CRASH_TITLE": "CRASH DETECTE / ERREUR FATALE",
        "PRESS_ENTER": "Appuyez sur Entree pour quitter...",
        "STARTING": "LOG_STARTING_TRICORE",
        "DEP_OK": "LOG_DEP_VERIFICATION_SUCCESS",
        "WINDOW_INIT": "LOG_INIT_MAIN_WINDOW",
        "FATAL_LOG": "LOG_UNHANDLED_FATAL_ERROR"
    },
    "EN": {
        "CRASH_TITLE": "CRASH DETECTED / FATAL ERROR",
        "PRESS_ENTER": "Press Enter to exit...",
        "STARTING": "LOG_STARTING_TRICORE",
        "DEP_OK": "LOG_DEP_VERIFICATION_SUCCESS",
        "WINDOW_INIT": "LOG_INIT_MAIN_WINDOW",
        "FATAL_LOG": "LOG_UNHANDLED_FATAL_ERROR"
    }
}

lang_dict = STRINGS[SYS_LANG]

# =====================================================================
# LOGGING INITIALIZATION
# =====================================================================
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TriCoreBoot")

def set_console_visibility(show=False):
    """Toggles Windows Command Prompt visibility for crash diagnostics."""
    if os.name == 'nt':
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 5 if show else 0)
        except Exception as e:
            logger.error(f"LOG_ERR_CONSOLE_VISIBILITY: {e}")

def crash_handler(exc_type, exc_value, exc_tb):
    """Global exception hook restoring console standard output on crash."""
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    
    set_console_visibility(show=True)
    logger.critical(lang_dict["FATAL_LOG"], exc_info=(exc_type, exc_value, exc_tb))
    
    print("\n" + "=" * 70)
    print(lang_dict["CRASH_TITLE"])
    print("=" * 70)
    traceback.print_exception(exc_type, exc_value, exc_tb)
    print("=" * 70)
    input(f"\n{lang_dict['PRESS_ENTER']}")
    sys.exit(1)

sys.excepthook = crash_handler
logger.info(lang_dict["STARTING"])

# =====================================================================
# ENV PATCHES & DEPENDENCIES
# =====================================================================
try:
    import netifaces2 as netifaces
    sys.modules["netifaces"] = netifaces
    logger.debug("LOG_NETIFACES2_ALIASED")
except ImportError as e:
    logger.warning(f"LOG_WARN_NETIFACES2_MISSING: {e}")

try:
    from TriCoreDownloader.dependencies import check_dependencies
    check_dependencies()
    logger.info(lang_dict["DEP_OK"])
except Exception as e:
    logger.error(f"LOG_ERR_DEP_VERIFICATION_FAILED: {e}")
    raise

warnings.filterwarnings("ignore", category=DeprecationWarning)

os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.*=false"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
logger.debug("LOG_QT_SCALING_CONFIGURED")

# =====================================================================
# APP LAUNCH PIPELINE
# =====================================================================
from PyQt6.QtWidgets import QApplication
from TriCoreDownloader.config import load_config
from TriCoreDownloader.styles import update_app_theme
from TriCoreDownloader.app_main_logic import FirmwareApp

if __name__ == "__main__":
    if os.name == 'nt':
        try:
            import ctypes
            myappid = 'tricoredownloader.app.1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            logger.debug("LOG_WIN_APP_ID_ISOLATED")
        except Exception as e:
            logger.warning(f"LOG_WARN_WIN_APP_ID_FAIL: {e}")

    app = QApplication(sys.argv)
    
    logger.debug("LOG_LOADING_CONFIG")
    initial_config, is_corrupted, tampered_rainbow = load_config()
    
    logger.debug("LOG_APPLYING_THEMES")
    update_app_theme(app, initial_config.get("theme", "auto"), initial_config.get("accent_color", ""))
    
    logger.info(lang_dict["WINDOW_INIT"])
    window = FirmwareApp(initial_config, is_corrupted, tampered_rainbow)
    
    set_console_visibility(show=False)
    
    logger.info("LOG_TRANSFER_QT_LOOP")
    sys.exit(app.exec())