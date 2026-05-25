import csv
import re
import struct
import time
import requests
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

def parse_fw_string(fw_str: str) -> tuple:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)-(\d+)", fw_str)
    if match: return tuple(int(x) for x in match.groups())
    return (0, 0, 0, 0)

def download_in_memory(url: str, is_stopped_cb=None, retries=3, log_cb=None, T_cb=None, adv_logs=False) -> tuple:
    user_agent = 'Nintendo 3DS (CTR-001)'
    headers = {'User-Agent': user_agent}
    session = requests.Session()
    
    for attempt in range(retries):
        if adv_logs and log_cb and T_cb:
            log_cb(T_cb("log_http_req").format(url, user_agent, attempt + 1, retries))
            
        try:
            r = session.get(url, headers=headers, timeout=10, verify=False)
            status = r.status_code
            
            if is_stopped_cb and is_stopped_cb():
                session.close()
                return None, "STOPPED"
                
            if status == 200:
                if adv_logs and log_cb and T_cb:
                    log_cb(T_cb("log_http_res").format(status, len(r.content)))
                data = r.content
                session.close()
                return data, status
            else:
                if adv_logs and log_cb and T_cb:
                    log_cb(T_cb("log_http_err").format(status, r.reason))
                if attempt == retries - 1:
                    session.close()
                    return None, status
                    
        except Exception as e:
            if adv_logs and log_cb and T_cb:
                log_cb(T_cb("log_http_fail").format(e))
            if attempt == retries - 1:
                session.close()
                return None, str(e)
            
        time.sleep(1)
        
    session.close()
    return None, "TIMEOUT"

def get_yls_db(sys_type: str, is_stopped_cb=None) -> dict:
    url = f"https://yls8.mtheall.com/ninupdates/titlelist.php?sys={sys_type}&csv=1"
    csv_data, status = download_in_memory(url, is_stopped_cb)
    if not csv_data: return {}

    lines = csv_data.decode('utf-8').splitlines()
    db = {}
    reader = csv.reader(lines)
    next(reader, None) 

    for row in reader:
        if len(row) < 4: continue
        t_id, region = row[0].strip().upper(), row[1].strip().upper()
        t_vers, f_vers = row[2].strip().split(), row[3].strip().split()
        
        if region not in db: db[region] = {}
        if t_id not in db[region]: db[region][t_id] = []
        
        for tv_str, fv_str in zip(t_vers, f_vers):
            tv_clean = int(tv_str.replace('v', '')) if tv_str.startswith('v') else int(tv_str)
            db[region][t_id].append((parse_fw_string(fv_str), tv_clean))
            
    return db

def download_raw_files(title_id: str, output_dir: Path, version: int, T_cb, is_stopped_cb=None, log_cb=None, advanced_logs=False) -> tuple:
    tmd_data, cetk_data = None, None
    successful_base_url = ""
    last_error = "UNKNOWN"

    if advanced_logs and log_cb:
        log_cb(T_cb("log_dl_start").format(title_id, version))

    for cdn in CDNS:
        if is_stopped_cb and is_stopped_cb(): return False, "STOPPED"
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
        if advanced_logs and log_cb: log_cb(T_cb("err_cdn_dl").format(title_id))
        return False, last_error

    (output_dir / "tmd.bin").write_bytes(tmd_data)
    (output_dir / "tik.bin").write_bytes(cetk_data)

    tmd_sig_type = struct.unpack(">I", tmd_data[0:4])[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    content_count = struct.unpack(">H", tmd_data[tmd_sig_len+0x9E : tmd_sig_len+0xA0])[0]
    
    if advanced_logs and log_cb:
        log_cb(T_cb("log_tmd_parsed").format(tmd_sig_type, content_count))

    c_ids = []
    c_offset = tmd_sig_len + 0x9C4
    for i in range(content_count):
        off = c_offset + (i * 0x30)
        cid = tmd_data[off:off+4].hex().lower()
        c_ids.append(cid)
        if advanced_logs and log_cb:
            log_cb(T_cb("log_tmd_cid").format(i, cid))

    servers_to_try = [successful_base_url] if successful_base_url else []
    servers_to_try += [f"{cdn}/{title_id}" for cdn in CDNS if f"{cdn}/{title_id}" not in servers_to_try]

    session = requests.Session()
    
    for cid in c_ids:
        if is_stopped_cb and is_stopped_cb():
            session.close()
            return False, "STOPPED"
        content_path = output_dir / cid
        fragment_downloaded = False
        
        for base_url in servers_to_try:
            for attempt in range(3):
                try:
                    req_url = f"{base_url}/{cid}"
                    if advanced_logs and log_cb: log_cb(T_cb("log_req_fragment").format(req_url))
                    
                    headers = {'User-Agent': 'Nintendo 3DS (CTR-001)'}
                    r = session.get(req_url, headers=headers, stream=True, timeout=15, verify=False)
                    
                    if r.status_code == 200:
                        with open(content_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=65536):
                                if is_stopped_cb and is_stopped_cb():
                                    f.close()
                                    session.close()
                                    return False, "STOPPED"
                                f.write(chunk)
                                
                        fragment_downloaded = True
                        if advanced_logs and log_cb: log_cb(T_cb("log_frag_saved").format(content_path.stat().st_size))
                        break
                    else:
                        last_error = r.status_code
                        if advanced_logs and log_cb: log_cb(T_cb("err_frag_http").format(r.status_code, req_url))
                        time.sleep(1)
                except Exception as e:
                    last_error = str(e)
                    if advanced_logs and log_cb: log_cb(T_cb("err_frag_fail").format(e))
                    time.sleep(1)
            if fragment_downloaded: break

        if not fragment_downloaded: 
            session.close()
            return False, last_error

    session.close()
    return True, 200

def verify_integrity(title_id: str, output_dir: Path, T_cb, is_stopped_cb=None, log_cb=None, advanced_logs=False) -> bool:
    tmd_path = output_dir / "tmd.bin"
    if not tmd_path.exists(): return False
    
    tmd_data = tmd_path.read_bytes()
    tmd_sig_type = struct.unpack(">I", tmd_data[0:4])[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    content_count = struct.unpack(">H", tmd_data[tmd_sig_len+0x9E : tmd_sig_len+0xA0])[0]
    c_offset = tmd_sig_len + 0x9C4

    for i in range(content_count):
        if is_stopped_cb and is_stopped_cb(): return False
        
        off = c_offset + (i * 0x30)
        cid = tmd_data[off:off+4].hex().lower()
        expected_size = struct.unpack(">Q", tmd_data[off+0x08 : off+0x10])[0]
        
        content_path = output_dir / cid
        if not content_path.exists(): return False

        actual_size = content_path.stat().st_size
        if actual_size != expected_size: 
            if advanced_logs and log_cb: log_cb(T_cb("err_size_invalid").format(cid, expected_size, actual_size))
            return False

    return True

def pack_cia(title_id: str, tmp_title_dir: Path, final_out_dir: Path, T_cb, boot9_path=None, is_stopped_cb=None, log_cb=None, decrypt=False, advanced_logs=False) -> bool:
    tmd_path = tmp_title_dir / "tmd.bin"
    tik_path = tmp_title_dir / "tik.bin"
    
    if not tmd_path.exists() or not tik_path.exists(): return False
    
    tmd_data = tmd_path.read_bytes()
    cetk_data = tik_path.read_bytes()
        
    tmd_sig_type = struct.unpack(">I", tmd_data[0:4])[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    actual_version = struct.unpack(">H", tmd_data[tmd_sig_len+0x9C : tmd_sig_len+0x9E])[0]
    
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
        if cia_path.exists():
            try: cia_path.unlink()
            except OSError: pass
        return False

    is_valid, msg = verify_built_cia(cia_path, T_cb, log_cb=log_cb, advanced_logs=advanced_logs)
    if not is_valid:
        if log_cb: log_cb(T_cb("err_pack_cia").format(msg))
        try: cia_path.unlink(missing_ok=True)
        except OSError: pass
        return False
    elif advanced_logs and log_cb:
        log_cb(T_cb("log_pack_success").format(cia_path.name))
    
    return True