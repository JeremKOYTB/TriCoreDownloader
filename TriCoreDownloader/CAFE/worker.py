import os
import json
import time
import shutil
import re
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..Languages.locales import STRINGS

from .worker_ops import (
    get_common_key, 
    verify_common_key_online,
    download_title_files, 
    verify_title_integrity, 
    process_title,
    get_yls8_versions
)

class CafeDownloaderWorker(QThread):
    log_signal = pyqtSignal(str)
    log_replace_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    ask_overwrite_signal = pyqtSignal(str)
    ask_skip_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, version, config):
        super().__init__()
        print(f"[CAFE WORKER] Initialized with target firmware version: {version}")
        self.version = version
        self.config = config
        self._is_running = True
        
        self._skip_choice = None
        self._always_choice = False
        self._skip_event = threading.Event()
        self._always_skip_404 = False
        
        self.lang = self.config.get("lang", "en")
        self.region = self.version.upper() if self.version.upper() in ["EUR", "USA", "JPN"] else "EUR"
        
        base_dir = Path(__file__).resolve().parent.parent
        self.titles_json_path = base_dir / "titles_cafe.json"
        self.region_dir = None

    def receive_skip_choice(self, choice, always=False):
        print(f"[CAFE WORKER] Received 404 skip choice from UI: {choice} (Always: {always})")
        self._skip_choice = choice
        self._always_choice = always
        self._skip_event.set()

    def T(self, key):
        return STRINGS.get(self.lang, STRINGS.get("en", {})).get(key, key)

    def debug_log(self, msg):
        if self.config.get("advanced_logs", False):
            self.log_signal.emit(msg)

    def is_running(self):
        return self._is_running

    def stop(self):
        print("[CAFE WORKER] Interruption signal received.")
        self._is_running = False

    def _generate_bar(self, current, total, length=20):
        percent = current / total if total > 0 else 1
        filled = int(length * percent)
        bar = '█' * filled + ' ' * (length - filled)
        return f"[{bar}] {int(percent * 100)}%"

    def _cleanup_partial_files(self):
        try:
            purged = False
            if self.region_dir and self.region_dir.exists():
                time.sleep(0.5) 
                shutil.rmtree(self.region_dir, ignore_errors=True)
                purged = True
                
            if purged:
                print(f"[CAFE WORKER] Cleaned up temporary directory: {self.region_dir}")
                msg_purge = self.T("log_purge_interrupt").format(self.region)
                self.log_signal.emit(msg_purge)
        except Exception as e:
            print(f"[CAFE WORKER ERROR] Cleanup failed: {e}")
            self.log_signal.emit(self.T("log_purge_err").format(e))

    def run(self):
        try:
            print("[CAFE WORKER] Execution thread started.")
            adv_logs = self.config.get("advanced_logs", False)
            start_time = time.time()

            out_base_str = self.config.get("output_dir", "").strip()
            if not out_base_str:
                raise ValueError(self.T("err_no_out_dir"))

            out_base = Path(out_base_str)
            self.region_dir = out_base / self.region

            if self.region_dir.exists():
                try:
                    shutil.rmtree(self.region_dir, ignore_errors=True)
                    msg_pre_purge = self.T("log_pre_purge").format(self.region)
                    self.log_signal.emit(msg_pre_purge)
                except Exception as e:
                    raise RuntimeError(self.T("err_pre_purge").format(self.region, e))

            if not self.titles_json_path.exists():
                raise FileNotFoundError(self.T("err_titles_json_missing"))

            with open(self.titles_json_path, "r", encoding="utf-8") as f:
                titles_data = json.load(f)

            otp_input = self.config.get("otp_path", "").strip()
            common_key = get_common_key(otp_input, self.T, self.debug_log)
            verify_common_key_online(common_key, self.T, self.debug_log)
            
            raw_partitions = self.config.get("cafe_partitions", ["MLC", "SLC"])
            title_types_list = [raw_partitions] if isinstance(raw_partitions, str) else raw_partitions
            
            will_extract = self.config.get("cafe_extract", False)
            phases_count = 3 if will_extract else 2
            
            if adv_logs:
                self.log_signal.emit(self.T("log_worker_config_ok").format(self.region))
            
            target_fw = self.config.get("target_firmware", "").strip()
            title_versions = {}
            is_legacy_fw = False
            
            if target_fw:
                match = re.match(r"^(\d+)\.", target_fw)
                if match and int(match.group(1)) < 2:
                    is_legacy_fw = True
                    
                if is_legacy_fw:
                    msg_legacy = self.T("log_legacy_fw").format(target_fw)
                    self.log_signal.emit(f"[*] {msg_legacy}")
                else:
                    msg_fetch = self.T("log_yls8_fetch").format(target_fw)
                    self.log_signal.emit(f"[*] {msg_fetch}")
                    
                    try:
                        title_versions = get_yls8_versions(self.region, target_fw)
                    except ValueError:
                        err_nf = self.T("err_yls8_not_found").format(target_fw, self.region)
                        raise RuntimeError(self.T("err_yls8_fail").format(err_nf))
                    except Exception as e:
                        raise RuntimeError(self.T("err_yls8_fail").format(str(e)))

            tasks_per_partition = {}
            global_total_steps = 0
            total_processed_tids = 0

            for title_type in title_types_list:
                titles_map = titles_data.get(title_type, {})
                selected_region_titles = titles_map.get(self.region, [])
                all_region_titles = titles_map.get("All", [])
                all_tids = [tid for tid in (selected_region_titles + all_region_titles) if tid != "dummy"]
                
                valid_tids = []
                for tid in all_tids:
                    if target_fw:
                        if is_legacy_fw:
                            title_versions[tid.lower()] = 0
                            valid_tids.append(tid)
                        else:
                            if tid.lower() in title_versions:
                                valid_tids.append(tid)
                            else:
                                fallback_msg = f"[*] Skipped {tid} (not found for {target_fw})"
                                skip_str = self.T("log_title_skipped")
                                self.log_signal.emit(skip_str.format(tid) if skip_str != "log_title_skipped" else fallback_msg)
                    else:
                        valid_tids.append(tid)
                
                tasks_per_partition[title_type] = valid_tids
                global_total_steps += len(valid_tids) * phases_count
                total_processed_tids += len(valid_tids)

            if global_total_steps == 0:
                print("[CAFE WORKER] No valid Title IDs compiled to download.")
                self.log_signal.emit(self.T("log_no_titles_found"))
                self.finished_signal.emit(True, "")
                return

            global_current_step = 0
            
            for title_type in title_types_list:
                if not self._is_running: break
                
                all_tids = tasks_per_partition[title_type]
                if not all_tids: continue

                raw_dir = self.region_dir / title_type
                total_tids = len(all_tids)
                
                msg_found = self.T("log_found_ready").format(total_tids, title_type)
                self.log_signal.emit(f"\n{msg_found}")

                skipped_tids = set()

                msg_dl_adv = self.T("log_phase1_adv").format(title_type).strip()
                msg_dl_norm = self.T("log_phase1_norm").format(title_type).strip()

                if adv_logs: self.log_signal.emit(msg_dl_adv)
                else: self.log_signal.emit(f" {msg_dl_norm} {self._generate_bar(0, total_tids)}")

                for i, tid in enumerate(all_tids):
                    if not self._is_running: break
                    work_dir = raw_dir / tid
                    
                    if adv_logs:
                        self.log_signal.emit(self.T("log_worker_dl_id_adv").format(tid))
                    else:
                        self.log_replace_signal.emit(f" {msg_dl_norm} {self._generate_bar(i + 1, total_tids)}")
                    
                    target_ver = title_versions.get(tid.lower())
                    
                    try:
                        if not download_title_files(tid, str(work_dir), self.T, self.is_running, self.debug_log, target_ver):
                            if self._is_running: raise RuntimeError(self.T("err_dl_id").format(tid))
                    except RuntimeError as e:
                        if "404" in str(e):
                            if self._always_skip_404:
                                self.log_signal.emit(self.T("log_skip_404").format(tid))
                                skipped_tids.add(tid)
                                global_current_step += 1
                                self.progress_signal.emit(global_current_step, global_total_steps)
                                if not adv_logs:
                                    self.log_signal.emit(f" {msg_dl_norm} {self._generate_bar(i + 1, total_tids)}")
                                continue

                            self._skip_choice = None
                            self._always_choice = False
                            self._skip_event.clear()
                            self.ask_skip_signal.emit(tid)
                            
                            while self._is_running and not self._skip_event.is_set():
                                time.sleep(0.1)
                                
                            if self._always_choice:
                                self._always_skip_404 = True

                            if self._skip_choice:
                                self.log_signal.emit(self.T("log_skip_404").format(tid))
                                skipped_tids.add(tid)
                                global_current_step += 1
                                self.progress_signal.emit(global_current_step, global_total_steps)
                                if not adv_logs:
                                    self.log_signal.emit(f" {msg_dl_norm} {self._generate_bar(i + 1, total_tids)}")
                                continue
                            else:
                                self.log_signal.emit(self.T("log_abort_404"))
                                raise RuntimeError(self.T("err_abort_404").format(tid))
                        else:
                            raise
                    
                    global_current_step += 1
                    self.progress_signal.emit(global_current_step, global_total_steps)

                if not adv_logs and self._is_running:
                    self.log_replace_signal.emit(f" {msg_dl_norm} ✓ {self._generate_bar(total_tids, total_tids)}")

                if not self._is_running: break

                msg_vr_adv = self.T("log_phase2_adv").format(title_type).strip()
                msg_vr_norm = self.T("log_phase2_norm").format(title_type).strip()

                if adv_logs: self.log_signal.emit(msg_vr_adv)
                else: self.log_signal.emit(f" {msg_vr_norm} {self._generate_bar(0, total_tids)}")
                    
                for i, tid in enumerate(all_tids):
                    if not self._is_running: break
                    
                    if tid in skipped_tids:
                        global_current_step += 1
                        self.progress_signal.emit(global_current_step, global_total_steps)
                        continue
                        
                    work_dir = raw_dir / tid
                    
                    if adv_logs:
                        self.log_signal.emit(self.T("log_worker_verify_id_adv").format(tid))
                    else:
                        self.log_replace_signal.emit(f" {msg_vr_norm} {self._generate_bar(i + 1, total_tids)}")
                    
                    if not verify_title_integrity(tid, str(work_dir), common_key, self.T, self.is_running, self.debug_log):
                        if self._is_running: raise RuntimeError(self.T("err_integ_id").format(tid))
                    
                    global_current_step += 1
                    self.progress_signal.emit(global_current_step, global_total_steps)

                if not adv_logs and self._is_running:
                    self.log_replace_signal.emit(f" {msg_vr_norm} ✓ {self._generate_bar(total_tids, total_tids)}")

                if not self._is_running: break

                if not will_extract:
                    msg_skip = self.T("log_ext_skip").format(title_type)
                    self.log_signal.emit(msg_skip)
                else:
                    msg_ex_adv = self.T("log_phase3_adv").format(title_type).strip()
                    msg_ex_norm = self.T("log_phase3_norm").format(title_type).strip()

                    if adv_logs: self.log_signal.emit(msg_ex_adv)
                    else: self.log_signal.emit(f" {msg_ex_norm} {self._generate_bar(0, total_tids)}")
                        
                    for i, tid in enumerate(all_tids):
                        if not self._is_running: break
                        
                        if tid in skipped_tids:
                            global_current_step += 1
                            self.progress_signal.emit(global_current_step, global_total_steps)
                            continue
                            
                        work_dir = raw_dir / tid
                        
                        if adv_logs:
                            self.log_signal.emit(self.T("log_worker_extract_id_adv").format(tid))
                        else:
                            self.log_replace_signal.emit(f" {msg_ex_norm} {self._generate_bar(i + 1, total_tids)}")
                        
                        clean_tid = tid.replace("-", "").replace("/", "").replace("\\", "").strip()

                        if self.config.get("cafe_cemu_layout", False):
                            if len(clean_tid) == 16:
                                tid_high = clean_tid[:8].lower() 
                                tid_low = clean_tid[8:].lower()  
                                title_dest = self.region_dir / "Extracted" / "mlc01" / "sys" / "title" / tid_high / tid_low
                            else:
                                title_dest = self.region_dir / "Extracted" / "mlc01" / "sys" / "title" / clean_tid.lower()
                        else:
                            title_dest = self.region_dir / "Extracted" / title_type / clean_tid

                        title_dest.mkdir(parents=True, exist_ok=True)
                        process_title(tid, str(work_dir), str(title_dest), common_key, self.T, self.is_running, self.debug_log)
                        
                        global_current_step += 1
                        self.progress_signal.emit(global_current_step, global_total_steps)

                    if not adv_logs and self._is_running:
                        self.log_replace_signal.emit(f" {msg_ex_norm} ✓ {self._generate_bar(total_tids, total_tids)}")

            if not self._is_running:
                self._cleanup_partial_files()
                self.finished_signal.emit(False, "STOPPED")
                return

            self.region_dir = None
            elapsed_time = time.time() - start_time
            
            self.log_signal.emit("\n==================================================")
            self.log_signal.emit(self.T("log_op_complete"))
            self.log_signal.emit("")
            self.log_signal.emit(self.T("log_time_elapsed").format(f"{elapsed_time:.2f}"))
            self.log_signal.emit(self.T("log_titles_proc").format(total_processed_tids))
            self.log_signal.emit("")
            self.log_signal.emit(self.T("log_all_verified"))
            
            if will_extract:
                if self.config.get("cafe_cemu_layout", False):
                    self.log_signal.emit(self.T("log_ext_cemu"))
                else:
                    self.log_signal.emit(self.T("log_ext_offline"))
            else:
                self.log_signal.emit(self.T("log_ext_isfshax"))
                
            self.log_signal.emit("==================================================")
            self.progress_signal.emit(global_total_steps, global_total_steps)
            print("[CAFE WORKER] Operations concluded successfully.")
            self.finished_signal.emit(True, "")

        except Exception as e:
            print(f"[CAFE WORKER FATAL ERROR] {traceback.format_exc()}")
            self._cleanup_partial_files()
            if self._is_running:
                self.log_signal.emit(f"\n[!] ERROR: {str(e)}")
                self.finished_signal.emit(False, str(e))
            else:
                self.finished_signal.emit(False, "STOPPED")