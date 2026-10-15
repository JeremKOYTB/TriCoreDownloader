import os
import sys
import json
import time
import shutil
import re
import stat
import threading
import traceback
import concurrent.futures
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..Languages.locales import STRINGS

from .worker_ops import (
    get_common_key,
    verify_common_key_online,
    get_default_cert,
    download_title_files,
    verify_title_integrity,
    process_title,
    get_yls8_versions,
    create_optimized_session,
)

RE_LEGACY_FW = re.compile(r"^(\d+)\.")

PRIORITY_HEAVY_TIDS = {
    "0005001010040000", "0005001010040100", "0005001010040200",
    "000500301001200a", "000500301001210a", "000500301001220a",
    "000500301001400a", "000500301001410a", "000500301001420a",
    "000500301001600a", "000500301001610a", "000500301001620a",
    "000500101004a000", "000500101004a100", "000500101004a200",
    "0005001010047000", "0005001010047100", "0005001010047200",
    "000500101004e000", "000500101004e100", "000500101004e200",
}


def _on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except Exception:
        pass


def _fast_rmtree(target_dir: Path):
    if not target_dir.exists():
        return
    for _ in range(3):
        try:
            shutil.rmtree(target_dir, onerror=_on_rm_error)
            if not target_dir.exists():
                return
        except Exception:
            pass
        time.sleep(0.05)


class CafeDownloaderWorker(QThread):
    log_signal = pyqtSignal(str)
    log_replace_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    ask_overwrite_signal = pyqtSignal(str)
    ask_skip_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, version, config):
        super().__init__()
        self.version = str(version).strip()
        self.config = config
        self._is_running = True

        self._skip_choice = None
        self._always_choice = False
        self._skip_event = threading.Event()
        self._always_skip_404 = False

        self._prompt_lock = threading.Lock()
        self._step_lock = threading.Lock()
        self._data_lock = threading.Lock()

        self.lang = str(self.config.get("lang", "EN")).upper()
        self._lang_dict = STRINGS.get(self.lang) or STRINGS.get(
            self.lang.lower(), STRINGS.get("EN", {})
        )

        reg_upper = self.version.upper()
        self.region = reg_upper if reg_upper in ["EUR", "USA", "JPN"] else "EUR"

        self.titles_json_path = self.resolve_titles_json_path()
        self.region_dir = None
        self._last_replace_str = ""
        self._last_replace_ts = 0.0
        self._active_session = None

    def resolve_titles_json_path(self) -> Path:
        filename = "titles_cafe.json"
        candidates = []

        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / filename)
            candidates.append(Path(sys._MEIPASS) / "TriCoreDownloader" / filename)

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / filename)
            candidates.append(exe_dir / "TriCoreDownloader" / filename)
            candidates.append(exe_dir / "_internal" / filename)
            candidates.append(exe_dir / "_internal" / "TriCoreDownloader" / filename)
            candidates.append(exe_dir.parent / "Resources" / filename)
            candidates.append(exe_dir.parent / "Resources" / "TriCoreDownloader" / filename)

        curr = Path(__file__).resolve()
        candidates.append(curr.parent.parent / filename)
        candidates.append(curr.parent / filename)
        candidates.append(Path.cwd() / filename)
        candidates.append(Path.cwd() / "TriCoreDownloader" / filename)

        for p in candidates:
            if p.is_file():
                return p

        return curr.parent.parent / filename

    def receive_skip_choice(self, choice, always=False):
        self._skip_choice = bool(choice)
        self._always_choice = bool(always)
        self._skip_event.set()

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

    def is_running(self):
        return self._is_running

    def stop(self):
        self._is_running = False
        self._skip_event.set()
        if self._active_session:
            try:
                self._active_session.close()
            except Exception:
                pass

    def _generate_bar(self, current, total, length=20):
        percent = current / total if total > 0 else 1.0
        filled = int(length * percent)
        empty_char = " " if sys.platform == "win32" or os.name == "nt" else "░"
        bar = "█" * filled + empty_char * (length - filled)
        return f"[{bar}] {int(percent * 100):>3}%"

    def _emit_replace_throttled(self, text: str, force: bool = False):
        now = time.monotonic()
        if force or (text != self._last_replace_str and (now - self._last_replace_ts) >= 0.03):
            self._last_replace_str = text
            self._last_replace_ts = now
            self.log_replace_signal.emit(text)

    def _cleanup_partial_files(self):
        if not self.region_dir:
            return

        target_dir = Path(self.region_dir)
        if not target_dir.exists():
            return

        _fast_rmtree(target_dir)

        if not target_dir.exists():
            msg_purge = self.T("log_purge_interrupt").format(self.region)
            self.log_signal.emit(msg_purge)

    def run(self):
        try:
            adv_logs = bool(self.config.get("advanced_logs", False))
            log_cb = self.debug_log if adv_logs else None
            start_time = time.monotonic()

            if adv_logs:
                self.debug_log("==================================================", raw=True)
                self.debug_log(self.T("log_cafe_banner_init"), raw=True)
                self.debug_log("==================================================", raw=True)

            out_base_str = self.config.get("output_dir", "").strip()
            if not out_base_str:
                raise ValueError(self.T("err_no_out_dir"))

            out_base = Path(out_base_str)
            self.region_dir = out_base / self.region

            if self.region_dir.exists():
                try:
                    _fast_rmtree(self.region_dir)
                    msg_pre_purge = self.T("log_pre_purge").format(self.region)
                    if adv_logs:
                        self.debug_log(msg_pre_purge)
                    else:
                        self.log_signal.emit(msg_pre_purge)
                except Exception as e:
                    raise RuntimeError(
                        self.T("err_pre_purge").format(self.region, e)
                    )

            if not self.titles_json_path.exists():
                raise FileNotFoundError(self.T("err_titles_json_missing"))

            try:
                with open(self.titles_json_path, "r", encoding="utf-8") as f:
                    titles_data = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(self.T("err_json_corrupted").format(str(e)))

            if adv_logs:
                mlc_map = titles_data.get("MLC", {})
                slc_map = titles_data.get("SLC", {})
                mlc_cnt = len(mlc_map.get(self.region, [])) + len(mlc_map.get("All", []))
                slc_cnt = len(slc_map.get(self.region, [])) + len(slc_map.get("All", []))
                self.debug_log(
                    self.T("log_cafe_json_loaded").format(
                        self.titles_json_path, mlc_cnt, slc_cnt
                    )
                )

            otp_input = self.config.get("otp_path", "").strip()
            common_key = get_common_key(otp_input, self.T, log_cb)
            verify_common_key_online(common_key, self.T, log_cb)

            raw_partitions = self.config.get("cafe_partitions", ["MLC", "SLC"])
            title_types_list = (
                [raw_partitions]
                if isinstance(raw_partitions, str)
                else (raw_partitions or ["MLC", "SLC"])
            )

            will_extract = bool(self.config.get("cafe_extract", False))
            cemu_layout = bool(self.config.get("cafe_cemu_layout", False))
            phases_count = 3 if will_extract else 2

            if adv_logs:
                try:
                    self.debug_log(
                        self.T("log_worker_config_ok").format(
                            self.region,
                            "ON" if will_extract else "OFF",
                            "ON" if cemu_layout else "OFF",
                        )
                    )
                except IndexError:
                    self.debug_log(self.T("log_worker_config_ok").format(self.region))

            target_fw = self.config.get("target_firmware", "").strip()
            title_versions = {}
            is_legacy_fw = False
            shared_session = create_optimized_session()
            self._active_session = shared_session

            try:
                get_default_cert(self.T, log_cb, session=shared_session)

                if target_fw:
                    match = RE_LEGACY_FW.match(target_fw)
                    if match and int(match.group(1)) < 2:
                        is_legacy_fw = True

                    if is_legacy_fw:
                        msg_legacy = self.T("log_legacy_fw").format(target_fw)
                        if adv_logs:
                            self.debug_log(msg_legacy)
                        else:
                            self.log_signal.emit(f"[*] {msg_legacy}")
                    else:
                        msg_fetch = self.T("log_yls8_fetch").format(target_fw)
                        if adv_logs:
                            self.debug_log(msg_fetch)
                        else:
                            self.log_signal.emit(f"[*] {msg_fetch}")

                        try:
                            title_versions = get_yls8_versions(
                                self.region,
                                target_fw,
                                session=shared_session,
                                T_cb=self.T,
                            )
                            if adv_logs:
                                self.debug_log(
                                    self.T("log_cafe_yls8_resolved").format(
                                        target_fw, self.region, len(title_versions)
                                    )
                                )
                        except ValueError as ve:
                            if str(ve) == "not_found":
                                err_nf = self.T("err_yls8_not_found").format(
                                    target_fw, self.region
                                )
                                raise RuntimeError(self.T("err_yls8_fail").format(err_nf))
                            raise RuntimeError(self.T("err_yls8_fail").format(str(ve)))
                        except Exception as e:
                            raise RuntimeError(self.T("err_yls8_fail").format(str(e)))

                tasks_per_partition = {}
                global_total_steps = 0
                total_processed_tids = 0

                for title_type in title_types_list:
                    titles_map = titles_data.get(title_type, {})
                    selected_region_titles = titles_map.get(self.region, [])
                    all_region_titles = titles_map.get("All", [])

                    seen_in_partition = set()
                    all_tids = []
                    for tid in (selected_region_titles + all_region_titles):
                        if tid == "dummy":
                            continue
                        norm_t = tid.lower().replace("-", "").strip()
                        if norm_t and norm_t not in seen_in_partition:
                            seen_in_partition.add(norm_t)
                            all_tids.append(tid)

                    valid_tids = []
                    for tid in all_tids:
                        tid_low = tid.lower()
                        if target_fw:
                            if is_legacy_fw:
                                title_versions[tid_low] = 0
                                valid_tids.append(tid)
                            else:
                                if tid_low in title_versions:
                                    valid_tids.append(tid)
                                else:
                                    skip_str = self.T("log_title_skipped")
                                    try:
                                        formatted_skip = skip_str.format(tid)
                                    except Exception:
                                        formatted_skip = f"[*] {skip_str} ({tid})"
                                    if adv_logs:
                                        self.debug_log(formatted_skip)
                                    else:
                                        self.log_signal.emit(formatted_skip)
                        else:
                            valid_tids.append(tid)

                    valid_tids.sort(
                        key=lambda t: (0 if t.lower().replace("-", "") in PRIORITY_HEAVY_TIDS else 1)
                    )
                    tasks_per_partition[title_type] = valid_tids
                    global_total_steps += len(valid_tids) * phases_count
                    total_processed_tids += len(valid_tids)

                if global_total_steps == 0:
                    self.log_signal.emit(self.T("log_no_titles_found"))
                    self.finished_signal.emit(True, "")
                    return

                global_current_step = 0

                cpu_count = os.cpu_count() or 4
                dl_workers = min(8, max(2, cpu_count))
                vr_workers = min(4, max(1, cpu_count - 1 or 1))
                ex_workers = min(4, max(1, cpu_count - 1 or 1))

                if adv_logs:
                    self.debug_log(
                        self.T("log_cafe_pool_config").format(
                            dl_workers, vr_workers, ex_workers
                        )
                    )

                for title_type in title_types_list:
                    if not self._is_running:
                        break

                    all_tids = tasks_per_partition[title_type]
                    if not all_tids:
                        continue

                    raw_dir = self.region_dir / title_type
                    total_tids = len(all_tids)

                    msg_found = self.T("log_found_ready").format(total_tids, title_type)
                    if adv_logs:
                        self.debug_log(msg_found.strip())
                    else:
                        self.log_signal.emit(f"\n{msg_found}")

                    skipped_tids = set()

                    msg_dl_adv = self.T("log_phase1_adv").format(title_type).strip()
                    msg_dl_norm = self.T("log_phase1_norm").format(title_type).strip()

                    if adv_logs:
                        self.debug_log("\n==================================================", raw=True)
                        self.debug_log(msg_dl_adv, raw=True)
                        self.debug_log("==================================================", raw=True)
                    else:
                        init_dl_str = f" {msg_dl_norm}   {self._generate_bar(0, total_tids)}"
                        self._last_replace_str = init_dl_str
                        self.log_signal.emit(init_dl_str)

                    completed_dl = 0

                    def _download_task(tid):
                        nonlocal completed_dl, global_current_step
                        if not self._is_running:
                            raise RuntimeError("STOPPED")

                        work_dir = raw_dir / tid
                        if adv_logs:
                            self.debug_log(
                                self.T("log_worker_dl_id_adv").format(tid)
                            )

                        target_ver = title_versions.get(tid.lower())
                        try:
                            if not download_title_files(
                                tid,
                                str(work_dir),
                                self.T,
                                self.is_running,
                                log_cb,
                                target_ver,
                                shared_session=shared_session,
                            ):
                                if self._is_running:
                                    raise RuntimeError(self.T("err_dl_id").format(tid))
                        except RuntimeError as e:
                            if "404" in str(e):
                                with self._prompt_lock:
                                    if not self._is_running:
                                        raise RuntimeError("STOPPED")

                                    if self._always_skip_404:
                                        self.log_signal.emit(self.T("log_skip_404").format(tid))
                                        with self._data_lock:
                                            skipped_tids.add(tid)
                                    else:
                                        self._skip_choice = None
                                        self._always_choice = False
                                        self._skip_event.clear()
                                        self.ask_skip_signal.emit(tid)

                                        while self._is_running and not self._skip_event.is_set():
                                            self._skip_event.wait(timeout=0.05)

                                        if not self._is_running:
                                            raise RuntimeError("STOPPED")

                                        if self._always_choice:
                                            self._always_skip_404 = True

                                        if self._skip_choice:
                                            self.log_signal.emit(self.T("log_skip_404").format(tid))
                                            with self._data_lock:
                                                skipped_tids.add(tid)
                                        else:
                                            self.log_signal.emit(self.T("log_abort_404"))
                                            raise RuntimeError(
                                                self.T("err_abort_404").format(tid)
                                            )
                            else:
                                raise

                        with self._step_lock:
                            completed_dl += 1
                            global_current_step += 1
                            if not adv_logs and self._is_running:
                                self._emit_replace_throttled(
                                    f" {msg_dl_norm}   {self._generate_bar(completed_dl, total_tids)}",
                                    force=(completed_dl == total_tids),
                                )
                            self.progress_signal.emit(
                                global_current_step, global_total_steps
                            )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=dl_workers) as executor:
                        futures = [executor.submit(_download_task, tid) for tid in all_tids]
                        try:
                            for fut in concurrent.futures.as_completed(futures):
                                if not self._is_running:
                                    executor.shutdown(wait=False, cancel_futures=True)
                                    raise RuntimeError("STOPPED")
                                fut.result()
                        except Exception:
                            executor.shutdown(wait=False, cancel_futures=True)
                            raise

                    if not adv_logs and self._is_running:
                        self._emit_replace_throttled(
                            f" {msg_dl_norm} ✓ {self._generate_bar(total_tids, total_tids)}",
                            force=True,
                        )

                    if not self._is_running:
                        break

                    msg_vr_adv = self.T("log_phase2_adv").format(title_type).strip()
                    msg_vr_norm = self.T("log_phase2_norm").format(title_type).strip()

                    if adv_logs:
                        self.debug_log("\n==================================================", raw=True)
                        self.debug_log(msg_vr_adv, raw=True)
                        self.debug_log("==================================================", raw=True)
                    else:
                        init_vr_str = f" {msg_vr_norm}   {self._generate_bar(0, total_tids)}"
                        self._last_replace_str = init_vr_str
                        self.log_signal.emit(init_vr_str)

                    completed_vr = 0

                    def _verify_task(tid):
                        nonlocal completed_vr, global_current_step
                        if not self._is_running:
                            raise RuntimeError("STOPPED")

                        if tid in skipped_tids:
                            with self._step_lock:
                                completed_vr += 1
                                global_current_step += 1
                                self.progress_signal.emit(
                                    global_current_step, global_total_steps
                                )
                            return

                        work_dir = raw_dir / tid
                        if adv_logs:
                            self.debug_log(
                                self.T("log_worker_verify_id_adv").format(tid)
                            )

                        if not verify_title_integrity(
                            tid,
                            str(work_dir),
                            common_key,
                            self.T,
                            self.is_running,
                            log_cb,
                        ):
                            if self._is_running:
                                raise RuntimeError(self.T("err_integ_id").format(tid))

                        with self._step_lock:
                            completed_vr += 1
                            global_current_step += 1
                            if not adv_logs and self._is_running:
                                self._emit_replace_throttled(
                                    f" {msg_vr_norm}   {self._generate_bar(completed_vr, total_tids)}",
                                    force=(completed_vr == total_tids),
                                )
                            self.progress_signal.emit(
                                global_current_step, global_total_steps
                            )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=vr_workers) as executor:
                        futures = [executor.submit(_verify_task, tid) for tid in all_tids]
                        try:
                            for fut in concurrent.futures.as_completed(futures):
                                if not self._is_running:
                                    executor.shutdown(wait=False, cancel_futures=True)
                                    raise RuntimeError("STOPPED")
                                fut.result()
                        except Exception:
                            executor.shutdown(wait=False, cancel_futures=True)
                            raise

                    if not adv_logs and self._is_running:
                        self._emit_replace_throttled(
                            f" {msg_vr_norm} ✓ {self._generate_bar(total_tids, total_tids)}",
                            force=True,
                        )

                    if not self._is_running:
                        break

                    if not will_extract:
                        msg_skip = self.T("log_ext_skip").format(title_type)
                        if adv_logs:
                            self.debug_log(msg_skip.strip())
                        else:
                            self.log_signal.emit(msg_skip)
                    else:
                        msg_ex_adv = self.T("log_phase3_adv").format(title_type).strip()
                        msg_ex_norm = self.T("log_phase3_norm").format(title_type).strip()

                        if adv_logs:
                            self.debug_log("\n==================================================", raw=True)
                            self.debug_log(msg_ex_adv, raw=True)
                            self.debug_log("==================================================", raw=True)
                        else:
                            init_ex_str = f" {msg_ex_norm}   {self._generate_bar(0, total_tids)}"
                            self._last_replace_str = init_ex_str
                            self.log_signal.emit(init_ex_str)

                        completed_ex = 0

                        def _extract_task(tid):
                            nonlocal completed_ex, global_current_step
                            if not self._is_running:
                                raise RuntimeError("STOPPED")

                            if tid in skipped_tids:
                                with self._step_lock:
                                    completed_ex += 1
                                    global_current_step += 1
                                    self.progress_signal.emit(
                                        global_current_step, global_total_steps
                                    )
                                return

                            work_dir = raw_dir / tid
                            if adv_logs:
                                self.debug_log(
                                    self.T("log_worker_extract_id_adv").format(tid)
                                )

                            clean_tid = (
                                tid.replace("-", "")
                                .replace("/", "")
                                .replace("\\", "")
                                .strip()
                            )

                            if cemu_layout:
                                if len(clean_tid) == 16:
                                    tid_high = clean_tid[:8].lower()
                                    tid_low = clean_tid[8:].lower()
                                    title_dest = (
                                        self.region_dir
                                        / "Extracted"
                                        / "mlc01"
                                        / "sys"
                                        / "title"
                                        / tid_high
                                        / tid_low
                                    )
                                else:
                                    title_dest = (
                                        self.region_dir
                                        / "Extracted"
                                        / "mlc01"
                                        / "sys"
                                        / "title"
                                        / clean_tid.lower()
                                    )
                            else:
                                title_dest = self.region_dir / "Extracted" / title_type / clean_tid

                            title_dest.mkdir(parents=True, exist_ok=True)
                            process_title(
                                tid,
                                str(work_dir),
                                str(title_dest),
                                common_key,
                                self.T,
                                self.is_running,
                                log_cb,
                            )

                            with self._step_lock:
                                completed_ex += 1
                                global_current_step += 1
                                if not adv_logs and self._is_running:
                                    self._emit_replace_throttled(
                                        f" {msg_ex_norm}   {self._generate_bar(completed_ex, total_tids)}",
                                        force=(completed_ex == total_tids),
                                    )
                                self.progress_signal.emit(
                                    global_current_step, global_total_steps
                                )

                        with concurrent.futures.ThreadPoolExecutor(max_workers=ex_workers) as executor:
                            futures = [executor.submit(_extract_task, tid) for tid in all_tids]
                            try:
                                for fut in concurrent.futures.as_completed(futures):
                                    if not self._is_running:
                                        executor.shutdown(wait=False, cancel_futures=True)
                                        raise RuntimeError("STOPPED")
                                    fut.result()
                            except Exception:
                                executor.shutdown(wait=False, cancel_futures=True)
                                raise

                        if not adv_logs and self._is_running:
                            self._emit_replace_throttled(
                                f" {msg_ex_norm} ✓ {self._generate_bar(total_tids, total_tids)}",
                                force=True,
                            )
            finally:
                self._active_session = None
                try:
                    shared_session.close()
                except Exception:
                    pass

            if not self._is_running:
                self._cleanup_partial_files()
                self.finished_signal.emit(False, "STOPPED")
                return

            final_dir_str = str(self.region_dir)
            self.region_dir = None
            elapsed_time = time.monotonic() - start_time

            self.log_signal.emit("\n==================================================")
            self.log_signal.emit(self.T("log_op_complete"))
            self.log_signal.emit("")
            self.log_signal.emit(self.T("log_time_elapsed").format(f"{elapsed_time:.2f}"))
            self.log_signal.emit(self.T("log_titles_proc").format(total_processed_tids))
            self.log_signal.emit("")
            self.log_signal.emit(self.T("log_all_verified"))

            if will_extract:
                if cemu_layout:
                    self.log_signal.emit(self.T("log_ext_cemu"))
                else:
                    self.log_signal.emit(self.T("log_ext_offline"))
            else:
                self.log_signal.emit(self.T("log_ext_isfshax"))

            self.log_signal.emit("==================================================")
            self.progress_signal.emit(global_total_steps, global_total_steps)
            self.finished_signal.emit(True, final_dir_str)

        except Exception as e:
            self._cleanup_partial_files()
            if self._is_running and str(e) != "STOPPED":
                self.log_signal.emit(f"\n[!] ERROR: {str(e)}")
                if self.config.get("advanced_logs", False):
                    self.log_signal.emit(self.T("log_tech_trace"))
                    for line in traceback.format_exc().strip().split("\n"):
                        self.log_signal.emit(f"   {line}")
                self.finished_signal.emit(False, str(e))
            else:
                self.finished_signal.emit(False, "STOPPED")
