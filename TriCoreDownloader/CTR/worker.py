import sys
import os
import re
import stat
import shutil
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal

from .system_titles import get_system_title_ids
from .worker_ops import (
    get_yls_db,
    download_raw_files,
    verify_integrity,
    pack_cia,
)
from ..Languages.locales import STRINGS

RE_CTR_FW = re.compile(r"^(\d+)\.(\d+)\.(\d+)-(\d+)$")
VALID_PREFIXES = (
    "00040010",
    "00040030",
    "00040130",
    "00040138",
    "0004009B",
    "000400DB",
    "0004800",
)
PRIORITY_HEAVY_CTR_PREFIXES = (
    "0004009B",
    "000400DB",
    "00040030",
    "00040010",
    "00048005",
    "00048004",
    "00040138",
)
REGION_TO_LETTER = {
    "EUR": "E",
    "USA": "U",
    "JPN": "J",
    "KOR": "K",
    "CHN": "C",
    "TWN": "T",
    "AUS": "E",
}


def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except Exception:
        pass


def _dir_total_size(path: Path) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
    except OSError:
        pass
    return total


class CtrDownloaderWorker(QThread):
    log_signal = pyqtSignal(str)
    log_replace_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)

    ask_overwrite_signal = pyqtSignal(str)
    ask_skip_signal = pyqtSignal(bool)

    def __init__(self, target_fw: str, is_new_3ds: bool, config: dict):
        super().__init__()
        self.target_fw = str(target_fw).strip()
        self.is_new_3ds = bool(is_new_3ds)
        self.config = config
        self._is_stopped = False
        self._step_lock = threading.Lock()

        cpu_count = os.cpu_count() or 4
        self.max_workers_dl = min(20, max(8, cpu_count * 2))
        self.max_workers_cpu = min(12, max(4, cpu_count))
        self.max_workers_build = min(8, max(2, cpu_count))

        self.lang = str(self.config.get("lang", "EN")).upper()
        self._lang_dict = STRINGS.get(self.lang) or STRINGS.get(
            self.lang.lower(), STRINGS.get("EN", {})
        )

        self._current_out_dir = None
        self._current_tmp_dir = None
        self._active_executor = None
        self._last_replace_text = ""
        self._last_replace_ts = 0.0

    def T(self, key, default=None):
        return self._lang_dict.get(key, default if default is not None else key)

    def debug_log(self, msg, raw=False):
        if self.config.get("advanced_logs", False):
            text = str(msg)
            if raw:
                self.log_signal.emit(text)
            else:
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.log_signal.emit(f"[{now}] {text}")

    def stop(self):
        self._is_stopped = True
        if self._active_executor:
            try:
                self._active_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def _is_stopped_cb(self):
        return self._is_stopped

    def _emit_replace_throttled(self, text: str, force: bool = False):
        now = time.monotonic()
        if force or (text != self._last_replace_text and (now - self._last_replace_ts) >= 0.03):
            self._last_replace_text = text
            self._last_replace_ts = now
            self.log_replace_signal.emit(text)

    def _robust_rmtree(self, path: Path):
        if not path or not isinstance(path, Path) or not path.exists():
            return
        for _ in range(3):
            try:
                shutil.rmtree(path, onerror=_rmtree_onerror)
                if not path.exists():
                    return
            except Exception:
                pass
            time.sleep(0.05)
        shutil.rmtree(path, ignore_errors=True)

    def _emergency_cleanup(self):
        if self._current_tmp_dir:
            self._robust_rmtree(self._current_tmp_dir)
        if self._current_out_dir and self._current_out_dir.exists():
            try:
                has_cia = any(self._current_out_dir.glob("*.cia"))
                if not has_cia:
                    self._robust_rmtree(self._current_out_dir)
            except Exception:
                pass

    def _text_bar(self, prefix: str, percent: int, width: int = 20) -> str:
        percent = max(0, min(100, percent))
        filled = (percent * width) // 100 if width > 0 else 0
        empty_char = " " if sys.platform == "win32" or os.name == "nt" else "░"
        bar = "█" * filled + empty_char * (width - filled)
        return f" {prefix} [{bar}] {int(percent):>3}%"

    def run(self):
        try:
            start_time = time.monotonic()
            is_latest_mode = self.target_fw in ("LATEST", "AUTO")
            verbose_logs = bool(self.config.get("advanced_logs", False))
            will_decrypt = bool(self.config.get("decrypt_cia", False))
            boot9_path = self.config.get("boot9_path") or self.config.get("boot9", None)

            def log_callback(msg):
                if verbose_logs:
                    self.debug_log(msg)
                else:
                    self.log_signal.emit(str(msg))

            if verbose_logs:
                self.debug_log("==================================================", raw=True)
                self.debug_log(self.T("log_ctr_banner_init"), raw=True)
                self.debug_log("==================================================", raw=True)
                self.debug_log(
                    self.T("log_ctr_pool_config").format(
                        self.max_workers_dl, self.max_workers_cpu, self.max_workers_build
                    )
                )

            if will_decrypt:
                if verbose_logs:
                    self.debug_log(self.T("log_boot9_precheck"))

                if not boot9_path or not Path(str(boot9_path).strip("\"'")).is_file():
                    self.log_signal.emit("\n[!] " + self.T("err_boot9_missing_fatal"))
                    self.finished_signal.emit(False, "BOOT9_MISSING")
                    return

                try:
                    from pyctr.crypto import CryptoEngine
                    resolved_b9 = str(Path(str(boot9_path).strip("\"'")).resolve())
                    _ = CryptoEngine(boot9=resolved_b9)
                    if verbose_logs:
                        try:
                            self.debug_log(self.T("log_boot9_ok").format(resolved_b9))
                        except IndexError:
                            self.debug_log(self.T("log_boot9_ok"))
                except Exception as e:
                    self.log_signal.emit(
                        "\n[!] " + self.T("err_boot9_corrupt").format(e)
                    )
                    self.finished_signal.emit(False, "BOOT9_CORRUPT")
                    return

            display_region = self.config.get("ctr_region", "EUR")
            region_key = "EUR" if display_region == "AUS" else display_region
            target_sys_ver = None

            if verbose_logs:
                self.debug_log(self.T("log_region_forced").format(f"{display_region} (NUS: {region_key})"))

            if not is_latest_mode:
                match = RE_CTR_FW.match(self.target_fw)
                if match:
                    target_sys_ver = tuple(int(x) for x in match.groups()[:4])
                else:
                    self.log_signal.emit("\n[!] " + self.T("err_invalid_fw_format"))
                    self.finished_signal.emit(False, "INVALID_FW_FORMAT")
                    return

            model_tag = "NEW" if self.is_new_3ds else "OLD"
            target_ids = list(get_system_title_ids(region_key, self.is_new_3ds))

            if not target_ids:
                self.log_signal.emit(
                    "\n[!] " + self.T("err_no_title_id").format(region_key)
                )
                self.finished_signal.emit(False, "NO_TITLE_ID_DB")
                return

            titles_to_download = []
            if verbose_logs:
                sys_label = "ctr + ktr" if self.is_new_3ds else "ctr"
                try:
                    self.debug_log(self.T("log_query_servers").format(sys_label))
                except IndexError:
                    self.debug_log(self.T("log_query_servers"))

            if self.is_new_3ds:
                with ThreadPoolExecutor(max_workers=2) as db_exec:
                    f_ctr = db_exec.submit(get_yls_db, "ctr", self._is_stopped_cb)
                    f_ktr = db_exec.submit(get_yls_db, "ktr", self._is_stopped_cb)
                    db_pool = f_ctr.result()
                    db_ktr = f_ktr.result()
                if self._is_stopped:
                    return self._handle_stop()
                if region_key in db_ktr:
                    if region_key not in db_pool:
                        db_pool[region_key] = {}
                    for t_id, versions in db_ktr[region_key].items():
                        db_pool[region_key][t_id] = versions
            else:
                db_pool = get_yls_db("ctr", self._is_stopped_cb)

            if self._is_stopped:
                return self._handle_stop()

            region_db = db_pool.get(region_key, {})
            if verbose_logs:
                self.debug_log(
                    self.T("log_ctr_yls8_resolved").format(
                        region_key, len(region_db)
                    )
                )

            if is_latest_mode:
                highest_fw_tuple = (0, 0, 0, 0)
                for versions in region_db.values():
                    for fw_tuple, _ in versions:
                        if fw_tuple > highest_fw_tuple:
                            highest_fw_tuple = fw_tuple

                if highest_fw_tuple != (0, 0, 0, 0):
                    fw_letter = REGION_TO_LETTER.get(region_key, "E")
                    self.target_fw = f"{highest_fw_tuple[0]}.{highest_fw_tuple[1]}.{highest_fw_tuple[2]}-{highest_fw_tuple[3]}{fw_letter}"

            self.log_signal.emit(self.T("log_dl_fw_target").format(self.target_fw))

            server_titles = set(region_db.keys())
            local_titles = set(target_ids)
            if self.is_new_3ds:
                local_titles.update(get_system_title_ids(region_key, False))

            missing_titles = server_titles - local_titles
            if missing_titles:
                filtered_new_titles = sorted(
                    t for t in missing_titles if t.startswith(VALID_PREFIXES)
                )
                if filtered_new_titles:
                    target_ids.extend(filtered_new_titles)
                    if verbose_logs:
                        try:
                            self.debug_log(
                                self.T("log_mapped_modules").format(
                                    len(filtered_new_titles), ", ".join(filtered_new_titles[:6])
                                )
                            )
                        except IndexError:
                            self.debug_log(
                                self.T("log_mapped_modules").format(len(filtered_new_titles))
                            )

            seen_tids = set()
            for t_id in target_ids:
                t_up = t_id.strip().upper()
                if not t_up or t_up in seen_tids:
                    continue
                seen_tids.add(t_up)

                versions = region_db.get(t_up, [])
                if not versions:
                    if is_latest_mode:
                        titles_to_download.append((t_up, None))
                    continue

                if is_latest_mode:
                    optimal_tv = max(versions, key=lambda x: x[1])[1]
                    titles_to_download.append((t_up, optimal_tv))
                else:
                    optimal_tv, optimal_sv = None, None
                    for sv, tv in versions:
                        if sv <= target_sys_ver:
                            if optimal_sv is None or sv > optimal_sv:
                                optimal_sv = sv
                                optimal_tv = tv
                    if optimal_tv is not None:
                        titles_to_download.append((t_up, optimal_tv))

            def _dl_priority_key(item):
                tid_str = item[0]
                for idx_p, pref in enumerate(PRIORITY_HEAVY_CTR_PREFIXES):
                    if tid_str.startswith(pref):
                        return (idx_p, tid_str)
                return (len(PRIORITY_HEAVY_CTR_PREFIXES), tid_str)

            titles_to_download.sort(key=_dl_priority_key)

            total_titles = len(titles_to_download)
            if total_titles == 0:
                self.log_signal.emit("\n[!] " + self.T("err_no_valid_titles"))
                self.finished_signal.emit(False, "NO_VALID_TITLES")
                return

            if verbose_logs:
                try:
                    self.debug_log(
                        self.T("log_resolve_versions").format(
                            total_titles, self.target_fw, model_tag
                        )
                    )
                except IndexError:
                    self.debug_log(self.T("log_resolve_versions"))

            base_out_dir = Path(self.config.get("output_dir", "output"))
            fw_folder_name = f"{self.target_fw.replace('.', '_').replace('-', '_')}_{display_region}_{model_tag}"

            self._current_out_dir = base_out_dir / fw_folder_name
            self._current_tmp_dir = self._current_out_dir / "tmp"

            if self._current_out_dir.exists() and any(self._current_out_dir.iterdir()):
                if verbose_logs:
                    self.debug_log(self.T("log_folder_cleared"))
                self._robust_rmtree(self._current_out_dir)

            self._current_out_dir.mkdir(parents=True, exist_ok=True)
            self._current_tmp_dir.mkdir(parents=True, exist_ok=True)

            global_total_steps = total_titles * (4 if will_decrypt else 3)
            global_current_step = 0

            if not verbose_logs:
                self.log_signal.emit(self.T("log_titles_found").format(total_titles))

            successful_downloads = []
            failed_downloads = []
            completed_downloads = 0

            if verbose_logs:
                self.debug_log("\n==================================================", raw=True)
                self.debug_log(self.T("log_phase1_start").format(total_titles).strip(), raw=True)
                self.debug_log("==================================================", raw=True)
            else:
                init_bar = self._text_bar(self.T("step_dl"), 0)
                self._last_replace_text = init_bar
                self.log_signal.emit(init_bar)

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers_dl)
            with self._active_executor as executor:
                future_to_tid = {}
                for t_id, ver in titles_to_download:
                    if self._is_stopped:
                        break
                    tmp_title_dir = self._current_tmp_dir / t_id
                    tmp_title_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        future = executor.submit(
                            download_raw_files,
                            t_id,
                            tmp_title_dir,
                            ver,
                            self.T,
                            self._is_stopped_cb,
                            log_callback,
                            verbose_logs,
                        )
                        future_to_tid[future] = (t_id, tmp_title_dir)
                    except RuntimeError:
                        break

                for future in as_completed(future_to_tid):
                    if self._is_stopped:
                        break
                    t_id, tmp_title_dir = future_to_tid[future]
                    completed_downloads += 1
                    global_current_step += 1

                    try:
                        success, err_code = future.result()
                        percent = (completed_downloads * 100) // total_titles
                        self.progress_signal.emit(
                            global_current_step, global_total_steps
                        )

                        if success:
                            successful_downloads.append((t_id, tmp_title_dir))
                        else:
                            failed_downloads.append((t_id, err_code))

                        if not verbose_logs:
                            self._emit_replace_throttled(
                                self._text_bar(self.T("step_dl"), percent),
                                force=(completed_downloads == total_titles),
                            )
                    except Exception as e:
                        failed_downloads.append((t_id, str(e)))

            self._active_executor = None
            if self._is_stopped:
                return self._handle_stop()
            if not successful_downloads:
                raise RuntimeError(self.T("err_phase1_fail"))

            total_verify = len(successful_downloads)
            verified_titles = []
            completed_verifications = 0

            if verbose_logs:
                self.debug_log("\n==================================================", raw=True)
                self.debug_log(self.T("log_phase2_start").format(total_verify).strip(), raw=True)
                self.debug_log("==================================================", raw=True)
            else:
                init_bar = self._text_bar(self.T("step_verify"), 0)
                self._last_replace_text = init_bar
                self.log_signal.emit(init_bar)

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers_cpu)
            with self._active_executor as executor:
                future_to_tid = {}
                for t_id, t_dir in successful_downloads:
                    if self._is_stopped:
                        break
                    try:
                        future = executor.submit(
                            verify_integrity,
                            t_id,
                            t_dir,
                            self.T,
                            self._is_stopped_cb,
                            log_callback,
                            verbose_logs,
                        )
                        future_to_tid[future] = (t_id, t_dir)
                    except RuntimeError:
                        break

                for future in as_completed(future_to_tid):
                    if self._is_stopped:
                        break
                    t_id, t_dir = future_to_tid[future]
                    completed_verifications += 1
                    global_current_step += 1

                    try:
                        is_valid = future.result()
                        if not is_valid:
                            if self._is_stopped:
                                return self._handle_stop()
                            raise RuntimeError(self.T("err_size_invalid"))

                        percent = (completed_verifications * 100) // total_verify
                        self.progress_signal.emit(
                            global_current_step, global_total_steps
                        )
                        verified_titles.append((t_id, t_dir, _dir_total_size(t_dir)))

                        if not verbose_logs:
                            self._emit_replace_throttled(
                                self._text_bar(self.T("step_verify"), percent),
                                force=(completed_verifications == total_verify),
                            )
                    except Exception as e:
                        if self._is_stopped:
                            return self._handle_stop()
                        raise RuntimeError(self.T("err_verify_fail").format(e))

            self._active_executor = None
            if self._is_stopped:
                return self._handle_stop()

            total_build = len(verified_titles)
            verified_titles.sort(key=lambda x: (-x[2], x[0]))
            built_titles = []
            completed_builds = 0

            if verbose_logs:
                self.debug_log("\n==================================================", raw=True)
                self.debug_log(self.T("log_phase3_start").format(total_build).strip(), raw=True)
                self.debug_log("==================================================", raw=True)
            else:
                init_bar = self._text_bar(self.T("step_build"), 0)
                self._last_replace_text = init_bar
                self.log_signal.emit(init_bar)

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers_build)
            with self._active_executor as executor:
                future_to_build = {}
                for t_id, t_dir, t_sz in verified_titles:
                    if self._is_stopped:
                        break
                    fut = executor.submit(
                        pack_cia,
                        t_id,
                        t_dir,
                        self._current_out_dir,
                        self.T,
                        boot9_path=boot9_path,
                        is_stopped_cb=self._is_stopped_cb,
                        log_callback=log_callback,
                        decrypt=False,
                        advanced_logs=verbose_logs,
                    )
                    future_to_build[fut] = (t_id, t_dir, t_sz)

                for fut in as_completed(future_to_build):
                    if self._is_stopped:
                        break
                    t_id, t_dir, t_sz = future_to_build[fut]
                    try:
                        success = fut.result()
                        if not success:
                            if self._is_stopped:
                                return self._handle_stop()
                            raise RuntimeError(self.T("err_build_failed").format(t_id))

                        with self._step_lock:
                            completed_builds += 1
                            global_current_step += 1
                            built_titles.append((t_id, t_dir, t_sz))
                            percent = (completed_builds * 100) // total_build
                            self.progress_signal.emit(global_current_step, global_total_steps)
                            if not verbose_logs:
                                self._emit_replace_throttled(
                                    self._text_bar(self.T("step_build"), percent),
                                    force=(completed_builds == total_build),
                                )
                    except Exception as e:
                        if self._is_stopped:
                            return self._handle_stop()
                        raise RuntimeError(self.T("err_assemble_fail").format(e))

            self._active_executor = None
            if self._is_stopped:
                return self._handle_stop()

            if will_decrypt and built_titles:
                built_titles.sort(key=lambda x: (-x[2], x[0]))
                total_decrypt = len(built_titles)
                completed_decrypts = 0

                if verbose_logs:
                    self.debug_log("\n==================================================", raw=True)
                    try:
                        self.debug_log(self.T("log_phase4_start").format(total_decrypt).strip(), raw=True)
                    except IndexError:
                        self.debug_log(self.T("log_phase4_start").strip(), raw=True)
                    self.debug_log("==================================================", raw=True)
                    self.debug_log(self.T("log_3ds_start_decrypt"))
                else:
                    init_bar = self._text_bar(self.T("step_decrypt"), 0)
                    self._last_replace_text = init_bar
                    self.log_signal.emit(init_bar)

                self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers_build)
                with self._active_executor as executor:
                    future_to_dec = {}
                    for t_id, t_dir, _ in built_titles:
                        if self._is_stopped:
                            break
                        fut = executor.submit(
                            pack_cia,
                            t_id,
                            t_dir,
                            self._current_out_dir,
                            self.T,
                            boot9_path=boot9_path,
                            is_stopped_cb=self._is_stopped_cb,
                            log_callback=log_callback,
                            decrypt=True,
                            advanced_logs=verbose_logs,
                        )
                        future_to_dec[fut] = (t_id, t_dir)

                    for fut in as_completed(future_to_dec):
                        if self._is_stopped:
                            break
                        t_id, t_dir = future_to_dec[fut]
                        try:
                            success = fut.result()
                            if not success:
                                if self._is_stopped:
                                    return self._handle_stop()
                                raise RuntimeError(self.T("err_decrypt_fail").format(t_id))

                            with self._step_lock:
                                completed_decrypts += 1
                                global_current_step += 1
                                percent = (completed_decrypts * 100) // total_decrypt
                                self.progress_signal.emit(
                                    global_current_step, global_total_steps
                                )
                                if not verbose_logs:
                                    self._emit_replace_throttled(
                                        self._text_bar(self.T("step_decrypt"), percent),
                                        force=(completed_decrypts == total_decrypt),
                                    )
                        except Exception as e:
                            if self._is_stopped:
                                return self._handle_stop()
                            raise RuntimeError(self.T("err_decrypt_fail").format(e))

                self._active_executor = None
                if self._is_stopped:
                    return self._handle_stop()

            self._robust_rmtree(self._current_tmp_dir)
            self._current_tmp_dir = None

            elapsed_time = time.monotonic() - start_time

            if failed_downloads:
                self.log_signal.emit("\n\n[!] " + self.T("warn_dl_failures"))
                for tid, err in failed_downloads:
                    self.log_signal.emit(
                        f"    • {tid} " + self.T("err_network_code").format(err)
                    )

            self.log_signal.emit("\n==================================================")
            self.log_signal.emit(
                self.T("log_success_final").format(self._current_out_dir)
            )

            try:
                stats_msg = self.T("log_stats_full").format(
                    elapsed_time, len(built_titles), total_titles
                )
            except Exception:
                stats_msg = self.T("log_stats_full").format(
                    f"{elapsed_time:.2f}", len(built_titles), total_titles
                )
            self.log_signal.emit(stats_msg)

            self.log_signal.emit("==================================================")

            self.progress_signal.emit(global_total_steps, global_total_steps)
            self.finished_signal.emit(True, str(self._current_out_dir))

        except Exception as e:
            if self._is_stopped:
                return self._handle_stop()

            if verbose_logs:
                self.log_signal.emit("\n==================================================")
                self.log_signal.emit(traceback.format_exc())

            self.log_signal.emit("\n[!] " + self.T("err_critical_abort"))
            self.log_signal.emit(" ▸ " + str(e))
            self.log_signal.emit(self.T("log_emergency_cleanup"))
            self._emergency_cleanup()
            self.finished_signal.emit(False, str(e))

        finally:
            if self._active_executor:
                self._active_executor.shutdown(wait=False, cancel_futures=True)

    def _handle_stop(self):
        self.log_signal.emit("\n\n[!] " + self.T("log_cancelled"))
        self._emergency_cleanup()
        self.finished_signal.emit(False, "STOPPED")
