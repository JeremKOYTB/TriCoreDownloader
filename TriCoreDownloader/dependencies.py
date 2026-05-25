import sys
import os
import subprocess
import locale

def _T(key, lang="EN"):
    try:
        from .Languages.locales import STRINGS
        return STRINGS.get(lang.upper(), STRINGS.get("EN", {})).get(key, key)
    except ImportError as e:
        print(f"LOG_WARN_TRANSLATION_IMPORT_FAILED: {e}")
        return key

def get_language():
    try:
        lang, _ = locale.getlocale()
        if lang:
            return lang.split('_')[0].upper()
    except Exception as e:
        print(f"LOG_WARN_LANG_DETECT_FAILED: {e}")
        pass
    return "EN"

def pause_exit(code=1, lang="EN"):
    input(f"\n{_T('dep_pause', lang)}")
    sys.exit(code)

def check_dependencies():
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
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
            print(f"LOG_MISSING_PACKAGE: {pip_name}")

    if not missing:
        print("LOG_ALL_DEPENDENCIES_PRESENT")
        return

    lang = get_language()
    missing_str = ", ".join(missing)

    print("\n" + "="*50)
    print(f"{_T('dep_title', lang):^50}") 
    print("="*50)
    print(_T('dep_modules', lang).format(missing_str))
    print(f" {_T('dep_prompt', lang)}")

    ans = input("\n > ").strip().lower()
    
    if ans not in ("", "o", "oui", "y", "yes"):
        print(f"\n{_T('dep_cancel', lang)}")
        pause_exit(1, lang)

    print(f"\n{_T('dep_installing', lang)}")

    try:
        pip_base_cmd = [sys.executable, "-m", "pip", "install", "--no-warn-script-location"]

        if os.name == "nt":
            std_pkgs = [p for p in missing if p != "anynet"]
            
            if std_pkgs:
                print(f"LOG_DEP_EXEC: {' '.join(pip_base_cmd + std_pkgs)}")
                subprocess.run(pip_base_cmd + std_pkgs, check=True)
            
            if "anynet" in missing:
                print(f"LOG_DEP_EXEC: {' '.join(pip_base_cmd + ['anynet', '--no-deps'])}")
                subprocess.run(pip_base_cmd + ["anynet", "--no-deps"], check=True)
        else:
            print(f"LOG_DEP_EXEC: {' '.join(pip_base_cmd + missing)}")
            subprocess.run(pip_base_cmd + missing, check=True)

        print(f"\n{_T('dep_success', lang)}")
        print(f"{_T('dep_restarting', lang)}\n")
        
        sys.stdout.flush() 

        subprocess.run([sys.executable] + sys.argv)
        sys.exit(0)

    except subprocess.CalledProcessError as e:
        print(f"LOG_ERR_PIP_INSTALL_FAILED_CODE_{e.returncode}")
        print("\n" + "="*50)
        print(f"{_T('dep_fail_title', lang):^50}")
        print("="*50)
        print(f" {_T('dep_fail_msg', lang).format(missing_str)}")
        pause_exit(1, lang)