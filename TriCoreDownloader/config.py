import os
import sys
import json
import re
from pathlib import Path
from typing import Tuple, Dict, Any

APP_NAME = "TriCoreDownloader"
APP_VERSION = "0.9.0"
IS_STORE_PYTHON = False
_HARD_RESET_LOCK = False

if os.name == "nt" and sys.executable and ("WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.executable):
    IS_STORE_PYTHON = True
    print("[CONFIG] Detected Microsoft Store Python environment.")

if IS_STORE_PYTHON:
    APPDATA_DIR = Path.home() / f".{APP_NAME}"
elif os.name == "nt":
    user_profile = os.environ.get("USERPROFILE", str(Path.home()))
    APPDATA_DIR = Path(user_profile) / "AppData" / "Roaming" / APP_NAME
else:
    app_data = os.environ.get("APPDATA", str(Path.home()))
    APPDATA_DIR = Path(app_data) / APP_NAME

print(f"[CONFIG] Base directory set to: {APPDATA_DIR}")

CONFIG_FILE = APPDATA_DIR / "config.json"
EULA_FILE = APPDATA_DIR / "terms.json"

def _T(key: str, lang: str = "en") -> str:
    try:
        from .Languages.locales import STRINGS
        return STRINGS.get(lang, STRINGS.get("en", {})).get(key, key)
    except ImportError:
        return key

def save_config(config_data: Dict[str, Any]) -> None:
    # Atomic execution check: if reset lock is engaged, reject disk access immediately
    if _HARD_RESET_LOCK:
        print("[CONFIG] Write operation aborted: Hard reset lifecycle lock engaged.")
        return

    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = CONFIG_FILE.with_suffix(".json.tmp")
    lang = config_data.get("lang", "en")
    
    ordered_keys = [
        "version", "console_mode", "hactool", "prod_keys", "prodinfo", "output_dir",
        "output_dir_nx", "output_dir_cafe", "output_dir_ctr", "cert_pem",
        "boot9_path", "decrypt_cia", "ctr_model", "ctr_region",
        "otp_path", "cafe_extract", "cafe_partitions", "lang", "theme",
        "accent_color", "rainbow_mode", "rainbow_speed", "custom_colors",
        "allow_resize", "advanced_mode", "advanced_logs", "exclude_exfat",
        "auto_save", "ask_open_folder_nx", "auto_open_folder_nx",
        "ask_open_folder_cafe", "auto_open_folder_cafe", "ask_open_folder_ctr",
        "auto_open_folder_ctr", "hide_privacy_warning", "redact_privacy_info",
        "use_aria2c", "aria2c_path", "openssl_path", "cafe_cemu_layout",
        "rainbow_targets", "cafe_region", "otp_key"
    ]
    
    ordered_config = {k: config_data[k] for k in ordered_keys if k in config_data}
    for k, v in config_data.items():
        if k not in ordered_config and not k.startswith("_"):
            ordered_config[k] = v
            
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(ordered_config, f, indent=4)
        temp_file.replace(CONFIG_FILE)
        print(f"[CONFIG] Configuration successfully saved to {CONFIG_FILE}")
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
    default_config = {
        "version": APP_VERSION,
        "console_mode": "NX",
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
        "rainbow_targets": {
            "title": True,
            "tabs": True,
            "buttons": True,
            "progress": True,
            "indicators": True,
            "text": False,
            "inputs": False,
            "console": False
        },
        "cafe_region": "EUR",
        "otp_key": "",
        "boot9_path": "", 
        "decrypt_cia": False,
        "ctr_model": "OLD",
        "ctr_region": "EUR"
    }
    
    is_corrupted = False
    tampered_rainbow = False
    
    if CONFIG_FILE.exists():
        print(f"[CONFIG] Loading existing config file from {CONFIG_FILE}")
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.loads(f.read())
                
                if not isinstance(saved, dict):
                    raise ValueError("Root element is not a dictionary.")
                
            merged_config = default_config.copy()
            merged_config.update(saved)
            force_rewrite = (len(saved) != len(merged_config)) or any(k not in saved for k in default_config)
            
            saved_version = saved.get("version", "0.0.0")
            adv_logs = saved.get("advanced_logs", False)

            if adv_logs:
                print(f"[CONFIG DEBUG] Local APP_VERSION: {APP_VERSION}")
                print(f"[CONFIG DEBUG] Saved Config Version: {saved_version}")

            def parse_version(v_str):
                try:
                    parts = re.findall(r'\d+', str(v_str))
                    if not parts: return (0, 0, 0)
                    t = [int(p) for p in parts[:3]]
                    while len(t) < 3: t.append(0)
                    return tuple(t)
                except Exception:
                    return (0, 0, 0)
            
            if saved_version != "0.0.0" and saved_version != APP_VERSION:
                curr_t = parse_version(APP_VERSION)
                saved_t = parse_version(saved_version)
                
                if curr_t > saved_t:
                    merged_config["_version_status"] = "upgrade"
                    merged_config["_old_version"] = saved_version
                    if adv_logs: print("[CONFIG DEBUG] Upgrade detected. Injecting flags.")
                elif curr_t < saved_t:
                    merged_config["_version_status"] = "downgrade"
                    merged_config["_old_version"] = saved_version
                    if adv_logs: print("[CONFIG DEBUG] Downgrade detected. Injecting flags.")
                
                merged_config["version"] = APP_VERSION
                force_rewrite = True

            if merged_config.get("console_mode") not in ["NX", "CTR", "CAFE", "WELCOME"]:
                merged_config["console_mode"] = "NX"
                force_rewrite = True
            
            for file_key in ["hactool", "prod_keys", "prodinfo", "cert_pem", "aria2c_path", "openssl_path", "boot9_path"]:
                val = merged_config.get(file_key, "")
                if val and not Path(val).is_file():
                    merged_config[file_key] = ""
                    force_rewrite = True
                    
            otp_val = merged_config.get("otp_path", "")
            if otp_val:
                if not Path(otp_val).is_file() and not re.match(r"^[A-Fa-f0-9]{32}$", otp_val.strip()):
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
                
                if speed > 6:
                    merged_config["rainbow_speed"] = 6
                    tampered_rainbow = True
                    force_rewrite = True
                elif speed < 1:
                    merged_config["rainbow_speed"] = 1
                    tampered_rainbow = True
                    force_rewrite = True

            if force_rewrite:
                save_config(merged_config)
                
            return merged_config, is_corrupted, tampered_rainbow

        except (json.JSONDecodeError, ValueError) as e:
            print(f"[CONFIG ERROR] Configuration file is corrupted or invalid: {e}")
            is_corrupted = True
            
    else:
        print("[CONFIG] No existing config found. Proceeding with defaults.")
            
    return default_config, is_corrupted, tampered_rainbow

if __name__ == "__main__":
    config, corrupted, tampered = load_config()
    print(f"{_T('log_config_loaded', config.get('lang', 'en'))} {config}")
    save_config(config)