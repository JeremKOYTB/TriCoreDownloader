import sys
import os
import re
import stat
import shutil
import time
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal

from .system_titles import get_system_title_ids
from .worker_ops import get_yls_db, download_raw_files, verify_integrity, pack_cia
from ..Languages.locales import STRINGS

RE_CTR_FW = re.compile(r"^(\d+)\.(\d+)\.(\d+)-(\d+)$")
VALID_PREFIXES = ("00040010", "00040030", "00040130", "00040138", "0004009B", "000400DB", "0004800")
REGION_TO_LETTER = {"EUR": "E", "USA": "U", "JPN": "J", "KOR": "K", "CHN": "C", "TWN": "T", "AUS": "E"}

def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

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
        
        cpu_count = os.cpu_count() or 4
        self.max_workers_dl = min(16, max(4, cpu_count * 2))
        self.max_workers_cpu = min(8, max(2, cpu_count))
        self.max_workers_build = min(4, max(1, cpu_count // 2))
        
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
        for _ in range(3):
            try:
                shutil.rmtree(path, onerror=_rmtree_onerror)
                if not path.exists():
                    return
            except Exception:
                pass
            time.sleep(0.1)
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
        bar = '█' * filled + '░' * (width - filled)
        return f" {prefix} [{bar}] {int(percent):>3}%"

    def run(self):
        try:
            start_time = time.monotonic()
            is_latest_mode = self.target_fw in ("LATEST", "AUTO")
            verbose_logs = self.config.get("advanced_logs", False)
            will_decrypt = self.config.get("decrypt_cia", False)
            boot9_path = self.config.get("boot9_path") or self.config.get("boot9", None)
            
            def log_callback(msg):
                self.log_signal.emit(msg)

            if verbose_logs:
                self.log_signal.emit(self.T("log_forensic_mode"))

            if will_decrypt:
                if verbose_logs:
                    log_callback(self.T("log_boot9_precheck"))
                
                if not boot9_path or not Path(str(boot9_path).strip('\"\'')).is_file():
                    self.log_signal.emit("\n[!] " + self.T("err_boot9_missing_fatal"))
                    self.finished_signal.emit(False, "BOOT9_MISSING")
                    return
                
                try:
                    from pyctr.crypto import CryptoEngine
                    _ = CryptoEngine(boot9=str(Path(str(boot9_path).strip('\"\'')).resolve()))
                    if verbose_logs:
                        log_callback(self.T("log_boot9_ok"))
                except Exception as e:
                    self.log_signal.emit("\n[!] " + self.T("err_boot9_corrupt").format(e))
                    self.finished_signal.emit(False, "BOOT9_CORRUPT")
                    return

            display_region = self.config.get("ctr_region", "EUR")
            region_key = "EUR" if display_region == "AUS" else display_region
            target_sys_ver = None

            if not is_latest_mode:
                match = RE_CTR_FW.match(self.target_fw)
                if match:
                    target_sys_ver = tuple(int(x) for x in match.groups()[:4])
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
            if verbose_logs:
                log_callback(self.T("log_query_servers"))
            
            db_pool = get_yls_db("ctr", self._is_stopped_cb)
            if self._is_stopped:
                return self._handle_stop()
            
            if self.is_new_3ds:
                db_ktr = get_yls_db("ktr", self._is_stopped_cb)
                if self._is_stopped:
                    return self._handle_stop()
                if region_key in db_ktr:
                    if region_key not in db_pool:
                        db_pool[region_key] = {}
                    for t_id, versions in db_ktr[region_key].items():
                        db_pool[region_key][t_id] = versions

            if self._is_stopped:
                return self._handle_stop()

            region_db = db_pool.get(region_key, {})

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
                filtered_new_titles = [t for t in missing_titles if t.startswith(VALID_PREFIXES)]
                if filtered_new_titles:
                    target_ids.extend(sorted(filtered_new_titles))

            for t_id in target_ids:
                versions = region_db.get(t_id, [])
                if not versions: 
                    if is_latest_mode:
                        titles_to_download.append((t_id, None))
                    continue
                    
                if is_latest_mode:
                    optimal_tv = max(versions, key=lambda x: x[1])[1]
                    titles_to_download.append((t_id, optimal_tv))
                else:
                    optimal_tv, optimal_sv = None, None
                    for sv, tv in versions:
                        if sv <= target_sys_ver:
                            if optimal_sv is None or sv > optimal_sv:
                                optimal_sv = sv
                                optimal_tv = tv
                    if optimal_tv is not None:
                        titles_to_download.append((t_id, optimal_tv))
                    
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
                self._robust_rmtree(self._current_out_dir)
            
            self._current_out_dir.mkdir(parents=True, exist_ok=True)
            self._current_tmp_dir.mkdir(parents=True, exist_ok=True)

            global_total_steps = total_titles * (4 if will_decrypt else 3)
            global_current_step = 0

            self.log_signal.emit(self.T("log_titles_found").format(total_titles))
            
            successful_downloads = []
            failed_downloads = []
            completed_downloads = 0

            if verbose_logs:
                log_callback(self.T("log_phase1_start").format(total_titles))
            else:
                self.log_signal.emit(self._text_bar(self.T("step_dl"), 0))

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers_dl)
            with self._active_executor as executor:
                future_to_tid = {}
                for t_id, ver in titles_to_download:
                    if self._is_stopped:
                        break
                    tmp_title_dir = self._current_tmp_dir / t_id
                    tmp_title_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        future = executor.submit(download_raw_files, t_id, tmp_title_dir, ver, self.T, self._is_stopped_cb, log_callback, verbose_logs)
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
                        self.progress_signal.emit(global_current_step, global_total_steps)
                        
                        if success:
                            successful_downloads.append((t_id, tmp_title_dir))
                        else:
                            failed_downloads.append((t_id, err_code))
                            
                        if not verbose_logs:
                            self.log_replace_signal.emit(self._text_bar(self.T("step_dl"), percent))
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
                log_callback(self.T("log_phase2_start").format(total_verify))
            else:
                self.log_signal.emit(self._text_bar(self.T("step_verify"), 0))

            self._active_executor = ThreadPoolExecutor(max_workers=self.max_workers_cpu)
            with self._active_executor as executor:
                future_to_tid = {}
                for t_id, t_dir in successful_downloads:
                    if self._is_stopped:
                        break
                    try:
                        future = executor.submit(verify_integrity, t_id, t_dir, self.T, self._is_stopped_cb, log_callback, verbose_logs)
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
                        self.progress_signal.emit(global_current_step, global_total_steps)
                        verified_titles.append((t_id, t_dir))
                        
                        if not verbose_logs: 
                            self.log_replace_signal.emit(self._text_bar(self.T("step_verify"), percent))
                    except Exception as e:
                        if self._is_stopped:
                            return self._handle_stop()
                        raise RuntimeError(self.T("err_verify_fail").format(e))

            self._active_executor = None
            if self._is_stopped:
                return self._handle_stop()

            total_build = len(verified_titles)
            verified_titles.sort(key=lambda x: x[0]) 
            built_titles = []

            if verbose_logs:
                log_callback(self.T("log_phase3_start").format(total_build))
            else:
                self.log_signal.emit(self._text_bar(self.T("step_build"), 0))

            for i, (t_id, t_dir) in enumerate(verified_titles, 1):
                if self._is_stopped:
                    return self._handle_stop()
                
                global_current_step += 1
                self.progress_signal.emit(global_current_step, global_total_steps)
                percent = (i * 100) // total_build
                
                if not verbose_logs: 
                    self.log_replace_signal.emit(self._text_bar(self.T("step_build"), percent))
                
                try:
                    success = pack_cia(
                        t_id, t_dir, self._current_out_dir, self.T, 
                        boot9_path=boot9_path, is_stopped_cb=self._is_stopped_cb, 
                        log_cb=log_callback, decrypt=False, advanced_logs=verbose_logs
                    )
                    if not success: 
                        if self._is_stopped:
                            return self._handle_stop()
                        raise RuntimeError(self.T("err_build_failed").format(t_id))
                    built_titles.append((t_id, t_dir))
                except Exception as e:
                    if self._is_stopped:
                        return self._handle_stop()
                    raise RuntimeError(self.T("err_assemble_fail").format(e))

            if will_decrypt and built_titles:
                total_decrypt = len(built_titles)
                
                if verbose_logs:
                    log_callback(self.T("log_phase4_start"))
                else:
                    self.log_signal.emit(self._text_bar(self.T("step_decrypt"), 0))
                
                for i, (t_id, t_dir) in enumerate(built_titles, 1):
                    if self._is_stopped:
                        return self._handle_stop()
                    
                    global_current_step += 1
                    self.progress_signal.emit(global_current_step, global_total_steps)
                    percent = (i * 100) // total_decrypt
                    
                    if not verbose_logs: 
                        self.log_replace_signal.emit(self._text_bar(self.T("step_decrypt"), percent))
                    
                    try:
                        success = pack_cia(
                            t_id, t_dir, self._current_out_dir, self.T, 
                            boot9_path=boot9_path, is_stopped_cb=self._is_stopped_cb, 
                            log_cb=log_callback, decrypt=True, advanced_logs=verbose_logs
                        )
                        if not success: 
                            if self._is_stopped:
                                return self._handle_stop()
                            raise RuntimeError(self.T("err_decrypt_fail").format(t_id))
                    except Exception as e:
                        if self._is_stopped:
                            return self._handle_stop()
                        raise RuntimeError(self.T("err_decrypt_fail").format(e))

            self._robust_rmtree(self._current_tmp_dir)
            self._current_tmp_dir = None 

            elapsed_time = time.monotonic() - start_time
            
            if failed_downloads:
                self.log_signal.emit("\n\n[!] " + self.T("warn_dl_failures"))
                for tid, err in failed_downloads:
                    self.log_signal.emit(f"    - {tid} " + self.T("err_network_code").format(err))

            self.log_signal.emit("\n==================================================")
            self.log_signal.emit(self.T("log_success_final").format(self._current_out_dir))
            
            try:
                stats_msg = self.T("log_stats_full").format(elapsed_time, len(built_titles), total_titles)
            except Exception:
                stats_msg = self.T("log_stats_full").format(f"{elapsed_time:.2f}", len(built_titles), total_titles)
            self.log_signal.emit(stats_msg)
            
            self.log_signal.emit("==================================================")
            
            self.progress_signal.emit(global_total_steps, global_total_steps)
            self.finished_signal.emit(True, "OK")

        except Exception as e:
            if self._is_stopped:
                return self._handle_stop()
                
            if verbose_logs:
                self.log_signal.emit("\n==================================================")
                self.log_signal.emit(traceback.format_exc())
            
            self.log_signal.emit("\n[!] " + self.T("err_critical_abort"))
            self.log_signal.emit(" -> " + str(e))
            self.log_signal.emit(self.T("log_emergency_cleanup"))
            self._emergency_cleanup()
            self.finished_signal.emit(False, "CRASH")
            
        finally:
            if self._active_executor:
                self._active_executor.shutdown(wait=False, cancel_futures=True)

    def _handle_stop(self):
        self.log_signal.emit("\n\n[!] " + self.T("log_cancelled"))
        self._emergency_cleanup()
        self.finished_signal.emit(False, "STOPPED")