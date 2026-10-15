import os
import sys
import json
import re
import hashlib
import zipfile
import tarfile
import urllib.request
import urllib.error
import subprocess
import importlib.util
import signal
import colorsys
import shutil
import time
import ssl
import locale
import stat
import platform
import errno
import tempfile
import traceback

ssl._create_default_https_context = ssl._create_unverified_context


def _tlog(msg, level="INFO"):
    try:
        stream = sys.stderr if level in ("ERROR", "WARN") else sys.stdout
        if stream is not None:
            ts = time.strftime("%H:%M:%S")
            stream.write(f"[{ts}] [TCD-Updater/{level}] {msg}\n")
            stream.flush()
    except Exception:
        pass


def _install_excepthook():
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _tlog(f"Unhandled exception:\n{tb_str.rstrip()}", "ERROR")
    sys.excepthook = _hook


_install_excepthook()

if "--install-dir" in sys.argv:
    try:
        idx = sys.argv.index("--install-dir")
        install_dir_path = sys.argv[idx + 1]
        if os.path.exists(install_dir_path):
            sys.path.insert(0, os.path.abspath(install_dir_path))
    except IndexError:
        pass

base_script_dir = os.path.abspath(os.path.dirname(__file__))
if base_script_dir not in sys.path:
    sys.path.insert(0, base_script_dir)


def _resolve_venv_environment():
    if getattr(sys, "frozen", False):
        return
    search_dirs = [base_script_dir, os.getcwd()]
    if "--install-dir" in sys.argv:
        try:
            idx = sys.argv.index("--install-dir")
            search_dirs.insert(0, os.path.abspath(sys.argv[idx + 1]))
        except IndexError:
            pass

    venv_names = [".venv", "venv", "env", "ENV", ".env"]
    for s_dir in search_dirs:
        if not s_dir or not os.path.isdir(s_dir):
            continue
        for v_name in venv_names:
            v_path = os.path.join(s_dir, v_name)
            if os.path.isdir(v_path):
                sp_win = os.path.join(v_path, "Lib", "site-packages")
                if os.path.isdir(sp_win) and sp_win not in sys.path:
                    sys.path.insert(0, sp_win)
                lib_dir = os.path.join(v_path, "lib")
                if os.path.isdir(lib_dir):
                    try:
                        for py_ver in os.listdir(lib_dir):
                            sp_unix = os.path.join(lib_dir, py_ver, "site-packages")
                            if os.path.isdir(sp_unix) and sp_unix not in sys.path:
                                sys.path.insert(0, sp_unix)
                    except OSError:
                        pass


_resolve_venv_environment()

RE_MARKDOWN_NL = re.compile(r'(?<!\n)\n(?!\n)')
RE_APP_VERSION = re.compile(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']')
RE_SHA256_LINE = re.compile(r'([a-fA-F0-9]{64})\s+\*?([^\s\r\n]+)')


def get_mac_app_bundle_path(path):
    abs_path = os.path.abspath(path)
    parts = abs_path.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep.join(parts[:i + 1])
    return abs_path


def get_app_dir():
    try:
        from TriCoreDownloader.config import APPDATA_DIR
        return str(APPDATA_DIR)
    except Exception:
        pass

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            user_prof = os.environ.get("USERPROFILE", os.path.expanduser("~"))
            base = os.path.join(user_prof, "AppData", "Roaming")
        return os.path.join(base, "TriCoreDownloader")
    elif sys.platform == "darwin":
        legacy_mac = os.path.expanduser("~/.config/TriCoreDownloader")
        std_mac = os.path.expanduser("~/Library/Application Support/TriCoreDownloader")
        if os.path.exists(legacy_mac) and not os.path.exists(std_mac):
            return legacy_mac
        return std_mac
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return os.path.join(base, "TriCoreDownloader")


def _files_quickly_match(src, dst):
    try:
        if not os.path.isfile(src) or not os.path.isfile(dst):
            return False
        st_src = os.stat(src)
        st_dst = os.stat(dst)
        if st_src.st_size != st_dst.st_size or st_src.st_size == 0:
            return False
        if int(st_src.st_mtime) == int(st_dst.st_mtime):
            return True
        with open(src, "rb") as f1, open(dst, "rb") as f2:
            if f1.read(65536) != f2.read(65536):
                return False
            if st_src.st_size > 131072:
                f1.seek(-65536, os.SEEK_END)
                f2.seek(-65536, os.SEEK_END)
                if f1.read(65536) != f2.read(65536):
                    return False
        return True
    except Exception:
        return False


def _has_valid_std_stream():
    try:
        return (sys.stdout is not None and hasattr(sys.stdout, "fileno") and sys.stdout.fileno() >= 0)
    except Exception:
        return False


def _relocate_and_relaunch_if_needed():
    is_frozen = getattr(sys, "frozen", False)
    appdata_dir = get_app_dir()

    try:
        old_log = os.path.join(appdata_dir, "updater_debug.log")
        if os.path.isfile(old_log):
            os.remove(old_log)
    except Exception:
        pass

    already_relocated_flag = (
        "--relocated" in sys.argv
        or os.environ.get("TCD_UPDATER_RELOCATED") == "1"
    )

    if is_frozen:
        if sys.platform == "darwin":
            mac_app = get_mac_app_bundle_path(sys.executable)
            if mac_app.endswith(".app"):
                src_target = mac_app
                temp_updater_app = os.path.join(appdata_dir, "TempUpdater.app")
                temp_updater = os.path.join(temp_updater_app, "Contents", "MacOS", os.path.basename(sys.executable))
                is_relocated = already_relocated_flag or (
                    os.path.normcase(mac_app) == os.path.normcase(temp_updater_app)
                )
            else:
                src_target = os.path.abspath(sys.executable)
                temp_updater_app = None
                temp_updater = os.path.join(appdata_dir, "TempUpdater")
                is_relocated = already_relocated_flag or (
                    os.path.normcase(src_target) == os.path.normcase(temp_updater)
                )
        else:
            temp_updater_app = None
            exe_ext = ".exe" if sys.platform == "win32" else ""
            temp_updater = os.path.join(appdata_dir, f"TempUpdater{exe_ext}")

            current_appimage = os.environ.get("APPIMAGE", "")
            orig_appimage = os.environ.get("ORIGINAL_APPIMAGE", "")
            argv0_abs = os.path.abspath(sys.argv[0]) if sys.argv else ""
            exe_abs = os.path.abspath(sys.executable)

            is_relocated = (
                already_relocated_flag
                or (current_appimage and os.path.normcase(os.path.abspath(current_appimage)) == os.path.normcase(temp_updater))
                or (os.path.normcase(exe_abs) == os.path.normcase(temp_updater))
                or (argv0_abs and os.path.normcase(argv0_abs) == os.path.normcase(temp_updater))
                or "tempupdater" in os.path.basename(current_appimage).lower()
                or "tempupdater" in os.path.basename(exe_abs).lower()
                or "tempupdater" in os.path.basename(argv0_abs).lower()
            )

            if orig_appimage and os.path.exists(orig_appimage) and "tempupdater" not in os.path.basename(orig_appimage).lower():
                src_target = os.path.abspath(orig_appimage)
            elif current_appimage and os.path.exists(current_appimage) and "tempupdater" not in os.path.basename(current_appimage).lower():
                src_target = os.path.abspath(current_appimage)
            else:
                src_target = exe_abs
    else:
        temp_updater_app = None
        current_script = os.path.abspath(__file__)
        temp_updater = os.path.join(appdata_dir, "TempUpdater.py")
        is_relocated = (
            already_relocated_flag
            or os.path.normcase(current_script) == os.path.normcase(temp_updater)
            or "tempupdater" in os.path.basename(current_script).lower()
        )
        src_target = current_script

    if is_relocated:
        _tlog(f"Running in relocated mode (PID={os.getpid()}, target={temp_updater})")
        return

    _tlog(f"Preparing standalone updater relocation from '{src_target}' to '{temp_updater}'...")
    try:
        os.makedirs(appdata_dir, exist_ok=True)

        if sys.platform == "darwin" and is_frozen and src_target.endswith(".app"):
            if os.path.exists(temp_updater_app):
                shutil.rmtree(temp_updater_app, ignore_errors=True)
            subprocess.run(["ditto", src_target, temp_updater_app], check=True)
        else:
            if not _files_quickly_match(src_target, temp_updater):
                tmp_temp_updater = f"{temp_updater}.{os.getpid()}.tmp"
                shutil.copy2(src_target, tmp_temp_updater)
                if sys.platform != "win32":
                    try:
                        st = os.stat(tmp_temp_updater)
                        os.chmod(tmp_temp_updater, st.st_mode | stat.S_IEXEC | 0o755)
                    except Exception:
                        pass
                os.replace(tmp_temp_updater, temp_updater)
            elif sys.platform != "win32":
                try:
                    st = os.stat(temp_updater)
                    if not (st.st_mode & stat.S_IEXEC):
                        os.chmod(temp_updater, st.st_mode | stat.S_IEXEC | 0o755)
                except Exception:
                    pass

        passed_args = [a for a in sys.argv[1:] if a not in ("--updater", "--relocated")]

        if is_frozen:
            args = [temp_updater, "--updater", "--relocated"]
        else:
            args = [sys.executable, temp_updater, "--relocated"]

        if "--install-dir" not in passed_args:
            inst_dir = src_target if (sys.platform == "darwin" and is_frozen and src_target.endswith(".app")) else os.path.dirname(src_target)
            args.extend(["--install-dir", inst_dir])

        if "--original-target" not in passed_args:
            if not is_frozen:
                main_candidate = os.path.join(os.path.dirname(src_target), "run_TriCoreDownloader.py")
                original_entry = main_candidate if os.path.exists(main_candidate) else src_target
            else:
                original_entry = src_target
            args.extend(["--original-target", original_entry])

        args.extend(passed_args)

        clean_env = os.environ.copy()
        for var in (
            "_MEIPASS", "_MEIPASS2", "APPDIR", "APPIMAGE", "OWD", "ARGV0",
            "LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH",
            "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"
        ):
            clean_env.pop(var, None)

        clean_env["TCD_UPDATER_RELOCATED"] = "1"
        if sys.platform.startswith("linux"):
            clean_env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
            if is_frozen and "tempupdater" not in os.path.basename(src_target).lower():
                clean_env["ORIGINAL_APPIMAGE"] = src_target

        has_tty = _has_valid_std_stream()
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "env": clean_env,
            "cwd": os.path.expanduser("~"),
        }
        if not has_tty:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL

        if sys.platform == "win32":
            if not has_tty:
                kwargs["creationflags"] = 0x00000008 | 0x00000200
            elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
            kwargs["close_fds"] = True

        if sys.platform != "win32" and os.path.exists(temp_updater):
            try:
                st = os.stat(temp_updater)
                os.chmod(temp_updater, st.st_mode | stat.S_IEXEC | 0o755)
            except Exception:
                pass

        _tlog(f"Launching relocated updater process: {' '.join(args)}")
        proc = subprocess.Popen(args, **kwargs)

        alive = False
        for _ in range(15):
            time.sleep(0.1)
            if proc.poll() is not None:
                break
        else:
            alive = True

        if not alive and is_frozen and sys.platform.startswith("linux"):
            _tlog(f"Relocated AppImage exited early (code={proc.returncode}), retrying with APPIMAGE_EXTRACT_AND_RUN=1...", "WARN")
            clean_env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
            kwargs["env"] = clean_env
            proc = subprocess.Popen(args, **kwargs)
            for _ in range(8):
                time.sleep(0.05)
                if proc.poll() is not None:
                    break
            else:
                alive = True

        if alive:
            _tlog(f"Relocated process active (PID={proc.pid}). Handing over control.")
            os._exit(0)
        else:
            _tlog(f"Relocated process exited prematurely (code={proc.returncode}). Continuing in current process.", "WARN")
    except Exception as e:
        _tlog(f"Relocation skipped due to error ({e}). Continuing in current process.", "WARN")


if __name__ == "__main__" or "--updater" in sys.argv:
    _relocate_and_relaunch_if_needed()


_SSL_CTX_CACHE = None


def _get_verified_ssl_context():
    global _SSL_CTX_CACHE
    if _SSL_CTX_CACHE is not None:
        return _SSL_CTX_CACHE
    try:
        import certifi
        _SSL_CTX_CACHE = ssl.create_default_context(cafile=certifi.where())
        return _SSL_CTX_CACHE
    except Exception:
        pass
    try:
        _SSL_CTX_CACHE = ssl.create_default_context()
        return _SSL_CTX_CACHE
    except Exception:
        _SSL_CTX_CACHE = ssl._create_unverified_context()
        return _SSL_CTX_CACHE


def urlopen_safe(req, timeout=10):
    ctx = _get_verified_ssl_context()
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            _tlog(f"SSL verification failed ({e.reason}), falling back to unverified SSL context.", "WARN")
            unverified_ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=timeout, context=unverified_ctx)
        raise
    except ssl.SSLError as e:
        _tlog(f"Direct SSL error ({e}), falling back to unverified SSL context.", "WARN")
        unverified_ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=unverified_ctx)


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFrame,
    QMessageBox, QCheckBox, QSizePolicy,
    QGraphicsOpacityEffect, QTextEdit, QProgressBar, QMenu,
    QDialog
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QByteArray,
    QPropertyAnimation, QAbstractAnimation, QPoint, QSize,
    QEasingCurve, QParallelAnimationGroup
)
from PyQt6.QtGui import QIcon, QPixmap, QTextOption, QAction

try:
    import darkdetect
except ImportError:
    darkdetect = None


def _compute_file_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(131072)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_expected_sha256(release_dict, asset_dict):
    if isinstance(asset_dict, dict):
        digest_val = str(asset_dict.get("digest", "")).strip().lower()
        if digest_val.startswith("sha256:") and len(digest_val) == 71:
            return digest_val.split(":", 1)[1]

        asset_name = str(asset_dict.get("name", "")).strip()
        if asset_name and isinstance(release_dict, dict):
            body = str(release_dict.get("body", "") or "")
            for match in RE_SHA256_LINE.finditer(body):
                hash_hex, fname = match.group(1).lower(), os.path.basename(match.group(2).strip())
                if fname.lower() == asset_name.lower():
                    return hash_hex
    return ""


def _force_rm_readonly(action, name, exc):
    try:
        os.chmod(name, stat.S_IWRITE | 0o700)
        if os.path.isdir(name):
            os.rmdir(name)
        else:
            os.remove(name)
    except Exception:
        pass


def resolve_mac_target_app(original_target=None, install_dir=None):
    candidates = []
    if original_target:
        cand = get_mac_app_bundle_path(original_target)
        if (
            cand.endswith(".app")
            and "tempupdater" not in os.path.basename(cand).lower()
            and not cand.startswith("/Volumes/")
        ):
            candidates.append(cand)
    if install_dir:
        cand = get_mac_app_bundle_path(install_dir)
        if (
            cand.endswith(".app")
            and "tempupdater" not in os.path.basename(cand).lower()
            and not cand.startswith("/Volumes/")
        ):
            candidates.append(cand)
        elif os.path.isdir(install_dir) and not install_dir.startswith("/Volumes/"):
            app_in_dir = os.path.join(install_dir, "TriCoreDownloader.app")
            candidates.append(app_in_dir)

    candidates.append("/Applications/TriCoreDownloader.app")
    candidates.append(os.path.expanduser("~/Applications/TriCoreDownloader.app"))

    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return "/Applications/TriCoreDownloader.app"


def detect_system_language():
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleLanguages"],
                text=True,
                timeout=1,
                stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                clean = line.strip().strip('",();')
                if clean:
                    return "FR" if clean[:2].lower() == "fr" else "EN"
        elif os.name == 'nt':
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            sys_lang_raw = locale.windows_locale.get(lang_id, "")
            return "FR" if sys_lang_raw.lower().startswith("fr") else "EN"
        else:
            sys_lang_raw = (
                os.environ.get("LC_ALL")
                or os.environ.get("LC_MESSAGES")
                or os.environ.get("LANG")
                or ""
            )
            if not sys_lang_raw or sys_lang_raw == "C":
                loc_val, _ = locale.getlocale()
                sys_lang_raw = loc_val or ""
            return "FR" if sys_lang_raw.lower().startswith("fr") else "EN"
    except Exception:
        return "EN"
    return "EN"


def _is_arm64_arch_string(arch_str: str) -> bool:
    clean = (arch_str or "").strip().lower()
    return clean.startswith("arm64") or clean.startswith("aarch64")


def _is_macos_apple_silicon() -> bool:
    machine = (platform.machine() or "").strip().lower()
    if _is_arm64_arch_string(machine):
        return True

    if hasattr(os, "uname"):
        try:
            if _is_arm64_arch_string(os.uname().machine):
                return True
        except Exception:
            pass

    if sys.platform == "darwin":
        for sysctl_key in ("hw.optional.arm64", "sysctl.proc_translated"):
            try:
                res = subprocess.run(
                    ["sysctl", "-n", sysctl_key],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1,
                )
                if res.stdout.strip() == "1":
                    return True
            except Exception:
                pass

    return False


def is_tricoredownloader_running(target_file=None):
    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else -1
    ignored_pids = {current_pid, parent_pid}

    if sys.platform == "win32":
        if target_file and os.path.exists(target_file) and target_file.lower().endswith(".exe"):
            try:
                with open(target_file, "r+b"):
                    pass
            except PermissionError:
                return True
            except OSError as e:
                if e.errno in (errno.EACCES, errno.EPERM):
                    return True

        try:
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                text=True,
                timeout=2,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000
            )
            for line in out.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    proc_name = parts[0].lower()
                    try:
                        proc_pid = int(parts[1])
                    except ValueError:
                        continue
                    if proc_pid in ignored_pids:
                        continue
                    if "tricoredownloader" in proc_name and "updater" not in proc_name:
                        return True
        except Exception:
            pass
        return False

    elif sys.platform.startswith("linux"):
        if target_file and os.path.exists(target_file) and not target_file.lower().endswith(".py"):
            try:
                with open(target_file, "r+b"):
                    pass
            except OSError as e:
                if e.errno == errno.ETXTBSY:
                    return True

        if os.path.isdir("/proc"):
            try:
                for entry in os.listdir("/proc"):
                    if not entry.isdigit():
                        continue
                    pid = int(entry)
                    if pid in ignored_pids:
                        continue
                    try:
                        with open(f"/proc/{pid}/cmdline", "rb") as f:
                            raw_cmd = f.read().replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip().lower()
                    except Exception:
                        continue
                    if not raw_cmd:
                        continue
                    if "tempupdater" in raw_cmd or "updater.py" in raw_cmd or "--updater" in raw_cmd or "--relocated" in raw_cmd:
                        continue
                    if "run_tricoredownloader.py" in raw_cmd or ("tricoredownloader" in raw_cmd and "updater" not in raw_cmd):
                        return True
                return False
            except Exception:
                pass

        try:
            out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, timeout=2, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                if pid in ignored_pids:
                    continue
                cmd = parts[1].lower()
                if "tempupdater" in cmd or "updater.py" in cmd or "--updater" in cmd or "--relocated" in cmd:
                    continue
                if "run_tricoredownloader.py" in cmd or ("tricoredownloader" in cmd and "updater" not in cmd):
                    return True
        except Exception:
            pass
        return False

    elif sys.platform == "darwin":
        target_norm = os.path.abspath(target_file).lower() if target_file else ""
        try:
            out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True, timeout=2, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                if pid in ignored_pids:
                    continue
                cmd = parts[1].lower()
                if "tempupdater" in cmd or "updater.py" in cmd or "--updater" in cmd or "--relocated" in cmd:
                    continue
                if target_norm and target_norm in cmd:
                    return True
                if "tricoredownloader.app/contents/macos" in cmd or "run_tricoredownloader.py" in cmd:
                    return True
        except Exception:
            pass
        return False

    return False


def wait_for_main_app_exit(target_file=None, timeout=3.5):
    if not is_tricoredownloader_running(target_file):
        return True
    _tlog("Waiting for main TriCoreDownloader instance to close...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_tricoredownloader_running(target_file):
            _tlog("Main TriCoreDownloader instance is now closed.")
            return True
        time.sleep(0.15)
    still_running = is_tricoredownloader_running(target_file)
    if still_running:
        _tlog("Main TriCoreDownloader instance is still running after timeout!", "WARN")
    return not still_running


def _resolve_app_version():
    try:
        from TriCoreDownloader.config import APP_VERSION as cfg_ver
        if cfg_ver:
            return str(cfg_ver).strip()
    except Exception:
        pass

    search_roots = [base_script_dir, os.getcwd()]
    if "--install-dir" in sys.argv:
        try:
            idx = sys.argv.index("--install-dir")
            search_roots.insert(0, os.path.abspath(sys.argv[idx + 1]))
        except IndexError:
            pass

    for root in search_roots:
        cfg_file = os.path.join(root, "TriCoreDownloader", "config.py")
        if os.path.isfile(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    m = RE_APP_VERSION.search(f.read())
                    if m and m.group(1).strip():
                        return m.group(1).strip()
            except Exception:
                pass
    return "1.1.0"


APP_VERSION = _resolve_app_version()

if sys.platform == "darwin":
    BASE_FONT = "\".AppleSystemUIFont\", \"Helvetica Neue\", sans-serif"
    FS_BASE = "11pt"
    FS_TITLE = "13.5pt"
    FS_DIM = "9.5pt"
    FS_BADGE = "9pt"
    FS_BTN_EXEC = "11.5pt"
elif sys.platform == "win32":
    BASE_FONT = "\"Segoe UI Variable\", \"Segoe UI\", \"Roboto\", sans-serif"
    FS_BASE = "10pt"
    FS_TITLE = "13pt"
    FS_DIM = "9pt"
    FS_BADGE = "8.5pt"
    FS_BTN_EXEC = "11pt"
else:
    BASE_FONT = "\"Noto Sans\", \"Ubuntu\", \"DejaVu Sans\", sans-serif"
    FS_BASE = "9pt"
    FS_TITLE = "11.5pt"
    FS_DIM = "8pt"
    FS_BADGE = "8pt"
    FS_BTN_EXEC = "10pt"

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

LOCALES = {
    "FR": {
        "window_title": "TriCoreDownloader Updater",
        "card_title": "TriCoreDownloader Updater 2.0.1",
        "current_version": "Version actuelle de votre TriCoreDownloader : {}",
        "env_badge_format": "{os} ({arch}) • {mode}",
        "env_mode_compiled": "Version compilée",
        "env_mode_source": "Code source",
        "env_unknown": "Inconnu",
        "env_tooltip_click": "Cliquez pour modifier manuellement le système / type de version cible",
        "env_prompt_title": "Système ou environnement non reconnu",
        "env_prompt_desc": "Un ou plusieurs éléments de votre environnement ({detected}) n'ont pas pu être reconnus automatiquement.\n\nVeuillez sélectionner quelle version correspond à votre système d'exploitation :",
        "env_opt_win_x64": "Windows (x64) • Version compilée (.exe)",
        "env_opt_linux_x64": "Linux (x86_64) • Version compilée (.AppImage)",
        "env_opt_mac_arm64": "macOS (arm64 / Apple Silicon) • Version compilée (.dmg)",
        "env_opt_mac_x64": "macOS (x64 / Intel) • Version compilée (.dmg)",
        "env_opt_source": "Code source Python brut • Multiplateforme (.zip / .7z)",
        "btn_confirm_env": "Confirmer",
        "beta_checkbox": "Inclure la branche main [non recommandé]",
        "checking_versions": "Recherche des versions disponibles...",
        "select_release": "Sélectionnez une version :",
        "refreshing_data": "Actualisation des données depuis GitHub...",
        "auto_reinstall": "Réinstallation automatique lancée...",
        "auto_reinstall_beta": "Réinstallation automatique (bêta) lancée...",
        "no_releases": "Aucune version publique trouvée ?",
        "api_error": "Erreur de connexion API : {}",
        "api_error_403": "GitHub est temporairement indisponible (limite de requêtes atteinte).<br>Vous pouvez télécharger directement la version depuis : <a href='https://github.com/JeremKOYTB/TriCoreDownloader/releases' style='color:{accent};'>GitHub Releases</a>",
        "btn_install": "Installer",
        "btn_reinstall": "Réinstaller la version actuelle",
        "btn_beta": "Installer la version bêta",
        "btn_cant_install": "Impossible d'installer cette version",
        "btn_not_available_exe": "Non disponible en exécutable",
        "tag_cant_install": " [Impossible d'installer cette version]",
        "tag_source_only": " [Code source uniquement]",
        "warn_main_on_frozen": "La branche main ne fournit que le code source Python brut. Les exécutables autonomes ne peuvent pas se mettre à jour directement depuis le code source.",
        "warn_incompatible_version": "⚠️ Cette version ne fournit pas de livrable compatible avec votre système ({env}).",
        "warn_090": "⚠️ ATTENTION : La structure de l'archive 0.9.0 est incompatible avec cet updater.",
        "warn_dev": "ATTENTION : Ces versions sont en cours de développement. La fiabilité peut être réduite.",
        "warn_prerelease": "ATTENTION : Cette version préliminaire est en cours d'évaluation. La fiabilité peut être réduite.",
        "err_fetch_main": "Échec de récupération des métadonnées de la branche main : {}",
        "fetching_commit": "Récupération du dernier commit sur GitHub...",
        "latest_commit": "Dernier commit Main :",
        "commit_date": "Date :",
        "commit_notes": "Notes de modification :",
        "err_commit_api": "Échec de connexion à l'API des commits : {}",
        "no_changelog": "Aucun changelog fourni.",
        "btn_cancel": "Annuler",
        "asset_incompatible_title": "Livrable incompatible",
        "asset_incompatible_desc": "Sécurité : Aucun livrable adapté à votre environnement n'a été trouvé dans cette version.",
        "loading_7z": "Chargement des modules d'extraction 7z...",
        "downloading_update": "Téléchargement de la mise à jour...",
        "downloading_pct": "Téléchargement... ({}%)",
        "downloading_stats": "Téléchargement... {pct}% ({dl:.1f} / {tot:.1f} Mo • {spd:.1f} Mo/s)",
        "replacing_binary": "Remplacement du fichier exécutable...",
        "extracting_files": "Extraction des fichiers...",
        "analyzing_arch": "Analyse de la structure...",
        "mounting_dmg": "Montage de l'image disque macOS...",
        "err_no_exe_in_archive": "Sécurité : Aucun exécutable compilé compatible n'a été trouvé dans cette archive.",
        "err_no_vital_files": "Sécurité : Ni 'run_TriCoreDownloader.py' ni aucun exécutable n'ont été trouvés.",
        "cleaning_old": "Nettoyage des anciens fichiers...",
        "cleaning_cache": "Nettoyage du cache (__pycache__, fichiers temporaires)...",
        "installing_new": "Installation des nouveaux fichiers...",
        "verifying_install": "Vérification du remplacement et de l'intégrité SHA-256...",
        "err_verify_failed": "Échec de vérification : L'ancien fichier n'a pas pu être remplacé correctement ({0}).",
        "err_sha256_mismatch": "Sécurité : Le hash SHA-256 du fichier téléchargé ne correspond pas à celui publié sur GitHub ({0}).",
        "update_success": "Mise à jour installée et vérifiée avec succès.",
        "complete": "Terminé.",
        "success_title": "Succès :",
        "success_desc": "TriCoreDownloader a été mis à jour et vérifié avec succès.\n\nCliquez sur OK pour relancer la nouvelle version.",
        "install_failed_title": "Échec de l'installation...",
        "critical_err": "Erreur critique d'exécution :\n{}",
        "cancel_dialog_title": "Annuler la mise à jour",
        "cancel_dialog_desc": "Voulez-vous retourner à TriCoreDownloader ({}) ou quitter complètement ?",
        "btn_return": "Retourner à TriCoreDownloader",
        "btn_exit": "Quitter",
        "btn_stay": "Rester ici",
        "err_permission_denied": "Permissions insuffisantes : Impossible d'écrire dans le dossier d'installation ({0}). Veuillez vérifier vos droits d'accès.",
        "err_app_running_title": "Application ouverte",
        "err_app_running_desc": "TriCoreDownloader est actuellement en cours d'exécution.\n\nVeuillez fermer l'application avant de continuer la mise à jour.",
        "err_dmg_corrupt": "L'image disque DMG est corrompue (TriCoreDownloader.app est introuvable à l'intérieur).",
        "err_not_in_applications": "Échec de la mise à jour : TriCoreDownloader.app est introuvable dans le dossier cible.",
        "confirm_target_title": "Confirmation de l'emplacement",
        "confirm_target_desc_linux": "Est-ce bien cette AppImage qu'il faut remplacer ?\n\nChemin cible :\n{0}",
        "confirm_target_desc_win": "Est-ce bien cet exécutable qu'il faut remplacer ?\n\nChemin cible :\n{0}",
        "confirm_target_desc_mac": "Est-ce bien cette application qu'il faut remplacer ?\n\nChemin cible :\n{0}"
    },
    "EN": {
        "window_title": "TriCoreDownloader Updater",
        "card_title": "TriCoreDownloader Updater 2.0.1",
        "current_version": "Current version of your TriCoreDownloader: {}",
        "env_badge_format": "{os} ({arch}) • {mode}",
        "env_mode_compiled": "Compiled build",
        "env_mode_source": "Source code",
        "env_unknown": "Unknown",
        "env_tooltip_click": "Click to manually change target OS / build type",
        "env_prompt_title": "Unrecognized System or Environment",
        "env_prompt_desc": "One or more elements of your environment ({detected}) could not be automatically recognized.\n\nPlease select which version corresponds to your operating system:",
        "env_opt_win_x64": "Windows (x64) • Compiled executable (.exe)",
        "env_opt_linux_x64": "Linux (x86_64) • Compiled executable (.AppImage)",
        "env_opt_mac_arm64": "macOS (arm64 / Apple Silicon) • Compiled app (.dmg)",
        "env_opt_mac_x64": "macOS (x64 / Intel) • Compiled app (.dmg)",
        "env_opt_source": "Raw Python source code • Multiplatform (.zip / .7z)",
        "btn_confirm_env": "Confirm",
        "beta_checkbox": "Include main branch [not recommended]",
        "checking_versions": "Checking available TriCoreDownloader versions...",
        "select_release": "Select a release:",
        "refreshing_data": "Refreshing data from GitHub...",
        "auto_reinstall": "Automatic reinstallation triggered...",
        "auto_reinstall_beta": "Automatic reinstallation (beta) triggered...",
        "no_releases": "No public release distributions found?",
        "api_error": "API Connection Error: {}",
        "api_error_403": "GitHub is temporarily unavailable (rate limit exceeded).<br>You can directly download updates here: <a href='https://github.com/JeremKOYTB/TriCoreDownloader/releases' style='color:{accent};'>GitHub Releases</a>",
        "btn_install": "Install",
        "btn_reinstall": "Reinstall Current Version",
        "btn_beta": "Install Beta Build",
        "btn_cant_install": "Can't install this version",
        "btn_not_available_exe": "Not available as an executable",
        "tag_cant_install": " [Can't install this version]",
        "tag_source_only": " [Source only]",
        "warn_main_on_frozen": "The main branch only provides raw Python source code. Standalone executables cannot update directly from source code.",
        "warn_incompatible_version": "⚠️ This version does not provide a compatible build for your system ({env}).",
        "warn_090": "⚠️ WARNING: The structure of the 0.9.0 archive is incompatible with this updater.",
        "warn_dev": "WARNING: These versions are actively under development. Reliability might be lower.",
        "warn_prerelease": "WARNING: This pre-release build is nearly complete, but remains actively under evaluation.",
        "err_fetch_main": "Failed to fetch main branch metadata: {}",
        "fetching_commit": "Fetching latest commit data from GitHub...",
        "latest_commit": "Latest Main Commit:",
        "commit_date": "Date:",
        "commit_notes": "Modification Notes:",
        "err_commit_api": "Failed to reach main branch commit API endpoint: {}",
        "no_changelog": "No changelog provided.",
        "btn_cancel": "Cancel",
        "asset_incompatible_title": "Asset Incompatible",
        "asset_incompatible_desc": "Security: No valid asset suitable for your environment was found in this release.",
        "loading_7z": "Loading 7z extraction modules...",
        "downloading_update": "Downloading update...",
        "downloading_pct": "Downloading... ({}%)",
        "downloading_stats": "Downloading... {pct}% ({dl:.1f} / {tot:.1f} MB • {spd:.1f} MB/s)",
        "replacing_binary": "Replacing executable binary...",
        "extracting_files": "Extracting files...",
        "analyzing_arch": "Analyzing architecture...",
        "mounting_dmg": "Mounting macOS disk image...",
        "err_no_exe_in_archive": "Security: No compatible compiled executable was found in this archive.",
        "err_no_vital_files": "Security: Neither 'run_TriCoreDownloader.py' nor an executable was found in the archive.",
        "cleaning_old": "Cleaning up old files...",
        "cleaning_cache": "Cleaning cache (__pycache__, temporary files)...",
        "installing_new": "Installing new files...",
        "verifying_install": "Verifying replacement and SHA-256 integrity...",
        "err_verify_failed": "Verification failed: The old file could not be properly replaced ({0}).",
        "err_sha256_mismatch": "Security: Downloaded file SHA-256 hash does not match the official GitHub release hash ({0}).",
        "update_success": "Update installed and verified successfully.",
        "complete": "Complete.",
        "success_title": "Success:",
        "success_desc": "TriCoreDownloader has been updated and verified successfully.\n\nPress OK to reload the new version.",
        "install_failed_title": "Installation Failed...",
        "critical_err": "Critical execution error:\n{}",
        "cancel_dialog_title": "Cancel Update",
        "cancel_dialog_desc": "Do you want to return to TriCoreDownloader ({}) or exit completely?",
        "btn_return": "Return to TriCoreDownloader",
        "btn_exit": "Exit",
        "btn_stay": "Stay here",
        "err_permission_denied": "Insufficient permissions: Cannot write to installation directory ({0}). Please check your permissions.",
        "err_app_running_title": "Application Running",
        "err_app_running_desc": "TriCoreDownloader is currently running.\n\nPlease close the application before proceeding with the update.",
        "err_dmg_corrupt": "The DMG disk image is corrupted (TriCoreDownloader.app was not found inside).",
        "err_not_in_applications": "Update failed: TriCoreDownloader.app was not found in the target folder.",
        "confirm_target_title": "Confirm Target Location",
        "confirm_target_desc_linux": "Are you sure this is the AppImage to replace?\n\nTarget path:\n{0}",
        "confirm_target_desc_win": "Are you sure this is the executable to replace?\n\nTarget path:\n{0}",
        "confirm_target_desc_mac": "Are you sure this is the application to replace?\n\nTarget path:\n{0}"
    }
}


def find_compatible_asset(release, is_frozen=False, env_profile=None):
    if not isinstance(release, dict):
        return None, False

    effective_source = (env_profile == "source") or (env_profile is None and not is_frozen)

    if release.get("is_main_branch_node", False):
        if not effective_source:
            return None, False
        return release.get("zipball_url"), False

    assets = release.get("assets", [])

    if effective_source:
        os_keywords = (
            "win", "windows", "mac", "macos", "darwin", "linux",
            "appimage", ".exe", ".dmg", "x64", "x86_64", "arm64", "aarch64", "intel", "apple", "silicon"
        )
        for asset in assets:
            name = asset.get("name", "").lower()
            if name in ("tricoredownloader.zip", "tricoredownloader.7z"):
                return asset, False
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith((".zip", ".7z")):
                if not any(kw in name for kw in os_keywords):
                    return asset, False
        return None, False

    if env_profile is None:
        sys_plat = sys.platform.lower()
        if sys_plat == "darwin":
            env_profile = "macos_arm64" if _is_macos_apple_silicon() else "macos_x64"
        elif sys_plat == "win32":
            env_profile = "win_x64"
        elif "linux" in sys_plat:
            env_profile = "linux_x86_64"

    if env_profile in ("macos_arm64", "macos_x64"):
        want_arm = (env_profile == "macos_arm64")
        exact_target = "tricoredownloader_macos_arm64.dmg" if want_arm else "tricoredownloader_macos_x64.dmg"
        for asset in assets:
            if asset.get("name", "").lower() == exact_target:
                return asset, False
        for asset in assets:
            name = asset.get("name", "").lower()
            if not name.endswith(".dmg"):
                continue
            if want_arm and ("arm64" in name or "aarch64" in name or "silicon" in name or "apple" in name):
                return asset, False
            if not want_arm and ("x64" in name or "x86_64" in name or "intel" in name):
                return asset, False
        return None, False

    elif env_profile == "win_x64":
        for asset in assets:
            if asset.get("name", "").lower() == "tricoredownloader_windows_x64.exe":
                return asset, True
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".exe") and "updater" not in name:
                return asset, True
        return None, False

    elif env_profile == "linux_x86_64":
        for asset in assets:
            if asset.get("name", "").lower() == "tricoredownloader_linux_x86_64.appimage":
                return asset, True
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".appimage") and "updater" not in name:
                return asset, True
        return None, False

    return None, False


def check_directory_permissions(target_dir):
    try:
        check_path = os.path.abspath(target_dir)
        while not os.path.exists(check_path):
            parent = os.path.dirname(check_path)
            if parent == check_path:
                break
            check_path = parent

        if not os.access(check_path, os.W_OK | os.X_OK):
            return False

        probe_file = os.path.join(check_path, f".perm_probe_{os.getpid()}_{int(time.time())}.tmp")
        with open(probe_file, "wb") as f:
            f.write(b"probe")
        if os.path.exists(probe_file):
            os.remove(probe_file)
        return True
    except Exception as e:
        _tlog(f"Directory permission check failed for '{target_dir}': {e}", "WARN")
        return False


def load_tricore_config():
    config_path = os.path.join(get_app_dir(), 'config.json')
    cfg = {
        "theme": "dark",
        "console_mode": "NX",
        "accent_color": "",
        "rainbow_mode": False,
        "rainbow_speed": 2,
        "lang": ""
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k in cfg:
                    if k in data:
                        cfg[k] = data[k]
        except Exception as e:
            _tlog(f"Failed to read config.json: {e}", "WARN")

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
    QWidget {{ font-family: {BASE_FONT}; font-size: {FS_BASE}; }}
    QLabel {{ color: {c['text']}; }}
    QFrame#Card {{ background-color: {c['card']}; border-radius: 8px; border: 1px solid {c['border']}; }}
    QLabel#CardTitle {{ color: {c['text_title']}; font-size: {FS_TITLE}; font-weight: 700; }}
    QLabel#CardVersion {{ color: {c['text_dim']}; font-size: {FS_DIM}; font-weight: 500; }}
    QPushButton#EnvInfoBadge {{
        background-color: {c['bg_input']};
        color: {c['text_dim']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 4px 10px;
        font-size: {FS_BADGE};
        font-weight: 600;
        min-height: 20px;
    }}
    QPushButton#EnvInfoBadge:hover {{
        background-color: {c['border_hover']};
        color: {c['text_title']};
        border: 1px solid {accent_color};
    }}

    QPushButton#ConsoleSelector {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 14px;
        color: {c['text']};
        text-align: left;
        font-weight: 600;
        font-size: {FS_BASE};
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
        icon-size: 24px;
    }}
    QMenu#ConsoleCustomMenu::item {{
        padding: 8px 16px;
        color: {c['text']};
        border-radius: 6px;
        font-size: {FS_BASE};
        font-weight: 500;
        min-height: 24px;
    }}
    QMenu#ConsoleCustomMenu::item:selected {{
        background-color: {c['card']};
        color: {c['text_title']};
    }}

    QCheckBox {{ color: {c['text']}; outline: none; font-size: {FS_BASE}; padding: 2px; }}
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
        font-size: {FS_BTN_EXEC};
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
        self.setIconSize(QSize(24, 24))

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
             (28 if (item['icon'] and not item['icon'].isNull()) else 0) + 40)
            for item in self.items
        )
        if max_w > 0:
            self.setMinimumWidth(min(max_w, 480))

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
        action.setIconVisibleInMenu(True)

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
        action.setIconVisibleInMenu(True)
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
                lbl_icon.setPixmap(new_item['icon'].pixmap(QSize(24, 24)))
                lay.addWidget(lbl_icon)

            lbl_text = QLabel(new_item['text'])
            lbl_text.setStyleSheet(f"font-size: {FS_BASE}; font-weight: 600;")
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


class EnvironmentSelectDialog(QDialog):
    def __init__(self, parent, detected_str, current_profile=None):
        super().__init__(parent)
        self.parent_win = parent
        self.T = parent.T
        self.selected_profile = None

        self.setWindowTitle(self.T("env_prompt_title"))
        self.setModal(True)
        self.setMinimumWidth(520)
        if sys.platform != "darwin" and hasattr(parent, "get_app_icon"):
            self.setWindowIcon(parent.get_app_icon())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)

        lbl_desc = QLabel(self.T("env_prompt_desc").format(detected=detected_str), self)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"font-size: {FS_BASE}; line-height: 1.4;")
        layout.addWidget(lbl_desc)

        self.combo_env = CustomConsoleSelector(self)
        self.combo_env.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        options = [
            ("win_x64", self.T("env_opt_win_x64")),
            ("linux_x86_64", self.T("env_opt_linux_x64")),
            ("macos_arm64", self.T("env_opt_mac_arm64")),
            ("macos_x64", self.T("env_opt_mac_x64")),
            ("source", self.T("env_opt_source")),
        ]

        default_idx = 0
        for i, (code, label) in enumerate(options):
            self.combo_env.addItem(label, code)
            if current_profile and code == current_profile:
                default_idx = i

        if not current_profile:
            if not getattr(sys, "frozen", False):
                default_idx = 4
            elif sys.platform == "win32":
                default_idx = 0
            elif sys.platform.startswith("linux"):
                default_idx = 1
            elif sys.platform == "darwin":
                default_idx = 2 if _is_macos_apple_silicon() else 3

        self.combo_env.blockSignals(True)
        self.combo_env.setCurrentIndex(default_idx)
        self.combo_env.blockSignals(False)
        layout.addWidget(self.combo_env)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        self.btn_confirm = QPushButton(self.T("btn_confirm_env"), self)
        self.btn_confirm.setObjectName("btnExecute")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setMinimumWidth(140)
        self.btn_confirm.clicked.connect(self._on_confirm)

        btn_layout.addWidget(self.btn_confirm)
        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)

    def _on_confirm(self):
        self.selected_profile = self.combo_env.currentData()
        self.accept()


class ReleasesFetchThread(QThread):
    finished = pyqtSignal(list, str)

    def _fetch_releases_fallback_html(self):
        try:
            _tlog("Attempting GitHub Web fallback for latest release...")
            req = urllib.request.Request(
                "https://github.com/JeremKOYTB/TriCoreDownloader/releases/latest",
                headers={'User-Agent': 'TriCoreDownloader-Updater'}
            )
            with urlopen_safe(req, timeout=10) as resp:
                final_url = resp.geturl()
            if "/tag/" in final_url:
                tag = final_url.rstrip("/").split("/tag/")[-1]
                base_dl = f"https://github.com/JeremKOYTB/TriCoreDownloader/releases/download/{tag}"
                asset_names = [
                    "TriCoreDownloader_Windows_x64.exe",
                    "TriCoreDownloader_Linux_x86_64.AppImage",
                    "TriCoreDownloader_macOS_arm64.dmg",
                    "TriCoreDownloader_macOS_x64.dmg",
                    "TriCoreDownloader.zip",
                    "TriCoreDownloader.7z",
                ]
                assets = [
                    {"name": n, "browser_download_url": f"{base_dl}/{n}"}
                    for n in asset_names
                ]
                _tlog(f"Fallback resolved latest tag: {tag}")
                return [{
                    "tag_name": tag,
                    "prerelease": False,
                    "body": f"Release {tag} (GitHub Web Fallback)",
                    "assets": assets,
                }]
        except Exception as e:
            _tlog(f"GitHub Web fallback failed: {e}", "WARN")
        return []

    def run(self):
        url = f"https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/releases?t={int(time.time())}"
        _tlog("Fetching available releases from GitHub API...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urlopen_safe(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            _tlog(f"Fetched {len(data) if isinstance(data, list) else 0} releases from GitHub API.")
            self.finished.emit(data, "")
        except urllib.error.HTTPError as e:
            _tlog(f"GitHub API HTTP error: {e.code}", "WARN")
            if e.code == 403:
                fallback = self._fetch_releases_fallback_html()
                if fallback:
                    self.finished.emit(fallback, "")
                else:
                    self.finished.emit([], "HTTP 403")
            else:
                self.finished.emit([], str(e))
        except Exception as e:
            _tlog(f"Failed to fetch releases: {e}", "ERROR")
            self.finished.emit([], str(e))


class DownloadWorkerThread(QThread):
    progress = pyqtSignal(str)
    progress_val = pyqtSignal(int)
    completed = pyqtSignal(bool, str)

    def __init__(
        self,
        download_url,
        install_dir,
        target_version,
        is_direct_binary=False,
        asset_name="",
        lang="EN",
        custom_dst_file="",
        env_profile=None,
        expected_sha256="",
    ):
        super().__init__()
        self.download_url = download_url
        self.env_profile = env_profile
        self.expected_sha256 = (expected_sha256 or "").strip().lower()
        self.is_frozen = (env_profile != "source") if env_profile else getattr(sys, "frozen", False)
        if (sys.platform == "darwin" or env_profile in ("macos_arm64", "macos_x64")) and self.is_frozen and ".app" in install_dir:
            self.install_dir = get_mac_app_bundle_path(install_dir)
        else:
            self.install_dir = os.path.abspath(install_dir)
        self.target_version = target_version
        self.is_direct_binary = is_direct_binary
        self.asset_name = asset_name
        self.lang = lang
        self.custom_dst_file = custom_dst_file
        self.installed_target_path = ""
        self.is_7z = download_url.lower().endswith(".7z") or asset_name.lower().endswith(".7z")
        self.is_dmg = download_url.lower().endswith(".dmg") or asset_name.lower().endswith(".dmg")
        self.skip_updater = self.target_version in ["0.9.0", "0.9.0.1", "0.9.0.2", "0.9.0.3", "0.9.0.4", "0.9.0.5"]

    def T(self, key):
        return LOCALES.get(self.lang, LOCALES["EN"]).get(key, key)

    def _purge_caches(self, root_dir=None):
        _tlog("Cleaning temporary files and caches...")
        self.progress.emit(self.T("cleaning_cache"))
        target_root = os.path.abspath(root_dir or self.install_dir)

        if os.path.isdir(target_root) and not target_root.endswith(".app"):
            for dirpath, dirnames, filenames in os.walk(target_root, topdown=False):
                for fname in filenames:
                    if fname.endswith((".pyc", ".pyo", ".tmp_update", ".old_update")):
                        fpath = os.path.join(dirpath, fname)
                        try:
                            os.chmod(fpath, stat.S_IWRITE | 0o600)
                            os.remove(fpath)
                        except Exception:
                            pass
                for dname in dirnames:
                    if dname == "__pycache__":
                        dpath = os.path.join(dirpath, dname)
                        try:
                            shutil.rmtree(dpath, onerror=_force_rm_readonly)
                        except Exception:
                            pass

        try:
            appdata_dir = get_app_dir()
            fw_cache = os.path.join(appdata_dir, "nx_firmwares_cache.json")
            if os.path.isfile(fw_cache):
                os.remove(fw_cache)
        except Exception:
            pass

        try:
            audio_cache = os.path.join(tempfile.gettempdir(), "TriCoreDownloader_AudioCache")
            if os.path.isdir(audio_cache):
                shutil.rmtree(audio_cache, onerror=_force_rm_readonly)
        except Exception:
            pass

    def _safe_replace(self, src, dst, verify_hash=True):
        expected_sha256 = _compute_file_sha256(src) if verify_hash else None
        expected_size = os.path.getsize(src)

        tmp_dst = dst + ".tmp_update"
        old_backup = dst + ".old_update"

        if os.path.exists(tmp_dst):
            try:
                os.chmod(tmp_dst, stat.S_IWRITE | 0o600)
                os.remove(tmp_dst)
            except Exception:
                pass

        shutil.copy2(src, tmp_dst)
        if sys.platform != "win32":
            try:
                st = os.stat(tmp_dst)
                ext = os.path.splitext(dst)[1].lower()
                if ext in ("", ".sh", ".command", ".py", ".appimage") or self.is_direct_binary:
                    os.chmod(tmp_dst, st.st_mode | stat.S_IEXEC | 0o755)
            except Exception:
                pass

        replaced = False
        for attempt in range(12):
            try:
                if os.path.exists(dst):
                    try:
                        os.chmod(dst, stat.S_IWRITE | 0o755)
                    except Exception:
                        pass
                os.replace(tmp_dst, dst)
                replaced = True
                break
            except (PermissionError, OSError):
                if attempt >= 4 and os.path.exists(dst):
                    try:
                        if os.path.exists(old_backup):
                            os.remove(old_backup)
                        os.rename(dst, old_backup)
                        os.replace(tmp_dst, dst)
                        replaced = True
                        break
                    except Exception:
                        pass
                time.sleep(0.35)

        if not replaced:
            os.replace(tmp_dst, dst)

        if os.path.exists(old_backup):
            try:
                os.remove(old_backup)
            except Exception:
                pass

        if not os.path.isfile(dst) or os.path.getsize(dst) != expected_size:
            raise RuntimeError(self.T("err_verify_failed").format(os.path.basename(dst)))

        if verify_hash and expected_sha256:
            actual_sha256 = _compute_file_sha256(dst)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(self.T("err_verify_failed").format(os.path.basename(dst)))

    def _find_mac_bundle_executable(self, app_bundle):
        macos_dir = os.path.join(app_bundle, "Contents", "MacOS")
        preferred = os.path.join(macos_dir, "TriCoreDownloader")
        if os.path.isfile(preferred):
            return preferred
        if os.path.isdir(macos_dir):
            for fname in os.listdir(macos_dir):
                fpath = os.path.join(macos_dir, fname)
                if os.path.isfile(fpath):
                    return fpath
        return None

    def _replace_mac_app_bundle(self, src_app, dst_app):
        _tlog(f"Replacing macOS application bundle: {dst_app}")
        self.progress.emit(self.T("replacing_binary"))
        src_inner_exe = self._find_mac_bundle_executable(src_app)
        if not src_inner_exe:
            raise RuntimeError(self.T("err_dmg_corrupt"))
        expected_exe_hash = _compute_file_sha256(src_inner_exe)

        tmp_app = dst_app + ".new_update"
        if os.path.exists(tmp_app):
            shutil.rmtree(tmp_app, onerror=_force_rm_readonly)

        subprocess.run(["ditto", src_app, tmp_app], check=True)

        backup_app = dst_app + ".old_update"
        if os.path.exists(dst_app):
            if os.path.exists(backup_app):
                shutil.rmtree(backup_app, onerror=_force_rm_readonly)
            os.rename(dst_app, backup_app)

        try:
            os.rename(tmp_app, dst_app)
        except Exception:
            if os.path.exists(backup_app) and not os.path.exists(dst_app):
                os.rename(backup_app, dst_app)
            raise

        subprocess.run(["xattr", "-cr", dst_app], check=False)

        if os.path.exists(backup_app):
            shutil.rmtree(backup_app, onerror=_force_rm_readonly)

        self.progress.emit(self.T("verifying_install"))
        dst_inner_exe = self._find_mac_bundle_executable(dst_app)
        if not dst_inner_exe or not os.path.isfile(dst_inner_exe):
            raise RuntimeError(self.T("err_verify_failed").format("TriCoreDownloader.app"))

        try:
            st = os.stat(dst_inner_exe)
            os.chmod(dst_inner_exe, st.st_mode | stat.S_IEXEC | 0o755)
        except Exception:
            pass

        if _compute_file_sha256(dst_inner_exe) != expected_exe_hash:
            raise RuntimeError(self.T("err_verify_failed").format("TriCoreDownloader.app"))

        try:
            os.utime(dst_app, None)
            lsregister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
            if os.path.exists(lsregister):
                subprocess.run([lsregister, "-f", dst_app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except Exception:
            pass

        self._purge_caches()
        self.installed_target_path = os.path.abspath(dst_app)

    def _extract_dmg(self, dmg_file_path):
        mount_point = os.path.join(get_app_dir(), f"TCD_Mount_{os.getpid()}")
        os.makedirs(mount_point, exist_ok=True)
        _tlog(f"Mounting DMG '{dmg_file_path}' at '{mount_point}'...")
        self.progress.emit(self.T("mounting_dmg"))

        attach_cmd = [
            "hdiutil", "attach", dmg_file_path,
            "-mountpoint", mount_point,
            "-nobrowse", "-readonly", "-noautoopen"
        ]
        subprocess.run(attach_cmd, check=True)

        try:
            found_app = None
            if os.path.exists(mount_point):
                for item in os.listdir(mount_point):
                    if item == "TriCoreDownloader.app":
                        found_app = os.path.join(mount_point, item)
                        break

            if not found_app:
                for root, dirs, _ in os.walk(mount_point):
                    for d in dirs:
                        if d == "TriCoreDownloader.app":
                            found_app = os.path.join(root, d)
                            break
                    if found_app:
                        break

            if not found_app or not os.path.exists(found_app):
                raise Exception(self.T("err_dmg_corrupt"))

            if self.custom_dst_file and self.custom_dst_file.endswith(".app"):
                dst_app = self.custom_dst_file
            else:
                dst_app = resolve_mac_target_app(install_dir=self.install_dir)

            if not os.path.exists(dst_app) and not os.path.isdir(os.path.dirname(dst_app)):
                raise Exception(self.T("err_not_in_applications"))

            self._replace_mac_app_bundle(found_app, dst_app)

        finally:
            subprocess.run(["hdiutil", "detach", mount_point, "-force"], check=False)
            shutil.rmtree(mount_point, ignore_errors=True)

    def _find_source_root(self, extract_root):
        direct_candidate = os.path.join(extract_root, "run_TriCoreDownloader.py")
        if os.path.exists(direct_candidate):
            return extract_root

        for root, dirs, files in os.walk(extract_root):
            dirs[:] = [d for d in dirs if d != "__MACOSX" and not d.startswith(".")]
            if "run_TriCoreDownloader.py" in files:
                return root

        return None

    def run(self):
        _tlog(f"Starting installation worker for version '{self.target_version}' (asset='{self.asset_name}', profile='{self.env_profile}')")
        if (sys.platform == "darwin" or self.env_profile in ("macos_arm64", "macos_x64")) and self.is_frozen and (self.is_dmg or self.custom_dst_file):
            target_mac_app = self.custom_dst_file if (self.custom_dst_file and self.custom_dst_file.endswith(".app")) else resolve_mac_target_app(install_dir=self.install_dir)
            check_dir = os.path.dirname(target_mac_app)
        elif self.custom_dst_file:
            check_dir = os.path.dirname(self.custom_dst_file)
        else:
            check_dir = os.path.dirname(self.install_dir) if self.install_dir.endswith(".app") else self.install_dir

        _tlog(f"Checking write permissions on directory: {check_dir}")
        if not check_directory_permissions(check_dir):
            _tlog(f"Permission denied on target directory: {check_dir}", "ERROR")
            self.completed.emit(False, self.T("err_permission_denied").format(check_dir))
            return

        if not wait_for_main_app_exit(self.custom_dst_file):
            _tlog("Aborting update because TriCoreDownloader is still running.", "ERROR")
            self.completed.emit(False, self.T("err_app_running_desc"))
            return

        temp_download_path = os.path.join(get_app_dir(), f"TCD_Download_Temp_{os.getpid()}.bin")
        temp_extract_dir = os.path.join(get_app_dir(), f"TCD_Extract_Temp_{os.getpid()}")

        try:
            if not self.is_direct_binary and not self.is_dmg and self.is_7z:
                self.progress.emit(self.T("loading_7z"))
                if importlib.util.find_spec("py7zr") is None:
                    if not getattr(sys, "frozen", False):
                        _tlog("Installing py7zr dependency for .7z archive extraction...")
                        try:
                            subprocess.check_call(
                                [sys.executable, "-m", "pip", "install", "py7zr", "--no-warn-script-location"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                        except subprocess.CalledProcessError:
                            raise Exception("Failed to install py7zr.")
                    else:
                        raise Exception("Extraction format 7z requires 'py7zr'.")

            _tlog(f"Downloading package from: {self.download_url}")
            self.progress.emit(self.T("downloading_update"))
            self.progress_val.emit(0)
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            dl_hasher = hashlib.sha256()
            t_start = time.monotonic()

            with urlopen_safe(req, timeout=30) as response:
                total_length = response.headers.get('content-length')
                total_size = int(total_length) if total_length and total_length.isdigit() else 0
                downloaded = 0
                chunk_size = 131072
                last_pct = -1
                last_logged_step = -1
                with open(temp_download_path, 'wb') as out_file:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        dl_hasher.update(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            if pct != last_pct:
                                last_pct = pct
                                elapsed = max(0.05, time.monotonic() - t_start)
                                dl_mb = downloaded / (1024 * 1024)
                                tot_mb = total_size / (1024 * 1024)
                                spd_mb = dl_mb / elapsed
                                self.progress_val.emit(pct)
                                self.progress.emit(
                                    self.T("downloading_stats").format(
                                        pct=pct, dl=dl_mb, tot=tot_mb, spd=spd_mb
                                    )
                                )
                                step_bucket = pct // 20
                                if step_bucket > last_logged_step:
                                    last_logged_step = step_bucket
                                    _tlog(f"Download progress: {pct}% ({dl_mb:.1f}/{tot_mb:.1f} MB at {spd_mb:.1f} MB/s)")

            if total_size > 0 and os.path.getsize(temp_download_path) != total_size:
                raise RuntimeError(self.T("err_verify_failed").format("Download incomplete"))

            computed_dl_hash = dl_hasher.hexdigest().lower()
            _tlog(f"Download complete ({os.path.getsize(temp_download_path)} bytes). Computed SHA-256: {computed_dl_hash}")

            if self.expected_sha256:
                _tlog(f"Verifying against official release SHA-256: {self.expected_sha256}")
                if computed_dl_hash != self.expected_sha256:
                    _tlog("SHA-256 mismatch detected!", "ERROR")
                    raise RuntimeError(
                        self.T("err_sha256_mismatch").format(self.asset_name or "update package")
                    )
                _tlog("SHA-256 integrity verified successfully.")

            self.progress_val.emit(100)

            if not wait_for_main_app_exit(self.custom_dst_file):
                raise Exception(self.T("err_app_running_desc"))

            if self.is_frozen and self.is_dmg:
                self._extract_dmg(temp_download_path)
                _tlog("macOS DMG update completed and verified.")
                self.completed.emit(True, self.T("update_success"))
                return

            if self.is_direct_binary and self.is_frozen:
                self.progress.emit(self.T("replacing_binary"))
                if self.custom_dst_file:
                    dst_file = self.custom_dst_file
                elif self.env_profile == "win_x64" or sys.platform == "win32":
                    target_name = self.asset_name or "TriCoreDownloader_Windows_x64.exe"
                    dst_file = os.path.join(self.install_dir, target_name)
                elif self.env_profile == "linux_x86_64" or sys.platform.startswith("linux"):
                    target_name = self.asset_name or "TriCoreDownloader_Linux_x86_64.AppImage"
                    dst_file = os.path.join(self.install_dir, target_name)
                else:
                    target_name = self.asset_name or "TriCoreDownloader"
                    dst_file = os.path.join(self.install_dir, target_name)

                _tlog(f"Replacing target binary atomically: {dst_file}")
                self._safe_replace(temp_download_path, dst_file, verify_hash=True)
                self.progress.emit(self.T("verifying_install"))
                self._purge_caches(os.path.dirname(dst_file))
                self.installed_target_path = os.path.abspath(dst_file)
                _tlog(f"Binary replacement and SHA-256 verification succeeded: {self.installed_target_path}")
                self.completed.emit(True, self.T("update_success"))
                return

            _tlog("Extracting source archive...")
            self.progress.emit(self.T("extracting_files"))
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir, onerror=_force_rm_readonly)
            os.makedirs(temp_extract_dir, exist_ok=True)

            if self.is_7z:
                import py7zr
                with py7zr.SevenZipFile(temp_download_path, mode='r') as z:
                    z.extractall(path=temp_extract_dir)
            elif tarfile.is_tarfile(temp_download_path):
                with tarfile.open(temp_download_path, 'r:*') as t:
                    try:
                        t.extractall(path=temp_extract_dir, filter='data')
                    except TypeError:
                        t.extractall(path=temp_extract_dir)
            else:
                with zipfile.ZipFile(temp_download_path, 'r') as z:
                    z.extractall(temp_extract_dir)

            self.progress.emit(self.T("analyzing_arch"))

            base_target = self._find_source_root(temp_extract_dir)
            if not base_target:
                raise Exception(self.T("err_no_vital_files"))

            self.progress.emit(self.T("cleaning_old"))
            self._purge_caches(self.install_dir)

            extracted_files = set()
            for root, dirs, files in os.walk(base_target):
                dirs[:] = [d for d in dirs if d != "__MACOSX" and d != "__pycache__"]
                for f in files:
                    if f == ".DS_Store" or f.endswith((".pyc", ".pyo")):
                        continue
                    if self.skip_updater and f in ["Updater.py", "Updater.exe", "TempUpdater.exe", "TempUpdater"]:
                        continue
                    rel_path = os.path.relpath(os.path.join(root, f), base_target)
                    extracted_files.add(os.path.normcase(os.path.abspath(os.path.join(self.install_dir, rel_path))))

            ALLOWED_FOLDERS = ["TriCoreDownloader", "CAFE", "CTR", "NX", "Languages", "Songs", "icons", "hactool"]
            ALLOWED_ROOT_FILES = [
                "clean_pycache.bat", "run_TriCoreDownloader.py", "start.bat",
                "run_TriCoreDownloader.command", "run_TriCoreDownloader.sh",
                "start.sh", "start.command", "clean_save.bat", "LICENSE", "README.md",
                "TriCoreDownloader.spec", "Updater.py"
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
                                os.chmod(file_path, stat.S_IWRITE | 0o600)
                                os.remove(file_path)
                            except Exception:
                                pass
                    try:
                        if not os.listdir(dirpath):
                            os.rmdir(dirpath)
                    except Exception:
                        pass

            for root_file in ALLOWED_ROOT_FILES:
                if self.skip_updater and root_file in ["Updater.py", "Updater.exe", "TempUpdater.exe", "TempUpdater"]:
                    continue
                file_path = os.path.abspath(os.path.join(self.install_dir, root_file))
                file_norm = os.path.normcase(file_path)
                if os.path.exists(file_path) and file_norm not in extracted_files:
                    try:
                        os.chmod(file_path, stat.S_IWRITE | 0o600)
                        os.remove(file_path)
                    except Exception:
                        pass

            _tlog(f"Installing {len(extracted_files)} source files into '{self.install_dir}'...")
            self.progress.emit(self.T("installing_new"))
            for root, dirs, files in os.walk(base_target):
                dirs[:] = [d for d in dirs if d != "__MACOSX" and d != "__pycache__"]
                for f in files:
                    if f == ".DS_Store" or f.endswith((".pyc", ".pyo")):
                        continue
                    if self.skip_updater and f in ["Updater.py", "Updater.exe", "TempUpdater.exe", "TempUpdater"]:
                        continue
                    src_file = os.path.join(root, f)
                    rel_path = os.path.relpath(src_file, base_target)
                    dst_file = os.path.join(self.install_dir, rel_path)
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    self._safe_replace(src_file, dst_file, verify_hash=True)

            self.progress.emit(self.T("verifying_install"))
            vital_checks = [
                ("run_TriCoreDownloader.py",),
                ("TriCoreDownloader", "config.py"),
            ]
            for rel_parts in vital_checks:
                src_v = os.path.join(base_target, *rel_parts)
                dst_v = os.path.join(self.install_dir, *rel_parts)
                if os.path.isfile(src_v):
                    if not os.path.isfile(dst_v) or _compute_file_sha256(src_v) != _compute_file_sha256(dst_v):
                        raise RuntimeError(self.T("err_verify_failed").format("/".join(rel_parts)))

            self._purge_caches(self.install_dir)
            self.installed_target_path = os.path.abspath(os.path.join(self.install_dir, "run_TriCoreDownloader.py"))
            _tlog(f"Source update completed and verified: {self.installed_target_path}")
            self.completed.emit(True, self.T("update_success"))

        except Exception as e:
            _tlog(f"Installation worker error: {e}", "ERROR")
            self.completed.emit(False, str(e))
        finally:
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir, onerror=_force_rm_readonly)
            if os.path.exists(temp_download_path):
                try:
                    os.remove(temp_download_path)
                except Exception:
                    pass


class UpdaterWindow(QMainWindow):
    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        self._is_closing = False
        self._in_cancel_prompt = False
        self.is_frozen = getattr(sys, "frozen", False)
        self.target_confirmed = None
        self.installed_target_path = None
        self.env_profile = None
        self.env_has_unknown = False

        self._retained_threads = []

        self.install_dir = os.getcwd()
        if "--install-dir" in sys.argv:
            try:
                idx = sys.argv.index("--install-dir")
                raw_dir = sys.argv[idx + 1]
                if sys.platform == "darwin" and self.is_frozen and ".app" in raw_dir:
                    self.install_dir = get_mac_app_bundle_path(raw_dir)
                else:
                    self.install_dir = os.path.abspath(raw_dir)
            except IndexError:
                pass

        self.original_target = None
        if "--original-target" in sys.argv:
            try:
                idx = sys.argv.index("--original-target")
                self.original_target = os.path.abspath(sys.argv[idx + 1])
            except IndexError:
                pass

        self.app_cfg = load_tricore_config()

        saved_lang = str(self.app_cfg.get("lang", "")).strip().upper()
        if saved_lang in ["FR", "EN"]:
            self.lang = saved_lang
        else:
            self.lang = detect_system_language()

        self.setWindowTitle(self.T("window_title"))
        if sys.platform != "darwin":
            self.setWindowIcon(self.get_app_icon())

        self.releases_data = []
        self.cached_releases = []

        self.force_reinstall_mode = "--reinstall" in sys.argv
        self.force_prerelease_mode = "--prerelease" in sys.argv
        self.force_view_all_mode = "--view-all" in sys.argv

        self.theme_name = self.app_cfg.get("theme", "auto").lower()
        if self.theme_name not in THEMES or self.theme_name == "auto":
            is_dark = True
            try:
                scheme = QApplication.styleHints().colorScheme()
                if scheme != Qt.ColorScheme.Unknown:
                    is_dark = (scheme == Qt.ColorScheme.Dark)
                elif darkdetect is not None:
                    is_dark = bool(darkdetect.isDark())
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

        self._detect_initial_environment()
        _tlog(f"Environment detected: {self.get_environment_display_text()} | install_dir='{self.install_dir}' | original_target='{self.original_target}'")
        self.init_ui()
        self.apply_style()

        if self.rainbow_mode:
            self.rainbow_timer = QTimer(self)
            self.rainbow_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.rainbow_timer.timeout.connect(self.update_rainbow_tick)
            self.rainbow_timer.start(33)

        if self.initial_env_has_unknown or "--force-os-prompt" in sys.argv:
            QTimer.singleShot(150, self._startup_prompt_then_fetch)
        else:
            self.fetch_all_releases()

    def T(self, key):
        return LOCALES.get(self.lang, LOCALES["EN"]).get(key, key)

    def _start_tracked_thread(self, attr_name, thread_obj):
        old_thread = getattr(self, attr_name, None)
        if old_thread and old_thread.isRunning():
            try:
                old_thread.finished.disconnect()
            except Exception:
                pass
            old_thread.quit()

        setattr(self, attr_name, thread_obj)
        self._retained_threads.append(thread_obj)

        def _cleanup():
            if thread_obj in self._retained_threads:
                self._retained_threads.remove(thread_obj)

        thread_obj.finished.connect(_cleanup)
        thread_obj.start()

    def _detect_initial_environment(self):
        unknown_str = self.T("env_unknown")

        if sys.platform == "win32":
            os_str = "Windows"
        elif sys.platform == "darwin":
            os_str = "macOS"
        elif sys.platform.startswith("linux"):
            os_str = "Linux"
        else:
            os_str = unknown_str

        raw_mach = (platform.machine() or "").strip().lower()
        arch_str = unknown_str

        if sys.platform == "darwin":
            if _is_arm64_arch_string(raw_mach) or _is_macos_apple_silicon():
                arch_str = "arm64 / Apple Silicon"
            elif raw_mach in ("x86_64", "amd64", "x64"):
                arch_str = "x64 / Intel"
        elif sys.platform == "win32":
            proc_arch = os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
            if raw_mach in ("amd64", "x86_64", "x64") or proc_arch in ("amd64", "x64"):
                arch_str = "x64"
            elif _is_arm64_arch_string(raw_mach) or proc_arch == "arm64":
                arch_str = "arm64"
        elif sys.platform.startswith("linux"):
            if raw_mach in ("x86_64", "amd64", "x64"):
                arch_str = "x86_64"
            elif _is_arm64_arch_string(raw_mach):
                arch_str = "arm64"

        is_frozen = bool(getattr(sys, "frozen", False))
        mode_str = self.T("env_mode_compiled") if is_frozen else self.T("env_mode_source")

        self.env_os_str = os_str
        self.env_arch_str = arch_str
        self.env_mode_str = mode_str

        self.initial_env_display_text = self.T("env_badge_format").format(
            os=os_str, arch=arch_str, mode=mode_str
        )

        if not is_frozen:
            self.env_profile = "source"
            self.is_frozen = False
            self.env_has_unknown = (os_str == unknown_str or arch_str == unknown_str)
        else:
            self.is_frozen = True
            if os_str == "Windows" and arch_str == "x64":
                self.env_profile = "win_x64"
                self.env_has_unknown = False
            elif os_str == "Linux" and arch_str == "x86_64":
                self.env_profile = "linux_x86_64"
                self.env_has_unknown = False
            elif os_str == "macOS" and arch_str == "arm64 / Apple Silicon":
                self.env_profile = "macos_arm64"
                self.env_has_unknown = False
            elif os_str == "macOS" and arch_str == "x64 / Intel":
                self.env_profile = "macos_x64"
                self.env_has_unknown = False
            else:
                self.env_profile = None
                self.env_has_unknown = True

        self.initial_env_has_unknown = self.env_has_unknown

    def _apply_manual_env_profile(self, profile_code):
        if profile_code == "win_x64":
            self.env_os_str = "Windows"
            self.env_arch_str = "x64"
            self.env_mode_str = self.T("env_mode_compiled")
            self.is_frozen = True
            self.env_profile = "win_x64"
            self.env_has_unknown = False
        elif profile_code == "linux_x86_64":
            self.env_os_str = "Linux"
            self.env_arch_str = "x86_64"
            self.env_mode_str = self.T("env_mode_compiled")
            self.is_frozen = True
            self.env_profile = "linux_x86_64"
            self.env_has_unknown = False
        elif profile_code == "macos_arm64":
            self.env_os_str = "macOS"
            self.env_arch_str = "arm64 / Apple Silicon"
            self.env_mode_str = self.T("env_mode_compiled")
            self.is_frozen = True
            self.env_profile = "macos_arm64"
            self.env_has_unknown = False
        elif profile_code == "macos_x64":
            self.env_os_str = "macOS"
            self.env_arch_str = "x64 / Intel"
            self.env_mode_str = self.T("env_mode_compiled")
            self.is_frozen = True
            self.env_profile = "macos_x64"
            self.env_has_unknown = False
        elif profile_code == "source":
            if self.env_os_str == self.T("env_unknown"):
                if sys.platform == "win32":
                    self.env_os_str = "Windows"
                elif sys.platform == "darwin":
                    self.env_os_str = "macOS"
                elif sys.platform.startswith("linux"):
                    self.env_os_str = "Linux"
                else:
                    self.env_os_str = "Python"
            if self.env_arch_str == self.T("env_unknown"):
                raw_m = (platform.machine() or "").strip()
                if sys.platform == "darwin" and (_is_arm64_arch_string(raw_m) or _is_macos_apple_silicon()):
                    self.env_arch_str = "arm64 / Apple Silicon"
                else:
                    self.env_arch_str = raw_m or "Multi-arch"
            self.env_mode_str = self.T("env_mode_source")
            self.is_frozen = False
            self.env_profile = "source"
            self.env_has_unknown = False

        _tlog(f"Environment profile set to: {self.env_profile} ({self.get_environment_display_text()})")
        self.update_env_badge_ui()

    def get_environment_display_text(self):
        return self.T("env_badge_format").format(
            os=getattr(self, "env_os_str", self.T("env_unknown")),
            arch=getattr(self, "env_arch_str", self.T("env_unknown")),
            mode=getattr(self, "env_mode_str", self.T("env_unknown")),
        )

    def update_env_badge_ui(self):
        if hasattr(self, "env_info_lbl"):
            self.env_info_lbl.setText(self.get_environment_display_text())
            can_modify = self.initial_env_has_unknown or ("--force-os-prompt" in sys.argv)
            if can_modify:
                self.env_info_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                self.env_info_lbl.setToolTip(self.T("env_tooltip_click"))
            else:
                self.env_info_lbl.setCursor(Qt.CursorShape.ArrowCursor)
                self.env_info_lbl.setToolTip("")

    def on_env_badge_clicked(self):
        can_modify = self.initial_env_has_unknown or ("--force-os-prompt" in sys.argv)
        if can_modify:
            self.prompt_manual_environment_selection(auto_refresh=True)

    def _startup_prompt_then_fetch(self):
        self.prompt_manual_environment_selection(auto_refresh=False)
        self.fetch_all_releases()

    def prompt_manual_environment_selection(self, auto_refresh=True, force=False):
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            return

        can_modify = self.initial_env_has_unknown or force or ("--force-os-prompt" in sys.argv)
        if not can_modify:
            return

        dlg = EnvironmentSelectDialog(
            self,
            getattr(self, "initial_env_display_text", self.get_environment_display_text()),
            current_profile=self.env_profile,
        )
        dlg.setStyleSheet(get_stylesheet(self.theme_name, self.accent_color))
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_profile:
            self._apply_manual_env_profile(dlg.selected_profile)
            if auto_refresh and self.releases_data:
                self.process_releases(self.releases_data, "")

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

    def clean_up_resources(self):
        if hasattr(self, 'spinner_timer') and self.spinner_timer and self.spinner_timer.isActive():
            self.spinner_timer.stop()
        if hasattr(self, 'rainbow_timer') and self.rainbow_timer and self.rainbow_timer.isActive():
            self.rainbow_timer.stop()
        if hasattr(self, 'pulse_anim') and self.pulse_anim and self.pulse_anim.state() == QAbstractAnimation.State.Running:
            self.pulse_anim.stop()

        all_threads = set(getattr(self, '_retained_threads', []))
        for th_attr in ('commit_thread', 'fetch_thread', 'worker'):
            th = getattr(self, th_attr, None)
            if th is not None:
                all_threads.add(th)

        for th in all_threads:
            try:
                th.finished.disconnect()
            except Exception:
                pass
            if th.isRunning():
                th.requestInterruption()
                th.quit()
                th.wait(300)

        self._retained_threads.clear()

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        card_frame = QFrame(self)
        card_frame.setObjectName("Card")
        card_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        header_top_layout = QHBoxLayout()
        header_top_layout.setContentsMargins(0, 0, 0, 0)
        header_top_layout.setSpacing(10)

        title_lbl = QLabel(self.T("card_title"), card_frame)
        title_lbl.setObjectName("CardTitle")
        header_top_layout.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        header_top_layout.addStretch(1)

        self.env_info_lbl = QPushButton(self.get_environment_display_text(), card_frame)
        self.env_info_lbl.setObjectName("EnvInfoBadge")
        self.update_env_badge_ui()
        self.env_info_lbl.clicked.connect(self.on_env_badge_clicked)
        header_top_layout.addWidget(self.env_info_lbl, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        card_layout.addLayout(header_top_layout)

        self.version_lbl = QLabel(self.T("current_version").format(self.current_version), card_frame)
        self.version_lbl.setObjectName("CardVersion")
        card_layout.addWidget(self.version_lbl)

        cb_layout = QHBoxLayout()
        cb_layout.setContentsMargins(0, 0, 0, 0)

        self.beta_checkbox = QCheckBox(self.T("beta_checkbox"), card_frame)
        self.beta_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.beta_checkbox.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.beta_checkbox.stateChanged.connect(self.toggle_beta_mode)
        cb_layout.addWidget(self.beta_checkbox)
        cb_layout.addStretch(1)

        card_layout.addLayout(cb_layout)

        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 2, 0, 2)

        self.status_lbl = QLabel(self.T("checking_versions"), card_frame)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setOpenExternalLinks(True)
        self.status_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        status_layout.addWidget(self.status_lbl, 1)

        self.status_icon_lbl = QLabel("", card_frame)
        self.status_icon_lbl.setFixedWidth(24)
        self.status_icon_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_layout.addWidget(self.status_icon_lbl)

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
        self.warn_lbl.setStyleSheet(f"color: #EF5350; font-size: {FS_DIM};")
        self.warn_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.warn_lbl.hide()
        card_layout.addWidget(self.warn_lbl)

        self.browser = QTextEdit(card_frame)
        self.browser.setReadOnly(True)
        self.browser.setMinimumHeight(140)
        self.browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        card_layout.addWidget(self.browser)

        self.version_combo.currentIndexChanged.connect(self.on_version_changed_index)

        main_layout.addWidget(card_frame)

        btn_layout = QHBoxLayout()

        self.btn_execute = QPushButton(self.T("btn_install"), self)
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

        self.btn_cancel = QPushButton(self.T("btn_cancel"), self)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.handle_cancel)

        btn_layout.addWidget(self.btn_execute)
        btn_layout.addWidget(self.lbl_warning_symbol)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(btn_layout)

        self.setMinimumSize(640, 560)
        self.resize(640, 560)

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
                font-size: {FS_BASE};
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

    def refresh_data(self):
        _tlog("Manual release refresh requested.")
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(False)
        self.status_icon_lbl.setText("")
        self.status_lbl.setText(self.T("refreshing_data"))
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
            if self.version_combo.count() > 0:
                self.on_version_changed_index(self.version_combo.currentIndex())

    def fetch_all_releases(self):
        th = ReleasesFetchThread()
        th.finished.connect(self.process_releases)
        self._start_tracked_thread("fetch_thread", th)

    def process_releases(self, data, error_str):
        if error_str:
            self.status_icon_lbl.setText("❌")
            if "403" in error_str:
                self.status_lbl.setText(self.T("api_error_403").format(accent=self.accent_color))
            else:
                self.status_lbl.setText(self.T("api_error").format(error_str))
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.setEnabled(True)
            return

        self.releases_data = data
        self.cached_releases = []
        self.version_combo.clear()
        self.browser.clear()
        self.status_icon_lbl.setText("")

        first_stable_idx = -1
        first_compatible_idx = -1
        prerelease_idx = -1

        for idx, release in enumerate(data):
            tag = release.get("tag_name", "").strip().lstrip('v')
            if not tag:
                continue

            compatible_asset, _ = find_compatible_asset(release, self.is_frozen, self.env_profile)
            is_compat = (compatible_asset is not None)

            if release.get("prerelease", False):
                display_name = f"{tag} [!Pre-release!]"
                if prerelease_idx == -1 and is_compat:
                    prerelease_idx = idx
            else:
                display_name = tag
                if first_stable_idx == -1:
                    first_stable_idx = idx
                if first_compatible_idx == -1 and is_compat:
                    first_compatible_idx = idx

            if not is_compat:
                display_name = f"{display_name}{self.T('tag_cant_install')}"

            self.cached_releases.append((display_name, release))
            self.version_combo.addItem(display_name, release)

        if self.version_combo.count() > 0:
            self.status_lbl.setText(self.T("select_release"))
            self.version_combo.setEnabled(True)

            target_select_idx = 0
            if self.force_reinstall_mode:
                target_select_idx = first_compatible_idx if first_compatible_idx != -1 else 0
            elif self.force_prerelease_mode and prerelease_idx != -1:
                target_select_idx = prerelease_idx
            elif self.force_view_all_mode:
                target_select_idx = 0
            else:
                if first_compatible_idx != -1:
                    target_select_idx = first_compatible_idx
                elif first_stable_idx != -1:
                    target_select_idx = first_stable_idx

            self.version_combo.setCurrentIndex(target_select_idx)
            self.on_version_changed_index(target_select_idx)

            if self.force_reinstall_mode and self.btn_execute.isEnabled():
                self.status_lbl.setText(self.T("auto_reinstall"))
                QTimer.singleShot(300, self.start_installation)
            elif self.force_prerelease_mode and prerelease_idx != -1 and self.btn_execute.isEnabled():
                self.status_lbl.setText(self.T("auto_reinstall_beta"))
                QTimer.singleShot(300, self.start_installation)

            if self.beta_checkbox.isChecked():
                self.toggle_beta_mode(2)
        else:
            self.status_lbl.setText(self.T("no_releases"))
            self.btn_execute.setEnabled(False)

        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(True)

    def fetch_beta_source(self):
        url = f"https://raw.githubusercontent.com/JeremKOYTB/TriCoreDownloader/refs/heads/main/TriCoreDownloader/config.py?t={int(time.time())}"
        _tlog("Fetching main branch version metadata...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urlopen_safe(req, timeout=5) as response:
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

            label_text = f"main branch ({display_version})"
            if self.is_frozen:
                label_text += self.T("tag_source_only")

            self.version_combo.insertItem(0, label_text, dummy_release)
            self.version_combo.setCurrentIndex(0)
            self.on_version_changed_index(0)
        except Exception as e:
            _tlog(f"Failed to fetch main branch metadata: {e}", "WARN")
            self.set_warning(self.T("err_fetch_main").format(e))
            self.btn_execute.setEnabled(False)

        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(True)

    def on_version_changed_index(self, index):
        if index < 0 or index >= self.version_combo.count():
            return
        current_data = self.version_combo.currentData()
        self.browser.clear()

        compatible_asset, _ = find_compatible_asset(current_data, self.is_frozen, self.env_profile)
        is_main_branch = isinstance(current_data, dict) and current_data.get("is_main_branch_node", False)

        if not compatible_asset:
            self.btn_execute.setEnabled(False)
            if self.is_frozen and is_main_branch:
                self.btn_execute.setText(self.T("btn_not_available_exe"))
                self.set_warning(self.T("warn_main_on_frozen"))
            else:
                self.btn_execute.setText(self.T("btn_cant_install"))
                self.set_warning(self.T("warn_incompatible_version").format(env=self.get_environment_display_text()))
        else:
            self.btn_execute.setEnabled(True)
            if self.force_reinstall_mode:
                self.btn_execute.setText(self.T("btn_reinstall"))
            elif self.force_prerelease_mode:
                self.btn_execute.setText(self.T("btn_beta"))
            else:
                self.btn_execute.setText(self.T("btn_install"))
            self.check_version_warnings(index)

        if is_main_branch:
            self.browser.setHtml(f"<div style='color: #8A8A95; font-style: italic;'>{self.T('fetching_commit')}</div>")
            th = MainBranchCommitFetchThread(self.lang)
            th.finished.connect(self.on_main_branch_commit_loaded)
            self._start_tracked_thread("commit_thread", th)
        else:
            changelog_text = current_data.get("body", self.T("no_changelog")) if isinstance(current_data, dict) else ""
            self.browser.setMarkdown(self._convert_markdown_to_html(changelog_text))

    def on_main_branch_commit_loaded(self, commit_text):
        self.browser.setHtml(commit_text)

    def check_version_warnings(self, index):
        if index < 0:
            return
        current_text = self.version_combo.currentText()
        base_version = current_text.split(" ")[0]

        if base_version == "0.9.0":
            self.set_warning(self.T("warn_090"))
        elif "main branch" in current_text:
            self.set_warning(self.T("warn_dev"))
        else:
            current_data = self.version_combo.currentData()
            if isinstance(current_data, dict) and current_data.get("prerelease", False):
                self.set_warning(self.T("warn_prerelease"))
            else:
                self.set_warning("")

    def handle_progress_val(self, val):
        if val >= 100:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(val)

    def start_installation(self, *args):
        if self.env_has_unknown or not self.env_profile:
            self.prompt_manual_environment_selection(auto_refresh=True, force=True)
            if self.env_has_unknown or not self.env_profile:
                return

        current_data = self.version_combo.currentData()
        if not current_data:
            return

        compatible_asset, is_direct_binary = find_compatible_asset(current_data, self.is_frozen, self.env_profile)

        download_url = None
        asset_name = ""
        expected_sha256 = ""
        is_main_branch = current_data.get("is_main_branch_node", False)

        if is_main_branch:
            download_url = current_data.get("zipball_url")
        elif compatible_asset:
            if isinstance(compatible_asset, str):
                download_url = compatible_asset
            else:
                download_url = compatible_asset.get("browser_download_url")
                asset_name = compatible_asset.get("name", "")
                expected_sha256 = _extract_expected_sha256(current_data, compatible_asset)

        target_file_to_confirm = None
        confirm_msg = None

        if (sys.platform == "darwin" or self.env_profile in ("macos_arm64", "macos_x64")) and self.is_frozen:
            target_file_to_confirm = resolve_mac_target_app(self.original_target, self.install_dir)
            if not os.path.exists(target_file_to_confirm):
                self.status_icon_lbl.setText("❌")
                err_box = QMessageBox(self)
                err_box.setIcon(QMessageBox.Icon.Critical)
                err_box.setWindowTitle(self.T("install_failed_title"))
                err_box.setText(self.T("err_not_in_applications"))
                err_box.exec()
                return
            confirm_msg = self.T("confirm_target_desc_mac").format(target_file_to_confirm)

        elif (sys.platform.startswith("linux") or self.env_profile == "linux_x86_64") and self.is_frozen:
            candidate = None
            if self.original_target and os.path.exists(self.original_target) and "tempupdater" not in os.path.basename(self.original_target).lower():
                candidate = os.path.abspath(self.original_target)
            elif os.environ.get("ORIGINAL_APPIMAGE") and os.path.exists(os.environ.get("ORIGINAL_APPIMAGE")):
                candidate = os.path.abspath(os.environ["ORIGINAL_APPIMAGE"])
            elif os.path.isdir(self.install_dir):
                for f in os.listdir(self.install_dir):
                    if f.endswith(".AppImage") and "updater" not in f.lower():
                        candidate = os.path.join(self.install_dir, f)
                        break
            if not candidate:
                appimage_env = os.environ.get("APPIMAGE")
                if appimage_env and os.path.exists(appimage_env) and "tempupdater" not in os.path.basename(appimage_env).lower():
                    candidate = os.path.abspath(appimage_env)
                else:
                    candidate = os.path.join(self.install_dir, asset_name or "TriCoreDownloader_Linux_x86_64.AppImage")
            target_file_to_confirm = candidate
            confirm_msg = self.T("confirm_target_desc_linux").format(target_file_to_confirm)

        elif (sys.platform == "win32" or self.env_profile == "win_x64") and self.is_frozen:
            candidate = None
            if self.original_target and os.path.exists(self.original_target) and "updater" not in os.path.basename(self.original_target).lower():
                candidate = os.path.abspath(self.original_target)
            elif os.path.isdir(self.install_dir):
                for f in os.listdir(self.install_dir):
                    if f.lower().endswith(".exe") and "updater" not in f.lower():
                        candidate = os.path.join(self.install_dir, f)
                        break
            if not candidate:
                candidate = os.path.join(self.install_dir, asset_name or "TriCoreDownloader_Windows_x64.exe")
            target_file_to_confirm = candidate
            confirm_msg = self.T("confirm_target_desc_win").format(target_file_to_confirm)

        if not wait_for_main_app_exit(target_file_to_confirm):
            self.status_icon_lbl.setText("❌")
            err_box = QMessageBox(self)
            if sys.platform != "darwin":
                err_box.setWindowIcon(self.get_app_icon())
            err_box.setIcon(QMessageBox.Icon.Warning)
            err_box.setWindowTitle(self.T("err_app_running_title"))
            err_box.setText(self.T("err_app_running_desc"))
            err_box.exec()
            return

        if target_file_to_confirm and confirm_msg:
            confirm_box = QMessageBox(self)
            if sys.platform != "darwin":
                confirm_box.setWindowIcon(self.get_app_icon())
            confirm_box.setIcon(QMessageBox.Icon.Question)
            confirm_box.setWindowTitle(self.T("confirm_target_title"))
            confirm_box.setText(confirm_msg)
            btn_yes = confirm_box.addButton(QMessageBox.StandardButton.Yes)
            confirm_box.addButton(QMessageBox.StandardButton.No)
            confirm_box.setDefaultButton(btn_yes)
            confirm_box.exec()
            if confirm_box.clickedButton() != btn_yes:
                _tlog("Target confirmation declined by user.")
                return
            self.target_confirmed = target_file_to_confirm
            _tlog(f"Target location confirmed by user: {self.target_confirmed}")

        if target_file_to_confirm:
            check_dir = os.path.dirname(target_file_to_confirm)
        else:
            check_dir = os.path.dirname(self.install_dir) if self.install_dir.endswith(".app") else self.install_dir

        if not check_directory_permissions(check_dir):
            self.status_icon_lbl.setText("❌")
            err_box = QMessageBox(self)
            if sys.platform != "darwin":
                err_box.setWindowIcon(self.get_app_icon())
            err_box.setIcon(QMessageBox.Icon.Critical)
            err_box.setWindowTitle(self.T("install_failed_title"))
            err_box.setText(self.T("err_permission_denied").format(check_dir))
            err_box.exec()
            return

        current_text = self.version_combo.currentText()
        base_version = current_text.split(" ")[0]

        if self.is_frozen and is_main_branch:
            return

        if not download_url:
            self.status_icon_lbl.setText("❌")
            self.status_lbl.setText(self.T("select_release"))
            err_box = QMessageBox(self)
            if sys.platform != "darwin":
                err_box.setWindowIcon(self.get_app_icon())
            err_box.setIcon(QMessageBox.Icon.Critical)
            err_box.setWindowTitle(self.T("asset_incompatible_title"))
            err_box.setText(self.T("asset_incompatible_desc"))
            err_box.exec()
            return

        self.version_combo.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.beta_checkbox.setEnabled(False)
        if hasattr(self, "env_info_lbl"):
            self.env_info_lbl.setEnabled(False)
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setEnabled(False)

        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.spinner_timer.start(100)

        worker_thread = DownloadWorkerThread(
            download_url,
            self.install_dir,
            base_version,
            is_direct_binary,
            asset_name,
            self.lang,
            custom_dst_file=target_file_to_confirm,
            env_profile=self.env_profile,
            expected_sha256=expected_sha256,
        )
        worker_thread.progress.connect(self.status_lbl.setText)
        worker_thread.progress_val.connect(self.handle_progress_val)
        worker_thread.completed.connect(self.installation_finished)
        self._start_tracked_thread("worker", worker_thread)

    def _find_python_for_source_launch(self, exec_dir):
        venv_names = [".venv", "venv", "env", "ENV", ".env"]
        for v_name in venv_names:
            if sys.platform == "win32":
                pyw = os.path.join(exec_dir, v_name, "Scripts", "pythonw.exe")
                if os.path.isfile(pyw):
                    return pyw
                py = os.path.join(exec_dir, v_name, "Scripts", "python.exe")
                if os.path.isfile(py):
                    return py
            else:
                py = os.path.join(exec_dir, v_name, "bin", "python")
                if os.path.isfile(py):
                    return py

        if not getattr(sys, "frozen", False):
            if sys.platform == "win32" and sys.executable.lower().endswith("python.exe"):
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if os.path.exists(pyw):
                    return pyw
            return sys.executable

        return "python" if sys.platform == "win32" else "python3"

    def launch_main_app(self):
        try:
            target = getattr(self, "installed_target_path", None)
            if target and not os.path.exists(target):
                target = None

            if not target:
                target = getattr(self, "target_confirmed", None)
                if target and not os.path.exists(target):
                    target = None

            if not target and hasattr(self, 'original_target') and self.original_target:
                candidate = os.path.abspath(self.original_target)
                base_name = os.path.basename(candidate).lower()
                if "updater" not in base_name and os.path.exists(candidate):
                    target = candidate

            base_dir = os.path.abspath(self.install_dir)

            if not self.is_frozen and not target:
                main_script = os.path.join(base_dir, "run_TriCoreDownloader.py")
                if os.path.exists(main_script):
                    target = main_script

            if self.is_frozen and sys.platform == "darwin" and not target:
                target = resolve_mac_target_app(self.original_target, base_dir)

            if not target or not os.path.exists(target) or "updater" in os.path.basename(target).lower():
                target = None
                search_dir = base_dir if not base_dir.endswith(".app") else os.path.dirname(base_dir)

                if os.path.exists(search_dir):
                    if not self.is_frozen:
                        main_script = os.path.join(search_dir, "run_TriCoreDownloader.py")
                        if os.path.exists(main_script):
                            target = main_script

                    if not target and sys.platform == "darwin":
                        for item in os.listdir(search_dir):
                            if item.endswith(".app") and "updater" not in item.lower():
                                target = os.path.join(search_dir, item)
                                break
                    elif not target and sys.platform == "win32":
                        candidates = [
                            "TriCoreDownloader_Windows_x64.exe",
                            "TriCoreDownloader-Windows-x64.exe",
                            "TriCoreDownloader.exe"
                        ]
                        for c in candidates:
                            p = os.path.join(search_dir, c)
                            if os.path.exists(p):
                                target = p
                                break
                        if not target:
                            for item in os.listdir(search_dir):
                                if item.lower().endswith(".exe") and "updater" not in item.lower():
                                    target = os.path.join(search_dir, item)
                                    break
                    elif not target:
                        orig_env = os.environ.get("ORIGINAL_APPIMAGE")
                        if orig_env and os.path.exists(orig_env):
                            target = orig_env
                        else:
                            for item in os.listdir(search_dir):
                                if item.endswith(".AppImage") and "updater" not in item.lower():
                                    target = os.path.join(search_dir, item)
                                    break
                            if not target:
                                main_bin = os.path.join(search_dir, "TriCoreDownloader")
                                if os.path.exists(main_bin) and not main_bin.endswith(".py"):
                                    target = main_bin

                    if not target:
                        main_script = os.path.join(search_dir, "run_TriCoreDownloader.py")
                        if os.path.exists(main_script):
                            target = main_script

            if not target or not os.path.exists(target):
                _tlog("Could not locate main TriCoreDownloader executable/script to relaunch.", "WARN")
                return

            if sys.platform != "win32" and not target.endswith(".app"):
                try:
                    st = os.stat(target)
                    os.chmod(target, st.st_mode | stat.S_IEXEC | 0o755)
                except Exception:
                    pass

            env = os.environ.copy()
            exec_dir = os.path.dirname(target) if target.endswith(".app") else (
                base_dir if os.path.isdir(base_dir) and not base_dir.endswith(".app") else os.path.dirname(target)
            )

            for clean_var in (
                "APPDIR", "APPIMAGE", "OWD", "ARGV0",
                "_MEIPASS", "_MEIPASS2", "ORIGINAL_APPIMAGE", "TCD_UPDATER_RELOCATED",
                "LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"
            ):
                env.pop(clean_var, None)

            if sys.platform.startswith("linux"):
                env["APPIMAGE_EXTRACT_AND_RUN"] = "1"

            is_python_script = target.lower().endswith(".py")
            if is_python_script:
                if exec_dir not in env.get("PYTHONPATH", ""):
                    env["PYTHONPATH"] = exec_dir + os.pathsep + env.get("PYTHONPATH", "")
            else:
                env.pop("PYTHONPATH", None)

            _tlog(f"Relaunching TriCoreDownloader: {target}")
            if sys.platform == "darwin":
                if target.endswith(".app"):
                    subprocess.Popen(["open", "-n", target], cwd=os.path.dirname(target), env=env)
                elif is_python_script:
                    py_exec = self._find_python_for_source_launch(exec_dir)
                    subprocess.Popen([py_exec, target], env=env, start_new_session=True, cwd=exec_dir)
                else:
                    subprocess.Popen([target], env=env, start_new_session=True, cwd=exec_dir)

            elif sys.platform == "win32":
                creationflags = 0
                if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                    creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
                if hasattr(subprocess, "DETACHED_PROCESS"):
                    creationflags |= subprocess.DETACHED_PROCESS

                if is_python_script:
                    py_exec = self._find_python_for_source_launch(exec_dir)
                    if hasattr(subprocess, "CREATE_NO_WINDOW"):
                        creationflags |= subprocess.CREATE_NO_WINDOW
                    subprocess.Popen([py_exec, target], cwd=exec_dir, env=env, creationflags=creationflags, close_fds=True)
                else:
                    subprocess.Popen([target], cwd=exec_dir, env=env, creationflags=creationflags, close_fds=True)

            else:
                if is_python_script:
                    py_exec = self._find_python_for_source_launch(exec_dir)
                    subprocess.Popen([py_exec, target], env=env, start_new_session=True, cwd=exec_dir, close_fds=True)
                else:
                    proc = subprocess.Popen([target], env=env, start_new_session=True, cwd=exec_dir, close_fds=True)
                    if target.lower().endswith(".appimage"):
                        time.sleep(0.15)
                        if proc.poll() is not None and proc.returncode != 0:
                            _tlog("AppImage launch failed (FUSE unavailable), relaunching with APPIMAGE_EXTRACT_AND_RUN=1...", "WARN")
                            env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
                            subprocess.Popen([target], env=env, start_new_session=True, cwd=exec_dir, close_fds=True)

        except Exception as e:
            _tlog(f"Error while relaunching main app: {e}", "ERROR")

    def _graceful_quit_app(self, relaunch_main=False):
        if self._is_closing:
            return
        self._is_closing = True
        _tlog("Shutting down updater cleanly...")
        self.clean_up_resources()
        if relaunch_main:
            self.launch_main_app()
        self.close()
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.quit()

    def installation_finished(self, success, message):
        self.spinner_timer.stop()
        if success:
            if self.worker and getattr(self.worker, "installed_target_path", ""):
                self.installed_target_path = self.worker.installed_target_path

            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self.status_icon_lbl.setText("✅")
            self.status_lbl.setText(self.T("complete"))
            success_box = QMessageBox(self)
            if sys.platform != "darwin":
                success_box.setWindowIcon(self.get_app_icon())
            success_box.setIcon(QMessageBox.Icon.Information)
            success_box.setWindowTitle(self.T("success_title"))
            success_box.setText(self.T("success_desc"))
            success_box.exec()

            self._graceful_quit_app(relaunch_main=True)
        else:
            self.progress_bar.hide()
            self.status_icon_lbl.setText("❌")
            self.status_lbl.setText(self.T("select_release"))
            fail_box = QMessageBox(self)
            if sys.platform != "darwin":
                fail_box.setWindowIcon(self.get_app_icon())
            fail_box.setIcon(QMessageBox.Icon.Critical)
            fail_box.setWindowTitle(self.T("install_failed_title"))
            fail_box.setText(self.T("critical_err").format(message))
            fail_box.exec()

            self.version_combo.setEnabled(True)
            self.btn_execute.setEnabled(True)
            self.btn_cancel.setEnabled(True)
            self.beta_checkbox.setEnabled(True)
            if hasattr(self, "env_info_lbl"):
                self.env_info_lbl.setEnabled(True)
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.setEnabled(True)

    def closeEvent(self, event):
        if self._is_closing:
            self.clean_up_resources()
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

        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            return

        self._in_cancel_prompt = True
        try:
            box = QMessageBox(self)
            if sys.platform != "darwin":
                box.setWindowIcon(self.get_app_icon())
            box.setWindowTitle(self.T("cancel_dialog_title"))
            box.setText(self.T("cancel_dialog_desc").format(self.current_version))
            box.setIcon(QMessageBox.Icon.Question)

            btn_return = box.addButton(self.T("btn_return"), QMessageBox.ButtonRole.YesRole)
            btn_exit = box.addButton(self.T("btn_exit"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(self.T("btn_stay"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_return)
            box.exec()

            clicked = box.clickedButton()
            if clicked == btn_return:
                self._graceful_quit_app(relaunch_main=True)
            elif clicked == btn_exit:
                self._graceful_quit_app(relaunch_main=False)
            else:
                self.status_icon_lbl.setText("❌")
                self.status_lbl.setText(self.T("select_release"))
        finally:
            self._in_cancel_prompt = False


class MainBranchCommitFetchThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, lang="EN"):
        super().__init__()
        self.lang = lang

    def T(self, key):
        return LOCALES.get(self.lang, LOCALES["EN"]).get(key, key)

    def run(self):
        url = f"https://api.github.com/repos/JeremKOYTB/TriCoreDownloader/commits/main?t={int(time.time())}"
        _tlog("Fetching latest commit information for main branch...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TriCoreDownloader-Updater'})
            with urlopen_safe(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))

            sha = data.get("sha", "")[:7]
            commit_info = data.get("commit", {})
            message = commit_info.get("message", self.T("no_changelog"))
            author_info = commit_info.get("author", {})
            date_str = author_info.get("date", "").replace("T", " ").replace("Z", "")

            _tlog(f"Loaded latest main commit: {sha} ({date_str})")
            html_output = (
                f"<div style='margin-bottom: 4px;'><b style='color: #C4A1FF;'>{self.T('latest_commit')}</b> <code style='background-color: #2D2D36; padding: 2px 4px; border-radius: 4px; color: #FFFFFF;'>{sha}</code></div>"
                f"<div style='margin-bottom: 4px;'><b style='color: #8A8A95;'>{self.T('commit_date')}</b> <span style='color: #E8E8E8;'>{date_str}</span></div>"
                f"<hr style='border: none; border-top: 1px solid #4A4A55; margin: 6px 0;'>"
                f"<div><b style='color: #FFFFFF;'>{self.T('commit_notes')}</b></div>"
                f"<div style='color: #E8E8E8; white-space: pre-wrap; margin-top: 4px;'>{message}</div>"
            )
            self.finished.emit(html_output)
        except Exception as e:
            _tlog(f"Failed to load main branch commit: {e}", "WARN")
            self.finished.emit(f"<div style='color: #EF5350;'>{self.T('err_commit_api').format(e)}</div>")


def handle_interrupt(window_instance):
    _tlog("Interrupt signal received in terminal.")
    window_instance.handle_cancel()


_UPDATER_STARTED = False


def main():
    global _UPDATER_STARTED
    if _UPDATER_STARTED:
        return
    _UPDATER_STARTED = True

    _relocate_and_relaunch_if_needed()

    _tlog(f"Starting TriCoreDownloader Updater GUI (current app version: {APP_VERSION})")
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = UpdaterWindow(APP_VERSION)
    window.show()

    timer = QTimer(app)
    timer.start(350)
    timer.timeout.connect(lambda: None)
    signal.signal(signal.SIGINT, lambda sig, frame: handle_interrupt(window))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda sig, frame: window._graceful_quit_app(relaunch_main=False))

    exit_code = app.exec()
    timer.stop()
    window.clean_up_resources()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    _tlog(f"Updater exited with code {exit_code}.")
    sys.exit(exit_code)


run_updater = main

if __name__ == "__main__" or "--updater" in sys.argv:
    main()
