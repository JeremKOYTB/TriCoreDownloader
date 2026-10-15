import binascii
import concurrent.futures
import hashlib
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PyQt6.QtCore import QThread, pyqtSignal
import requests
from requests.adapters import HTTPAdapter
import urllib3
from urllib3.connection import HTTPConnection
from urllib3.util.retry import Retry

from .switch_core import NSPRepacker, SwitchCore, _write_bytes_fast
from .worker_ops import WorkerOperations

try:
    from ..config import APPDATA_DIR, IS_STORE_PYTHON
except Exception:
    APPDATA_DIR = None
    IS_STORE_PYTHON = False

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RE_DEVICE_ID = re.compile(r"device_id=[a-fA-F0-9]+", re.IGNORECASE)
RE_DID = re.compile(r"did:[a-fA-F0-9]+", re.IGNORECASE)


class _FastTCPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        sock_opts = list(HTTPConnection.default_socket_options) + [
            (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        pool_kwargs["socket_options"] = sock_opts
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _detect_os_and_arch_for_log(unknown_str=""):
    if sys.platform == "win32":
        os_str = "Windows"
    elif sys.platform == "darwin":
        os_str = "macOS"
    elif sys.platform.startswith("linux"):
        os_str = "Linux"
    else:
        os_str = unknown_str

    raw_m = (platform.machine() or "").strip().lower()
    arch_str = unknown_str

    if sys.platform == "darwin":
        is_arm = raw_m.startswith("arm64") or raw_m.startswith("aarch64")
        if not is_arm and hasattr(os, "uname"):
            try:
                um = (os.uname().machine or "").strip().lower()
                if um.startswith("arm64") or um.startswith("aarch64"):
                    is_arm = True
            except Exception:
                pass
        if not is_arm:
            for k in ("hw.optional.arm64", "sysctl.proc_translated"):
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", k],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=1,
                    )
                    if res.stdout.strip() == "1":
                        is_arm = True
                        break
                except Exception:
                    pass
        if is_arm:
            arch_str = f"arm64 / Apple Silicon ({platform.architecture()[0]})"
        elif raw_m in ("x86_64", "amd64", "x64"):
            arch_str = f"x64 / Intel ({platform.architecture()[0]})"
        elif raw_m:
            arch_str = f"{raw_m} ({platform.architecture()[0]})"
    else:
        if raw_m in ("amd64", "x86_64", "x64"):
            norm = "x64" if sys.platform == "win32" else "x86_64"
            arch_str = f"{norm} ({platform.architecture()[0]})"
        elif raw_m.startswith("arm64") or raw_m.startswith("aarch64"):
            arch_str = f"arm64 ({platform.architecture()[0]})"
        elif raw_m:
            arch_str = f"{raw_m} ({platform.architecture()[0]})"

    return os_str, arch_str


class DownloaderWorker(QThread, WorkerOperations):
    log_signal = pyqtSignal(str)
    log_replace_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, version, config):
        super().__init__()
        self.version = version
        self.config = config
        self.lang = config.get("lang", "en")
        self.env = "lp1"
        self.is_running = True
        self.start_time = time.time()

        self.seen_titles, self.queued_ncas = set(), set()
        self.expected_hashes, self.expected_sizes = {}, {}
        self.update_files, self.update_dls = [], []
        self.verified_files = set()
        self._active_procs = set()
        self._last_progress_msg = ""
        self._last_emitted_pct = -1
        self._privacy_notice_shown = False
        (
            self.sv_nca_fat,
            self.sv_nca_exfat,
            self.device_id,
            self.user_agent,
        ) = ("", "", None, None)

        self.pfs0_map = {
            "tik": [],
            "cert": [],
            "meta_nca": [],
            "meta_xml": [],
            1: [],
            2: [],
            3: [],
            4: [],
            5: [],
            6: [],
        }

        self._dl_lock = threading.Lock()

        self.use_aria2c = self.config.get("use_aria2c", False)
        self.aria2c_path = (
            self.config.get("aria2c_path", "") if self.use_aria2c else None
        )

        if APPDATA_DIR is not None:
            appdata_base = str(APPDATA_DIR)
            self.keys_dir = os.path.join(appdata_base, "temp_keys")
        else:
            if sys.platform == "win32":
                appdata_base = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
            elif sys.platform == "darwin":
                appdata_base = os.path.expanduser("~/Library/Application Support")
            else:
                appdata_base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            self.keys_dir = os.path.join(appdata_base, "TriCoreDownloader", "temp_keys")

        self.req_cert_crt = os.path.join(self.keys_dir, "switch_client.crt")
        self.req_cert_key = os.path.join(self.keys_dir, "switch_client.key")

        self.http_session = requests.Session()
        adapter = _FastTCPAdapter(
            max_retries=Retry(
                total=5,
                backoff_factor=0.2,
                status_forcelist=[429, 500, 502, 503, 504],
            ),
            pool_connections=64,
            pool_maxsize=64,
            pool_block=False,
        )
        self.http_session.mount("https://", adapter)
        self.http_session.mount("http://", adapter)
        self.http_session.headers.update({"Connection": "keep-alive"})

        self.core = None
        self._strings_cache = None

    def T(self, key, default=None):
        if self._strings_cache is None:
            from ..Languages.locales import STRINGS
            lang_key = str(self.lang).lower()
            self._strings_cache = STRINGS.get(lang_key) or STRINGS.get(lang_key.upper()) or STRINGS.get("en", {})
        return self._strings_cache.get(key, default if default is not None else key)

    def sanitize_log(self, text):
        if not isinstance(text, str):
            return text
        adv_logs = self.config.get("advanced_logs", False)
        redact = self.config.get("redact_privacy_info", False)

        if not adv_logs or redact:
            if getattr(self, "device_id", None):
                text = text.replace(self.device_id, "[REDACTED_DID]")
                if len(self.device_id) >= 8:
                    text = text.replace(self.device_id[:8], "[REDACTED_DID]")
            text = RE_DEVICE_ID.sub("device_id=[REDACTED_DID]", text)
            text = RE_DID.sub("did:[REDACTED_DID]", text)

        return text

    def log(self, text):
        self.log_signal.emit(self.sanitize_log(text))

    def log_adv(self, text, raw=False):
        if not self.config.get("advanced_logs", False):
            return
        clean_text = self.sanitize_log(text)
        if raw:
            self.log_signal.emit(clean_text)
        else:
            now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.log_signal.emit(f"[{now}] {clean_text}")

    def _emit_privacy_status_banner(self):
        if not self.config.get("advanced_logs", False) or self._privacy_notice_shown:
            return
        self._privacy_notice_shown = True

        if self.config.get("redact_privacy_info", False):
            self.log_signal.emit(self.T("log_privacy_redacted_active"))
        elif not self.config.get("hide_privacy_warning", False):
            self.log_signal.emit(self.T("log_privacy_warn_title"))
            self.log_signal.emit(self.T("log_privacy_warn_msg1"))
            self.log_signal.emit(self.T("log_privacy_warn_msg2"))

    def _emit_progress_throttled(self, val, total=100):
        if val != self._last_emitted_pct or val in (0, 100):
            self._last_emitted_pct = val
            self.progress_signal.emit(val, total)

    def update_text_progress(self, current, total, prefix="", is_first=False):
        if self.config.get("advanced_logs", False):
            return
        pct = int((current / total) * 100) if total > 0 else 100
        bars = int((current / total) * 20) if total > 0 else 20

        empty_char = " " if sys.platform == "win32" or os.name == "nt" else "░"
        bar_str = "█" * bars + empty_char * (20 - bars)

        msg = f"{prefix} [{bar_str}] {pct:>3}%"
        msg = self.sanitize_log(msg)

        if is_first:
            self._last_progress_msg = msg
            self.log_signal.emit(msg)
        elif msg != self._last_progress_msg or current >= total:
            self._last_progress_msg = msg
            self.log_replace_signal.emit(msg)

    def _verify_sandbox_persistence(self):
        try:
            os.makedirs(self.keys_dir, exist_ok=True)
            if sys.platform != "win32":
                try:
                    os.chmod(self.keys_dir, 0o700)
                except OSError:
                    pass

            test_lock = os.path.join(self.keys_dir, ".persistence_lock")
            with open(test_lock, "w", encoding="utf-8") as f:
                f.write("PERSIST_VALIDATION")

            if os.path.exists(test_lock):
                try:
                    os.remove(test_lock)
                except OSError:
                    pass

        except Exception as e:
            raise RuntimeError(self.T("err_nx_temp_storage").format(e))

    def dlfile(self, url, out, fhash=None, force_requests=False, expected_size=None):
        try:
            super().dlfile(
                url,
                out,
                fhash=fhash,
                force_requests=force_requests,
                expected_size=expected_size,
            )
        except Exception as e:
            if str(e) == "STOPPED":
                raise
            if "atumn.hac." in url:
                fallback_url = url.replace("atumn.hac.", "sun.hac.")
                self.log_adv(
                    self.T("log_http_cdn_fallback").format(os.path.basename(out))
                )
                try:
                    super().dlfile(
                        fallback_url,
                        out,
                        fhash=fhash,
                        force_requests=force_requests,
                        expected_size=expected_size,
                    )
                    return
                except Exception as fb_err:
                    if str(fb_err) == "STOPPED":
                        raise RuntimeError("STOPPED")
            raise e

    def nin_request(self, method, url, **kwargs):
        try:
            return super().nin_request(method, url, **kwargs)
        except requests.exceptions.HTTPError as e:
            if (
                e.response is not None
                and e.response.status_code == 404
                and "010000000000081b" in url.lower()
            ):
                raise e
            if "atumn.hac." in url:
                fallback_url = url.replace("atumn.hac.", "sun.hac.")
                self.log_adv(self.T("log_http_cdn_fallback").format(url))
                try:
                    return super().nin_request(method, fallback_url, **kwargs)
                except Exception:
                    pass
            raise e
        except Exception as e:
            if str(e) == "STOPPED":
                raise
            if "atumn.hac." in url:
                fallback_url = url.replace("atumn.hac.", "sun.hac.")
                self.log_adv(self.T("log_http_cdn_fallback").format(url))
                try:
                    return super().nin_request(method, fallback_url, **kwargs)
                except Exception:
                    pass
            raise e

    def _download_cnmt_nca_fast(self, p, cnmt_id, cnmt_nca):
        expected_prefix = cnmt_id.lower()[:32]
        if os.path.isfile(cnmt_nca) and os.path.getsize(cnmt_nca) >= 0xC00:
            try:
                with open(cnmt_nca, "rb") as f:
                    existing_bytes = f.read()
                if hashlib.sha256(existing_bytes).hexdigest()[:32] == expected_prefix:
                    return existing_bytes
            except OSError:
                pass

        url = f"https://atumn.hac.{self.env}.d4c.nintendo.net/c/{p}/{cnmt_id}?device_id={self.device_id}"
        resp = self.nin_request("GET", url)
        data = resp.content
        full_sha256 = hashlib.sha256(data).hexdigest()
        if full_sha256[:32] != expected_prefix:
            raise RuntimeError(self.T("err_hash_corrupt").format(os.path.basename(cnmt_nca)))

        _write_bytes_fast(cnmt_nca, data)
        with self._dl_lock:
            self.expected_hashes[cnmt_nca] = full_sha256
            self.expected_sizes[cnmt_nca] = len(data)
        self._mark_verified(cnmt_nca)
        return data

    def dltitle(self, title_id, version, is_su=False):
        if not self.is_running:
            raise RuntimeError("STOPPED")

        t_id_lower = str(title_id).lower()

        if (
            self.config.get("exclude_exfat", False)
            and t_id_lower == "010000000000081b"
        ):
            self.log_adv(
                self.T("log_skip_exfat").format(t_id_lower)
            )
            return

        key = (t_id_lower, version, is_su)
        with self._dl_lock:
            if key in self.seen_titles:
                return
            self.seen_titles.add(key)

        p = "s" if is_su else "a"
        try:
            resp = self.nin_request(
                "HEAD",
                f"https://atumn.hac.{self.env}.d4c.nintendo.net/t/{p}/{title_id}/{version}?device_id={self.device_id}",
            )
            cnmt_id = resp.headers["X-Nintendo-Content-ID"]
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                if t_id_lower == "010000000000081b":
                    with self._dl_lock:
                        self.sv_nca_exfat = ""
                return
            raise
        except Exception as e:
            if str(e) == "STOPPED":
                raise RuntimeError("STOPPED")
            if t_id_lower == "010000000000081b":
                with self._dl_lock:
                    self.sv_nca_exfat = ""
            return

        if is_su:
            self.log_adv(self.T("log_adv_dl_su_cnmt").format(cnmt_id))

        cnmt_nca = os.path.join(self.raw_dir, f"{cnmt_id}.cnmt.nca")
        with self._dl_lock:
            if cnmt_nca not in self.update_files:
                self.update_files.append(cnmt_nca)
            if cnmt_nca not in self.pfs0_map["meta_nca"]:
                self.pfs0_map["meta_nca"].append(cnmt_nca)

        cnmt_raw_bytes = self._download_cnmt_nca_fast(p, cnmt_id, cnmt_nca)
        parsed_data = self.core.parse_cnmt(cnmt_nca, self.raw_dir, nca_bytes=cnmt_raw_bytes)

        if is_su:
            workers = min(20, max(8, (os.cpu_count() or 4) * 2))
            self.log_adv(self.T("log_adv_su_pool").format(workers, len(parsed_data)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [
                    ex.submit(self.dltitle, n_t_id, ver, False)
                    for n_t_id, ver, _ in parsed_data
                ]
                try:
                    for f in concurrent.futures.as_completed(futures):
                        if not self.is_running:
                            for fut in futures:
                                fut.cancel()
                            raise RuntimeError("STOPPED")
                        f.result()
                except Exception:
                    for fut in futures:
                        fut.cancel()
                    raise
        else:
            added_count = 0
            with self._dl_lock:
                for nca_id, nca_hash, entry_type in parsed_data:
                    if t_id_lower == "0100000000000809":
                        self.sv_nca_fat = f"{nca_id}.nca"
                    elif t_id_lower == "010000000000081b":
                        self.sv_nca_exfat = f"{nca_id}.nca"

                    if nca_id not in self.queued_ncas:
                        self.queued_ncas.add(nca_id)
                        added_count += 1
                        nca_target = os.path.join(self.raw_dir, f"{nca_id}.nca")
                        self.update_files.append(nca_target)

                        if entry_type in self.pfs0_map:
                            self.pfs0_map[entry_type].append(nca_target)

                        nca_sz = self.core.nca_sizes.get(nca_id, 0)
                        self.expected_hashes[nca_target] = nca_hash
                        if nca_sz > 0:
                            self.expected_sizes[nca_target] = nca_sz

                        if not os.path.exists(nca_target) or (
                            nca_sz > 0 and os.path.getsize(nca_target) != nca_sz
                        ):
                            self.update_dls.append((
                                f"https://atumn.hac.{self.env}.d4c.nintendo.net/c/c/{nca_id}?device_id={self.device_id}",
                                self.raw_dir,
                                f"{nca_id}.nca",
                                nca_hash,
                            ))
            self.log_adv(
                self.T("log_adv_title_cnmt").format(
                    t_id_lower, version, cnmt_id, added_count
                )
            )

    def _resolve_firmware_identity(self, ver_raw, ver_string_simple):
        real_ver_raw = getattr(self.core, "system_update_ver_raw", 0) or ver_raw
        v_maj = (real_ver_raw >> 26) & 0x3F
        v_min = (real_ver_raw >> 20) & 0x3F
        v_s1 = (real_ver_raw >> 16) & 0xF
        v_bld = real_ver_raw & 0xFFFF
        real_full_ver = f"{v_maj}.{v_min}.{v_s1}.{v_bld:04d}"

        sdk_title = ""
        comm_ver = ver_string_simple
        sdk_found = False

        if not getattr(self, "sv_nca_fat", ""):
            self.log_adv(self.T("log_adv_ident_skip"))
            return None

        sv_path = os.path.join(self.raw_dir, self.sv_nca_fat)
        if not os.path.exists(sv_path):
            self.log_adv(self.T("log_adv_ident_missing").format(sv_path))
            return None

        if self.core is not None:
            ram_comm_ver, ram_sdk_title = self.core.extract_romfs_identity_in_ram(sv_path)
            if ram_sdk_title:
                if ram_comm_ver:
                    comm_ver = ram_comm_ver
                sdk_title = ram_sdk_title
                sdk_found = True
                self.log_adv(self.T("log_adv_ident_ram_ok").format(comm_ver, sdk_title))

        if not sdk_found:
            configured_hactool = self.config.get("hactool", "").strip()
            default_bin = "hactool.exe" if sys.platform == "win32" else "hactool"
            hactool_bin = configured_hactool or shutil.which(default_bin) or default_bin
            prod_keys = self.config.get("prod_keys", "")

            tmp_romfs = os.path.join(self.raw_dir, f"_ident_romfs_{int(time.time())}")
            try:
                cmd = [hactool_bin, "-k", prod_keys, sv_path, f"--romfsdir={tmp_romfs}"]
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    **({"creationflags": 0x08000000} if sys.platform == "win32" or os.name == "nt" else {})
                )
                if res.returncode != 0:
                    err_msg = res.stderr.decode(errors="ignore").strip()
                    self.log_adv(self.T("log_adv_ident_err").format(err_msg))
                elif os.path.exists(tmp_romfs):
                    raw_data = b""
                    target_file = os.path.join(tmp_romfs, "file")
                    if os.path.exists(target_file):
                        with open(target_file, "rb") as vf:
                            raw_data = vf.read()
                    else:
                        for r, _, fls in os.walk(tmp_romfs):
                            for fl in fls:
                                with open(os.path.join(r, fl), "rb") as vf:
                                    raw_data += vf.read()

                    if raw_data and len(raw_data) >= 0x100:
                        disp_ver = raw_data[0x68:0x80].split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                        disp_sdk = raw_data[0x80:0x100].split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                        if disp_ver:
                            comm_ver = disp_ver
                        if disp_sdk.startswith("NintendoSDK"):
                            sdk_title = disp_sdk
                            sdk_found = True

                    if not sdk_found:
                        m = re.search(rb"NintendoSDK Firmware for NX [0-9.-]+", raw_data)
                        if m:
                            sdk_title = m.group(0).decode("utf-8")
                            sdk_found = True

                    if sdk_found:
                        self.log_adv(self.T("log_adv_ident_hactool_ok").format(comm_ver, sdk_title))
            except Exception as e:
                self.log_adv(self.T("log_adv_ident_err").format(e))
            finally:
                if os.path.exists(tmp_romfs):
                    shutil.rmtree(tmp_romfs, ignore_errors=True)

        if sdk_found and sdk_title:
            identity_line = f"Firmware {comm_ver} ({sdk_title}) ({real_full_ver})"
            self.log_adv(self.T("log_adv_ident_resolved").format(identity_line))
            return identity_line

        return None

    def run(self):
        work_dir = ""
        try:
            adv = self.config.get("advanced_logs", False)
            self._verify_sandbox_persistence()

            os_str, arch_str = _detect_os_and_arch_for_log(self.T("sys_unknown_val"))
            is_frozen = getattr(sys, "frozen", False)
            build_mode_str = (
                self.T("sys_compiled_edition")
                if is_frozen
                else self.T("sys_source_edition")
            )

            py_distro = (
                self.T("log_env_ms_store")
                if (IS_STORE_PYTHON or self.config.get("is_store_python", False))
                else self.T("log_env_standard")
            )

            self.log_adv("==================================================", raw=True)
            self.log_adv(self.T("log_adv_banner_pre"), raw=True)
            self.log_adv("==================================================", raw=True)
            self.log_adv(self.T("log_env_hw"))
            self.log_adv(self.T("log_env_os").format(os_str))
            self.log_adv(self.T("log_env_plat").format(platform.platform()))
            self.log_adv(self.T("log_env_arch").format(arch_str))
            self.log_adv(self.T("log_env_mode").format(f"{build_mode_str} ({py_distro})"))
            self.log_adv(self.T("log_env_py").format(f"{platform.python_version()} ({py_distro})"))
            self.log_adv(
                self.T("log_env_req").format(
                    requests.__version__, getattr(urllib3, "__version__", "")
                )
            )

            cfg_hactool = self.config.get("hactool", "NOT SET")
            self.log_adv(self.T("log_env_hactool").format(cfg_hactool))

            if cfg_hactool and os.path.isfile(cfg_hactool):
                if sys.platform != "win32":
                    try:
                        st = os.stat(cfg_hactool)
                        if not (st.st_mode & 0o111):
                            os.chmod(cfg_hactool, st.st_mode | 0o111)
                    except Exception:
                        pass

            cfg_keys = self.config.get("prod_keys", "NOT SET")
            self.log_adv(self.T("log_env_keys").format(cfg_keys))
            self.log_adv(self.T("log_env_prodinfo").format(self.config.get("prodinfo", "NOT SET")))
            self.log_adv(self.T("log_env_outdir").format(self.config.get("output_dir", "NOT SET")))

            self.aria2c_enabled = (
                self.use_aria2c
                and bool(self.aria2c_path)
                and os.path.exists(self.aria2c_path)
            )
            if self.aria2c_enabled and sys.platform != "win32" and os.path.isfile(self.aria2c_path):
                try:
                    st = os.stat(self.aria2c_path)
                    if not (st.st_mode & 0o111):
                        os.chmod(self.aria2c_path, st.st_mode | 0o111)
                except OSError:
                    pass

            engine_desc = (
                self.T("log_env_engine_aria").format(self.aria2c_path)
                if self.aria2c_enabled
                else self.T("log_env_engine_req")
            )
            self.log_adv(self.T("log_env_dl_engine").format(engine_desc))
            self.log_adv(self.T("log_adv_sandbox_ok").format(self.keys_dir))

            self.log_adv("\n==================================================", raw=True)
            self.log_adv(self.T("log_adv_banner_crypto"), raw=True)
            self.log_adv("==================================================", raw=True)

            bis_key_00 = None
            bis_key_00_crypt = None
            bis_key_00_tweak = None
            ssl_rsa_keks = []
            raw_key_dict = {}
            total_parsed_keys = 0

            with open(
                self.config["prod_keys"],
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    total_parsed_keys += 1
                    k, v = line.split("=", 1)
                    k_str, v_str = k.strip().lower(), v.strip()

                    try:
                        val_bytes = bytes.fromhex(v_str)
                        raw_key_dict[k_str] = val_bytes
                    except ValueError:
                        continue

                    if k_str in ("bis_key_00", "bis_key_0", "bis_key0"):
                        bis_key_00 = val_bytes
                    elif k_str in ("bis_key_00_crypt", "bis_key_0_crypt", "bis_key0_crypt"):
                        bis_key_00_crypt = val_bytes
                    elif k_str in ("bis_key_00_tweak", "bis_key_0_tweak", "bis_key0_tweak"):
                        bis_key_00_tweak = val_bytes

                    if "ssl_rsa_kek" in k_str and not k_str.endswith(("_source_x", "_seed_y", "_source")):
                        if len(val_bytes) == 16 and val_bytes not in ssl_rsa_keks:
                            ssl_rsa_keks.append(val_bytes)

            if not bis_key_00 and bis_key_00_crypt and bis_key_00_tweak:
                bis_key_00 = bis_key_00_crypt + bis_key_00_tweak

            if not ssl_rsa_keks:
                mk0 = raw_key_dict.get("master_key_00") or raw_key_dict.get("master_key_0")
                kek_gen_src = raw_key_dict.get("aes_kek_generation_source")
                ssl_src_x = raw_key_dict.get("ssl_rsa_kek_source_x")
                ssl_seed_y = raw_key_dict.get("ssl_rsa_kek_seed_y") or raw_key_dict.get("aes_key_generation_source")
                if mk0 and kek_gen_src and ssl_src_x and ssl_seed_y and len(mk0) == 16:
                    try:
                        backend_k = default_backend()
                        d1 = Cipher(algorithms.AES(mk0), modes.ECB(), backend=backend_k).decryptor()
                        kek0 = d1.update(kek_gen_src) + d1.finalize()
                        d2 = Cipher(algorithms.AES(kek0), modes.ECB(), backend=backend_k).decryptor()
                        src_kek = d2.update(ssl_src_x) + d2.finalize()
                        d3 = Cipher(algorithms.AES(src_kek), modes.ECB(), backend=backend_k).decryptor()
                        derived_ssl_kek = d3.update(ssl_seed_y) + d3.finalize()
                        if len(derived_ssl_kek) == 16:
                            ssl_rsa_keks.append(derived_ssl_kek)
                    except Exception:
                        pass

            bis_status = "OK (32 B)" if (bis_key_00 and len(bis_key_00) == 32) else "MISSING"
            self.log_adv(
                self.T("log_adv_keys_loaded").format(
                    bis_status, len(ssl_rsa_keks), total_parsed_keys
                )
            )

            if not ssl_rsa_keks:
                raise ValueError(self.T("err_nx_ssl_kek_missing"))

            sector_size = 0x8000
            self.log_adv(
                self.T("log_adv_cal0_read").format(sector_size, self.config["prodinfo"])
            )
            with open(self.config["prodinfo"], "rb") as pf:
                encrypted_data = pf.read(sector_size)

            if len(encrypted_data) < 0x3BF0:
                raise ValueError(self.T("err_nx_prodinfo_decrypt"))

            if encrypted_data[:4] == b"CAL0":
                decrypted_data = encrypted_data
                self.log_adv(self.T("log_adv_cal0_raw"))
            else:
                if not bis_key_00 or len(bis_key_00) != 32:
                    raise ValueError(self.T("err_nx_bis_key_missing"))

                backend = default_backend()
                dec_chunks = []
                num_cal_sectors = (len(encrypted_data) + 0x3FFF) // 0x4000
                for sec_idx in range(num_cal_sectors):
                    sec_slice = encrypted_data[sec_idx * 0x4000 : (sec_idx + 1) * 0x4000]
                    if len(sec_slice) < 16:
                        break
                    tweak = sec_idx.to_bytes(16, "little")
                    cipher = Cipher(
                        algorithms.AES(bis_key_00), modes.XTS(tweak), backend=backend
                    )
                    decryptor = cipher.decryptor()
                    dec_chunks.append(decryptor.update(sec_slice) + decryptor.finalize())
                decrypted_data = b"".join(dec_chunks)
                self.log_adv(self.T("log_adv_cal0_decrypt"))

            if decrypted_data[:4] != b"CAL0":
                raise ValueError(self.T("err_nx_prodinfo_decrypt"))

            device_id_bytes = decrypted_data[0x2B56 : 0x2B56 + 0x10]
            self.device_id = device_id_bytes.decode("utf-8", errors="ignore").strip("\x00")

            def _cal0_log_bridge(stage, args):
                if stage == "cert_der":
                    self.log_adv(self.T("log_adv_cert_der").format(*args))
                elif stage == "rsa_recover":
                    self.log_adv(self.T("log_adv_rsa_recover"))
                elif stage == "cal0_hash_warn":
                    self.log_adv(self.T("warn_nx_cal0_body_hash"))
                elif stage == "cert_hash_warn":
                    self.log_adv(self.T("warn_nx_cal0_cert_hash"))

            cert_pem, key_pem = SwitchCore.extract_client_cert_and_key(
                decrypted_data, ssl_rsa_keks, log_cb=_cal0_log_bridge, tr_cb=self.T
            )

            self._verify_sandbox_persistence()
            _write_bytes_fast(self.req_cert_crt, cert_pem)
            _write_bytes_fast(self.req_cert_key, key_pem)

            if sys.platform != "win32":
                try:
                    os.chmod(self.req_cert_key, 0o600)
                except OSError:
                    pass

            if not (
                os.path.exists(self.req_cert_crt)
                and os.path.getsize(self.req_cert_crt) > 0
                and os.path.exists(self.req_cert_key)
                and os.path.getsize(self.req_cert_key) > 0
            ):
                raise RuntimeError(self.T("err_nx_temp_cert_fail"))

            self.log_adv(
                self.T("log_adv_tls_ready").format(len(cert_pem), len(key_pem))
            )

            self.http_session.cert = (self.req_cert_crt, self.req_cert_key)
            self.http_session.verify = False

            fw_ua_ver = self.version if self.version else "23.0.1"
            self.user_agent = (
                f"NintendoSDK Firmware for NX {fw_ua_ver}-1.0 (platform:NX;"
                f" did:{self.device_id}; eid:{self.env})"
            )
            self.log_adv(
                self.T("log_env_ident").format(self.device_id, self.env, self.user_agent)
            )
            self._emit_privacy_status_banner()

            self.core = SwitchCore(
                self.config,
                self.device_id,
                self.env,
                self.user_agent,
                self.log_adv,
                self.T,
            )

            self.log_adv("\n==================================================", raw=True)
            self.log_adv(self.T("log_adv_banner_meta"), raw=True)
            self.log_adv("==================================================", raw=True)

            if not self.version:
                self.log_adv(self.T("log_query_cdn"))
                resp = self.nin_request(
                    "GET",
                    f"https://sun.hac.{self.env}.d4c.nintendo.net/v1/system_update_meta?device_id={self.device_id}",
                )
                meta_json_data = resp.json()
                ver_raw = meta_json_data["system_update_metas"][0]["title_version"]

                v_maj = (ver_raw >> 26) & 0x3F
                v_min = (ver_raw >> 20) & 0x3F
                v_s1 = (ver_raw >> 16) & 0xF
                ver_string_simple = f"{v_maj}.{v_min}.{v_s1}"
                self.log_adv(
                    self.T("log_adv_cdn_latest_resolved").format(ver_string_simple, ver_raw)
                )
            else:
                ver_string_simple = self.version
                parts = list(map(int, self.version.split(".")))
                if len(parts) == 3:
                    parts.append(0)
                ver_raw = (
                    (parts[0] << 26)
                    | (parts[1] << 20)
                    | (parts[2] << 16)
                    | parts[3]
                )
                self.log_adv(
                    self.T("log_adv_ver_encoded").format(ver_string_simple, ver_raw)
                )

            work_dir = os.path.join(
                self.config["output_dir"], f"Firmware {ver_string_simple}"
            )
            out_zip = f"{work_dir}.zip"

            if os.path.exists(work_dir) or os.path.exists(out_zip):
                self.log(self.T("log_auto_delete"))
                if os.path.exists(work_dir):
                    try:
                        shutil.rmtree(work_dir, ignore_errors=True)
                    except Exception:
                        pass
                if os.path.exists(out_zip):
                    try:
                        os.remove(out_zip)
                    except Exception:
                        pass
                time.sleep(0.05)

            self.raw_dir = work_dir
            os.makedirs(self.raw_dir, exist_ok=True)

            self._emit_progress_throttled(0, 100)
            self.log(self.T("log_dl_fw").format(ver_string_simple))

            try:
                self.log_adv(self.T("log_adv_head_check").format(ver_raw))
                self.nin_request(
                    "HEAD",
                    f"https://atumn.hac.{self.env}.d4c.nintendo.net/t/s/0100000000000816/{ver_raw}?device_id={self.device_id}",
                )
            except Exception as e:
                if str(e) == "STOPPED":
                    raise RuntimeError("STOPPED")
                raise RuntimeError("INCOMPLETE_FIRMWARE")

            if not self.is_running:
                raise RuntimeError("STOPPED")

            if not adv:
                self.update_text_progress(
                    0, 2, self.T("log_dl_cnmt"), is_first=True
                )

            self.dltitle("0100000000000816", ver_raw, is_su=True)
            if not adv:
                self.update_text_progress(1, 2, self.T("log_dl_cnmt"))
            self._emit_progress_throttled(5, 100)

            if not getattr(self, "sv_nca_exfat", "") and not self.config.get(
                "exclude_exfat", False
            ):
                self.log_adv(self.T("log_exfat_fallback"))
                self.dltitle("010000000000081b", ver_raw, is_su=False)
                if not getattr(self, "sv_nca_exfat", ""):
                    self.log_adv(self.T("log_exfat_missing"))
            elif self.config.get("exclude_exfat", False):
                self.log_adv(self.T("log_exfat_excluded"))

            if not adv:
                self.update_text_progress(2, 2, self.T("log_dl_cnmt"))
            self._emit_progress_throttled(10, 100)

            if not self.is_running:
                raise RuntimeError("STOPPED")

            self.update_dls.sort(
                key=lambda item: self.expected_sizes.get(os.path.join(item[1], item[2]), 0),
                reverse=True,
            )

            self.log_adv("\n==================================================", raw=True)
            self.log_adv(self.T("log_adv_banner_dl"), raw=True)
            self.log_adv("==================================================", raw=True)

            self.dlfiles(self.update_dls)

            if not self.is_running:
                raise RuntimeError("STOPPED")

            self.log_adv("\n==================================================", raw=True)
            self.log_adv(self.T("log_adv_banner_verify"), raw=True)
            self.log_adv("==================================================", raw=True)

            total_val = len(self.expected_hashes)
            val_completed = 0
            verify_workers = min(8, max(4, os.cpu_count() or 4))

            self.log_adv(
                self.T("log_verify_crypto").format(total_val, verify_workers)
            )

            if not adv:
                self.log("")
                self.update_text_progress(
                    0, total_val, self.T("log_verifying_files"), is_first=True
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=verify_workers
            ) as ex:
                futures = [
                    ex.submit(self._verify_single_file, p, eh)
                    for p, eh in self.expected_hashes.items()
                ]

                for f in concurrent.futures.as_completed(futures):
                    if not self.is_running:
                        for fut in futures:
                            fut.cancel()
                        raise RuntimeError("STOPPED")

                    path, computed_hash, expected_hash = f.result()

                    if computed_hash != expected_hash.lower():
                        self.log_adv(
                            self.T("log_hash_failed").format(
                                os.path.basename(path), expected_hash.lower(), computed_hash
                            )
                        )
                        raise RuntimeError(
                            self.T("err_hash_corrupt").format(os.path.basename(path))
                        )
                    else:
                        fsize = os.path.getsize(path) if os.path.exists(path) else 0
                        exp_sz = self.expected_sizes.get(path, 0)
                        if exp_sz > 0 and fsize != exp_sz:
                            raise RuntimeError(
                                self.T("err_hash_corrupt").format(os.path.basename(path))
                            )
                        self.log_adv(
                            self.T("log_hash_match").format(
                                os.path.basename(path), fsize, computed_hash[:16]
                            )
                        )

                    val_completed += 1
                    if not adv:
                        self.update_text_progress(
                            val_completed, total_val, self.T("log_verifying_files")
                        )
                    self._emit_progress_throttled(
                        80 + int((val_completed / total_val) * 10), 100
                    )

            if not self.is_running:
                raise RuntimeError("STOPPED")

            for expected_path in self.update_files:
                if not os.path.isfile(expected_path) or os.path.getsize(expected_path) == 0:
                    raise RuntimeError("INCOMPLETE_FIRMWARE")

            file_paths = []
            for root, dirs, files in os.walk(self.raw_dir):
                dirs.sort()
                files.sort()
                for name in files:
                    if not name.startswith(".") and not name.endswith(".tmp"):
                        file_paths.append(os.path.join(root, name))

            file_paths.sort(
                key=lambda p: os.path.relpath(p, start=self.raw_dir).replace("\\", "/")
            )

            if len(file_paths) < len(self.update_files):
                raise RuntimeError("INCOMPLETE_FIRMWARE")

            total_size_bytes = sum(os.path.getsize(p) for p in file_paths)
            if total_size_bytes < (50 * 1024 * 1024):
                raise RuntimeError("INCOMPLETE_FIRMWARE")

            fw_identity_line = self._resolve_firmware_identity(ver_raw, ver_string_simple)

            self.log_adv("\n==================================================", raw=True)
            self.log_adv(self.T("log_adv_banner_pack"), raw=True)
            self.log_adv("==================================================", raw=True)
            self.log_adv(self.T("log_compressing_zip"))

            total_files = len(file_paths)
            if not adv:
                self.log("")
                self.update_text_progress(
                    0, total_files, self.T("log_compressing_zip"), is_first=True
                )

            build_nsp = self.config.get("build_nsp", False)

            with ZipFile(out_zip, "w", compression=ZIP_STORED) as zf:
                for i, full in enumerate(file_paths, 1):
                    if not self.is_running:
                        raise RuntimeError("STOPPED")

                    rel = os.path.relpath(full, start=self.raw_dir).replace("\\", "/")

                    try:
                        os.utime(full, (1780315200, 1780315200))
                    except Exception:
                        pass

                    zinfo = ZipInfo.from_file(full, arcname=rel)
                    zinfo.date_time = (2026, 1, 1, 0, 0, 0)
                    zinfo.create_system = 0
                    zinfo.external_attr = 0
                    zinfo.compress_type = ZIP_STORED

                    with open(full, "rb") as src:
                        raw_bytes = src.read()
                        crc_hex = f"{binascii.crc32(raw_bytes) & 0xFFFFFFFF:08X}"
                        zf.writestr(zinfo, raw_bytes)

                    self.log_adv(
                        self.T("log_zip_file").format(rel, zinfo.file_size, crc_hex)
                    )

                    if not adv:
                        self.update_text_progress(
                            i, total_files, self.T("log_compressing_zip")
                        )
                    if build_nsp:
                        self._emit_progress_throttled(
                            90 + int((i / total_files) * 5), 100
                        )
                    else:
                        self._emit_progress_throttled(
                            90 + int((i / total_files) * 10), 100
                        )

            if build_nsp:
                out_nsp = f"{work_dir}.nsp"
                self.log_adv(self.T("log_building_nsp"))

                if not adv:
                    self.log("")
                    self.update_text_progress(
                        0,
                        total_files,
                        self.T("log_building_nsp"),
                        is_first=True,
                    )

                try:
                    if os.path.exists(out_nsp):
                        os.remove(out_nsp)

                    def _nsp_progress_cb(current, total):
                        if not adv:
                            self.update_text_progress(
                                current,
                                total,
                                self.T("log_building_nsp"),
                            )
                        self._emit_progress_throttled(
                            95 + int((current / total) * 5), 100
                        )

                    repacker = NSPRepacker(
                        out_nsp,
                        self.pfs0_map,
                        log_callback=lambda m: self.log_adv(m) if adv else None,
                        progress_callback=_nsp_progress_cb,
                        tr_callback=self.T,
                    )
                    repacker.repack()

                    if repacker.verify_integrity():
                        nsp_sha256 = repacker.sha256_hash
                        if not nsp_sha256:
                            if hasattr(hashlib, "file_digest"):
                                with open(out_nsp, "rb") as f:
                                    nsp_sha256 = hashlib.file_digest(f, "sha256").hexdigest()
                            else:
                                h_nsp = hashlib.sha256()
                                with open(out_nsp, "rb") as f:
                                    for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                                        h_nsp.update(chunk)
                                nsp_sha256 = h_nsp.hexdigest()
                        self.log(
                            self.T("log_nsp_created").format(
                                os.path.basename(out_nsp)
                            )
                        )
                        self.log(
                            self.T("log_nsp_sha256").format(nsp_sha256)
                        )
                    else:
                        self.log(self.T("log_nsp_failed"))

                except Exception:
                    self.log(self.T("log_nsp_failed"))

            shutil.rmtree(self.raw_dir, ignore_errors=True)

            if not self.is_running:
                raise RuntimeError("STOPPED")

            self.log_adv(self.T("log_calc_final_sig"))

            if hasattr(hashlib, "file_digest"):
                with open(out_zip, "rb") as f:
                    zip_sha256 = hashlib.file_digest(f, "sha256").hexdigest()
            else:
                h_sha256 = hashlib.sha256()
                with open(out_zip, "rb") as f:
                    for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                        h_sha256.update(chunk)
                zip_sha256 = h_sha256.hexdigest()

            elapsed_time = time.time() - self.start_time

            self.log("\n==================================================")
            self.log(self.T("log_dl_complete"))
            if fw_identity_line:
                self.log(fw_identity_line)
                self.log("")
            self.log(self.T("log_del_temp"))
            self.log(self.T("log_time_elapsed").format(f"{elapsed_time:.2f}"))
            self.log(self.T("log_archive_created").format(os.path.basename(out_zip)))
            self.log(self.T("log_zip_sha256").format(zip_sha256))
            self.log("")
            self.log(self.T("log_all_verified"))
            self.log(self.T("log_ready_offline"))
            self.log("==================================================")

            self.finished_signal.emit(True, work_dir)

        except Exception as e:
            error_str = str(e)

            if error_str == "STOPPED":
                if work_dir and os.path.exists(work_dir):
                    try:
                        shutil.rmtree(work_dir, ignore_errors=True)
                    except Exception:
                        pass

                self.log("\n==================================================")
                self.log(self.T("log_cancelled"))
                self.log("==================================================")
                self.finished_signal.emit(False, "STOPPED")
                return

            self.log("\n==================================================")
            self.log(self.T("log_crit_halt"))
            self.log("==================================================")

            if "INCOMPLETE_FIRMWARE" in error_str:
                reason = self.T("log_err_incomplete")
                reason_label = self.T("log_reason")
                self.log(f" {reason_label} {reason}")
            else:
                self.log(self.T("log_fatal_suspend"))
                self.log("")
                self.log(self.T("log_fail_cause").format(type(e).__name__))
                self.log(self.T("log_fail_detail").format(error_str))
                if self.config.get("advanced_logs", False):
                    self.log(self.T("log_tech_trace"))
                    for ligne in traceback.format_exc().strip().split("\n"):
                        self.log(f"   {ligne}")

            self.log(self.T("log_purge_success"))
            self.log("==================================================")

            try:
                if work_dir and os.path.exists(work_dir):
                    shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

            self.finished_signal.emit(False, error_str)

        finally:
            self.http_session.close()
            if os.path.exists(self.keys_dir):
                try:
                    shutil.rmtree(self.keys_dir, ignore_errors=True)
                    self.log_adv(self.T("log_adv_cleanup_sandbox"))
                except Exception:
                    pass

    def stop(self):
        self.is_running = False
        self._dl_lock.acquire()
        try:
            procs = list(getattr(self, "_active_procs", []))
        finally:
            self._dl_lock.release()
        for proc in procs:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
