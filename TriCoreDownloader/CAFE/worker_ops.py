import os
import shutil
import struct
import stat
import socket
import hashlib
import binascii
import requests
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .wiiu_core import (
    parse_tmd,
    aes_cbc_decrypt,
    get_common_key,
    WIIU_COMMON_KEY_SHA1,
)

CDN_HOSTS = [
    "ccs.cdn.c.shop.nintendowifi.net",
    "ccs.cdn.wup.shop.nintendo.net",
    "nus.cdn.c.shop.nintendowifi.net",
    "nus.cdn.wup.shop.nintendo.net",
]
cdn_lock = threading.Lock()
cert_lock = threading.Lock()
active_cdn_idx = 0

CDN_PATH = "/ccs/download"
BASE_URL = f"http://{CDN_HOSTS[0]}{CDN_PATH}"
FST_MAGIC = b"FST\x00"
OSV10_TID = "000500101000400a"
MAX_RETRIES = 5
DEFAULT_CERT_DATA = b""
CHUNK_SIZE = 4 * 1024 * 1024
IN_MEMORY_MAX_SIZE = 4 * 1024 * 1024
FAST_REQ_TIMEOUT = (3.05, 8.0)
_BACKEND = default_backend()

RE_FW_TUPLE = re.compile(r"(\d+)\.(\d+)\.?(\d+)?")

STRUCT_Q = struct.Struct(">Q")
STRUCT_H = struct.Struct(">H")
STRUCT_I = struct.Struct(">I")
STRUCT_II = struct.Struct(">II")
STRUCT_HH = struct.Struct(">HH")


class _FastTCPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        sock_opts = list(HTTPConnection.default_socket_options) + [
            (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        pool_kwargs["socket_options"] = sock_opts
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _normalize_tid(title_id: str) -> str:
    return title_id.replace("-", "").replace("/", "").replace("\\", "").strip().lower()


def _validate_manifest_pair_for_tid(clean_tid: str, raw_tmd: bytes, raw_tik: bytes) -> bool:
    if not raw_tmd or not raw_tik:
        return False
    if len(raw_tmd) < 0x200 or len(raw_tik) < 0x1D0:
        return False
    try:
        expected_tid_int = int(clean_tid, 16)
    except ValueError:
        return False
    tmd_tid_int = STRUCT_Q.unpack_from(raw_tmd, 0x18C)[0]
    if len(raw_tik) >= 0x1E4:
        tik_tid_int = STRUCT_Q.unpack_from(raw_tik, 0x1DC)[0]
        if tik_tid_int != expected_tid_int:
            return False
    return tmd_tid_int == expected_tid_int


def _write_bytes_fast(dst_path: str, data, T_cb=None):
    mv = data if isinstance(data, memoryview) else memoryview(data)
    total = len(mv)
    try:
        with open(dst_path, "wb", buffering=0) as f:
            written = 0
            while written < total:
                n = f.write(mv[written:])
                if not n:
                    break
                written += n
    except PermissionError:
        if os.path.exists(dst_path):
            try:
                os.chmod(dst_path, stat.S_IWRITE | stat.S_IREAD)
                os.remove(dst_path)
            except Exception:
                pass
        with open(dst_path, "wb", buffering=0) as f:
            written = 0
            while written < total:
                n = f.write(mv[written:])
                if not n:
                    break
                written += n
    if written != total:
        if T_cb is not None:
            raise IOError(
                T_cb("err_io_write_incomplete").format(
                    os.path.basename(dst_path), written, total
                )
            )
        raise IOError(os.path.basename(dst_path))


def _verify_expected_files_fast(expected_files: dict, directories, T_cb):
    scanned_sizes = {}
    for d in directories:
        if not os.path.isdir(d):
            raise RuntimeError(T_cb("err_ext_dir_miss").format(d))
        try:
            with os.scandir(d) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        scanned_sizes[entry.path] = entry.stat(follow_symlinks=False).st_size
        except OSError:
            pass

    for f_path, expected_len in expected_files.items():
        actual_len = scanned_sizes.get(f_path)
        if actual_len is None:
            if not os.path.exists(f_path):
                raise RuntimeError(T_cb("err_ext_miss").format(f_path))
            actual_len = os.path.getsize(f_path)
        if actual_len != expected_len:
            raise RuntimeError(T_cb("err_ext_alt").format(f_path))


def _read_tmd_and_title_key(
    tmd_path, tik_path, common_key, T_cb, log_cb=None, expected_tid=None
):
    norm_expected = _normalize_tid(expected_tid) if expected_tid else None

    with open(tmd_path, "rb") as f:
        raw_tmd = f.read()
    tmd = parse_tmd(raw_tmd, T_cb, log_cb)
    tmd_tid_hex = f"{tmd.title_id:016x}"

    if norm_expected and tmd_tid_hex != norm_expected:
        raise ValueError(T_cb("err_tmd_invalid"))

    with open(tik_path, "rb") as f:
        raw_tik = f.read()

    if len(raw_tik) >= 0x1E4:
        tik_tid = STRUCT_Q.unpack_from(raw_tik, 0x1DC)[0]
        if tik_tid != tmd.title_id:
            raise ValueError(
                T_cb("err_manifest_mismatch").format(expected_tid or f"{tmd.title_id:016X}")
            )

    iv_tkey = tmd.title_id_bin + b"\x00" * 8
    title_key = aes_cbc_decrypt(common_key, iv_tkey, raw_tik[0x1BF:0x1CF])
    if log_cb:
        log_cb(
            T_cb("log_debug_title_key").format(binascii.hexlify(title_key).decode())
        )

    return tmd, title_key, raw_tmd, raw_tik


def apply_sticky_cdn(url):
    global active_cdn_idx
    if url.startswith("/"):
        with cdn_lock:
            current_host = CDN_HOSTS[active_cdn_idx]
        return f"http://{current_host}{url}"
    for host in CDN_HOSTS:
        if host in url:
            with cdn_lock:
                current_host = CDN_HOSTS[active_cdn_idx]
            return url.replace(host, current_host)
    return url


def _switch_cdn_host_on_error(sticky_url, T_cb, log_cb=None):
    global active_cdn_idx
    with cdn_lock:
        current = CDN_HOSTS[active_cdn_idx]
        if current in sticky_url:
            active_cdn_idx = (active_cdn_idx + 1) % len(CDN_HOSTS)
            new_host = CDN_HOSTS[active_cdn_idx]
            if log_cb:
                log_cb(T_cb("log_cafe_cdn_switch").format(new_host))


def force_remove(path, T_cb=lambda x: x, log_cb=None):
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            os.remove(path)
        except Exception as e:
            if log_cb:
                log_cb(T_cb("err_file_delete_fail").format(path, str(e)))
    except OSError:
        pass


def force_replace(src, dst):
    try:
        os.replace(src, dst)
        return
    except PermissionError:
        if os.path.exists(dst):
            try:
                os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)
                os.remove(dst)
            except Exception:
                pass
        os.replace(src, dst)


def create_optimized_session():
    session = requests.Session()
    adapter = _FastTCPAdapter(
        pool_connections=32,
        pool_maxsize=32,
        max_retries=1,
        pool_block=False,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "Connection": "keep-alive",
        "User-Agent": "WiiUDownloader/1.0",
        "Accept-Encoding": "identity",
    })
    return session


def verify_common_key_online(common_key, T_cb, log_cb=None):
    if log_cb:
        log_cb(T_cb("log_ops_online_auth_start"))

    try:
        key_signature = hashlib.sha1(common_key).hexdigest()
        if len(common_key) == 16 and key_signature == WIIU_COMMON_KEY_SHA1:
            if log_cb:
                log_cb(T_cb("log_ops_online_auth_ok"))
                log_cb(T_cb("log_debug_key_ok"))
            return True
        else:
            raise ValueError(T_cb("err_ops_heuristic_filter"))
    except Exception as e:
        if log_cb:
            log_cb(T_cb("log_ops_online_auth_failed").format(str(e)))
        raise RuntimeError(T_cb("err_common_key_invalid"))


def get_yls8_versions(region, fw_version, session=None, T_cb=None):
    match = RE_FW_TUPLE.search(fw_version)
    if not match:
        if T_cb is not None:
            raise ValueError(T_cb("err_fw_format_invalid").format(fw_version))
        raise ValueError(fw_version)
    target_tuple = (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)) if match.group(3) else 0,
    )
    region_upper = region.upper()

    csv_url = "https://yls8.mtheall.com/ninupdates/titlelist.php?sys=wup&csv=1"
    headers = {"User-Agent": "WiiUDownloader/1.0"}
    req_obj = session if session is not None else requests
    r = req_obj.get(csv_url, headers=headers, timeout=(5, 12))
    r.raise_for_status()
    csv_text = r.text

    title_versions = {}
    lines = csv_text.strip().replace("\r", "").split("\n")
    seen_firmwares = set()

    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) >= 4:
            tid = parts[0].strip().lower()
            csv_region = parts[1].strip().upper()

            if (
                csv_region == region_upper
                or csv_region == "ALL"
                or csv_region == ""
            ):
                t_vers = parts[2].strip().split(" ")
                u_vers = parts[3].strip().split(" ")
                best_ver = None

                for tv, uv in zip(t_vers, u_vers):
                    uv_match = RE_FW_TUPLE.search(uv)
                    if uv_match:
                        uv_tuple = (
                            int(uv_match.group(1)),
                            int(uv_match.group(2)),
                            int(uv_match.group(3)) if uv_match.group(3) else 0,
                        )
                    else:
                        uv_tuple = (
                            (4, 0, 1) if "10-07-13" in uv else (0, 0, 0)
                        )

                    seen_firmwares.add(uv_tuple)
                    if uv_tuple <= target_tuple:
                        best_ver = tv.replace("v", "")
                    else:
                        break

                if best_ver and best_ver.isdigit():
                    title_versions[tid] = int(best_ver)

    if target_tuple not in seen_firmwares:
        raise ValueError("not_found")

    return title_versions


def get_default_cert(T_cb, log_cb=None, session=None):
    global DEFAULT_CERT_DATA

    with cert_lock:
        if DEFAULT_CERT_DATA:
            return DEFAULT_CERT_DATA

    if log_cb:
        log_cb(T_cb("log_debug_cert"))
    url_path = f"{CDN_PATH}/{OSV10_TID}/cetk"
    req_obj = session if session else requests

    for attempt in range(MAX_RETRIES):
        sticky_url = apply_sticky_cdn(url_path)
        try:
            if log_cb:
                log_cb(T_cb("log_debug_req").format(sticky_url))
            r = req_obj.get(sticky_url, timeout=FAST_REQ_TIMEOUT)
            r.raise_for_status()
            data = r.content
            if len(data) >= 0x650:
                with cert_lock:
                    DEFAULT_CERT_DATA = data[0x350:0x650]
                if log_cb:
                    log_cb(T_cb("log_ops_cert_cached").format(len(DEFAULT_CERT_DATA)))
                return DEFAULT_CERT_DATA
        except Exception as e:
            if log_cb:
                log_cb(T_cb("err_ops_cert_fail").format(attempt + 1, str(e)))
            _switch_cdn_host_on_error(sticky_url, T_cb, log_cb)
            time.sleep(0.1)

    raise RuntimeError(T_cb("err_cert_dl_fail"))


def _download_small_in_memory(
    session,
    url,
    dst_path,
    is_running_cb,
    T_cb,
    log_cb=None,
    tmd_size=None,
    expected_sha1=None,
    return_bytes=False,
):
    last_error_msg = ""
    aligned_expected = ((tmd_size + 15) & ~15) if tmd_size is not None else None

    for attempt in range(MAX_RETRIES):
        if not is_running_cb():
            return (False, b"") if return_bytes else False

        sticky_url = apply_sticky_cdn(url)
        try:
            t0 = time.monotonic()
            r = session.get(sticky_url, timeout=FAST_REQ_TIMEOUT)
            r.raise_for_status()
            latency_ms = int((time.monotonic() - t0) * 1000)
            data = r.content
            actual_len = len(data)
            content_length = int(r.headers.get("Content-Length", actual_len))

            if log_cb:
                try:
                    log_cb(
                        T_cb("log_debug_headers").format(
                            r.status_code, content_length, latency_ms
                        )
                    )
                except IndexError:
                    log_cb(
                        T_cb("log_debug_headers").format(
                            r.status_code, content_length
                        )
                    )

            if content_length > 0 and actual_len != content_length:
                raise RuntimeError(T_cb("err_dl_cut").format(actual_len, content_length))

            if tmd_size is not None:
                if actual_len != tmd_size and actual_len != aligned_expected and actual_len < tmd_size:
                    raise RuntimeError(
                        T_cb("err_dl_size_mismatch").format(
                            os.path.basename(dst_path), actual_len, tmd_size
                        )
                    )

            if expected_sha1 is not None:
                if hashlib.sha1(data).digest() != expected_sha1:
                    raise RuntimeError(
                        T_cb("err_h3_dl_corrupt").format(os.path.basename(dst_path))
                    )

            _write_bytes_fast(dst_path, data, T_cb=T_cb)

            if log_cb:
                log_cb(
                    T_cb("log_cafe_dl_file_ok").format(
                        os.path.basename(dst_path), actual_len
                    )
                )
            return (True, data) if return_bytes else True

        except Exception as e:
            last_error_msg = str(e)
            if (
                isinstance(e, requests.exceptions.HTTPError)
                and e.response is not None
                and e.response.status_code == 404
            ):
                if log_cb:
                    log_cb(T_cb("err_ops_http_404").format(sticky_url))
                raise RuntimeError(f"404: {sticky_url}")

            _switch_cdn_host_on_error(sticky_url, T_cb, log_cb)

            if attempt < MAX_RETRIES - 1 and is_running_cb():
                time.sleep(0.1)

    raise RuntimeError(T_cb("err_dl_crit").format(last_error_msg))


def download_file(
    session,
    url,
    dst_path,
    is_running_cb,
    T_cb,
    log_cb=None,
    tmd_size=None,
    expected_sha1=None,
):
    if tmd_size is None or tmd_size <= IN_MEMORY_MAX_SIZE:
        return _download_small_in_memory(
            session,
            url,
            dst_path,
            is_running_cb,
            T_cb,
            log_cb,
            tmd_size=tmd_size,
            expected_sha1=expected_sha1,
            return_bytes=False,
        )

    tmp_path = dst_path + ".tmp"
    last_error_msg = ""
    total_downloaded = 0
    target_size = 0
    aligned_expected = (tmd_size + 15) & ~15

    for attempt in range(MAX_RETRIES):
        if not is_running_cb():
            return False

        sticky_url = apply_sticky_cdn(url)
        try:
            try:
                total_downloaded = os.path.getsize(tmp_path)
            except OSError:
                total_downloaded = 0

            if total_downloaded > aligned_expected:
                force_remove(tmp_path, T_cb, log_cb)
                total_downloaded = 0

            headers = {
                "User-Agent": "WiiUDownloader/1.0",
                "Accept-Encoding": "identity",
            }

            if total_downloaded > 0:
                headers["Range"] = f"bytes={total_downloaded}-"

            t0 = time.monotonic()
            r = session.get(sticky_url, headers=headers, stream=True, timeout=FAST_REQ_TIMEOUT)
            if r.status_code == 416:
                r.close()
                force_remove(tmp_path, T_cb, log_cb)
                total_downloaded = 0
                headers.pop("Range", None)
                t0 = time.monotonic()
                r = session.get(sticky_url, headers=headers, stream=True, timeout=FAST_REQ_TIMEOUT)

            try:
                r.raise_for_status()
                latency_ms = int((time.monotonic() - t0) * 1000)
                content_length = int(r.headers.get("Content-Length", 0))
                if log_cb:
                    try:
                        log_cb(
                            T_cb("log_debug_headers").format(
                                r.status_code, content_length, latency_ms
                            )
                        )
                    except IndexError:
                        log_cb(
                            T_cb("log_debug_headers").format(
                                r.status_code, content_length
                            )
                        )

                mode = "ab" if r.status_code == 206 else "wb"
                if mode == "wb":
                    total_downloaded = 0
                target_size = (
                    total_downloaded + content_length
                    if mode == "ab"
                    else content_length
                )

                if target_size > 0 and total_downloaded == target_size:
                    force_replace(tmp_path, dst_path)
                    return True

                with open(tmp_path, mode, buffering=CHUNK_SIZE) as f:
                    for chunk in r.iter_content(chunk_size=128 * 1024):
                        if not is_running_cb():
                            r.close()
                            return False
                        if chunk:
                            f.write(chunk)
                            total_downloaded += len(chunk)
            finally:
                r.close()

            if target_size > 0:
                if total_downloaded < target_size:
                    raise RuntimeError(
                        T_cb("err_dl_cut").format(total_downloaded, target_size)
                    )
                if total_downloaded > target_size:
                    force_remove(tmp_path, T_cb, log_cb)
                    raise RuntimeError(
                        T_cb("err_dl_over").format(total_downloaded)
                    )
            else:
                if tmd_size is not None and total_downloaded < tmd_size:
                    raise RuntimeError(
                        T_cb("err_dl_small").format(total_downloaded, tmd_size)
                    )

            force_replace(tmp_path, dst_path)
            if log_cb:
                log_cb(
                    T_cb("log_cafe_dl_file_ok").format(
                        os.path.basename(dst_path), total_downloaded
                    )
                )
            return True

        except Exception as e:
            last_error_msg = str(e)
            if (
                isinstance(e, requests.exceptions.HTTPError)
                and e.response is not None
                and e.response.status_code == 404
            ):
                if log_cb:
                    log_cb(T_cb("err_ops_http_404").format(sticky_url))
                raise RuntimeError(f"404: {sticky_url}")

            _switch_cdn_host_on_error(sticky_url, T_cb, log_cb)

            if attempt < MAX_RETRIES - 1 and is_running_cb():
                time.sleep(0.1)

    raise RuntimeError(T_cb("err_dl_crit").format(last_error_msg))


def _verify_all_downloaded_files_present(work_dir: str, parsed_tmd) -> bool:
    existing_sizes = {}
    try:
        with os.scandir(work_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if entry.name.endswith(".tmp"):
                        return False
                    existing_sizes[entry.name] = entry.stat(follow_symlinks=False).st_size
    except OSError:
        return False

    if existing_sizes.get("title.tmd", 0) < 0x200:
        return False
    if existing_sizes.get("title.tik", 0) < 0x1D0:
        return False

    for c in parsed_tmd.contents:
        cid_str = f"{c.id:08X}"
        app_name = f"{cid_str}.app"
        if app_name not in existing_sizes:
            return False
        app_sz = existing_sizes[app_name]
        aligned_c_size = (c.size + 15) & ~15
        if app_sz != c.size and app_sz != aligned_c_size and app_sz < c.size:
            return False

        if c.type & 0x02:
            h3_name = f"{cid_str}.h3"
            h3_sz = existing_sizes.get(h3_name, 0)
            if h3_sz == 0:
                return False
            try:
                with open(os.path.join(work_dir, h3_name), "rb") as fh3:
                    h3_mem = fh3.read()
            except OSError:
                return False
            if hashlib.sha1(h3_mem).digest() != c.hash:
                return False

    return True


def download_title_files(
    title_id,
    work_dir,
    T_cb,
    is_running_cb,
    log_cb=None,
    target_version=None,
    shared_session=None,
):
    os.makedirs(work_dir, exist_ok=True)
    session = shared_session if shared_session else create_optimized_session()
    clean_tid = _normalize_tid(title_id)
    title_url_path = f"{CDN_PATH}/{clean_tid}"

    if log_cb:
        ver_label = f"v{target_version}" if target_version is not None else "LATEST"
        try:
            log_cb(T_cb("log_ops_dl_init").format(title_id, ver_label))
        except IndexError:
            log_cb(T_cb("log_ops_dl_init").format(title_id))

    tmd_path = os.path.join(work_dir, "title.tmd")
    tik_path = os.path.join(work_dir, "title.tik")

    tmd_rel_url = (
        f"{title_url_path}/tmd.{target_version}"
        if target_version is not None
        else f"{title_url_path}/tmd"
    )
    tik_rel_url = f"{title_url_path}/cetk"

    try:
        ok_t, raw_tmd = _download_small_in_memory(
            session,
            tmd_rel_url,
            tmd_path,
            is_running_cb,
            T_cb,
            log_cb,
            return_bytes=True,
        )
        if not ok_t or not is_running_cb():
            if not shared_session:
                session.close()
            return False

        ok_k, raw_tik = _download_small_in_memory(
            session,
            tik_rel_url,
            tik_path,
            is_running_cb,
            T_cb,
            log_cb,
            return_bytes=True,
        )
    except Exception:
        if not shared_session:
            session.close()
        raise

    if not ok_t or not ok_k or not is_running_cb():
        if not shared_session:
            session.close()
        return False

    if not _validate_manifest_pair_for_tid(clean_tid, raw_tmd, raw_tik):
        if not shared_session:
            session.close()
        raise RuntimeError(T_cb("err_manifest_mismatch").format(title_id))

    tmd = parse_tmd(raw_tmd, T_cb, log_cb)

    existing_sizes = {}
    try:
        with os.scandir(work_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if entry.name.endswith(".tmp"):
                        force_remove(entry.path, T_cb, log_cb)
                    else:
                        existing_sizes[entry.name] = entry.stat(follow_symlinks=False).st_size
    except OSError:
        pass

    pending_downloads = []
    for c in tmd.contents:
        if not is_running_cb():
            break
        cid_str = f"{c.id:08X}"
        app_name = f"{cid_str}.app"
        app_p = os.path.join(work_dir, app_name)
        aligned_c_size = (c.size + 15) & ~15
        actual_size = existing_sizes.get(app_name, -1)

        if actual_size < 0 or (
            actual_size != c.size and actual_size != aligned_c_size
        ):
            if actual_size >= 0:
                force_remove(app_p, T_cb, log_cb)
            pending_downloads.append((
                f"{title_url_path}/{cid_str}",
                app_p,
                c.size,
                None,
            ))

        if c.type & 0x02:
            h3_name = f"{cid_str}.h3"
            h3_p = os.path.join(work_dir, h3_name)
            h3_valid = False
            h3_disk_sz = existing_sizes.get(h3_name, 0)
            if h3_disk_sz > 0:
                try:
                    with open(h3_p, "rb") as fh3:
                        if hashlib.sha1(fh3.read()).digest() == c.hash:
                            h3_valid = True
                except OSError:
                    h3_valid = False

            if not h3_valid:
                if h3_disk_sz > 0:
                    force_remove(h3_p, T_cb, log_cb)
                pending_downloads.append((
                    f"{title_url_path}/{cid_str}.h3",
                    h3_p,
                    None,
                    c.hash,
                ))

    pending_downloads.sort(key=lambda item: item[2] or 0, reverse=True)

    def _run_pending_downloads(dl_list):
        if not dl_list:
            return True
        for dl_url, dst_p, exp_sz, exp_sha1 in dl_list:
            if not is_running_cb():
                return False
            if not download_file(
                session,
                dl_url,
                dst_p,
                is_running_cb,
                T_cb,
                log_cb,
                tmd_size=exp_sz,
                expected_sha1=exp_sha1,
            ):
                return False
        return True

    try:
        if not _run_pending_downloads(pending_downloads):
            if not shared_session:
                session.close()
            return False
        if is_running_cb() and not _verify_all_downloaded_files_present(work_dir, tmd):
            raise RuntimeError(T_cb("err_dl_verify_fail").format(title_id))
    except Exception:
        if not shared_session:
            session.close()
        raise

    if is_running_cb():
        cert_path = os.path.join(work_dir, "title.cert")
        if not os.path.exists(cert_path) or os.path.getsize(cert_path) == 0:
            try:
                cert_offset = 0xB04 if tmd.version == 1 else 0x1E4
                cert_offset += (
                    0x30 if tmd.version == 1 else 0x24
                ) * tmd.content_count
                cert_1_2 = raw_tmd[cert_offset : cert_offset + 0x700]
                default_cert = get_default_cert(T_cb, log_cb, session=session)
                full_cert = cert_1_2 + default_cert
                _write_bytes_fast(cert_path, full_cert, T_cb=T_cb)
                if log_cb:
                    log_cb(
                        T_cb("log_cafe_cert_built").format(title_id, len(full_cert))
                    )
            except Exception as e:
                if log_cb:
                    log_cb(T_cb("err_ops_synthetic_cert").format(str(e)))

    if not shared_session:
        session.close()
    return True


def verify_title_integrity(
    title_id,
    work_dir,
    common_key,
    T_cb,
    is_running_cb,
    log_cb=None,
):
    tmd_p = os.path.join(work_dir, "title.tmd")
    tik_p = os.path.join(work_dir, "title.tik")
    clean_tid = _normalize_tid(title_id)

    if not os.path.exists(tmd_p) or not os.path.exists(tik_p):
        raise RuntimeError(T_cb("err_tmd_tik_miss").format(title_id))

    tmd, title_key, _, _ = _read_tmd_and_title_key(
        tmd_p, tik_p, common_key, T_cb, log_cb, expected_tid=clean_tid
    )

    if len(tmd.contents) <= 0:
        raise RuntimeError(T_cb("err_tmd_invalid"))

    if log_cb:
        try:
            log_cb(
                T_cb("log_ops_crypto_verify").format(title_id, len(tmd.contents))
            )
        except IndexError:
            log_cb(T_cb("log_ops_crypto_verify").format(title_id))

    aes_algo = algorithms.AES(title_key)

    def _verify_single_content(c):
        if not is_running_cb():
            return False

        app_name = f"{c.id:08X}.app"
        app_p = os.path.join(work_dir, app_name)

        if not os.path.exists(app_p):
            raise RuntimeError(T_cb("err_app_miss").format(app_name))

        iv = STRUCT_H.pack(c.index) + b"\x00" * 14
        if log_cb:
            iv_hex = binascii.hexlify(iv).decode("ascii")
            try:
                log_cb(
                    T_cb("log_debug_app_check").format(
                        app_name, c.index, c.type, c.size, iv_hex
                    )
                )
            except IndexError:
                log_cb(T_cb("log_debug_app_check").format(app_name))

        if c.type & 0x02:
            h3_name = f"{c.id:08X}.h3"
            h3_p = os.path.join(work_dir, h3_name)
            if not os.path.exists(h3_p):
                raise RuntimeError(T_cb("err_h3_miss").format(h3_name))

            with open(h3_p, "rb") as f:
                h3_raw = f.read()

            if hashlib.sha1(h3_raw).digest() != c.hash:
                raise RuntimeError(T_cb("err_h3_mismatch").format(h3_name))

            TOTAL_BLOCK = 0x10000
            BATCH_SIZE = TOTAL_BLOCK * 32
            h_iv = iv
            idx_hi = (c.index >> 8) & 0xFF
            idx_lo = c.index & 0xFF
            chunk_idx = 0
            c_iv = bytearray(16)
            expected_true_hash = bytearray(20)

            buf = bytearray(BATCH_SIZE)
            mv = memoryview(buf)
            with open(app_p, "rb", buffering=BATCH_SIZE) as f_app:
                while True:
                    if not is_running_cb():
                        return False
                    n_read = f_app.readinto(mv)
                    if not n_read:
                        break

                    pos = 0
                    while pos < n_read:
                        if not is_running_cb():
                            return False
                        block_end = min(n_read, pos + TOTAL_BLOCK)
                        block_len = block_end - pos
                        if block_len <= 0x400:
                            raise RuntimeError(T_cb("err_app_short").format(app_name))

                        hdr_dec = Cipher(aes_algo, modes.CBC(h_iv), backend=_BACKEND).decryptor()
                        hashes = hdr_dec.update(mv[pos : pos + 0x400]) + hdr_dec.finalize()

                        block_num = chunk_idx & 0xF
                        h0_off = block_num * 20
                        expected_h0_hash = hashes[h0_off : h0_off + 20]
                        expected_true_hash[:] = expected_h0_hash
                        c_iv[:] = expected_h0_hash[:16]

                        if block_num == 0:
                            c_iv[0] ^= idx_hi
                            c_iv[1] ^= idx_lo
                            expected_true_hash[0] ^= idx_hi
                            expected_true_hash[1] ^= idx_lo

                        payload_len = block_len - 0x400
                        enc_slice = mv[pos + 0x400 : block_end]
                        rem = payload_len & 0xF
                        body_dec = Cipher(aes_algo, modes.CBC(bytes(c_iv)), backend=_BACKEND).decryptor()
                        if rem != 0:
                            enc_bytes = bytes(enc_slice) + b"\x00" * (16 - rem)
                            dec_content = (body_dec.update(enc_bytes) + body_dec.finalize())[:payload_len]
                        else:
                            dec_content = body_dec.update(enc_slice) + body_dec.finalize()

                        if hashlib.sha1(dec_content).digest() != bytes(expected_true_hash):
                            raise RuntimeError(
                                T_cb("err_app_hash_fail").format(app_name, chunk_idx)
                            )

                        chunk_idx += 1
                        pos += TOTAL_BLOCK

            if log_cb:
                log_cb(T_cb("log_cafe_h3_ok").format(app_name, chunk_idx))
        else:
            aligned_size = (c.size + 15) & ~15
            actual_size = os.path.getsize(app_p)
            if actual_size != c.size and actual_size != aligned_size:
                raise RuntimeError(T_cb("err_app_size").format(app_name))

            decryptor = Cipher(aes_algo, modes.CBC(iv), backend=_BACKEND).decryptor()
            sha1 = hashlib.sha1()
            processed_size = 0
            buf = bytearray(CHUNK_SIZE)
            mv = memoryview(buf)

            with open(app_p, "rb", buffering=CHUNK_SIZE) as f:
                while processed_size < c.size:
                    if not is_running_cb():
                        return False
                    n_read = f.readinto(mv)
                    if not n_read:
                        raise RuntimeError(T_cb("err_app_stop").format(app_name))

                    rem = n_read & 0xF
                    if rem != 0:
                        padded = bytes(mv[:n_read]) + b"\x00" * (16 - rem)
                        dec_chunk = decryptor.update(padded)
                        chunk_len = len(padded)
                    else:
                        dec_chunk = decryptor.update(mv[:n_read])
                        chunk_len = n_read

                    if processed_size + len(dec_chunk) >= c.size:
                        valid_slice = dec_chunk[: c.size - processed_size]
                        sha1.update(valid_slice)
                        break
                    else:
                        sha1.update(dec_chunk)
                    processed_size += chunk_len

            computed_digest = sha1.digest()
            if computed_digest != c.hash:
                raise RuntimeError(T_cb("err_app_sha1_fail").format(app_name))

            if log_cb:
                log_cb(
                    T_cb("log_cafe_linear_ok").format(
                        app_name, c.size, binascii.hexlify(computed_digest[:8]).decode("ascii")
                    )
                )

        return True

    for c in tmd.contents:
        if not is_running_cb():
            return False
        if _verify_single_content(c) is False:
            return False

    return True


def _extract_standard_from_handle(
    f_in,
    dst_path,
    aes_algo,
    content_idx,
    offset,
    length,
    is_running_cb,
    T_cb,
    io_mv=None,
):
    force_remove(dst_path, T_cb)
    if length == 0:
        _write_bytes_fast(dst_path, b"", T_cb=T_cb)
        return

    base_iv = STRUCT_H.pack(content_idx) + b"\x00" * 14

    aligned_offset = offset & ~0xF
    skip_bytes = offset - aligned_offset
    if aligned_offset > 0:
        f_in.seek(aligned_offset - 16)
        iv = f_in.read(16)
    else:
        iv = base_iv

    decryptor = Cipher(aes_algo, modes.CBC(iv), backend=_BACKEND).decryptor()
    f_in.seek(aligned_offset)

    remaining = length
    chunk_size = CHUNK_SIZE
    first_chunk = True

    if io_mv is None:
        local_buf = bytearray(chunk_size)
        io_mv = memoryview(local_buf)

    buf_mode = 0 if length <= 262144 else min(chunk_size, max(65536, length))
    with open(dst_path, "wb", buffering=buf_mode) as f_out:
        while remaining > 0:
            if not is_running_cb():
                return
            to_read = min(chunk_size, ((remaining + skip_bytes + 15) & ~0xF))
            actual_read = f_in.readinto(io_mv[:to_read])
            if not actual_read:
                f_out.write(b"\x00" * remaining)
                break

            rem = actual_read & 0xF
            if rem != 0:
                enc_slice = bytes(io_mv[:actual_read]) + b"\x00" * (16 - rem)
                dec_data = decryptor.update(enc_slice)
            else:
                dec_data = decryptor.update(io_mv[:actual_read])

            if first_chunk:
                dec_data = dec_data[skip_bytes:]
                actual_read = max(0, actual_read - skip_bytes)
                first_chunk = False

            write_len = min(remaining, actual_read)
            f_out.write(dec_data[:write_len])
            remaining -= write_len

            if actual_read < to_read and remaining > 0:
                f_out.write(b"\x00" * remaining)
                break

    if is_running_cb() and os.path.getsize(dst_path) != length:
        raise RuntimeError(
            T_cb("err_ext_size_fail").format(os.path.basename(dst_path))
        )


def _extract_hashed_from_handle(
    f_in,
    dst_path,
    aes_algo,
    content_idx,
    offset,
    length,
    is_running_cb,
    T_cb,
    stream_state=None,
    block_mv=None,
):
    force_remove(dst_path, T_cb)
    if length == 0:
        _write_bytes_fast(dst_path, b"", T_cb=T_cb)
        return

    DATA_BLOCK, TOTAL_BLOCK = 0xFC00, 0x10000
    start_chunk_idx = offset // DATA_BLOCK
    soffset = offset % DATA_BLOCK
    h_iv = STRUCT_H.pack(content_idx) + b"\x00" * 14
    idx_hi = (content_idx >> 8) & 0xFF
    idx_lo = content_idx & 0xFF

    remaining = length
    current_chunk_idx = start_chunk_idx
    c_iv = bytearray(16)

    if block_mv is None:
        local_blk = bytearray(TOTAL_BLOCK)
        block_mv = memoryview(local_blk)

    buf_mode = 0 if length <= 262144 else min(CHUNK_SIZE, max(65536, length))
    with open(dst_path, "wb", buffering=buf_mode) as f_out:
        while remaining > 0:
            if not is_running_cb():
                return

            if stream_state is not None and stream_state[0] == current_chunk_idx:
                dec_content = stream_state[1]
            else:
                target_pos = current_chunk_idx * TOTAL_BLOCK
                if f_in.tell() != target_pos:
                    f_in.seek(target_pos)
                n_read = f_in.readinto(block_mv)
                if not n_read or n_read <= 0x400:
                    f_out.write(b"\x00" * remaining)
                    break

                hdr_dec = Cipher(aes_algo, modes.CBC(h_iv), backend=_BACKEND).decryptor()
                hashes = hdr_dec.update(block_mv[:0x400]) + hdr_dec.finalize()

                block_num = current_chunk_idx & 0xF
                h0_off = block_num * 20
                c_iv[:] = hashes[h0_off : h0_off + 16]

                if block_num == 0:
                    c_iv[0] ^= idx_hi
                    c_iv[1] ^= idx_lo

                payload_len = n_read - 0x400
                rem = payload_len & 0xF
                body_dec = Cipher(aes_algo, modes.CBC(bytes(c_iv)), backend=_BACKEND).decryptor()
                if rem != 0:
                    enc_data = bytes(block_mv[0x400:n_read]) + b"\x00" * (16 - rem)
                    dec_content = body_dec.update(enc_data) + body_dec.finalize()
                else:
                    dec_content = body_dec.update(block_mv[0x400:n_read]) + body_dec.finalize()

                if stream_state is not None:
                    stream_state[0] = current_chunk_idx
                    stream_state[1] = dec_content

            available_in_block = DATA_BLOCK - soffset
            write_len = min(remaining, available_in_block)
            to_write = dec_content[soffset : soffset + write_len]

            if len(to_write) < write_len:
                to_write += b"\x00" * (write_len - len(to_write))

            f_out.write(to_write)
            remaining -= write_len
            soffset = 0
            current_chunk_idx += 1

    if is_running_cb() and os.path.getsize(dst_path) != length:
        raise RuntimeError(
            T_cb("err_ext_size_fail").format(os.path.basename(dst_path))
        )


def extract_file_standard(
    src_app,
    dst_path,
    tkey,
    content_idx,
    offset,
    length,
    is_running_cb,
    T_cb,
):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    aes_algo = algorithms.AES(tkey)
    with open(src_app, "rb", buffering=CHUNK_SIZE) as f_in:
        _extract_standard_from_handle(
            f_in, dst_path, aes_algo, content_idx, offset, length, is_running_cb, T_cb
        )


def extract_file_hashed(
    src_app,
    dst_path,
    tkey,
    content_idx,
    offset,
    length,
    is_running_cb,
    T_cb,
):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    aes_algo = algorithms.AES(tkey)
    with open(src_app, "rb", buffering=CHUNK_SIZE) as f_in:
        _extract_hashed_from_handle(
            f_in, dst_path, aes_algo, content_idx, offset, length, is_running_cb, T_cb
        )


def process_title(
    tid,
    work_dir,
    target_dir,
    common_key,
    T_cb,
    is_running_cb,
    log_cb=None,
):
    tmd_p = os.path.join(work_dir, "title.tmd")
    tik_p = os.path.join(work_dir, "title.tik")
    cert_p = os.path.join(work_dir, "title.cert")
    clean_tid = _normalize_tid(tid)

    tmd, title_key, raw_tmd, raw_tik = _read_tmd_and_title_key(
        tmd_p, tik_p, common_key, T_cb, log_cb, expected_tid=clean_tid
    )
    aes_algo = algorithms.AES(title_key)

    c0 = next(c for c in tmd.contents if c.index == 0)
    if log_cb:
        try:
            log_cb(T_cb("log_ops_unpack_init").format(f"{c0.id:08X}", tid))
        except IndexError:
            log_cb(T_cb("log_ops_unpack_init").format(tid))

    fst_path = os.path.join(work_dir, f"{c0.id:08X}.app")
    with open(fst_path, "rb") as f:
        fst_enc = f.read()
    fst_dec = aes_cbc_decrypt(title_key, b"\x00" * 16, fst_enc, aes_algo=aes_algo)

    code_dir = os.path.join(target_dir, "code")
    os.makedirs(code_dir, exist_ok=True)
    expected_files = {}
    created_dirs = {target_dir, code_dir}

    dst_tmd_p = os.path.join(code_dir, "title.tmd")
    _write_bytes_fast(dst_tmd_p, raw_tmd, T_cb=T_cb)
    expected_files[dst_tmd_p] = len(raw_tmd)

    dst_tik_p = os.path.join(code_dir, "title.tik")
    _write_bytes_fast(dst_tik_p, raw_tik, T_cb=T_cb)
    expected_files[dst_tik_p] = len(raw_tik)

    dst_cert_p = os.path.join(code_dir, "title.cert")
    if os.path.exists(cert_p):
        shutil.copy2(cert_p, dst_cert_p)
        expected_files[dst_cert_p] = os.path.getsize(cert_p)

    is_fst = False
    info_count = 0
    entries_ptr = 0
    total_entries = 0
    name_table_off = 0

    try:
        if len(fst_dec) >= 0x20:
            info_count = STRUCT_I.unpack_from(fst_dec, 0x08)[0]
            entries_ptr = 0x20 + (info_count * 0x20)
            if entries_ptr + 16 <= len(fst_dec):
                total_entries = STRUCT_I.unpack_from(fst_dec, entries_ptr + 8)[0]
                name_table_off = entries_ptr + (total_entries * 0x10)
                if name_table_off <= len(fst_dec) and 0 < total_entries < 100000:
                    is_fst = True
    except Exception:
        pass

    if is_fst:
        fst_out_path = os.path.join(code_dir, "title.fst")
        _write_bytes_fast(fst_out_path, fst_dec, T_cb=T_cb)
        expected_files[fst_out_path] = len(fst_dec)

        if log_cb:
            try:
                log_cb(
                    T_cb("log_debug_fst_pointers").format(
                        info_count, entries_ptr, name_table_off, total_entries
                    )
                )
            except IndexError:
                log_cb(
                    T_cb("log_debug_fst_pointers").format(
                        info_count, entries_ptr, name_table_off
                    )
                )
            log_cb(T_cb("log_debug_fst_info").format(total_entries))

        path_stack, end_stack = [target_dir], [total_entries]
        content_map = {c.index: c for c in tmd.contents}
        tasks_by_cid = {}
        unpack_ii = STRUCT_II.unpack_from
        unpack_hh = STRUCT_HH.unpack_from

        for i in range(1, total_entries):
            if not is_running_cb():
                return

            while i >= end_stack[-1]:
                path_stack.pop()
                end_stack.pop()

            off = entries_ptr + (i * 0x10)
            e_type = fst_dec[off]
            e_name_off = (fst_dec[off + 1] << 16) | (fst_dec[off + 2] << 8) | fst_dec[off + 3]
            e_off, e_len = unpack_ii(fst_dec, off + 4)
            e_flags, e_cid = unpack_hh(fst_dec, off + 12)

            name_start = name_table_off + e_name_off
            name_end = fst_dec.find(b"\x00", name_start)
            if name_end == -1:
                continue

            name = fst_dec[name_start:name_end].decode("utf-8", errors="ignore")
            if not name:
                continue

            current_path = os.path.join(path_stack[-1], name)

            if e_type & 0x01:
                if log_cb:
                    log_cb(T_cb("log_debug_fst_dir").format(current_path))
                if current_path not in created_dirs:
                    os.makedirs(current_path, exist_ok=True)
                    created_dirs.add(current_path)
                path_stack.append(current_path)
                end_stack.append(e_len)
            else:
                if not (e_type & 0x80) and e_cid in content_map:
                    c = content_map[e_cid]
                    src_app = os.path.join(work_dir, f"{c.id:08X}.app")
                    real_offset = (
                        e_off << 5 if (e_flags & 0x04) == 0 else e_off
                    )
                    parent_dir = os.path.dirname(current_path)
                    if parent_dir not in created_dirs:
                        os.makedirs(parent_dir, exist_ok=True)
                        created_dirs.add(parent_dir)

                    tasks_by_cid.setdefault(e_cid, []).append((
                        real_offset,
                        c,
                        src_app,
                        current_path,
                        e_cid,
                        e_len,
                        name,
                    ))
                    expected_files[current_path] = e_len

        std_buf = None
        std_mv = None
        hsh_buf = None
        hsh_mv = None

        for e_cid, cid_tasks in tasks_by_cid.items():
            if not is_running_cb():
                return
            cid_tasks.sort(key=lambda item: item[0])
            first_c = cid_tasks[0][1]
            src_app_path = cid_tasks[0][2]
            is_hashed = bool(first_c.type & 0x02)

            if is_hashed and hsh_mv is None:
                hsh_buf = bytearray(0x10000)
                hsh_mv = memoryview(hsh_buf)
            elif not is_hashed and std_mv is None:
                std_buf = bytearray(CHUNK_SIZE)
                std_mv = memoryview(std_buf)

            stream_state = [-1, b""] if is_hashed else None
            with open(src_app_path, "rb", buffering=CHUNK_SIZE) as f_in:
                for real_offset, c, _, current_path, cid_val, e_len, name in cid_tasks:
                    if not is_running_cb():
                        return
                    try:
                        if log_cb:
                            try:
                                log_cb(
                                    T_cb("log_debug_fst_file").format(
                                        current_path, cid_val, real_offset, e_len
                                    )
                                )
                            except IndexError:
                                log_cb(
                                    T_cb("log_debug_fst_file").format(
                                        current_path, real_offset, e_len
                                    )
                                )
                        if is_hashed:
                            _extract_hashed_from_handle(
                                f_in,
                                current_path,
                                aes_algo,
                                cid_val,
                                real_offset,
                                e_len,
                                is_running_cb,
                                T_cb,
                                stream_state=stream_state,
                                block_mv=hsh_mv,
                            )
                        else:
                            _extract_standard_from_handle(
                                f_in,
                                current_path,
                                aes_algo,
                                cid_val,
                                real_offset,
                                e_len,
                                is_running_cb,
                                T_cb,
                                io_mv=std_mv,
                            )
                    except Exception as e:
                        raise RuntimeError(
                            T_cb("err_ext_fatal").format(name, str(e))
                        )

        if is_running_cb():
            _verify_expected_files_fast(expected_files, created_dirs, T_cb)
            if log_cb:
                log_cb(
                    T_cb("log_cafe_fst_summary").format(
                        tid, len(expected_files), len(created_dirs)
                    )
                )
    else:
        if log_cb:
            try:
                log_cb(
                    T_cb("log_ops_raw_binary_mode").format(tid, len(tmd.contents))
                )
            except IndexError:
                log_cb(T_cb("log_ops_raw_binary_mode").format(tid))

        content_dir = os.path.join(target_dir, "content")
        os.makedirs(content_dir, exist_ok=True)
        created_dirs.add(content_dir)
        buf = bytearray(CHUNK_SIZE)
        mv = memoryview(buf)

        for c in tmd.contents:
            if not is_running_cb():
                return
            src_app = os.path.join(work_dir, f"{c.id:08X}.app")
            dst_path = os.path.join(content_dir, f"{c.id:08X}.app")

            if not os.path.exists(src_app):
                raise RuntimeError(T_cb("err_app_miss").format(f"{c.id:08X}.app"))

            iv = STRUCT_H.pack(c.index) + b"\x00" * 14
            with open(src_app, "rb", buffering=CHUNK_SIZE) as f_in, open(
                dst_path, "wb", buffering=CHUNK_SIZE
            ) as f_out:
                decryptor = Cipher(aes_algo, modes.CBC(iv), backend=_BACKEND).decryptor()
                remaining = c.size
                while remaining > 0:
                    if not is_running_cb():
                        return
                    n_read = f_in.readinto(mv)
                    if not n_read:
                        break
                    rem = n_read & 0xF
                    if rem != 0:
                        padded = bytes(mv[:n_read]) + b"\x00" * (16 - rem)
                        dec = decryptor.update(padded)
                    else:
                        dec = decryptor.update(mv[:n_read])
                    write_len = min(remaining, len(dec))
                    f_out.write(dec[:write_len])
                    remaining -= write_len

            expected_files[dst_path] = c.size

        if is_running_cb():
            _verify_expected_files_fast(expected_files, created_dirs, T_cb)

    return True
