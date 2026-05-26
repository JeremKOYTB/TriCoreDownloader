import os
import time
import hashlib
import subprocess
import stat
import concurrent.futures

SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}

class WorkerOperations:

    def _safe_unlink(self, path):
        if os.path.exists(path):
            try:
                os.remove(path)
            except PermissionError:
                try:
                    os.chmod(path, stat.S_IWRITE)
                    os.remove(path)
                except Exception:
                    pass
            except OSError:
                pass

    def nin_request(self, method, url, headers=None):
        if headers is None: headers = {}
        headers.update({"User-Agent": self.user_agent or "NintendoSDK Firmware/UNKNOWN"})
        
        self.log_adv(self.T("log_http_req").format(method, url))
        print(f"[NX OPS] Network Request: {method} {url}")
        
        t0 = time.time()
        resp = self.http_session.request(method, url, headers=headers, timeout=15)
        t1 = time.time()
        
        c_len = resp.headers.get("Content-Length", "Unknown")
        self.log_adv(self.T("log_http_resp").format(resp.status_code, int((t1-t0)*1000), c_len))
        print(f"[NX OPS] Response: {resp.status_code} in {int((t1-t0)*1000)}ms. Length: {c_len}")
        
        resp.raise_for_status()
        return resp

    def dlfile(self, url, out, fhash=None, force_requests=False):
        if not self.is_running: raise RuntimeError("STOPPED")
        
        if getattr(self, "aria2c_enabled", False) and not force_requests:
            out_dir, fname = os.path.dirname(out), os.path.basename(out)
            try:
                cmd_args = [
                    self.aria2c_path, "--no-conf", "--console-log-level=error",
                    "--file-allocation=none", "--summary-interval=0",
                    "--download-result=hide", 
                    f"--certificate={self.req_cert_crt}",
                    f"--private-key={self.req_cert_key}",
                    f"--header=User-Agent: {self.user_agent}",
                    "--check-certificate=false", "--min-split-size=1M", "--dir", out_dir,
                    "--out", fname, "-c", url,
                    "--auto-file-renaming=false", "--allow-overwrite=true"
                ]
                
                print(f"[NX OPS] Delegating download to Aria2c: {fname}")
                proc = subprocess.Popen(cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SUBPROCESS_FLAGS)
                
                while proc.poll() is None:
                    if not self.is_running:
                        print(f"[NX OPS WARNING] Killing active Aria2c process for {fname}")
                        proc.terminate()
                        proc.wait()
                        raise RuntimeError("STOPPED")
                    time.sleep(0.1)
                    
                if proc.returncode != 0:
                    print(f"[NX OPS ERROR] Aria2c exited with non-zero code {proc.returncode} for {fname}")
                    raise Exception("Aria2c failed")
                return
            except Exception as e:
                if str(e) == "STOPPED": raise RuntimeError("STOPPED")
                print(f"[NX OPS WARNING] Aria2c delegation failed: {e}. Falling back to internal requests.")
                pass 

        self.log_adv(self.T("log_dl_fallback").format(url, out))
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[NX OPS] Internal Download: {os.path.basename(out)} (Attempt {attempt+1}/{max_retries})")
                with self.http_session.get(url, headers={"User-Agent": self.user_agent}, stream=True, timeout=15) as resp:
                    resp.raise_for_status()
                    
                    h = hashlib.sha256()
                    chunk_count = 0
                    chunk_size = 4194304
                    
                    with open(out, "wb") as f:
                        for chunk in resp.iter_content(chunk_size):
                            if not self.is_running: raise RuntimeError("STOPPED")
                            if chunk: 
                                h.update(chunk)
                                f.write(chunk)
                                chunk_count += 1
                                
                    if not self.is_running: raise RuntimeError("STOPPED")
                    
                    if fhash is not None:
                        computed = h.hexdigest()
                        if computed != fhash.lower():
                            print(f"[NX OPS ERROR] Inline hash mismatch on {os.path.basename(out)}. Got {computed}, Expected {fhash.lower()}")
                            raise ValueError("HASH_MISMATCH")

                self.log_adv(self.T("log_dl_stream_done").format(chunk_count))
                return 
                
            except Exception as e:
                if str(e) == "STOPPED": raise RuntimeError("STOPPED")
                print(f"[NX OPS WARNING] Download interrupted on {os.path.basename(out)}: {e}")
                self.log_adv(self.T("log_dl_err_retry").format(attempt + 1, max_retries, os.path.basename(out), str(e)))
                
                self._safe_unlink(out)
                    
                if attempt < max_retries - 1:
                    time.sleep(1.5)
                else:
                    if str(e) == "HASH_MISMATCH":
                        err_msg = self.T("log_err_sha256").format(os.path.basename(out))
                        raise RuntimeError(err_msg)
                    raise RuntimeError(self.T("err_dl_net").format(os.path.basename(out), max_retries))

    def dlfiles(self, dltable):
        if not self.is_running or not dltable: return
        
        total = len(dltable)
        adv = self.config.get("advanced_logs", False)
        
        if not adv:
            self.log("")
            self.log(self.T("log_nca_found").format(total))
            if getattr(self, "sv_nca_fat", ""):
                self.log(self.T("log_nca_fat").format(self.sv_nca_fat))
                
            if self.config.get("exclude_exfat", False):
                self.log(self.T("log_nca_exfat_excluded"))
            elif getattr(self, "sv_nca_exfat", ""):
                self.log(self.T("log_nca_exfat").format(self.sv_nca_exfat))
        else:
            self.log_adv(self.T("log_nca_queue").format(total))
            
        dl_tmp_path = os.path.join(self.config["output_dir"], "dl.tmp")
        
        if getattr(self, "aria2c_enabled", False):
            try:
                print(f"[NX OPS] Preparing Aria2c input list for {total} files.")
                with open(dl_tmp_path, "w") as f:
                    for url, dirc, fname, fhash in dltable:
                        f.write(f"{url}\n\tout={fname}\n\tdir={dirc}\n\tchecksum=sha-256={fhash}\n")
                        
                if not adv:
                    self.log("")
                    self.update_text_progress(0, 100, self.T("log_dl_ncas"), is_first=True)
                else:
                    self.log_adv(self.T("log_aria_invoke").format(total))
                    
                max_concurrent = str(min(32, (os.cpu_count() or 4) * 4))
                
                print(f"[NX OPS] Spawning bulk Aria2c process. Max concurrent: {max_concurrent}")
                proc = subprocess.Popen([
                    self.aria2c_path, "--no-conf", "--console-log-level=notice",
                    "--file-allocation=none", "--summary-interval=1", "--download-result=hide",
                    "--auto-file-renaming=false", "--allow-overwrite=true",
                    f"--certificate={self.req_cert_crt}", 
                    f"--private-key={self.req_cert_key}",
                    f"--header=User-Agent: {self.user_agent}",
                    "--check-certificate=false", "--min-split-size=1M", "-j", max_concurrent, "-x", "16", "-s", "16", "-i", dl_tmp_path
                ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", **SUBPROCESS_FLAGS)
                
                last_pct = 0
                for line in proc.stdout:
                    if not self.is_running:
                        print("[NX OPS WARNING] Killing bulk Aria2c process.")
                        proc.terminate()
                        proc.wait()
                        raise RuntimeError("STOPPED")
                    
                    if adv and "Download complete:" in line:
                        self.log_adv(line.strip(), raw=True)
                        
                    m = re.search(r"\((\d+)%\)", line)
                    if m:
                        pct = int(m.group(1))
                        if pct >= last_pct:
                            last_pct = pct
                            if not adv:
                                self.update_text_progress(pct, 100, self.T("log_dl_ncas"))
                            self.progress_signal.emit(10 + int(pct * 0.70), 100)
                proc.wait()
                
                if not adv and last_pct < 100:
                    self.update_text_progress(100, 100, self.T("log_dl_ncas"))
                elif adv:
                    self.log_adv(self.T("log_aria_exit").format(proc.returncode))
                return
            except Exception as e:
                if str(e) == "STOPPED": raise RuntimeError("STOPPED")
                print(f"[NX OPS WARNING] Bulk Aria2c execution failed: {e}. Reverting to internal multithreading.")
                self.log_adv(self.T("log_aria_fail").format(str(e)))
            finally:
                if os.path.exists(dl_tmp_path): 
                    try: os.remove(dl_tmp_path)
                    except: pass

        completed = 0
        if not adv:
            self.log("")
            self.update_text_progress(0, total, self.T("log_dl_ncas"), is_first=True)
        else:
            self.log_adv(self.T("log_tp_start").format(min(32, (os.cpu_count() or 4) * 4), total))
            
        print("[NX OPS] Spawning internal ThreadPool Downloader.")
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 4) * 4)) as ex:
            futs = []
            for url, dirc, fname, fhash in dltable:
                os.makedirs(dirc, exist_ok=True)
                futs.append(ex.submit(self.dlfile, url, os.path.join(dirc, fname), fhash))
            for f in concurrent.futures.as_completed(futs):
                if not self.is_running: raise RuntimeError("STOPPED")
                f.result()
                completed += 1
                if not adv:
                    self.update_text_progress(completed, total, self.T("log_dl_ncas"))
                self.progress_signal.emit(10 + int((completed / total) * 70), 100)

    def _verify_single_file(self, path, expected_hash):
        print(f"[NX OPS] Verifying {os.path.basename(path)}")
        if hasattr(hashlib, "file_digest"):
            with open(path, "rb") as f:
                computed_hash = hashlib.file_digest(f, "sha256").hexdigest()
        else:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4194304), b""): 
                    h.update(chunk)
            computed_hash = h.hexdigest()
            
        return path, computed_hash, expected_hash