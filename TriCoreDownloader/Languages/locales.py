import importlib
import sys
from pathlib import Path

STRINGS = {}

try:
    from . import locales_en
    if hasattr(locales_en, "STRINGS_EN"):
        STRINGS["en"] = locales_en.STRINGS_EN
except Exception:
    pass

try:
    from . import locales_fr
    if hasattr(locales_fr, "STRINGS_FR"):
        STRINGS["fr"] = locales_fr.STRINGS_FR
except Exception:
    pass

try:
    if getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "TriCoreDownloader" / "Languages"
    else:
        base_dir = Path(__file__).parent

    if base_dir.exists():
        for file_path in base_dir.glob("locales_*.py"):
            module_name = file_path.stem
            parts = module_name.split("_")
            if len(parts) >= 2:
                lang_code = parts[1].lower()
                if lang_code not in STRINGS:
                    try:
                        module = importlib.import_module(f".{module_name}", package=__package__)
                        dict_name = f"STRINGS_{lang_code.upper()}"
                        if hasattr(module, dict_name):
                            STRINGS[lang_code] = getattr(module, dict_name)
                    except Exception:
                        pass
except Exception:
    pass
