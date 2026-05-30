import os
import time
import shutil
import hashlib
import binascii
import threading
import concurrent.futures
import platform
import traceback
import re
from datetime import datetime
from zipfile import ZipFile, ZIP_STORED, ZipInfo

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.exceptions import HTTPError
from anynet import tls

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from PyQt6.QtCore import QThread, pyqtSignal

from .worker_ops import WorkerOperations
from .switch_core import SwitchCore, NSPRepacker

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class DownloaderWorker(QThread, WorkerOperations):
    log_signal = pyqtSignal(str)
    log_replace_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, version, config):
        super().__init__()
        print(f"[NX WORKER] Booting worker. Target FW: {version}")
        self.version = version
        self.config = config
        self.lang = config.get("lang", "en")
        self.env = "lp1"
        self.is_running = True
        self.start_time = time.time()
        
        self.seen_titles, self.queued_ncas = set(), set()
        self.expected_hashes, self.update_files, self.update_dls = {}, [], []
        self.sv_nca_fat, self.sv_nca_exfat, self.device_id, self.user_agent = "", "", None, None
        
        self.pfs0_map = {
            "tik": [], "cert": [], "meta_nca": [], "meta_xml": [],
            1: [], 2: [], 3: [], 4: [], 5: [], 6: []
        }
        
        self._dl_lock = threading.Lock()
        
        self.cdn_hosts = [
            f"atumn.hac.{self.env}.d4c.nintendo.net",
            f"sun.hac.{self.env}.d4c.nintendo.net"
        ]
        self.active_cdn_idx = 0

        self.use_aria2c = self.config.get("use_aria2c", False)
        self.aria2c_path = self.config.get("aria2c_path", "") if self.use_aria2c else None

        appdata_base = os.environ.get("APPDATA", "")
        if not appdata_base:
            appdata_base = os.path.expanduser("~\\AppData\\Roaming")
            
        self.keys_dir = os.path.join(appdata_base, "TriCoreDownloader", "temp_keys")
        self.req_cert_crt = os.path.join(self.keys_dir, "switch_client.crt")
        self.req_cert_key = os.path.join(self.keys_dir, "switch_client.key")
        
        self.http_session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=5, 
                backoff_factor=0.3, 
                status_forcelist=[429, 500, 502, 503, 504]
            ), 
            pool_connections=128, 
            pool_maxsize=128
        )
        self.http_session.mount("https://", adapter)
        self.http_session.mount("http://", adapter)
        
        self.core = None

    def T(self, key, default=None):
        from ..Languages.locales import STRINGS
        return STRINGS.get(self.lang, STRINGS.get("en", {})).get(key, default or key)

    def sanitize_log(self, text):
        if not isinstance(text, str): return text
        adv_logs = self.config.get("advanced_logs", False)
        redact = self.config.get("redact_privacy_info", False)

        if not adv_logs or redact:
            if getattr(self, "device_id", None):
                text = text.replace(self.device_id, "[REDACTED_DID]")
                if len(self.device_id) >= 8:
                    text = text.replace(self.device_id[:8], "[REDACTED_DID]")
            text = re.sub(r'device_id=[a-fA-F0-9]+', 'device_id=[REDACTED_DID]', text)
            text = re.sub(r'did:[a-fA-F0-9]+', 'did:[REDACTED_DID]', text)

        return text

    def log(self, text): 
        self.log_signal.emit(self.sanitize_log(text))

    def log_adv(self, text, raw=False):
        text = self.sanitize_log(text)
        if self.config.get("advanced_logs", False):
            if raw: self.log_signal.emit(text)
            else:
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.log_signal.emit(f"[{now}] {text}")

            if not self.config.get("hide_privacy_warning", False):
                if "device_id=" in text.lower() or "did:" in text.lower() or "[redacted_did]" in text.lower():
                    if "PRIVACY WARNING" not in text and "AVERTISSEMENT" not in text:
                        self.log_signal.emit(self.T("log_privacy_warn_title"))
                        self.log_signal.emit(self.T("log_privacy_warn_msg1"))
                        self.log_signal.emit(self.T("log_privacy_warn_msg2"))

    def update_text_progress(self, current, total, prefix="", is_first=False):
        if self.config.get("advanced_logs", False): return
        pct = int((current / total) * 100) if total > 0 else 100
        bars = int((current / total) * 20) if total > 0 else 20
        bar_str = "█" * bars + "░" * (20 - bars)
        
        msg = f"{prefix} [{bar_str}] {pct:>3}%"
        msg = self.sanitize_log(msg)
        
        if is_first: self.log_signal.emit(msg)
        else: self.log_replace_signal.emit(msg)

    def _verify_sandbox_persistence(self):
        try:
            os.makedirs(self.keys_dir, exist_ok=True)
            if platform.system() != "Windows":
                os.chmod(self.keys_dir, 0o700)
                
            test_lock = os.path.join(self.keys_dir, ".persistence_lock")
            with open(test_lock, "w") as f:
                f.write("PERSIST_VALIDATION")
            
            if os.path.exists(test_lock):
                try: os.remove(test_lock)
                except OSError: pass
                    
        except Exception as e:
            raise RuntimeError(f"Erreur d'accès au stockage temporaire : {e}")

    def _apply_sticky_cdn(self, url):
        for host in self.cdn_hosts:
            if host in url:
                with self._dl_lock:
                    active_host = self.cdn_hosts[self.active_cdn_idx]
                return url.replace(host, active_host)
        return url

    def dlfile(self, url, out_path, force_requests=False):
        last_e = None
        for attempt in range(3):
            sticky_url = self._apply_sticky_cdn(url)
            try:
                super().dlfile(sticky_url, out_path, force_requests=force_requests)
                return
            except Exception as e:
                if str(e) == "STOPPED": raise
                last_e = e
                with self._dl_lock:
                    current_host = self.cdn_hosts[self.active_cdn_idx]
                    if current_host in sticky_url:
                        self.active_cdn_idx = (self.active_cdn_idx + 1) % len(self.cdn_hosts)
        raise last_e

    def nin_request(self, method, url, **kwargs):
        last_e = None
        for attempt in range(3):
            sticky_url = self._apply_sticky_cdn(url)
            try:
                return super().nin_request(method, sticky_url, **kwargs)
            except HTTPError as e:
                if e.response is not None and e.response.status_code == 404 and "010000000000081b" in url.lower():
                    raise e 
                last_e = e
                with self._dl_lock:
                    current_host = self.cdn_hosts[self.active_cdn_idx]
                    if current_host in sticky_url:
                        self.active_cdn_idx = (self.active_cdn_idx + 1) % len(self.cdn_hosts)
            except Exception as e:
                if str(e) == "STOPPED": raise
                last_e = e
                with self._dl_lock:
                    current_host = self.cdn_hosts[self.active_cdn_idx]
                    if current_host in sticky_url:
                        self.active_cdn_idx = (self.active_cdn_idx + 1) % len(self.cdn_hosts)
        raise last_e

    def dltitle(self, title_id, version, is_su=False):
        if not self.is_running: raise RuntimeError("STOPPED")
        
        t_id_lower = str(title_id).lower()
        
        if self.config.get("exclude_exfat", False) and t_id_lower == "010000000000081b":
            self.log_adv(self.T("log_skip_exfat", "Skipped exFAT title.").format(t_id_lower))
            return
            
        key = (t_id_lower, version, is_su)
        with self._dl_lock:
            if key in self.seen_titles: return
            self.seen_titles.add(key)
        
        self.log_adv(f"Processing Title: {t_id_lower} (Ver: {version})")
        
        p = "s" if is_su else "a"
        try: 
            resp = self.nin_request("HEAD", f"https://atumn.hac.{self.env}.d4c.nintendo.net/t/{p}/{title_id}/{version}?device_id={self.device_id}")
            cnmt_id = resp.headers["X-Nintendo-Content-ID"]
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                self.log_adv(f"INFO: Title {t_id_lower} version {version} not found (404).")
                if t_id_lower == "010000000000081b":
                    with self._dl_lock: self.sv_nca_exfat = ""
                return
            raise
        except Exception as e:
            if str(e) == "STOPPED": raise RuntimeError("STOPPED")
            if t_id_lower == "010000000000081b": 
                with self._dl_lock: self.sv_nca_exfat = ""
            return
            
        cnmt_nca = os.path.join(self.raw_dir, f"{cnmt_id}.cnmt.nca")
        with self._dl_lock:
            self.update_files.append(cnmt_nca)
            self.pfs0_map["meta_nca"].append(cnmt_nca)
            
        if not os.path.exists(cnmt_nca): 
            self.dlfile(f"https://atumn.hac.{self.env}.d4c.nintendo.net/c/{p}/{cnmt_id}?device_id={self.device_id}", cnmt_nca, force_requests=True)
        
        parsed_data = self.core.parse_cnmt(cnmt_nca, self.raw_dir)
        
        if is_su:
            workers = min(16, (os.cpu_count() or 4) * 4)
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(self.dltitle, n_t_id, ver, False) for n_t_id, ver, _ in parsed_data]
                for f in concurrent.futures.as_completed(futures):
                    if not self.is_running: raise RuntimeError("STOPPED")
                    f.result()
        else:
            with self._dl_lock:
                for nca_id, nca_hash, entry_type in parsed_data:
                    if t_id_lower == "0100000000000809": self.sv_nca_fat = f"{nca_id}.nca"
                    elif t_id_lower == "010000000000081b": self.sv_nca_exfat = f"{nca_id}.nca"
                    
                    if nca_id not in self.queued_ncas:
                        self.queued_ncas.add(nca_id)
                        nca_target = os.path.join(self.raw_dir, f"{nca_id}.nca")
                        self.update_files.append(nca_target)
                        
                        if entry_type in self.pfs0_map:
                            self.pfs0_map[entry_type].append(nca_target)
                            
                        self.expected_hashes[nca_target] = nca_hash
                        if not os.path.exists(nca_target):
                            self.update_dls.append((f"https://atumn.hac.{self.env}.d4c.nintendo.net/c/c/{nca_id}?device_id={self.device_id}", self.raw_dir, f"{nca_id}.nca", nca_hash))

    def run(self):
        work_dir = ""
        persist_keys_on_disk = False
        try:
            adv = self.config.get("advanced_logs", False)
            print("[NX WORKER] Analyzing local environment and keys...")
            
            self._verify_sandbox_persistence()
            
            self.log_adv("==================================================", raw=True)
            self.log_adv("            PRE-FLIGHT ENVIRONMENT                ", raw=True)
            self.log_adv("==================================================\n", raw=True)
            self.log_adv(self.T("log_env_hw"))
            self.log_adv(self.T("log_env_plat").format(platform.platform()))
            self.log_adv(self.T("log_env_arch").format(f"{platform.machine()} ({platform.architecture()[0]})"))
            
            py_distro = self.T("log_env_ms_store", "Microsoft Store") if self.config.get("is_store_python", False) else self.T("log_env_standard", "Standard")
            self.log_adv(self.T("log_env_py").format(f"{platform.python_version()} ({py_distro})"))
            self.log_adv(self.T("log_env_req").format(requests.__version__))
            
            cfg_hactool = self.config.get("hactool", "NOT SET")
            self.log_adv(self.T("log_env_hactool").format(cfg_hactool))
            
            cfg_keys = self.config.get("prod_keys", "NOT SET")
            self.log_adv(self.T("log_env_keys").format(cfg_keys))
            
            print("[NX WORKER] Decrypting PRODINFO to safely extract Device ID...")
            try:
                bis_key_00 = None
                with open(self.config["prod_keys"], 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("bis_key_00"):
                            bis_key_00 = bytes.fromhex(line.split('=', 1)[1].strip())
                            break

                if not bis_key_00:
                    raise ValueError("bis_key_00 missing from prod.keys")

                with open(self.config["prodinfo"], "rb") as pf:
                    encrypted_data = pf.read()

                if encrypted_data[:4] == b"CAL0":
                    decrypted_data = encrypted_data
                else:
                    sector_size = 0x4000
                    decrypted_data = bytearray()
                    backend = default_backend()

                    for i in range(0, len(encrypted_data), sector_size):
                        chunk = encrypted_data[i:i+sector_size]
                        if len(chunk) < 16:
                            decrypted_data += chunk
                            continue
                            
                        tweak = (i // sector_size).to_bytes(16, 'little')
                        cipher = Cipher(algorithms.AES(bis_key_00), modes.XTS(tweak), backend=backend)
                        decryptor = cipher.decryptor()
                        decrypted_data += decryptor.update(chunk)
                    
                    decrypted_data = bytes(decrypted_data)

                if decrypted_data[:4] != b"CAL0":
                    raise ValueError("Failed to decrypt PRODINFO. Invalid file or bad key.")

                device_id_bytes = decrypted_data[0x2b56 : 0x2b56 + 0x10]
                self.device_id = device_id_bytes.decode("utf-8").strip('\x00')
                print(f"[NX WORKER] Successfully extracted Device ID: {self.device_id[:8]}...")
                
            except Exception as e:
                self.log_adv(f"[-] FATAL: PRODINFO decryption error: {e}")
                raise RuntimeError(f"Invalid PRODINFO (Decryption failed): {e}")
                
            self.user_agent = f"NintendoSDK Firmware/11.0.0-0 (platform:NX; did:{self.device_id}; eid:{self.env})"
            self.log_adv(self.T("log_env_ident").format(self.device_id[:8], self.env))
            
            self.core = SwitchCore(self.config, self.device_id, self.env, self.user_agent, self.log_adv, self.T)
            
            print("[NX WORKER] Extracting and mounting client TLS certificates...")
            pem_data = open(self.config["cert_pem"], "rb").read()
            cert = tls.TLSCertificate.parse(pem_data, tls.TYPE_PEM)
            priv = tls.TLSPrivateKey.parse(pem_data, tls.TYPE_PEM)
            
            self._verify_sandbox_persistence()
            cert.save(self.req_cert_crt, tls.TYPE_PEM)
            priv.save(self.req_cert_key, tls.TYPE_PEM)
            
            self.http_session.cert = (self.req_cert_crt, self.req_cert_key)
            self.http_session.verify = False
            
            self.aria2c_enabled = self.use_aria2c and bool(self.aria2c_path) and os.path.exists(self.aria2c_path)

            print("[NX WORKER] Querying target firmware identifiers...")
            if not self.version:
                self.log_adv(self.T("log_query_cdn"), raw=True)
                resp = self.nin_request("GET", f"https://sun.hac.{self.env}.d4c.nintendo.net/v1/system_update_meta?device_id={self.device_id}")
                meta_json_data = resp.json()
                ver_raw = meta_json_data["system_update_metas"][0]["title_version"]
                
                v_maj = (ver_raw >> 26) & 0x3F
                v_min = (ver_raw >> 20) & 0x3F
                v_s1  = (ver_raw >> 16) & 0xF
                v_s2  = ver_raw & 0xFFFF
                
                ver_string_simple = f"{v_maj}.{v_min}.{v_s1}"
            else:
                ver_string_simple = self.version
                parts = list(map(int, self.version.split(".")))
                if len(parts) == 3: parts.append(0)
                ver_raw = (parts[0] << 26) | (parts[1] << 20) | (parts[2] << 16) | parts[3]

            work_dir = os.path.join(self.config["output_dir"], f"Firmware {ver_string_simple}")
            out_zip = f"{work_dir}.zip"

            if os.path.exists(work_dir) or os.path.exists(out_zip):
                self.log(self.T("log_auto_delete", f"{ver_string_simple} already exists. Deleting for a clean download..."))
                if os.path.exists(work_dir):
                    try: shutil.rmtree(work_dir, ignore_errors=True)
                    except: pass
                if os.path.exists(out_zip):
                    try: os.remove(out_zip)
                    except: pass
                time.sleep(0.5)

            self.raw_dir = work_dir
            os.makedirs(self.raw_dir, exist_ok=True)

            self.progress_signal.emit(0, 100)
            self.log(self.T("log_dl_fw").format(ver_string_simple))
            
            try:
                self.nin_request("HEAD", f"https://atumn.hac.{self.env}.d4c.nintendo.net/t/s/0100000000000816/{ver_raw}?device_id={self.device_id}")
            except Exception as e:
                if str(e) == "STOPPED": raise RuntimeError("STOPPED")
                raise RuntimeError("INCOMPLETE_FIRMWARE")

            if not self.is_running: raise RuntimeError("STOPPED")

            if not adv:
                self.update_text_progress(0, 2, self.T("log_dl_cnmt"), is_first=True)

            print("[NX WORKER] Building dependency map...")
            self.dltitle("0100000000000816", ver_raw, is_su=True)
            if not adv: self.update_text_progress(1, 2, self.T("log_dl_cnmt"))
            self.progress_signal.emit(5, 100)

            if not getattr(self, "sv_nca_exfat", "") and not self.config.get("exclude_exfat", False):
                self.log_adv(self.T("log_exfat_fallback", "INFO: exFAT not found via meta — direct attempt 010000000000081b…"))
                self.dltitle("010000000000081b", ver_raw, is_su=False)
                if not getattr(self, "sv_nca_exfat", ""):
                    self.log_adv(self.T("log_exfat_missing", "INFO: No separate SystemVersion exFAT found for this firmware version."))
            elif self.config.get("exclude_exfat", False):
                self.log_adv(self.T("log_exfat_excluded", "ExFAT Firmware Excluded."))

            if not adv: self.update_text_progress(2, 2, self.T("log_dl_cnmt"))
            self.progress_signal.emit(10, 100)

            if not self.is_running: raise RuntimeError("STOPPED")

            print(f"[NX WORKER] Executing multithreaded download of {len(self.update_dls)} fragments...")
            self.dlfiles(self.update_dls)

            if not self.is_running:
                raise RuntimeError("STOPPED")

            self.log_adv(self.T("log_verify_crypto"), raw=True)
            print("[NX WORKER] Verifying cryptographic signatures...")
            
            total_val = len(self.expected_hashes)
            val_completed = 0
            
            if not adv:
                self.log("")
                self.update_text_progress(0, total_val, self.T("log_verifying_files"), is_first=True)
            
            verify_workers = min(32, (os.cpu_count() or 4) * 2)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=verify_workers) as ex:
                futures = [ex.submit(self._verify_single_file, p, eh) for p, eh in self.expected_hashes.items()]
                
                for f in concurrent.futures.as_completed(futures):
                    if not self.is_running:
                        raise RuntimeError("STOPPED")
                    
                    path, computed_hash, expected_hash = f.result()
                    
                    if computed_hash != expected_hash.lower():
                        print(f"[NX WORKER ERROR] Hash mismatch on {path}")
                        self.log_adv(self.T("log_hash_failed").format(os.path.basename(path), expected_hash.lower(), computed_hash))
                        raise RuntimeError(self.T("err_hash_corrupt").format(os.path.basename(path)))
                    else:
                        self.log_adv(self.T("log_hash_match").format(os.path.basename(path)))
                        
                    val_completed += 1
                    if not adv:
                        self.update_text_progress(val_completed, total_val, self.T("log_verifying_files"))
                    self.progress_signal.emit(80 + int((val_completed / total_val) * 10), 100)

            if not self.is_running: raise RuntimeError("STOPPED")

            file_paths = []
            for root, dirs, files in os.walk(self.raw_dir):
                dirs.sort()
                files.sort()
                for name in files: file_paths.append(os.path.join(root, name))
            file_paths.sort()

            total_size_bytes = sum(os.path.getsize(p) for p in file_paths)
            if total_size_bytes < (50 * 1024 * 1024):
                raise RuntimeError("INCOMPLETE_FIRMWARE")

            self.log_adv(self.T("log_compressing_zip"), raw=True)
            print("[NX WORKER] Consolidating and packaging firmware into ZIP...")
            
            total_files = len(file_paths)
            if not adv:
                self.log("") 
                self.update_text_progress(0, total_files, self.T("log_compressing_zip"), is_first=True)
                
            build_nsp = self.config.get("build_nsp", False)
            
            with ZipFile(out_zip, "w", compression=ZIP_STORED) as zf:
                for i, full in enumerate(file_paths, 1):
                    if not self.is_running: raise RuntimeError("STOPPED")
                    rel = os.path.relpath(full, start=self.raw_dir)
                    file_size = os.path.getsize(full)
                    
                    try: os.utime(full, (1780315200, 1780315200))
                    except: pass
                    
                    zinfo = ZipInfo.from_file(full, arcname=rel)
                    zinfo.date_time = (2026, 1, 1, 0, 0, 0)
                    zinfo.create_system = 0
                    zinfo.external_attr = 0 
                    zinfo.compress_type = ZIP_STORED
                    
                    crc = 0
                    with open(full, "rb") as src, zf.open(zinfo, "w") as dest:
                        while True:
                            chunk = src.read(4194304)
                            if not chunk:
                                break
                            crc = binascii.crc32(chunk, crc)
                            dest.write(chunk)
                    
                    self.log_adv(self.T("log_zip_file").format(rel, file_size, f"{crc & 0xFFFFFFFF:08X}"))
                    
                    if not adv:
                        self.update_text_progress(i, total_files, self.T("log_compressing_zip"))
                    if build_nsp:
                        self.progress_signal.emit(90 + int((i / total_files) * 5), 100) # ZIP prend 90-95%
                    else:
                        self.progress_signal.emit(90 + int((i / total_files) * 10), 100) # ZIP prend 90-100%

            if build_nsp:
                out_nsp = f"{work_dir}.nsp"
                self.log_adv(self.T("log_building_nsp", "Building NSP..."), raw=True)
                print("[NX WORKER] Repacking raw files into NSP...")
                
                if not adv:
                    self.log("")
                    self.update_text_progress(0, total_files, self.T("log_building_nsp", "Building NSP..."), is_first=True)
                
                try:
                    if os.path.exists(out_nsp):
                        os.remove(out_nsp)
                        
                    def _nsp_progress_cb(current, total):
                        if not adv:
                            self.update_text_progress(current, total, self.T("log_building_nsp", "Building NSP..."))
                        self.progress_signal.emit(95 + int((current / total) * 5), 100) # NSP prend 95-100%
                        
                    repacker = NSPRepacker(
                        out_nsp, 
                        self.pfs0_map, 
                        log_callback=lambda m: self.log_adv(m) if adv else None,
                        progress_callback=_nsp_progress_cb
                    )
                    repacker.repack()
                    
                    if repacker.verify_integrity():
                        h_nsp = hashlib.sha256()
                        with open(out_nsp, "rb") as f:
                            for chunk in iter(lambda: f.read(4194304), b""):
                                h_nsp.update(chunk)
                        nsp_sha256 = h_nsp.hexdigest()
                        self.log(self.T("log_nsp_created", "NSP created: {}").format(os.path.basename(out_nsp)))
                        self.log(self.T("log_nsp_sha256", "NSP SHA256: {}").format(nsp_sha256))
                    else:
                        self.log(self.T("log_nsp_failed", "NSP compilation failed. Only ZIP is provided."))
                        
                except Exception as e:
                    print(f"[NX WORKER ERROR] NSP Repacking failed: {e}")
                    self.log(self.T("log_nsp_failed", "NSP compilation failed. Only ZIP is provided."))

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
                    for chunk in iter(lambda: f.read(4194304), b""): 
                        h_sha256.update(chunk)
                zip_sha256 = h_sha256.hexdigest()
                
            elapsed_time = time.time() - self.start_time

            self.log("\n==================================================")
            self.log(self.T("log_dl_complete"))
            self.log(self.T("log_del_temp"))
            self.log(self.T("log_time_elapsed").format(f"{elapsed_time:.2f}"))
            self.log(self.T("log_archive_created").format(os.path.basename(out_zip)))
            self.log(self.T("log_zip_sha256").format(zip_sha256))
            self.log(self.T("log_all_verified"))
            self.log(self.T("log_ready_offline"))
            self.log("==================================================")
            
            print("[NX WORKER] Concluded. Retaining keys on success.")
            self.finished_signal.emit(True, work_dir)

        except Exception as e:
            error_str = str(e)
            print(f"[NX WORKER FATAL] Caught Exception: {error_str}")
            
            if error_str == "STOPPED":
                if work_dir and os.path.exists(work_dir):
                    try: shutil.rmtree(work_dir, ignore_errors=True)
                    except: pass
                    
                self.log("\n==================================================")
                self.log(self.T("log_cancelled", "Download cancelled cleanly."))
                self.log("==================================================")
                
                if os.path.exists(self.keys_dir):
                    try: shutil.rmtree(self.keys_dir, ignore_errors=True)
                    except: pass
                
                self.finished_signal.emit(False, "STOPPED")
                return

            persist_keys_on_disk = True
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
            except:
                pass
                
            self.finished_signal.emit(False, error_str)
            
        finally:
            self.http_session.close()
            if not persist_keys_on_disk and os.path.exists(self.keys_dir):
                try:
                    shutil.rmtree(self.keys_dir, ignore_errors=True)
                except:
                    pass

    def stop(self): 
        print("[NX WORKER] Interruption signal invoked.")
        self.is_running = False