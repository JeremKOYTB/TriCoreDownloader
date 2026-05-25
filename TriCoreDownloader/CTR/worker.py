import sys
import re
import shutil
import time
import inspect
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal

from .system_titles import get_system_title_ids
from .worker_ops import get_yls_db, download_raw_files, verify_integrity, pack_cia
from ..Languages.locales import STRINGS

class CtrDownloaderWorker(QThread):
    log_signal = pyqtSignal(str)
    log_replace_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    
    ask_overwrite_signal = pyqtSignal(str)
    ask_skip_signal = pyqtSignal(bool)

    def __init__(self, target_fw: str, is_new_3ds: bool, config: dict):
        super().__init__()
        self.target_fw = target_fw
        self.is_new_3ds = is_new_3ds
        self.config = config
        self._is_stopped = False
        self.max_workers = 4 
        self.lang = self.config.get("lang", "en")
        
        self._current_out_dir = None
        self._current_tmp_dir = None
        self._active_executor = None

    def T(self, key, default=None):
        try:
            return STRINGS.get(self.lang, STRINGS.get("en", {})).get(key, default or key)
        except Exception:
            return default or key

    def stop(self):
        self._is_stopped = True
        if self._active_executor:
            try:
                self._active_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def _is_stopped_cb(self):
        return self._is_stopped

    def _robust_rmtree(self, path: Path):
        if not path or not isinstance(path, Path) or not path.exists():
            return
        for _ in range(5):
            try:
                shutil.rmtree(path)
                return
            except Exception:
                time.sleep(0.5)
        shutil.rmtree(path, ignore_errors=True)

    def _emergency_cleanup(self):
        if self._current_tmp_dir:
            self._robust_rmtree(self._current_tmp_dir)
        if self._current_out_dir:
            self._robust_rmtree(self._current_out_dir)

    def _text_bar(self, prefix: str, percent: int, width: int = 20) -> str:
        percent = max(0, min(100, percent))
        filled = int((percent / 100) * width) if width > 0 else 0
        bar = '█' * filled + '░' * (width - filled)
        return f" {prefix} [{bar}] {percent}%"

    def run(self):
        try:
            start_time = time.time()
            is_latest_mode = self.target_fw in ["LATEST", "AUTO"]
            verbose_logs = self.config.get("advanced_logs", False)
            will_decrypt = self.config.get("decrypt_cia", False)
            boot9_path = self.config.get("boot9_path") or self.config.get("boot9", None)
            
            if will_decrypt:
                if verbose_logs: self.log_signal.emit(self.T("log_boot9_precheck"))
                
                if not boot9_path or not Path(boot9_path).is_file():
                    self.log_signal.emit("\n[!] " + self.T("err_boot9_missing_fatal"))
                    self.finished_signal.emit(False, "BOOT9_MISSING")
                    return
                
                try:
                    from pyctr.crypto import CryptoEngine
                    _ = CryptoEngine(boot9=str(boot9_path))
                    if verbose_logs: self.log_signal.emit(self.T("log_boot9_ok"))
                except Exception as e:
                    self.log_signal.emit("\n[!] " + self.T("err_boot9_corrupt").format(e))
                    self.finished_signal.emit(False, "BOOT9_CORRUPT")
                    return
            
            if verbose_logs:
                self.log_signal.emit("\n" + self.T("log_forensic_mode"))

            display_region = self.config.get("ctr_region", "EUR")
            region_key = "EUR" if display_region == "AUS" else display_region
            target_sys_ver = None

            if not is_latest_mode:
                match = re.match(r"^(\d+)\.(\d+)\.(\d+)-(\d+)$", self.target_fw)
                if match:
                    target_sys_ver = tuple(int(x) for x in match.groups()[:4])
                    if verbose_logs:
                        self.log_signal.emit(self.T("log_region_forced").format(region_key))
                else:
                    self.log_signal.emit("\n[!] " + self.T("err_invalid_fw_format"))
                    self.finished_signal.emit(False, "INVALID_FW_FORMAT")
                    return
            
            model_tag = "NEW" if self.is_new_3ds else "OLD"
            target_ids = get_system_title_ids(region_key, self.is_new_3ds)

            if not target_ids:
                self.log_signal.emit("\n[!] " + self.T("err_no_title_id").format(region_key))
                self.finished_signal.emit(False, "NO_TITLE_ID_DB")
                return

            titles_to_download = []
            
            if verbose_logs: self.log_signal.emit(self.T("log_query_servers"))
            
            db_pool = get_yls_db("ctr", self._is_stopped_cb)
            if self._is_stopped: return self._handle_stop()
            
            if self.is_new_3ds:
                db_ktr = get_yls_db("ktr", self._is_stopped_cb)
                if self._is_stopped: return self._handle_stop()
                if region_key in db_ktr:
                    if region_key not in db_pool: db_pool[region_key] = {}
                    for t_id, versions in db_ktr[region_key].items():
                        db_pool[region_key][t_id] = versions

            if self._is_stopped: return self._handle_stop()

            if is_latest_mode:
                highest_fw_tuple = (0, 0, 0, 0)
                for t_id, versions in db_pool.get(region_key, {}).items():
                    for fw_tuple, tv in versions:
                        if fw_tuple > highest_fw_tuple:
                            highest_fw_tuple = fw_tuple
                
                if highest_fw_tuple != (0, 0, 0, 0):
                    region_to_letter = {"EUR": "E", "USA": "U", "JPN": "J", "KOR": "K", "CHN": "C", "TWN": "T", "AUS": "E"}
                    fw_letter = region_to_letter.get(region_key, "E")
                    self.target_fw = f"{highest_fw_tuple[0]}.{highest_fw_tuple[1]}.{highest_fw_tuple[2]}-{highest_fw_tuple[3]}{fw_letter}"

            self.log_signal.emit(self.T("log_dl_fw_target").format(self.target_fw))

            if verbose_logs: self.log_signal.emit(self.T("log_verify_sys_sig"))
            
            server_titles = set(db_pool.get(region_key, {}).keys())
            local_titles = set(target_ids)
            if self.is_new_3ds:
                local_titles.update(set(get_system_title_ids(region_key, False)))
                
            missing_titles = server_titles - local_titles
            
            if missing_titles:
                valid_prefixes = ("00040010", "00040030", "00040130", "00040138", "0004009B", "000400DB", "0004800")
                filtered_new_titles = [t for t in missing_titles if t.startswith(valid_prefixes)]
                if filtered_new_titles:
                    if verbose_logs: self.log_signal.emit(self.T("log_mapped_modules").format(len(filtered_new_titles)))
                    target_ids.extend(sorted(filtered_new_titles))

            if verbose_logs: self.log_signal.emit(self.T("log_resolve_versions"))
            
            for t_id in target_ids:
                versions = db_pool.get(region_key, {}).get(t_id, [])
                if not versions: 
                    if is_latest_mode: titles_to_download.append((t_id, None))
                    continue
                    
                if is_latest_mode:
                    optimal_tv = max(versions, key=lambda x: x[1])[1]
                    titles_to_download.append((t_id, optimal_tv))
                else:
                    optimal_tv, optimal_sv = None, None
                    for sv, tv in versions:
                        if sv <= target_sys_ver:
                            if optimal_sv is None or sv > optimal_sv:
                                 optimal_sv = sv; optimal_tv = tv
                    if optimal_tv is not None: titles_to_download.append((t_id, optimal_tv))
                    
            total_titles = len(titles_to_download)
            if total_titles == 0: 
                self.log_signal.emit("\n[!] " + self.T("err_no_valid_titles"))
                self.finished_signal.emit(False, "NO_VALID_TITLES")
                return

            base_out_dir = Path(self.config.get("output_dir", "output"))
            fw_folder_name = f"{self.target_fw.replace('.', '_').replace('-', '_')}_{display_region}_{model_tag}"
            
            self._current_out_dir = base_out_dir / fw_folder_name
            self._current_tmp_dir = self._current_out_dir / "tmp"

            if self._current_out_dir.exists() and any(self._current_out_dir.iterdir()):
                if verbose_logs:
                    self.log_signal.emit(self.T("log_folder_cleared"))
                self._robust_rmtree(self._current_out_dir)
            
            self._current_out_dir.mkdir(parents=True, exist_ok=True)
            self._current_tmp_dir.mkdir(parents=True, exist_ok=True)
            
            def log_callback(msg): 
                if verbose_logs: self.log_signal.emit(msg)

            global_total_steps = total_titles * (4 if will_decrypt else 3)
            global_current_step = 0

            self.log_signal.emit(self.T("log_titles_found").format(total_titles))

            if verbose_logs: self.log_signal.emit(self.T("log_phase1_start").format(total_titles))
            else: self.log_signal.emit("")
            
            successful_downloads = []
            failed_downloads = []
            completed_downloads = 0
            dl_kwargs = {'advanced_logs': verbose_logs} if verbose_logs else {}

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers)
            with self._active_executor as executor:
                future_to_tid = {}
                for t_id, ver in titles_to_download:
                    if self._is_stopped: break
                    tmp_title_dir = self._current_tmp_dir / t_id
                    tmp_title_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        future = executor.submit(download_raw_files, t_id, tmp_title_dir, ver, self.T, self._is_stopped_cb, log_callback, **dl_kwargs)
                        future_to_tid[future] = (t_id, tmp_title_dir)
                    except RuntimeError: break

                for future in as_completed(future_to_tid):
                    if self._is_stopped: break 
                    t_id, tmp_title_dir = future_to_tid[future]
                    completed_downloads += 1
                    global_current_step += 1
                    
                    try:
                        success, err_code = future.result()
                        percent = int((completed_downloads / total_titles) * 100)
                        self.progress_signal.emit(global_current_step, global_total_steps)
                        
                        if success:
                            successful_downloads.append((t_id, tmp_title_dir))
                            if verbose_logs: self.log_replace_signal.emit(self.T("log_dl_progress").format(percent, t_id))
                        else:
                            failed_downloads.append((t_id, err_code))
                            if verbose_logs: self.log_signal.emit(self.T("err_dl_fail_adv").format(t_id, err_code))
                            
                        if not verbose_logs:
                            self.log_replace_signal.emit(self._text_bar(self.T("step_dl"), percent))
                    except Exception as e:
                        failed_downloads.append((t_id, str(e)))
            
            self._active_executor = None 
            if self._is_stopped: return self._handle_stop()
            if not successful_downloads: raise RuntimeError(self.T("err_phase1_fail"))

            total_verify = len(successful_downloads)
            if verbose_logs: self.log_signal.emit(self.T("log_phase2_start").format(total_verify))
            else: self.log_signal.emit("")
            
            verified_titles = []
            completed_verifications = 0
            vi_kwargs = {'advanced_logs': verbose_logs} if verbose_logs else {}

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers)
            with self._active_executor as executor:
                future_to_tid = {}
                for t_id, t_dir in successful_downloads:
                    if self._is_stopped: break
                    try:
                        future = executor.submit(verify_integrity, t_id, t_dir, self.T, self._is_stopped_cb, log_callback, **vi_kwargs)
                        future_to_tid[future] = (t_id, t_dir)
                    except RuntimeError: break

                for future in as_completed(future_to_tid):
                    if self._is_stopped: break
                    t_id, t_dir = future_to_tid[future]
                    completed_verifications += 1
                    global_current_step += 1
                    
                    try:
                        is_valid = future.result()
                        if not is_valid: raise RuntimeError(self.T("err_hash_mismatch").format(t_id))
                        
                        percent = int((completed_verifications / total_verify) * 100)
                        self.progress_signal.emit(global_current_step, global_total_steps)
                        verified_titles.append((t_id, t_dir))
                        
                        if verbose_logs: self.log_replace_signal.emit(self.T("log_verify_progress").format(percent, t_id))
                        else: self.log_replace_signal.emit(self._text_bar(self.T("step_verify"), percent))
                    except Exception as e:
                        raise RuntimeError(self.T("err_verify_fail").format(e))

            self._active_executor = None
            if self._is_stopped: return self._handle_stop()

            total_build = len(verified_titles)
            if verbose_logs: self.log_signal.emit(self.T("log_phase3_start").format(total_build))
            else: self.log_signal.emit("")
            
            verified_titles.sort(key=lambda x: x[0]) 
            built_titles = []
            pack_kwargs_enc = {'decrypt': False, 'boot9_path': boot9_path, 'advanced_logs': verbose_logs}

            for i, (t_id, t_dir) in enumerate(verified_titles, 1):
                if self._is_stopped: return self._handle_stop()
                
                global_current_step += 1
                self.progress_signal.emit(global_current_step, global_total_steps)
                percent = int((i / total_build) * 100)
                
                if verbose_logs: self.log_replace_signal.emit(self.T("log_cia_assembling").format(percent, t_id))
                else: self.log_replace_signal.emit(self._text_bar(self.T("step_build"), percent))
                
                try:
                    success = pack_cia(t_id, t_dir, self._current_out_dir, self.T, is_stopped_cb=self._is_stopped_cb, log_cb=log_callback, **pack_kwargs_enc)
                    if not success: raise RuntimeError(self.T("err_build_failed").format(t_id))
                    built_titles.append((t_id, t_dir))
                except Exception as e:
                    raise RuntimeError(self.T("err_assemble_fail").format(e))

            if will_decrypt and built_titles:
                total_decrypt = len(built_titles)
                if verbose_logs: self.log_signal.emit(self.T("log_phase4_start").format(total_decrypt))
                else: self.log_signal.emit("")
                
                pack_kwargs_dec = {'decrypt': True, 'boot9_path': boot9_path, 'advanced_logs': verbose_logs}
                    
                for i, (t_id, t_dir) in enumerate(built_titles, 1):
                    if self._is_stopped: return self._handle_stop()
                    
                    global_current_step += 1
                    self.progress_signal.emit(global_current_step, global_total_steps)
                    percent = int((i / total_decrypt) * 100)
                    
                    if verbose_logs: self.log_replace_signal.emit(self.T("log_decrypting").format(percent, t_id))
                    else: self.log_replace_signal.emit(self._text_bar(self.T("step_decrypt"), percent))
                    
                    try:
                        success = pack_cia(t_id, t_dir, self._current_out_dir, self.T, is_stopped_cb=self._is_stopped_cb, log_cb=log_callback, **pack_kwargs_dec)
                        if not success: raise RuntimeError(self.T("err_decrypt_engine_failed").format(t_id))
                    except Exception as e:
                        raise RuntimeError(self.T("err_decrypt_fail").format(e))

            self._robust_rmtree(self._current_tmp_dir)
            self._current_tmp_dir = None 

            elapsed_time = time.time() - start_time
            
            if failed_downloads:
                self.log_signal.emit("\n\n[!] " + self.T("warn_dl_failures"))
                for tid, err in failed_downloads:
                    self.log_signal.emit(f"    - {tid} " + self.T("err_network_code").format(err))

            self.log_signal.emit(self.T("log_success_final").format(self._current_out_dir))
            self.log_signal.emit(self.T("log_stats_full").format(elapsed_time, len(built_titles), total_titles))
            
            self.progress_signal.emit(global_total_steps, global_total_steps)
            self.finished_signal.emit(True, self.T("msg_success_done"))

        except Exception as e:
            if verbose_logs:
                self.log_signal.emit("\n==================================================")
                self.log_signal.emit(self.T("log_tech_trace"))
                self.log_signal.emit(traceback.format_exc())
            
            self.log_signal.emit("\n[!] " + self.T("err_critical_abort"))
            self.log_signal.emit(f" -> {str(e)}")
            self.log_signal.emit(self.T("log_emergency_cleanup"))
            self._emergency_cleanup()
            self.finished_signal.emit(False, "CRASH")
            
        finally:
            if self._active_executor:
                self._active_executor.shutdown(wait=False, cancel_futures=True)

    def _handle_stop(self):
        self.log_signal.emit("\n\n[!] " + self.T("log_cancel_cleanup"))
        self._emergency_cleanup()
        self.log_signal.emit("[!] " + self.T("log_cancel_clean_done"))
        self.finished_signal.emit(False, "STOPPED")