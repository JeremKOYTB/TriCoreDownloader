import sys
import os
import subprocess
import locale
import platform
import importlib.util

def _T(key, lang="EN"):
    try:
        from .Languages.locales import STRINGS
        return STRINGS.get(lang.upper(), STRINGS.get("EN", {})).get(key, key)
    except Exception:
        return key

def get_language():
    try:
        lang, _ = locale.getlocale()
        if lang:
            return lang.split('_')[0].upper()
    except Exception:
        pass
    return "EN"

def pause_exit(code=1, lang="EN"):
    if sys.stdin and sys.stdin.isatty():
        try:
            input(f"\n{_T('dep_pause', lang)}")
        except Exception:
            pass
    sys.exit(code)

def check_dependencies(auto_install=False):
    print("LOG_SCANNING_DEPENDENCIES")
    packages = {
        "PyQt6": "PyQt6",
        "requests": "requests",
        "cryptography": "cryptography",
        "urllib3": "urllib3",
        "anyio": "anyio",
        "pyopenssl": "OpenSSL",
        "netifaces2": "netifaces",
        "pyctr": "pyctr",
        "anynet": "anynet"
    }
    
    missing = []

    for pip_name, import_name in packages.items():
        try:
            if importlib.util.find_spec(import_name) is None:
                missing.append(pip_name)
                print(f"LOG_MISSING_PACKAGE: {pip_name}")
        except Exception:
            try:
                __import__(import_name)
            except ImportError:
                missing.append(pip_name)
                print(f"LOG_MISSING_PACKAGE: {pip_name}")

    if not missing:
        print("LOG_ALL_DEPENDENCIES_PRESENT")
        return

    lang = get_language()
    missing_str = ", ".join(missing)
    is_interactive = bool(sys.stdin and sys.stdin.isatty())

    if not auto_install and is_interactive:
        print("\n" + "="*50)
        print(f"{_T('dep_title', lang):^50}") 
        print("="*50)
        print(_T('dep_modules', lang).format(missing_str))
        print(f" {_T('dep_prompt', lang)}")

        try:
            ans = input("\n > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        
        if ans not in ("", "o", "oui", "y", "yes"):
            print(f"\n{_T('dep_cancel', lang)}")
            pause_exit(1, lang)
    else:
        print(f"[*] Mode automatique ou non-interactif détecté. Installation des modules : {missing_str}")

    print(f"\n{_T('dep_installing', lang)}")

    try:
        pip_base_cmd = [sys.executable, "-m", "pip", "install", "--no-warn-script-location"]

        if platform.system() == "Darwin":
            pip_base_cmd.extend(["--only-binary", "cryptography"])

        if os.name == "nt":
            std_pkgs = [p for p in missing if p != "anynet"]
            if std_pkgs:
                subprocess.run(pip_base_cmd + std_pkgs, check=True)
            if "anynet" in missing:
                subprocess.run(pip_base_cmd + ["anynet", "--no-deps"], check=True)
        else:
            subprocess.run(pip_base_cmd + missing, check=True)

        print(f"\n{_T('dep_success', lang)}")

    except subprocess.CalledProcessError as e:
        print(f"LOG_ERR_PIP_INSTALL_FAILED_CODE_{e.returncode}")
        if is_interactive:
            print("\n" + "="*50)
            print(f"{_T('dep_fail_title', lang):^50}")
            print("="*50)
            print(f" {_T('dep_fail_msg', lang).format(missing_str)}")
            pause_exit(1, lang)
        else:
            raise RuntimeError(f"Échec de l'installation automatique des dépendances : {missing_str}")