import csv
import os
import re
import socket
import struct
import time
import stat
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .core_3ds import (
    build_cia,
    get_sig_len,
    validate_tmd_and_tik,
    verify_built_cia,
)

CDNS = [
    "http://nus.cdn.c.shop.nintendowifi.net/ccs/download",
    "https://nus.cdn.c.shop.nintendowifi.net/ccs/download",
    "http://ccs.cdn.c.shop.nintendowifi.net/ccs/download",
    "https://nus.cdn.t.shop.nintendowifi.net/ccs/download",
    "https://nus.c.shop.nintendowifi.net/ccs/download",
    "https://nus.cdn.shop.wii.com/ccs/download",
]

_cdn_lock = threading.Lock()
_active_cdn_idx = 0

MAX_CONCURRENT_SUB_DL = 32
CHUNK_SIZE = 4 * 1024 * 1024
IN_MEMORY_MAX_SIZE = 4 * 1024 * 1024

_SUB_DL_POOL = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SUB_DL)


class _FastTCPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        sock_opts = list(HTTPConnection.default_socket_options) + [
            (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        pool_kwargs["socket_options"] = sock_opts
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


SHARED_SESSION = requests.Session()
_adapter = _FastTCPAdapter(
    pool_connections=128, pool_maxsize=128, max_retries=2, pool_block=False
)
SHARED_SESSION.mount("http://", _adapter)
SHARED_SESSION.mount("https://", _adapter)
SHARED_SESSION.verify = False
SHARED_SESSION.headers.update({
    "User-Agent": "Nintendo 3DS (CTR-001)",
    "Connection": "keep-alive",
    "Accept-Encoding": "identity",
})

RE_FW = re.compile(r"(\d+)\.(\d+)\.(\d+)-(\d+)")
STRUCT_BE_I = struct.Struct(">I")
STRUCT_BE_H = struct.Struct(">H")
STRUCT_BE_Q = struct.Struct(">Q")


def _get_ordered_cdns() -> list:
    with _cdn_lock:
        idx = _active_cdn_idx
    return CDNS[idx:] + CDNS[:idx]


def _set_preferred_cdn(cdn_url: str):
    global _active_cdn_idx
    if cdn_url in CDNS:
        with _cdn_lock:
            _active_cdn_idx = CDNS.index(cdn_url)


def parse_fw_string(fw_str: str) -> tuple:
    match = RE_FW.search(fw_str)
    if match:
        return tuple(int(x) for x in match.groups())
    return (0, 0, 0, 0)


def _safe_unlink(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except PermissionError:
        try:
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
            path.unlink()
        except Exception:
            pass
    except OSError:
        pass


def _write_bytes_fast(dst_path: Path, data):
    mv = data if isinstance(data, memoryview) else memoryview(data)
    total = len(mv)
    raw_p = str(dst_path)
    try:
        with open(raw_p, "wb", buffering=0) as f:
            written = 0
            while written < total:
                n = f.write(mv[written:])
                if not n:
                    break
                written += n
    except PermissionError:
        _safe_unlink(dst_path)
        with open(raw_p, "wb", buffering=0) as f:
            written = 0
            while written < total:
                n = f.write(mv[written:])
                if not n:
                    break
                written += n
    if written != total:
        raise IOError(dst_path.name)


def download_in_memory(
    url: str,
    is_stopped_cb=None,
    retries=3,
    log_callback=None,
    T_cb=None,
    adv_logs=False,
) -> tuple:
    for attempt in range(retries):
        if is_stopped_cb and is_stopped_cb():
            return None, "STOPPED"
        if adv_logs and log_callback and T_cb:
            log_callback(T_cb("log_ctr_http_get").format(url, attempt + 1, retries))

        try:
            t0 = time.monotonic()
            r = SHARED_SESSION.get(url, timeout=(5, 12))
            latency_ms = int((time.monotonic() - t0) * 1000)
            status = r.status_code

            if status == 200:
                content = r.content
                content_len = int(r.headers.get("Content-Length", len(content)))
                if content_len > 0 and len(content) != content_len:
                    if attempt == retries - 1:
                        return None, "SIZE_MISMATCH"
                    time.sleep(0.15)
                    continue
                if adv_logs and log_callback and T_cb:
                    try:
                        log_callback(
                            T_cb("log_http_res").format(status, len(content), latency_ms)
                        )
                    except IndexError:
                        log_callback(T_cb("log_http_res").format(status, len(content)))
                return content, status
            else:
                if adv_logs and log_callback and T_cb:
                    log_callback(T_cb("log_ctr_http_err").format(status, url))
                if status == 404 or attempt == retries - 1:
                    return None, status

        except Exception as e:
            if adv_logs and log_callback and T_cb:
                log_callback(T_cb("log_ctr_http_err").format(str(e), url))
            if attempt == retries - 1:
                return None, str(e)

        time.sleep(0.15)

    return None, "TIMEOUT"


def get_yls_db(sys_type: str, is_stopped_cb=None) -> dict:
    url = f"https://yls8.mtheall.com/ninupdates/titlelist.php?sys={sys_type}&csv=1"
    csv_data, _ = download_in_memory(url, is_stopped_cb)
    if not csv_data:
        return {}

    lines = csv_data.decode("utf-8", errors="ignore").splitlines()
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
            tv_clean = int(tv_str[1:]) if tv_str.startswith("v") else int(tv_str)
            db[region][t_id].append((parse_fw_string(fv_str), tv_clean))

    return db


def _download_single_fragment(
    cid: str,
    expected_size: int,
    output_dir: Path,
    servers_to_try: list,
    T_cb,
    is_stopped_cb=None,
    log_callback=None,
    advanced_logs=False,
) -> tuple[bool, object]:
    content_path = output_dir / cid
    tmp_path = output_dir / f"{cid}.tmp"
    last_error = "UNKNOWN"

    for base_url in servers_to_try:
        for _ in range(3):
            if is_stopped_cb and is_stopped_cb():
                return False, "STOPPED"
            req_url = f"{base_url}/{cid}"
            try:
                if advanced_logs and log_callback:
                    try:
                        log_callback(T_cb("log_req_fragment").format(cid, req_url))
                    except IndexError:
                        log_callback(T_cb("log_req_fragment").format(req_url))

                t_frag0 = time.monotonic()

                if expected_size <= IN_MEMORY_MAX_SIZE:
                    r = SHARED_SESSION.get(req_url, timeout=(5, 15))
                    if r.status_code != 200:
                        last_error = r.status_code
                        if r.status_code == 404:
                            break
                        time.sleep(0.15)
                        continue

                    data = r.content
                    written = len(data)
                    if expected_size > 0 and written != expected_size:
                        last_error = "SIZE_MISMATCH"
                        time.sleep(0.15)
                        continue

                    _write_bytes_fast(content_path, data)
                else:
                    try:
                        downloaded_so_far = tmp_path.stat().st_size
                    except OSError:
                        downloaded_so_far = 0

                    if downloaded_so_far > expected_size:
                        _safe_unlink(tmp_path)
                        downloaded_so_far = 0

                    headers = {}
                    if downloaded_so_far > 0:
                        headers["Range"] = f"bytes={downloaded_so_far}-"

                    with SHARED_SESSION.get(
                        req_url, headers=headers, stream=True, timeout=(8, 25)
                    ) as r:
                        if r.status_code == 416:
                            _safe_unlink(tmp_path)
                            downloaded_so_far = 0
                            continue
                        if r.status_code not in (200, 206):
                            last_error = r.status_code
                            if r.status_code == 404:
                                break
                            time.sleep(0.2)
                            continue

                        mode = "ab" if r.status_code == 206 else "wb"
                        if mode == "wb":
                            downloaded_so_far = 0

                        written = downloaded_so_far
                        with open(tmp_path, mode, buffering=CHUNK_SIZE) as f:
                            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                                if is_stopped_cb and is_stopped_cb():
                                    return False, "STOPPED"
                                if chunk:
                                    f.write(chunk)
                                    written += len(chunk)

                    if expected_size > 0 and written != expected_size:
                        _safe_unlink(tmp_path)
                        last_error = "SIZE_MISMATCH"
                        time.sleep(0.2)
                        continue

                    os.replace(tmp_path, content_path)

                frag_ms = int((time.monotonic() - t_frag0) * 1000)
                if advanced_logs and log_callback:
                    try:
                        log_callback(
                            T_cb("log_frag_saved").format(cid, written, frag_ms)
                        )
                    except IndexError:
                        log_callback(T_cb("log_frag_saved").format(written))
                return True, 200

            except Exception as e:
                last_error = str(e)
                _safe_unlink(content_path)
                time.sleep(0.2)

    return False, last_error


def download_raw_files(
    title_id: str,
    output_dir: Path,
    version: int,
    T_cb,
    is_stopped_cb=None,
    log_callback=None,
    advanced_logs=False,
) -> tuple:
    tmd_data, cetk_data = None, None
    successful_base_url = ""
    last_error = "UNKNOWN"

    if advanced_logs and log_callback:
        ver_str = f"v{version}" if version is not None else "LATEST"
        log_callback(T_cb("log_dl_start").format(title_id, ver_str))

    ordered_cdns = _get_ordered_cdns()

    for idx_cdn, cdn in enumerate(ordered_cdns):
        if is_stopped_cb and is_stopped_cb():
            return False, "STOPPED"
        if idx_cdn > 0 and advanced_logs and log_callback:
            log_callback(T_cb("log_ctr_cdn_switch").format(cdn))

        base_url = f"{cdn}/{title_id}"
        tmd_url = f"{base_url}/tmd.{version}" if version is not None else f"{base_url}/tmd"
        tik_url = f"{base_url}/cetk"

        if not tmd_data and not cetk_data:
            fut_tik = _SUB_DL_POOL.submit(
                download_in_memory,
                tik_url,
                is_stopped_cb,
                2,
                log_callback,
                T_cb,
                advanced_logs,
            )
            tmd_data, st_tmd = download_in_memory(
                tmd_url,
                is_stopped_cb,
                2,
                log_callback=log_callback,
                T_cb=T_cb,
                adv_logs=advanced_logs,
            )
            cetk_data, st_tik = fut_tik.result()
            if st_tmd != 200:
                tmd_data = None
                last_error = st_tmd
                continue
            if st_tik != 200:
                cetk_data = None
                last_error = st_tik
                continue
        else:
            if not tmd_data:
                tmd_data, st_tmd = download_in_memory(
                    tmd_url,
                    is_stopped_cb,
                    2,
                    log_callback=log_callback,
                    T_cb=T_cb,
                    adv_logs=advanced_logs,
                )
                if st_tmd != 200:
                    tmd_data = None
                    last_error = st_tmd
                    continue
            if not cetk_data:
                cetk_data, st_tik = download_in_memory(
                    tik_url,
                    is_stopped_cb,
                    2,
                    log_callback=log_callback,
                    T_cb=T_cb,
                    adv_logs=advanced_logs,
                )
                if st_tik != 200:
                    cetk_data = None
                    last_error = st_tik
                    continue

        if tmd_data and cetk_data:
            successful_base_url = base_url
            _set_preferred_cdn(cdn)
            break

    if not tmd_data or not cetk_data:
        if advanced_logs and log_callback:
            log_callback(T_cb("err_dl_fail_adv").format(title_id, last_error))
        return False, last_error

    try:
        tmd_obj, _, _ = validate_tmd_and_tik(title_id, tmd_data, cetk_data, T_cb)
    except Exception as e:
        return False, str(e)

    _write_bytes_fast(output_dir / "tmd.bin", tmd_data)
    _write_bytes_fast(output_dir / "tik.bin", cetk_data)

    tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)

    if advanced_logs and log_callback:
        try:
            log_callback(
                T_cb("log_tmd_parsed").format(
                    tmd_sig_type, tmd_sig_len, tmd_obj.title_version, tmd_obj.content_count
                )
            )
        except IndexError:
            log_callback(T_cb("log_tmd_parsed").format(tmd_sig_type, tmd_obj.content_count))

    existing_sizes = {}
    try:
        with os.scandir(output_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if entry.name.endswith(".tmp"):
                        _safe_unlink(Path(entry.path))
                    else:
                        existing_sizes[entry.name] = entry.stat(follow_symlinks=False).st_size
    except OSError:
        pass

    pending_specs = []
    for i, c in enumerate(tmd_obj.contents):
        if advanced_logs and log_callback:
            try:
                log_callback(
                    T_cb("log_tmd_cid").format(c.index, c.id_hex, c.type, c.size)
                )
            except IndexError:
                log_callback(T_cb("log_tmd_cid").format(i, c.id_hex))

        if existing_sizes.get(c.id_hex, -1) != c.size:
            pending_specs.append(c)

    pending_specs.sort(key=lambda item: item.size, reverse=True)

    servers_to_try = [successful_base_url] if successful_base_url else []
    for cdn in ordered_cdns:
        url_candidate = f"{cdn}/{title_id}"
        if url_candidate not in servers_to_try:
            servers_to_try.append(url_candidate)

    if len(pending_specs) == 1:
        c = pending_specs[0]
        ok, err = _download_single_fragment(
            c.id_hex,
            c.size,
            output_dir,
            servers_to_try,
            T_cb,
            is_stopped_cb,
            log_callback,
            advanced_logs,
        )
        if not ok:
            return False, err
    elif len(pending_specs) > 1:
        sub_futures = [
            _SUB_DL_POOL.submit(
                _download_single_fragment,
                c.id_hex,
                c.size,
                output_dir,
                servers_to_try,
                T_cb,
                is_stopped_cb,
                log_callback,
                advanced_logs,
            )
            for c in pending_specs[1:]
        ]
        c0 = pending_specs[0]
        ok0, err0 = _download_single_fragment(
            c0.id_hex,
            c0.size,
            output_dir,
            servers_to_try,
            T_cb,
            is_stopped_cb,
            log_callback,
            advanced_logs,
        )
        if not ok0:
            for f in sub_futures:
                f.cancel()
            return False, err0

        for f in as_completed(sub_futures):
            ok_sub, err_sub = f.result()
            if not ok_sub:
                for rem_f in sub_futures:
                    rem_f.cancel()
                return False, err_sub

    return True, 200


def _read_meta_from_disk(output_dir: Path):
    tmd_path = output_dir / "tmd.bin"
    tik_path = output_dir / "tik.bin"
    if not tmd_path.is_file() or not tik_path.is_file():
        return None, None
    return tmd_path.read_bytes(), tik_path.read_bytes()


def verify_integrity(
    title_id: str,
    output_dir: Path,
    T_cb,
    is_stopped_cb=None,
    log_callback=None,
    advanced_logs=False,
) -> bool:
    tmd_data, cetk_data = _read_meta_from_disk(output_dir)
    if not tmd_data or not cetk_data:
        return False

    try:
        tmd_obj, _, _ = validate_tmd_and_tik(title_id, tmd_data, cetk_data, T_cb)
    except Exception as e:
        if advanced_logs and log_callback:
            log_callback(str(e))
        return False

    existing_sizes = {}
    try:
        with os.scandir(output_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if entry.name.endswith(".tmp"):
                        return False
                    existing_sizes[entry.name] = entry.stat(follow_symlinks=False).st_size
    except OSError:
        return False

    total_verified_bytes = 0
    for c in tmd_obj.contents:
        if is_stopped_cb and is_stopped_cb():
            return False

        actual_sz = existing_sizes.get(c.id_hex, -1)
        if actual_sz != c.size:
            if advanced_logs and log_callback:
                log_callback(T_cb("err_size_invalid"))
            return False

        total_verified_bytes += actual_sz

    if advanced_logs and log_callback:
        try:
            log_callback(
                T_cb("log_ctr_verify_ok").format(
                    title_id,
                    tmd_obj.title_version,
                    len(tmd_data),
                    len(cetk_data),
                    tmd_obj.content_count,
                    total_verified_bytes,
                )
            )
        except Exception:
            log_callback(T_cb("log_pack_success").format(title_id))

    return True


def pack_cia(
    title_id: str,
    tmp_title_dir: Path,
    final_out_dir: Path,
    T_cb,
    boot9_path=None,
    is_stopped_cb=None,
    log_callback=None,
    decrypt=False,
    advanced_logs=False,
) -> bool:
    tmd_data, cetk_data = _read_meta_from_disk(tmp_title_dir)
    if not tmd_data or not cetk_data:
        return False

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
        log_cb=log_callback,
        advanced_logs=advanced_logs,
    )

    if not success:
        _safe_unlink(cia_path)
        return False

    is_valid, msg = verify_built_cia(
        cia_path, T_cb, log_cb=log_callback, advanced_logs=advanced_logs
    )
    if not is_valid:
        if log_callback:
            log_callback(T_cb("err_pack_cia") + f" : {msg}")
        _safe_unlink(cia_path)
        return False
    elif advanced_logs and log_callback:
        cia_sz = cia_path.stat().st_size if cia_path.exists() else 0
        try:
            log_callback(T_cb("log_pack_success").format(cia_path.name, cia_sz))
        except IndexError:
            log_callback(T_cb("log_pack_success").format(cia_path.name))

    return True
