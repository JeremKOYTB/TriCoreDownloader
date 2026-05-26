import os
import shutil
import struct
import stat
import hashlib
import binascii
import requests
import time
import traceback
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .wiiu_core import parse_tmd, aes_cbc_decrypt, get_common_key

CDN_HOSTS = [
    "ccs.cdn.c.shop.nintendowifi.net",
    "ccs.cdn.wup.shop.nintendo.net"
]
cdn_lock = threading.Lock()
cert_lock = threading.Lock()
active_cdn_idx = 0

BASE_URL = "http://ccs.cdn.c.shop.nintendowifi.net/ccs/download"
MAX_CONCURRENT_DOWNLOADS = 30 
MAX_RETRIES = 10
DEFAULT_CERT_DATA = b"" 

def apply_sticky_cdn(url):
    global active_cdn_idx
    for host in CDN_HOSTS:
        if host in url:
            with cdn_lock:
                current_host = CDN_HOSTS[active_cdn_idx]
            return url.replace(host, current_host)
    return url

def force_remove(path, T_cb=lambda x: x):
    if os.path.exists(path):
        try: 
            os.remove(path)
        except PermissionError:
            try:
                os.chmod(path, stat.S_IWRITE)
                os.remove(path)
            except Exception as e:
                print(T_cb("err_file_delete_fail").format(path, str(e)))
                pass

def force_replace(src, dst):
    if os.path.exists(dst):
        try: 
            os.chmod(dst, stat.S_IWRITE)
        except Exception: 
            pass
    os.replace(src, dst)

def verify_common_key_online(common_key, T_cb, log_cb=lambda x: None):
    print(T_cb("log_ops_online_auth_start"))
    log_cb(T_cb("log_debug_online_key_auth"))
    
    try:
        key_signature = hashlib.sha1(common_key).hexdigest()
        if len(common_key) == 16 and key_signature == "6a0b87fc98b306ae3366f0e0a88d0b06a2813313":
            print(T_cb("log_ops_online_auth_ok"))
            log_cb(T_cb("log_debug_key_ok"))
            return True
        else:
            raise ValueError(T_cb("err_ops_heuristic_filter"))
    except Exception as e:
        print(T_cb("err_ops_online_auth_failed").format(str(e)))
        raise RuntimeError(T_cb("err_common_key_invalid"))

def get_yls8_versions(region, fw_version):
    print(f"[CAFE OPS] Fetching firmware dependencies from yls8 for: {fw_version} {region}")
    match = re.search(r'(\d+)\.(\d+)\.?(\d+)?', fw_version)
    if not match: raise ValueError(f"Format de firmware invalide: {fw_version}")
    target_tuple = (int(match.group(1)), int(match.group(2)), int(match.group(3)) if match.group(3) else 0)

    csv_url = "https://yls8.mtheall.com/ninupdates/titlelist.php?sys=wup&csv=1"
    headers = {'User-Agent': 'WiiUDownloader/1.0'}
    r = requests.get(csv_url, headers=headers, timeout=(10, 20))
    r.raise_for_status()
    
    title_versions = {}
    lines = r.text.strip().replace('\r', '').split('\n')
    seen_firmwares = set()
    
    for line in lines[1:]:
        parts = line.split(',')
        if len(parts) >= 4:
            tid = parts[0].strip().lower()
            csv_region = parts[1].strip().upper()
            
            if csv_region == region.upper() or csv_region == "ALL" or csv_region == "":
                t_vers = parts[2].strip().split(' ')
                u_vers = parts[3].strip().split(' ')
                best_ver = None
                
                for tv, uv in zip(t_vers, u_vers):
                    uv_match = re.search(r'(\d+)\.(\d+)\.?(\d+)?', uv)
                    if uv_match:
                        uv_tuple = (int(uv_match.group(1)), int(uv_match.group(2)), int(uv_match.group(3)) if uv_match.group(3) else 0)
                    else:
                        uv_tuple = (4, 0, 1) if "10-07-13" in uv else (0, 0, 0)
                        
                    seen_firmwares.add(uv_tuple)
                    if uv_tuple <= target_tuple: best_ver = tv.replace('v', '')
                    else: break
                        
                if best_ver and best_ver.isdigit(): title_versions[tid] = int(best_ver)
                    
    if target_tuple not in seen_firmwares:
        print(f"[CAFE OPS ERROR] Target firmware {target_tuple} not found in yls8 database.")
        raise ValueError("not_found")
    return title_versions

def get_default_cert(T_cb, log_cb=lambda x: None):
    global DEFAULT_CERT_DATA, active_cdn_idx
    
    with cert_lock:
        if DEFAULT_CERT_DATA: return DEFAULT_CERT_DATA
        
    log_cb(T_cb("log_debug_cert"))
    url = f"{BASE_URL}/000500101000400a/cetk"
    for attempt in range(MAX_RETRIES):
        sticky_url = apply_sticky_cdn(url)
        try:
            log_cb(T_cb("log_debug_req").format(sticky_url))
            r = requests.get(sticky_url, timeout=(10, 20))
            r.raise_for_status()
            data = r.content
            if len(data) >= 0x650:
                with cert_lock:
                    DEFAULT_CERT_DATA = data[0x350 : 0x650]
                print(T_cb("log_ops_cert_cached").format(len(DEFAULT_CERT_DATA)))
                return DEFAULT_CERT_DATA
        except Exception as e:
            print(T_cb("err_ops_cert_fail").format(attempt+1, str(e)))
            with cdn_lock:
                current = CDN_HOSTS[active_cdn_idx]
                if current in sticky_url: active_cdn_idx = (active_cdn_idx + 1) % len(CDN_HOSTS)
            time.sleep(1)
            
    raise RuntimeError(T_cb("err_cert_dl_fail"))

def download_file(session, url, dst_path, is_running_cb, T_cb, log_cb=lambda x: None, tmd_size=None):
    global active_cdn_idx
    tmp_path = dst_path + ".tmp"
    last_error_msg = ""
    total_downloaded = 0
    target_size = 0
    
    for attempt in range(MAX_RETRIES):
        sticky_url = apply_sticky_cdn(url)
        log_cb(T_cb("log_debug_req").format(sticky_url))
        
        try:
            total_downloaded = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers = {'User-Agent': 'WiiUDownloader/1.0', 'Accept-Encoding': 'identity'}
            
            if total_downloaded > 0: headers['Range'] = f'bytes={total_downloaded}-'
            
            with session.get(sticky_url, headers=headers, stream=True, timeout=(10, 30)) as r:
                if r.status_code == 416:
                    total_downloaded = 0
                    headers.pop('Range', None)
                    r.close()
                    r = session.get(sticky_url, headers=headers, stream=True, timeout=(10, 30))
                    
                r.raise_for_status()
                content_length = int(r.headers.get('Content-Length', 0))
                log_cb(T_cb("log_debug_headers").format(r.status_code, content_length))
                
                mode = "ab" if r.status_code == 206 else "wb"
                if mode == "wb": total_downloaded = 0
                target_size = total_downloaded + content_length if mode == "ab" else content_length
                
                if target_size > 0 and total_downloaded == target_size:
                    force_replace(tmp_path, dst_path)
                    return True

                with open(tmp_path, mode) as f:
                    for chunk in r.iter_content(chunk_size=4194304):
                        if not is_running_cb(): 
                            return False
                        if chunk:
                            f.write(chunk)
                            total_downloaded += len(chunk)
                            
            if target_size > 0:
                if total_downloaded < target_size: raise RuntimeError(T_cb("err_dl_cut").format(total_downloaded, target_size))
                if total_downloaded > target_size:
                    force_remove(tmp_path, T_cb)
                    raise RuntimeError(T_cb("err_dl_over").format(total_downloaded))
            else:
                if tmd_size is not None and total_downloaded < tmd_size:
                    raise RuntimeError(T_cb("err_dl_small").format(total_downloaded, tmd_size))
                    
            force_replace(tmp_path, dst_path)
            return True
            
        except Exception as e:
            last_error_msg = str(e)
            if isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 404:
                print(T_cb("err_ops_http_404").format(sticky_url))
                raise RuntimeError(f"404 Not Found for url: {sticky_url}")
                
            with cdn_lock:
                current = CDN_HOSTS[active_cdn_idx]
                if current in sticky_url: active_cdn_idx = (active_cdn_idx + 1) % len(CDN_HOSTS)
                    
            if attempt < MAX_RETRIES - 1 and is_running_cb(): time.sleep(1)  
                
    raise RuntimeError(T_cb("err_dl_crit").format(last_error_msg))

def download_title_files(title_id, work_dir, T_cb, is_running_cb, log_cb=lambda x: None, target_version=None):
    print(f"[CAFE OPS] Initiating download sequence for Title ID: {title_id}")
    os.makedirs(work_dir, exist_ok=True)
    
    session = requests.Session()

    adapter = HTTPAdapter(
        pool_connections=MAX_CONCURRENT_DOWNLOADS, 
        pool_maxsize=MAX_CONCURRENT_DOWNLOADS, 
        max_retries=3,
        pool_block=True
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    tmd_url = f"{BASE_URL}/{title_id}/tmd.{target_version}" if target_version is not None else f"{BASE_URL}/{title_id}/tmd"
    
    download_file(session, tmd_url, os.path.join(work_dir, "title.tmd"), is_running_cb, T_cb, log_cb)
    download_file(session, f"{BASE_URL}/{title_id}/cetk", os.path.join(work_dir, "title.tik"), is_running_cb, T_cb, log_cb)
    
    tmd_path = os.path.join(work_dir, "title.tmd")
    with open(tmd_path, "rb") as f: tmd = parse_tmd(f.read(), T_cb, log_cb)
    
    tasks = []
    
    active_threads = 10 if target_version is not None else MAX_CONCURRENT_DOWNLOADS
    log_cb(T_cb("log_debug_threads").format(active_threads))
    
    with ThreadPoolExecutor(max_workers=active_threads) as executor:
        for c in tmd.contents:
            if not is_running_cb(): break
                
            cid_str = f"{c.id:08X}"
            app_p = os.path.join(work_dir, f"{cid_str}.app")
            aligned_c_size = (c.size + 15) & ~15
            actual_size = os.path.getsize(app_p) if os.path.exists(app_p) else 0
            
            try:
                if actual_size == 0 or (actual_size != c.size and actual_size != aligned_c_size):
                    tasks.append(executor.submit(download_file, session, f"{BASE_URL}/{title_id}/{cid_str}", app_p, is_running_cb, T_cb, log_cb, c.size))
                    
                if c.type & 0x02:
                    h3_p = os.path.join(work_dir, f"{cid_str}.h3")
                    if not os.path.exists(h3_p) or os.path.getsize(h3_p) == 0:
                        tasks.append(executor.submit(download_file, session, f"{BASE_URL}/{title_id}/{cid_str}.h3", h3_p, is_running_cb, T_cb, log_cb))
            except RuntimeError:
                break
                
        for f in as_completed(tasks):
            if not is_running_cb():
                session.close()
                return False
            f.result()
            
    if is_running_cb():
        cert_path = os.path.join(work_dir, "title.cert")
        if not os.path.exists(cert_path) and os.path.exists(tmd_path):
            try:
                cert_offset = 0xB04 if tmd.version == 1 else 0x1E4
                cert_offset += (0x30 if tmd.version == 1 else 0x24) * tmd.content_count
                with open(tmd_path, "rb") as f_tmd:
                    f_tmd.seek(cert_offset)
                    cert_1_2 = f_tmd.read(0x700)
                default_cert = get_default_cert(T_cb, log_cb)
                with open(cert_path, "wb") as f_cert:
                    f_cert.write(cert_1_2 + default_cert)
            except Exception as e:
                print(f"[CAFE OPS WARN] Failed to build synthetic cert: {e}")
                pass 

    session.close()
    return True

def verify_title_integrity(title_id, work_dir, common_key, T_cb, is_running_cb, log_cb=lambda x: None):
    print(f"[CAFE OPS] Verifying cryptographical integrity of: {title_id}")
    tmd_p = os.path.join(work_dir, "title.tmd")
    tik_p = os.path.join(work_dir, "title.tik")
    
    if not os.path.exists(tmd_p) or not os.path.exists(tik_p): 
        raise RuntimeError(T_cb("err_tmd_tik_miss").format(title_id))
        
    with open(tmd_p, "rb") as f: tmd = parse_tmd(f.read(), T_cb, log_cb)
    with open(tik_p, "rb") as f: tik = f.read()

    iv_tkey = tmd.title_id_bin + b'\x00' * 8
    title_key = aes_cbc_decrypt(common_key, iv_tkey, tik[0x1BF:0x1CF])
    log_cb(T_cb("log_debug_title_key").format(binascii.hexlify(title_key).decode()))
    
    for c in tmd.contents:
        if not is_running_cb(): return False
        
        log_cb(T_cb("log_debug_app_check").format(f"{c.id:08X}.app"))
        app_p = os.path.join(work_dir, f"{c.id:08X}.app")
        if not os.path.exists(app_p): 
            raise RuntimeError(T_cb("err_app_miss").format(f"{c.id:08X}.app"))
        
        iv = struct.pack('>H', c.index) + b'\x00' * 14
        log_cb(T_cb("log_debug_iv").format(binascii.hexlify(iv).decode()))
        
        if c.type & 0x02:
            h3_p = os.path.join(work_dir, f"{c.id:08X}.h3")
            if not os.path.exists(h3_p): 
                raise RuntimeError(T_cb("err_h3_miss").format(f"{c.id:08X}.h3"))
                
            with open(h3_p, 'rb') as f: h3_raw = f.read()
            if hashlib.sha1(h3_raw).digest() != c.hash: 
                raise RuntimeError(T_cb("err_h3_mismatch").format(f"{c.id:08X}.h3"))
            
            TOTAL_BLOCK = 0x10000
            h_iv = struct.pack(">H", c.index) + b'\x00' * 14
            chunk_idx = 0
            
            with open(app_p, "rb") as f_app:
                while True:
                    if not is_running_cb(): return False
                    data = f_app.read(TOTAL_BLOCK)
                    if not data: break 
                    if len(data) <= 0x400: raise RuntimeError(T_cb("err_app_short").format(f"{c.id:08X}.app"))
                    
                    hashes = aes_cbc_decrypt(title_key, h_iv, data[:0x400])
                    block_num = chunk_idx % 16
                    expected_h0_hash = hashes[block_num * 20 : (block_num + 1) * 20]
                    expected_true_hash = bytearray(expected_h0_hash)
                    c_iv = bytearray(16)
                    c_iv[:16] = expected_h0_hash[:16]
                    
                    if chunk_idx % 16 == 0: 
                        c_iv[0] ^= (c.index >> 8)
                        c_iv[1] ^= (c.index & 0xFF)
                        expected_true_hash[0] ^= (c.index >> 8)
                        expected_true_hash[1] ^= (c.index & 0xFF)
                        
                    enc_data = data[0x400:]
                    if len(enc_data) % 16 != 0: enc_data += b'\x00' * (16 - (len(enc_data) % 16))
                        
                    dec_content = aes_cbc_decrypt(title_key, bytes(c_iv), enc_data)
                    actual_h0_hash = hashlib.sha1(dec_content[:len(data) - 0x400]).digest()
                    
                    if actual_h0_hash != bytes(expected_true_hash):
                        print(f"[CAFE OPS ERROR] Checksum mismatch on H3 Block #{chunk_idx}")
                        raise RuntimeError(T_cb("err_app_hash_fail").format(f"{c.id:08X}.app", chunk_idx))
                    chunk_idx += 1
        else:
            aligned_size = (c.size + 15) & ~15
            actual_size = os.path.getsize(app_p)
            if actual_size != c.size and actual_size != aligned_size: 
                raise RuntimeError(T_cb("err_app_size").format(f"{c.id:08X}.app"))
            
            cipher = Cipher(algorithms.AES(title_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            sha1 = hashlib.sha1()
            processed_size = 0
            
            with open(app_p, 'rb') as f:
                while processed_size < c.size:
                    if not is_running_cb(): return False
                    chunk = f.read(4194304)
                    if not chunk: raise RuntimeError(T_cb("err_app_stop").format(f"{c.id:08X}.app"))
                    if len(chunk) % 16 != 0: chunk += b'\x00' * (16 - (len(chunk) % 16))
                    dec_chunk = decryptor.update(chunk)
                    
                    if processed_size + len(dec_chunk) >= c.size:
                        sha1.update(dec_chunk[:c.size - processed_size])
                        break
                    else:
                        sha1.update(dec_chunk)
                    processed_size += len(chunk)
            
            if sha1.digest() != c.hash: 
                print(f"[CAFE OPS ERROR] Checksum mismatch on whole file {c.id:08X}.app")
                raise RuntimeError(T_cb("err_app_sha1_fail").format(f"{c.id:08X}.app"))
                
    return True

def extract_file_standard(src_app, dst_path, tkey, content_idx, offset, length, is_running_cb, T_cb):
    base_iv = struct.pack(">H", content_idx) + b'\x00' * 14
    force_remove(dst_path, T_cb)

    with open(src_app, "rb") as f_in, open(dst_path, "wb") as f_out:
        aligned_offset = offset & ~0xF
        skip_bytes = offset - aligned_offset
        if aligned_offset > 0:
            f_in.seek(aligned_offset - 16)
            iv = f_in.read(16)
        else:
            iv = base_iv
            
        cipher = Cipher(algorithms.AES(tkey), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        
        f_in.seek(aligned_offset)
        remaining = length
        chunk_size = 4194304
        first_chunk = True
        
        while remaining > 0:
            if not is_running_cb(): return
            enc_data = f_in.read(chunk_size)
            if not enc_data:
                f_out.write(b'\x00' * remaining)
                break
                
            actual_read = len(enc_data)
            if len(enc_data) % 16 != 0: enc_data += b'\x00' * (16 - (len(enc_data) % 16))
                
            dec_data = decryptor.update(enc_data)
            if first_chunk:
                dec_data = dec_data[skip_bytes:]
                actual_read = max(0, actual_read - skip_bytes)
                first_chunk = False
                
            write_len = min(remaining, actual_read)
            f_out.write(dec_data[:write_len])
            remaining -= write_len
            
            if actual_read < chunk_size and remaining > 0:
                f_out.write(b'\x00' * remaining)
                break

    if is_running_cb() and os.path.getsize(dst_path) != length:
        raise RuntimeError(T_cb("err_ext_size_fail").format(os.path.basename(dst_path)))

def extract_file_hashed(src_app, dst_path, tkey, content_idx, offset, length, is_running_cb, T_cb):
    DATA_BLOCK, TOTAL_BLOCK = 0xFC00, 0x10000
    start_chunk_idx = offset // DATA_BLOCK
    roffset = start_chunk_idx * TOTAL_BLOCK
    soffset = offset % DATA_BLOCK
    h_iv = struct.pack(">H", content_idx) + b'\x00' * 14
    force_remove(dst_path, T_cb)

    with open(src_app, "rb") as f_in, open(dst_path, "wb") as f_out:
        f_in.seek(roffset)
        remaining = length
        current_chunk_idx = start_chunk_idx
        
        while remaining > 0:
            if not is_running_cb(): return
            data = f_in.read(TOTAL_BLOCK)
            if not data:
                f_out.write(b'\x00' * remaining)
                break
            
            hashes = aes_cbc_decrypt(tkey, h_iv, data[:0x400])
            block_num = current_chunk_idx % 16
            expected_hash = hashes[block_num * 20 : (block_num + 1) * 20]
            c_iv = bytearray(16)
            c_iv[:16] = expected_hash[:16]
            
            if current_chunk_idx % 16 == 0: 
                c_iv[0] ^= (content_idx >> 8)
                c_iv[1] ^= (content_idx & 0xFF)
                
            enc_data = data[0x400:]
            if len(enc_data) % 16 != 0: enc_data += b'\x00' * (16 - (len(enc_data) % 16))
                
            dec_content = aes_cbc_decrypt(tkey, bytes(c_iv), enc_data)
            available_in_block = DATA_BLOCK - soffset
            write_len = min(remaining, available_in_block)
            to_write = dec_content[soffset : soffset + write_len]
            
            if len(to_write) < write_len: to_write += b'\x00' * (write_len - len(to_write))
                
            f_out.write(to_write)
            remaining -= write_len
            soffset = 0 
            current_chunk_idx += 1

    if is_running_cb() and os.path.getsize(dst_path) != length:
        raise RuntimeError(T_cb("err_ext_size_fail").format(os.path.basename(dst_path)))

def process_title(tid, work_dir, target_dir, common_key, T_cb, is_running_cb, log_cb=lambda x: None):
    print(f"[CAFE OPS] Unpacking encrypted content for Title ID: {tid}")
    tmd_p = os.path.join(work_dir, "title.tmd")
    tik_p = os.path.join(work_dir, "title.tik")
    cert_p = os.path.join(work_dir, "title.cert") 
    
    with open(tmd_p, "rb") as f: tmd = parse_tmd(f.read(), T_cb, log_cb)
    with open(tik_p, "rb") as f: tik = f.read()

    iv_tkey = tmd.title_id_bin + b'\x00' * 8
    title_key = aes_cbc_decrypt(common_key, iv_tkey, tik[0x1BF:0x1CF])
    log_cb(T_cb("log_debug_title_key").format(binascii.hexlify(title_key).decode()))

    c0 = next(c for c in tmd.contents if c.index == 0)
    fst_path = os.path.join(work_dir, f"{c0.id:08X}.app")
    with open(fst_path, "rb") as f: fst_enc = f.read()
    fst_dec = aes_cbc_decrypt(title_key, b'\x00'*16, fst_enc)
    
    code_dir = os.path.join(target_dir, "code")
    os.makedirs(code_dir, exist_ok=True)

    if os.path.exists(tmd_p): shutil.copy2(tmd_p, os.path.join(code_dir, "title.tmd"))
    if os.path.exists(tik_p): shutil.copy2(tik_p, os.path.join(code_dir, "title.tik"))
    if os.path.exists(cert_p): shutil.copy2(cert_p, os.path.join(code_dir, "title.cert"))

    is_fst = False
    try:
        if len(fst_dec) >= 0x20:
            info_count = struct.unpack(">I", fst_dec[0x08:0x0C])[0]
            entries_ptr = 0x20 + (info_count * 0x20)
            if entries_ptr + 16 <= len(fst_dec):
                total_entries = struct.unpack(">I", fst_dec[entries_ptr+8 : entries_ptr+12])[0]
                name_table_off = entries_ptr + (total_entries * 0x10)
                if name_table_off <= len(fst_dec) and 0 < total_entries < 100000:
                    is_fst = True
    except Exception: pass

    if is_fst:
        fst_out_path = os.path.join(code_dir, "title.fst")
        with open(fst_out_path, "wb") as f_fst: f_fst.write(fst_dec)
        
        log_cb(T_cb("log_debug_fst_pointers").format(info_count, entries_ptr, name_table_off))
        log_cb(T_cb("log_debug_fst_info").format(total_entries))

        path_stack, end_stack = [target_dir], [total_entries]
        content_map = {c.index: c for c in tmd.contents}
        expected_files = {}

        for i in range(1, total_entries):
            if not is_running_cb(): return
            
            while i >= end_stack[-1]: 
                path_stack.pop()
                end_stack.pop()
            
            off = entries_ptr + (i * 0x10)
            entry = fst_dec[off : off + 16]
            e_type = entry[0]
            e_name_off = struct.unpack(">I", b'\x00' + entry[1:4])[0]
            e_off = struct.unpack(">I", entry[4:8])[0]
            e_len = struct.unpack(">I", entry[8:12])[0]
            e_flags = struct.unpack(">H", entry[12:14])[0]
            e_cid = struct.unpack(">H", entry[14:16])[0]

            name_end = fst_dec.find(b'\x00', name_table_off + e_name_off)
            if name_end == -1: continue
            
            name = fst_dec[name_table_off + e_name_off : name_end].decode('utf-8', errors='ignore')
            if not name: continue
                
            current_path = os.path.join(path_stack[-1], name)

            if e_type & 0x01: 
                log_cb(T_cb("log_debug_fst_dir").format(current_path))
                os.makedirs(current_path, exist_ok=True)
                path_stack.append(current_path)
                end_stack.append(e_len)
            else: 
                if e_cid in content_map:
                    c = content_map[e_cid]
                    src_app = os.path.join(work_dir, f"{c.id:08X}.app")
                    try:
                        real_offset = e_off << 5 if (e_flags & 0x04) == 0 else e_off
                        log_cb(T_cb("log_debug_fst_file").format(current_path, real_offset, e_len))
                        
                        if c.type & 0x02: extract_file_hashed(src_app, current_path, title_key, e_cid, real_offset, e_len, is_running_cb, T_cb)
                        else: extract_file_standard(src_app, current_path, title_key, e_cid, real_offset, e_len, is_running_cb, T_cb)
                            
                        expected_files[current_path] = e_len
                    except Exception as e:
                        print(f"[CAFE OPS ERROR] Fatal extraction error on {name}: {e}")
                        raise RuntimeError(T_cb("err_ext_fatal").format(name, str(e)))

        if is_running_cb():
            for f_path, expected_len in expected_files.items():
                if not os.path.exists(f_path): raise RuntimeError(T_cb("err_ext_miss").format(f_path))
                if os.path.getsize(f_path) != expected_len: raise RuntimeError(T_cb("err_ext_alt").format(f_path))
    else:
        log_cb(f"Titre sans FST ({tid}) détecté. Décryptage des fichiers bruts...")
        print(f"[CAFE OPS] Unmapped binary detected for {tid}. Ripping raw AES contents.")
        content_dir = os.path.join(target_dir, "content")
        os.makedirs(content_dir, exist_ok=True)
        
        for c in tmd.contents:
            if not is_running_cb(): return
            src_app = os.path.join(work_dir, f"{c.id:08X}.app")
            dst_path = os.path.join(content_dir, f"{c.id:08X}.app")
            
            if not os.path.exists(src_app): continue
                
            iv = struct.pack(">H", c.index) + b'\x00' * 14
            with open(src_app, "rb") as f_in, open(dst_path, "wb") as f_out:
                cipher = Cipher(algorithms.AES(title_key), modes.CBC(iv), backend=default_backend())
                decryptor = cipher.decryptor()
                while True:
                    chunk = f_in.read(4194304)
                    if not chunk: break
                    if len(chunk) % 16 != 0: chunk += b'\x00' * (16 - (len(chunk) % 16))
                    f_out.write(decryptor.update(chunk))
            
            if os.path.exists(dst_path) and os.path.getsize(dst_path) > c.size:
                with open(dst_path, "r+b") as f_trunc:
                    f_trunc.truncate(c.size)

    return True