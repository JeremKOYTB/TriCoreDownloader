import sys
import os
import site
import subprocess
import locale
import platform
import importlib
import importlib.util

_FALLBACK_STRINGS = {
    "FR": {
        "dep_title": "DÉPENDANCES MANQUANTES",
        "dep_modules": "Modules requis manquants : {}",
        "dep_prompt": "Voulez-vous les installer automatiquement ? (O/n) :",
        "dep_cancel": "Installation annulée.",
        "dep_installing": "Installation des dépendances en cours...",
        "dep_success": "Toutes les dépendances ont été installées avec succès.",
        "dep_fail_title": "ÉCHEC DE L'INSTALLATION",
        "dep_fail_msg": "Impossible d'installer automatiquement : {}",
        "dep_pause": "Appuyez sur Entrée pour quitter...",
    },
    "EN": {
        "dep_title": "MISSING DEPENDENCIES",
        "dep_modules": "Missing required modules: {}",
        "dep_prompt": "Do you want to install them automatically? (Y/n):",
        "dep_cancel": "Installation cancelled.",
        "dep_installing": "Installing dependencies...",
        "dep_success": "All dependencies have been installed successfully.",
        "dep_fail_title": "INSTALLATION FAILED",
        "dep_fail_msg": "Could not automatically install: {}",
        "dep_pause": "Press Enter to exit...",
    },
}

_LOCALE_CACHE = {}


def _T(key, lang="EN"):
    lang_up = "FR" if str(lang).upper().startswith("FR") else "EN"
    if lang_up not in _LOCALE_CACHE:
        try:
            from .Languages.locales import STRINGS
            _LOCALE_CACHE[lang_up] = STRINGS.get(lang_up, STRINGS.get(lang_up.lower(), STRINGS.get("EN", {})))
        except Exception:
            _LOCALE_CACHE[lang_up] = {}

    val = _LOCALE_CACHE[lang_up].get(key)
    if val and val != key:
        return val
    return _FALLBACK_STRINGS.get(lang_up, _FALLBACK_STRINGS["EN"]).get(key, key)


def get_language():
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleLanguages"],
                text=True,
                timeout=1,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                clean = line.strip().strip('",();')
                if clean:
                    return "FR" if clean[:2].lower() == "fr" else "EN"
        elif os.name == "nt":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            sys_lang_raw = locale.windows_locale.get(lang_id, "")
            return "FR" if sys_lang_raw.lower().startswith("fr") else "EN"
        else:
            lang, _ = locale.getlocale()
            if not lang or lang == "C":
                lang = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
            return "FR" if lang.lower().startswith("fr") else "EN"
    except Exception:
        return "EN"
    return "EN"


def _in_virtualenv():
    return (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
        or bool(os.environ.get("VIRTUAL_ENV"))
    )


def _refresh_import_environment():
    importlib.invalidate_caches()
    candidate_Raw = []
    try:
        candidate_Raw.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            candidate_Raw.append(user_site)
    except Exception:
        pass

    for p in candidate_Raw:
        if p and os.path.isdir(p):
            site.addsitedir(p)
            if p not in sys.path:
                sys.path.insert(0, p)

    importlib.invalidate_caches()

    try:
        if "netifaces" not in sys.modules:
            import netifaces2 as netifaces
            sys.modules["netifaces"] = netifaces
    except Exception:
        pass


def pause_exit(code=1, lang="EN"):
    if sys.stdin and sys.stdin.isatty():
        try:
            input(f"\n{_T('dep_pause', lang)}")
        except Exception:
            pass
    sys.exit(code)


def _check_module_spec(pip_name, import_name):
    if pip_name == "netifaces2":
        return bool(
            importlib.util.find_spec("netifaces") is not None
            or importlib.util.find_spec("netifaces2") is not None
        )
    return importlib.util.find_spec(import_name) is not None


def _ensure_pip_available():
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if res.returncode == 0:
            return True
    except Exception:
        pass

    try:
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except Exception:
        return False


def check_dependencies(auto_install=False):
    if getattr(sys, "frozen", False):
        return

    packages = {
        "PyQt6": "PyQt6",
        "requests": "requests",
        "urllib3": "urllib3",
        "certifi": "certifi",
        "cryptography": "cryptography",
        "netifaces2": "netifaces",
        "pyctr": "pyctr",
        "anynet": "anynet",
        "py7zr": "py7zr",
        "darkdetect": "darkdetect",
    }

    missing = []

    for pip_name, import_name in packages.items():
        try:
            if not _check_module_spec(pip_name, import_name):
                missing.append(pip_name)
        except Exception:
            try:
                __import__(import_name)
            except ImportError:
                missing.append(pip_name)

    if not missing:
        return

    prev_stdout = sys.stdout
    if sys.__stdout__ is not None:
        sys.stdout = sys.__stdout__

    try:
        lang = get_language()
        missing_str = ", ".join(missing)
        is_interactive = bool(sys.stdin and sys.stdin.isatty())

        if not auto_install and is_interactive:
            print("\n" + "=" * 50)
            print(f"{_T('dep_title', lang):^50}")
            print("=" * 50)
            print(_T("dep_modules", lang).format(missing_str))
            print(f" {_T('dep_prompt', lang)}")

            try:
                ans = input("\n > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"

            if ans not in ("", "o", "oui", "y", "yes"):
                print(f"\n{_T('dep_cancel', lang)}")
                pause_exit(1, lang)

        print(f"\n{_T('dep_installing', lang)}")

        _ensure_pip_available()

        pip_base_cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--prefer-binary",
            "--no-warn-script-location",
            "--disable-pip-version-check",
        ]

        if platform.system() == "Darwin":
            pip_base_cmd.extend(["--only-binary", "cryptography"])

        std_pkgs = [p for p in missing if p != "anynet"]
        in_venv = _in_virtualenv()

        def run_pip_install(pkg_args):
            cmd_primary = pip_base_cmd + pkg_args
            try:
                subprocess.run(cmd_primary, check=True)
                return
            except subprocess.CalledProcessError:
                if in_venv:
                    raise

            if platform.system() != "Windows":
                try:
                    subprocess.run(
                        pip_base_cmd + ["--user", "--break-system-packages"] + pkg_args,
                        check=True,
                    )
                    return
                except subprocess.CalledProcessError:
                    pass

                try:
                    subprocess.run(
                        pip_base_cmd + ["--break-system-packages"] + pkg_args,
                        check=True,
                    )
                    return
                except subprocess.CalledProcessError:
                    pass

            subprocess.run(pip_base_cmd + ["--user"] + pkg_args, check=True)

        try:
            if std_pkgs:
                run_pip_install(std_pkgs)
            if "anynet" in missing:
                run_pip_install(["anynet", "--no-deps"])

            _refresh_import_environment()
            print(f"\n{_T('dep_success', lang)}")

        except subprocess.CalledProcessError as e:
            if is_interactive:
                print("\n" + "=" * 50)
                print(f"{_T('dep_fail_title', lang):^50}")
                print("=" * 50)
                print(f" {_T('dep_fail_msg', lang).format(missing_str)}")
                pause_exit(1, lang)
            else:
                raise RuntimeError(
                    f"Échec de l'installation automatique des dépendances : {missing_str}"
                ) from e
    finally:
        sys.stdout = prev_stdout
