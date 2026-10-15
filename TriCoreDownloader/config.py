import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Tuple, Dict, Any

APP_NAME = "TriCoreDownloader"
APP_VERSION = "2.0.2"
IS_STORE_PYTHON = False
_HARD_RESET_LOCK = False

RE_DIGITS = re.compile(r"\d+")
RE_HEX32 = re.compile(r"^[A-Fa-f0-9]{32}$")

if os.name == "nt" and sys.executable and (
    "WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.executable
):
    IS_STORE_PYTHON = True


def _resolve_appdata_dir() -> Path:
    if os.name == "nt":
        appdata_env = os.environ.get("APPDATA")
        if appdata_env:
            primary = Path(appdata_env) / APP_NAME
        else:
            user_profile = os.environ.get("USERPROFILE", str(Path.home()))
            primary = Path(user_profile) / "AppData" / "Roaming" / APP_NAME

        if primary.exists():
            return primary
        if IS_STORE_PYTHON:
            legacy_store = Path.home() / f".{APP_NAME}"
            if legacy_store.exists():
                return legacy_store
        return primary

    if sys.platform == "darwin":
        legacy_mac_dir = Path.home() / ".config" / APP_NAME
        std_mac_dir = Path.home() / "Library" / "Application Support" / APP_NAME
        if legacy_mac_dir.exists() and not std_mac_dir.exists():
            return legacy_mac_dir
        return std_mac_dir

    xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg_config) / APP_NAME


APPDATA_DIR = _resolve_appdata_dir()
CONFIG_FILE = APPDATA_DIR / "config.json"
EULA_FILE = APPDATA_DIR / "terms.json"

ORDERED_KEYS = (
    "version",
    "first_launch",
    "console_mode",
    "volume",
    "hactool",
    "prod_keys",
    "prodinfo",
    "output_dir",
    "output_dir_nx",
    "output_dir_cafe",
    "output_dir_ctr",
    "cert_pem",
    "boot9_path",
    "decrypt_cia",
    "ctr_model",
    "ctr_region",
    "otp_path",
    "cafe_extract",
    "cafe_partitions",
    "lang",
    "theme",
    "accent_color",
    "rainbow_mode",
    "rainbow_speed",
    "custom_colors",
    "allow_resize",
    "advanced_mode",
    "advanced_logs",
    "exclude_exfat",
    "build_nsp",
    "auto_save",
    "ask_open_folder_nx",
    "auto_open_folder_nx",
    "ask_open_folder_cafe",
    "auto_open_folder_cafe",
    "ask_open_folder_ctr",
    "auto_open_folder_ctr",
    "hide_privacy_warning",
    "redact_privacy_info",
    "use_aria2c",
    "aria2c_path",
    "openssl_path",
    "cafe_cemu_layout",
    "rainbow_targets",
    "cafe_region",
    "otp_key",
)

DEFAULT_RAINBOW_TARGETS: Dict[str, bool] = {
    "title": True,
    "tabs": True,
    "buttons": True,
    "progress": True,
    "indicators": True,
    "text": False,
    "inputs": False,
    "console": False,
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": APP_VERSION,
    "first_launch": True,
    "console_mode": "NX",
    "volume": 50,
    "hactool": "",
    "prod_keys": "",
    "prodinfo": "",
    "output_dir": "",
    "output_dir_nx": "",
    "output_dir_cafe": "",
    "output_dir_ctr": "",
    "cert_pem": "",
    "otp_path": "",
    "cafe_extract": False,
    "cafe_partitions": ["MLC"],
    "lang": None,
    "theme": "auto",
    "accent_color": "",
    "rainbow_mode": False,
    "rainbow_speed": 2,
    "custom_colors": [],
    "allow_resize": False,
    "advanced_mode": False,
    "advanced_logs": False,
    "exclude_exfat": False,
    "build_nsp": False,
    "auto_save": False,
    "ask_open_folder_nx": True,
    "auto_open_folder_nx": False,
    "ask_open_folder_cafe": True,
    "auto_open_folder_cafe": False,
    "ask_open_folder_ctr": True,
    "auto_open_folder_ctr": False,
    "hide_privacy_warning": False,
    "redact_privacy_info": False,
    "use_aria2c": False,
    "aria2c_path": "",
    "openssl_path": "",
    "cafe_cemu_layout": False,
    "rainbow_targets": DEFAULT_RAINBOW_TARGETS.copy(),
    "cafe_region": "EUR",
    "otp_key": "",
    "boot9_path": "",
    "decrypt_cia": False,
    "ctr_model": "OLD",
    "ctr_region": "EUR",
}

FILE_KEYS_TO_VERIFY = (
    "hactool",
    "prod_keys",
    "prodinfo",
    "cert_pem",
    "aria2c_path",
    "openssl_path",
    "boot9_path",
)


def _clone_default_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    cfg["cafe_partitions"] = list(DEFAULT_CONFIG["cafe_partitions"])
    cfg["custom_colors"] = list(DEFAULT_CONFIG["custom_colors"])
    cfg["rainbow_targets"] = DEFAULT_RAINBOW_TARGETS.copy()
    return cfg


def _T(key: str, lang: str = "en") -> str:
    try:
        from .Languages.locales import STRINGS
        lang_key = str(lang or "en").lower()
        return STRINGS.get(lang_key, STRINGS.get("en", {})).get(key, key)
    except Exception:
        return key


def parse_version(v_str) -> Tuple[int, int, int, int]:
    try:
        parts = RE_DIGITS.findall(str(v_str))
        if not parts:
            return (0, 0, 0, 0)
        t = [int(p) for p in parts[:4]]
        while len(t) < 4:
            t.append(0)
        return (t[0], t[1], t[2], t[3])
    except Exception:
        return (0, 0, 0, 0)


def save_config(config_data: Dict[str, Any]) -> None:
    if _HARD_RESET_LOCK:
        return

    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = CONFIG_FILE.with_suffix(".json.tmp")
    lang = config_data.get("lang", "en")

    ordered_config = {k: config_data[k] for k in ORDERED_KEYS if k in config_data}
    for k, v in config_data.items():
        if k not in ordered_config and not k.startswith("_"):
            ordered_config[k] = v

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(ordered_config, f, indent=4)

        for attempt in range(3):
            try:
                temp_file.replace(CONFIG_FILE)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
    except PermissionError as e:
        print(f"[CONFIG FATAL] {_T('err_perm_denied', lang)} : {e}")
    except Exception as e:
        print(f"[CONFIG FATAL] {_T('err_save_failed', lang)} : {e}")
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def load_config() -> Tuple[Dict[str, Any], bool, bool]:
    default_config = _clone_default_config()
    is_corrupted = False
    tampered_rainbow = False

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)

            if not isinstance(saved, dict):
                raise ValueError("Root element is not a dictionary.")

            merged_config = _clone_default_config()
            merged_config.update(saved)
            force_rewrite = (len(saved) != len(merged_config)) or any(
                k not in saved for k in DEFAULT_CONFIG
            )

            raw_rt = saved.get("rainbow_targets")
            if isinstance(raw_rt, dict):
                clean_rt = DEFAULT_RAINBOW_TARGETS.copy()
                for k in clean_rt:
                    if k in raw_rt:
                        clean_rt[k] = bool(raw_rt[k])
                    else:
                        force_rewrite = True
                merged_config["rainbow_targets"] = clean_rt
            else:
                merged_config["rainbow_targets"] = DEFAULT_RAINBOW_TARGETS.copy()
                force_rewrite = True

            saved_version = str(saved.get("version", "0.0.0")).strip()

            if saved_version != "0.0.0" and saved_version != APP_VERSION:
                curr_t = parse_version(APP_VERSION)
                saved_t = parse_version(saved_version)

                if curr_t > saved_t:
                    merged_config["_version_status"] = "upgrade"
                    merged_config["_old_version"] = saved_version
                elif curr_t < saved_t:
                    merged_config["_version_status"] = "downgrade"
                    merged_config["_old_version"] = saved_version

                merged_config["version"] = APP_VERSION
                force_rewrite = True

            if merged_config.get("console_mode") not in ("NX", "CTR", "CAFE", "WELCOME"):
                merged_config["console_mode"] = "NX"
                force_rewrite = True

            try:
                vol = int(float(merged_config.get("volume", 50)))
                clamped_vol = max(0, min(100, vol))
                if clamped_vol != merged_config.get("volume"):
                    merged_config["volume"] = clamped_vol
                    force_rewrite = True
            except (ValueError, TypeError):
                merged_config["volume"] = 50
                force_rewrite = True

            for file_key in FILE_KEYS_TO_VERIFY:
                val = merged_config.get(file_key, "")
                if val and not os.path.isfile(str(val)):
                    merged_config[file_key] = ""
                    force_rewrite = True

            otp_val = str(merged_config.get("otp_path", "") or "")
            if otp_val:
                cleaned_otp = otp_val.strip()
                if not os.path.isfile(otp_val) and not RE_HEX32.match(cleaned_otp):
                    merged_config["otp_path"] = ""
                    force_rewrite = True

            if not merged_config.get("advanced_mode", False):
                merged_config["advanced_logs"] = False
                merged_config["use_aria2c"] = False
                merged_config["hide_privacy_warning"] = False
                merged_config["redact_privacy_info"] = False
            else:
                if not merged_config.get("advanced_logs", False):
                    merged_config["hide_privacy_warning"] = False
                    merged_config["redact_privacy_info"] = False
                elif not merged_config.get("hide_privacy_warning", False):
                    merged_config["redact_privacy_info"] = False

            if "rainbow_speed" in merged_config:
                try:
                    speed = int(merged_config["rainbow_speed"])
                except (ValueError, TypeError):
                    speed = 2
                    force_rewrite = True

                if speed > 6:
                    merged_config["rainbow_speed"] = 6
                    tampered_rainbow = True
                    force_rewrite = True
                elif speed < 1:
                    merged_config["rainbow_speed"] = 1
                    tampered_rainbow = True
                    force_rewrite = True
                else:
                    merged_config["rainbow_speed"] = speed

            if force_rewrite:
                save_config(merged_config)

            return merged_config, is_corrupted, tampered_rainbow

        except (json.JSONDecodeError, ValueError, OSError):
            is_corrupted = True

    return default_config, is_corrupted, tampered_rainbow
