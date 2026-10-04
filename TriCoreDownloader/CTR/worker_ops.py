import csv
import re
import struct
import time
import stat
import requests
from requests.adapters import HTTPAdapter
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .core_3ds import build_cia, get_sig_len, verify_built_cia

CDNS = [
    "https://nus.cdn.c.shop.nintendowifi.net/ccs/download", 
    "https://nus.cdn.t.shop.nintendowifi.net/ccs/download", 
    "https://nus.c.shop.nintendowifi.net/ccs/download",     
    "https://ccs.cdn.c.shop.nintendowifi.net/ccs/download", 
    "https://nus.cdn.shop.wii.com/ccs/download"             
]

SHARED_SESSION = requests.Session()
_adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=3, pool_block=False)
SHARED_SESSION.mount('http://', _adapter)
SHARED_SESSION.mount('https://', _adapter)
SHARED_SESSION.verify = False
SHARED_SESSION.headers.update({
    'User-Agent': 'Nintendo 3DS (CTR-001)',
    'Connection': 'keep-alive'
})

RE_FW = re.compile(r"(\d+)\.(\d+)\.(\d+)-(\d+)")
STRUCT_BE_I = struct.Struct(">I")
STRUCT_BE_H = struct.Struct(">H")
STRUCT_BE_Q = struct.Struct(">Q")

def parse_fw_string(fw_str: str) -> tuple:
    match = RE_FW.search(fw_str)
    if match:
        return tuple(int(x) for x in match.groups())
    return (0, 0, 0, 0)

def _safe_unlink(path: Path):
    if path.exists():
        try:
            path.unlink()
        except PermissionError:
            try:
                path.chmod(stat.S_IWRITE)
                path.unlink()
            except Exception:
                pass
        except OSError:
            pass

def download_in_memory(url: str, is_stopped_cb=None, retries=3, log_cb=None, T_cb=None, adv_logs=False) -> tuple:
    for attempt in range(retries):
        if is_stopped_cb and is_stopped_cb():
            return None, "STOPPED"
        if adv_logs and log_cb:
            log_cb(f"  [HTTP GET] -> {url} ({attempt + 1}/{retries})")
            
        try:
            r = SHARED_SESSION.get(url, timeout=(5, 10))
            status = r.status_code
            
            if status == 200:
                content = r.content
                if adv_logs and log_cb and T_cb:
                    log_cb(f"  [HTTP 200 OK] " + T_cb("log_http_res").format(status, len(content)))
                return content, status
            else:
                if adv_logs and log_cb:
                    log_cb(f"  [HTTP ERR {status}] -> {url}")
                if attempt == retries - 1:
                    return None, status
                    
        except Exception as e:
            if adv_logs and log_cb:
                log_cb(f"  [HTTP FAIL] {e}")
            if attempt == retries - 1:
                return None, str(e)
            
        time.sleep(0.5)
        
    return None, "TIMEOUT"

def get_yls_db(sys_type: str, is_stopped_cb=None) -> dict:
    url = f"https://yls8.mtheall.com/ninupdates/titlelist.php?sys={sys_type}&csv=1"
    csv_data, status = download_in_memory(url, is_stopped_cb)
    if not csv_data:
        return {}

    lines = csv_data.decode('utf-8', errors='ignore').splitlines()
    db = {}
    reader = csv.reader(lines)
    next(reader, None) 

    for row in reader:
        if len(row) < 4:
            continue
        t_id, region = row[0].strip().upper(), row[1].strip().upper()
        t_vers, f_vers = row[2].strip().split(), row[3].strip().split()
        
        if region not in db:
            db[region] = {}
        if t_id not in db[region]:
            db[region][t_id] = []
        
        for tv_str, fv_str in zip(t_vers, f_vers):
            tv_clean = int(tv_str[1:]) if tv_str.startswith('v') else int(tv_str)
            db[region][t_id].append((parse_fw_string(fv_str), tv_clean))
            
    return db

def download_raw_files(title_id: str, output_dir: Path, version: int, T_cb, is_stopped_cb=None, log_cb=None, advanced_logs=False) -> tuple:
    tmd_data, cetk_data = None, None
    successful_base_url = ""
    last_error = "UNKNOWN"

    if advanced_logs and log_cb:
        log_cb(T_cb("log_dl_start").format(title_id, version))

    for cdn in CDNS:
        if is_stopped_cb and is_stopped_cb():
            return False, "STOPPED"
        base_url = f"{cdn}/{title_id}"
        
        if not tmd_data:
            tmd_url = f"{base_url}/tmd.{version}" if version is not None else f"{base_url}/tmd"
            tmd_data, status = download_in_memory(tmd_url, is_stopped_cb, log_cb=log_cb, T_cb=T_cb, adv_logs=advanced_logs)
            if status != 200: 
                tmd_data = None
                last_error = status
                continue 
        
        if tmd_data and not cetk_data:
            tik_url = f"{base_url}/cetk"
            cetk_data, status = download_in_memory(tik_url, is_stopped_cb, log_cb=log_cb, T_cb=T_cb, adv_logs=advanced_logs)
            if cetk_data: 
                successful_base_url = base_url
                break 
            else:
                last_error = status

    if not tmd_data or not cetk_data: 
        if advanced_logs and log_cb:
            log_cb(T_cb("err_dl_fail_adv").format(title_id, last_error))
        return False, last_error

    (output_dir / "tmd.bin").write_bytes(tmd_data)
    (output_dir / "tik.bin").write_bytes(cetk_data)

    tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    content_count = STRUCT_BE_H.unpack_from(tmd_data, tmd_sig_len + 0x9E)[0]

    c_ids = []
    c_offset = tmd_sig_len + 0x9C4
    for i in range(content_count):
        off = c_offset + (i * 0x30)
        cid = tmd_data[off : off + 4].hex().lower()
        c_ids.append(cid)
        if advanced_logs and log_cb:
            log_cb(T_cb("log_tmd_cid").format(i, cid))

    servers_to_try = [successful_base_url] if successful_base_url else []
    for cdn in CDNS:
        url_candidate = f"{cdn}/{title_id}"
        if url_candidate not in servers_to_try:
            servers_to_try.append(url_candidate)

    for cid in c_ids:
        if is_stopped_cb and is_stopped_cb():
            return False, "STOPPED"
        content_path = output_dir / cid
        fragment_downloaded = False
        
        for base_url in servers_to_try:
            for attempt in range(3):
                try:
                    req_url = f"{base_url}/{cid}"
                    if advanced_logs and log_cb:
                        log_cb(T_cb("log_req_fragment").format(req_url))
                        
                    with SHARED_SESSION.get(req_url, stream=True, timeout=(5, 15)) as r:
                        if r.status_code == 200:
                            with open(content_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=1048576):
                                    if is_stopped_cb and is_stopped_cb():
                                        _safe_unlink(content_path)
                                        return False, "STOPPED"
                                    if chunk:
                                        f.write(chunk)
                            fragment_downloaded = True
                            if advanced_logs and log_cb:
                                log_cb(T_cb("log_frag_saved").format(content_path.stat().st_size))
                            break
                        else:
                            last_error = r.status_code
                            time.sleep(0.5)
                except Exception as e:
                    last_error = str(e)
                    time.sleep(0.5)
            if fragment_downloaded:
                break

        if not fragment_downloaded: 
            return False, last_error

    return True, 200

def verify_integrity(title_id: str, output_dir: Path, T_cb, is_stopped_cb=None, log_cb=None, advanced_logs=False) -> bool:
    tmd_path = output_dir / "tmd.bin"
    tik_path = output_dir / "tik.bin"
    if not tmd_path.exists() or not tik_path.exists():
        return False
    
    tmd_data = tmd_path.read_bytes()
    tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    content_count = STRUCT_BE_H.unpack_from(tmd_data, tmd_sig_len + 0x9E)[0]
    c_offset = tmd_sig_len + 0x9C4

    for i in range(content_count):
        if is_stopped_cb and is_stopped_cb():
            return False
        
        off = c_offset + (i * 0x30)
        cid = tmd_data[off : off + 4].hex().lower()
        expected_size = STRUCT_BE_Q.unpack_from(tmd_data, off + 8)[0]
        
        content_path = output_dir / cid
        try:
            if content_path.stat().st_size != expected_size:
                if advanced_logs and log_cb:
                    log_cb(T_cb("err_size_invalid"))
                return False
        except OSError:
            return False

    if advanced_logs and log_cb:
        log_cb(T_cb("log_pack_success").format(title_id))

    return True

def pack_cia(title_id: str, tmp_title_dir: Path, final_out_dir: Path, T_cb, boot9_path=None, is_stopped_cb=None, log_cb=None, decrypt=False, advanced_logs=False) -> bool:
    tmd_path = tmp_title_dir / "tmd.bin"
    tik_path = tmp_title_dir / "tik.bin"
    
    if not tmd_path.exists() or not tik_path.exists():
        return False
    
    tmd_data = tmd_path.read_bytes()
    cetk_data = tik_path.read_bytes()
        
    tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    actual_version = STRUCT_BE_H.unpack_from(tmd_data, tmd_sig_len + 0x9C)[0]
    
    cia_path = final_out_dir / f"{title_id}_v{actual_version}.cia"
    
    success = build_cia(
        title_id=title_id, 
        tmd_data=tmd_data, 
        cetk_data=cetk_data, 
        app_folder=tmp_title_dir, 
        out_cia_path=cia_path, 
        T_cb=T_cb,
        decrypt=decrypt, 
        boot9_path=boot9_path, 
        is_stopped_cb=is_stopped_cb, 
        log_cb=log_cb,
        advanced_logs=advanced_logs
    )
    
    if not success: 
        _safe_unlink(cia_path)
        return False

    is_valid, msg = verify_built_cia(cia_path, T_cb, log_cb=log_cb, advanced_logs=advanced_logs)
    if not is_valid:
        if log_cb:
            log_cb(T_cb("err_pack_cia") + f" : {msg}")
        _safe_unlink(cia_path)
        return False
    elif advanced_logs and log_cb:
        log_cb(T_cb("log_pack_success").format(cia_path.name))
    
    return True