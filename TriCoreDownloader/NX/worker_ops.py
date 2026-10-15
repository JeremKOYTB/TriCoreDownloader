import concurrent.futures
import hashlib
import os
import re
import stat
import subprocess
import sys
import time

from .switch_core import _write_bytes_fast

SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if sys.platform == "win32" or os.name == "nt" else {}
RE_ARIA_PCT = re.compile(r"\((\d+)%\)")
IN_MEMORY_MAX_SIZE = 4 * 1024 * 1024
STREAM_CHUNK_SIZE = 4 * 1024 * 1024


class WorkerOperations:
    def _register_proc(self, proc):
        if hasattr(self, "_active_procs") and hasattr(self, "_dl_lock"):
            with self._dl_lock:
                self._active_procs.add(proc)

    def _unregister_proc(self, proc):
        if hasattr(self, "_active_procs") and hasattr(self, "_dl_lock"):
            with self._dl_lock:
                self._active_procs.discard(proc)

    def _mark_verified(self, path):
        if hasattr(self, "verified_files") and hasattr(self, "_dl_lock"):
            norm = os.path.normcase(os.path.abspath(path))
            with self._dl_lock:
                self.verified_files.add(norm)
                self.verified_files.add(path)

    def _is_verified(self, path):
        if not hasattr(self, "verified_files"):
            return False
        norm = os.path.normcase(os.path.abspath(path))
        with self._dl_lock:
            return norm in self.verified_files or path in self.verified_files

    def _safe_unlink(self, path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except PermissionError:
                try:
                    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                    os.remove(path)
                except Exception:
                    pass
            except OSError:
                pass

    def nin_request(self, method, url, headers=None):
        if not self.is_running:
            raise RuntimeError("STOPPED")

        if headers is None:
            headers = {}
        headers.update({
            "User-Agent": self.user_agent or "NintendoSDK Firmware/UNKNOWN"
        })

        self.log_adv(self.T("log_http_req").format(method, url))

        t0 = time.monotonic()
        resp = self.http_session.request(method, url, headers=headers, timeout=(6, 15))
        t1 = time.monotonic()

        c_len = resp.headers.get("Content-Length", "0")
        content_id = resp.headers.get("X-Nintendo-Content-ID", "")
        extra_hdr = f" | Content-ID: {content_id}" if content_id else ""

        self.log_adv(
            self.T("log_http_resp").format(
                resp.status_code, int((t1 - t0) * 1000), c_len, extra_hdr
            )
        )

        resp.raise_for_status()
        return resp

    def dlfile(self, url, out, fhash=None, force_requests=False, expected_size=None):
        if not self.is_running:
            raise RuntimeError("STOPPED")

        fname_only = os.path.basename(out)
        if expected_size is None and hasattr(self, "expected_sizes"):
            expected_size = self.expected_sizes.get(out)

        if getattr(self, "aria2c_enabled", False) and not force_requests:
            out_dir = os.path.dirname(out)
            cmd_args = [
                self.aria2c_path,
                "--no-conf",
                "--console-log-level=error",
                "--file-allocation=none",
                "--summary-interval=0",
                "--download-result=hide",
                f"--certificate={self.req_cert_crt}",
                f"--private-key={self.req_cert_key}",
                f"--header=User-Agent: {self.user_agent}",
                "--check-certificate=false",
                "--min-split-size=1M",
                "--dir",
                out_dir,
                "--out",
                fname_only,
                "-c",
                url,
                "--auto-file-renaming=false",
                "--allow-overwrite=true",
            ]
            if fhash:
                cmd_args.append(f"--checksum=sha-256={fhash}")

            proc = subprocess.Popen(
                cmd_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **SUBPROCESS_FLAGS,
            )
            self._register_proc(proc)

            try:
                while proc.poll() is None:
                    if not self.is_running:
                        proc.kill()
                        proc.wait()
                        raise RuntimeError("STOPPED")
                    time.sleep(0.05)

                if proc.returncode != 0:
                    raise RuntimeError(self.T("err_nx_aria_code").format(proc.returncode))
                if fhash:
                    self._mark_verified(out)
                return
            except Exception as e:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                if str(e) == "STOPPED":
                    raise RuntimeError("STOPPED")
                self.log_adv(self.T("log_dl_fallback").format(fname_only, url))
            finally:
                self._unregister_proc(proc)

        max_retries = 4
        use_in_memory = expected_size is not None and 0 < expected_size <= IN_MEMORY_MAX_SIZE

        for attempt in range(max_retries):
            try:
                if not self.is_running:
                    raise RuntimeError("STOPPED")

                if use_in_memory:
                    resp = self.http_session.get(
                        url,
                        headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
                        timeout=(6, 20),
                    )
                    resp.raise_for_status()
                    data = resp.content
                    bytes_written = len(data)
                    if expected_size and bytes_written != expected_size:
                        raise ValueError("HASH_MISMATCH")
                    if fhash is not None:
                        if hashlib.sha256(data).hexdigest() != fhash.lower():
                            raise ValueError("HASH_MISMATCH")
                    _write_bytes_fast(out, data)
                    if fhash is not None:
                        self._mark_verified(out)
                    self.log_adv(
                        self.T("log_dl_stream_done").format(fname_only, bytes_written, 1)
                    )
                    return

                with self.http_session.get(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
                    stream=True,
                    timeout=(8, 25),
                ) as resp:
                    resp.raise_for_status()

                    h = hashlib.sha256() if fhash is not None else None
                    chunk_count = 0
                    bytes_written = 0

                    with open(out, "wb", buffering=STREAM_CHUNK_SIZE) as f:
                        for chunk in resp.iter_content(STREAM_CHUNK_SIZE):
                            if not self.is_running:
                                raise RuntimeError("STOPPED")
                            if chunk:
                                if h is not None:
                                    h.update(chunk)
                                f.write(chunk)
                                chunk_count += 1
                                bytes_written += len(chunk)

                    if not self.is_running:
                        raise RuntimeError("STOPPED")

                    if expected_size and bytes_written != expected_size:
                        raise ValueError("HASH_MISMATCH")

                    if fhash is not None:
                        computed = h.hexdigest()
                        if computed != fhash.lower():
                            raise ValueError("HASH_MISMATCH")
                        self._mark_verified(out)

                self.log_adv(
                    self.T("log_dl_stream_done").format(
                        fname_only, bytes_written, chunk_count
                    )
                )
                return

            except Exception as e:
                if str(e) == "STOPPED" or not self.is_running:
                    self._safe_unlink(out)
                    raise RuntimeError("STOPPED")
                self.log_adv(
                    self.T("log_dl_err_retry").format(
                        attempt + 1, max_retries, fname_only, str(e)
                    )
                )

                self._safe_unlink(out)

                if attempt < max_retries - 1:
                    time.sleep(0.25)
                else:
                    if str(e) == "HASH_MISMATCH":
                        err_msg = self.T("log_err_sha256").format(fname_only)
                        raise RuntimeError(err_msg)
                    raise RuntimeError(
                        self.T("err_dl_net").format(fname_only, max_retries)
                    )

    def dlfiles(self, dltable):
        if not self.is_running or not dltable:
            return

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
            cnmt_count = len(self.pfs0_map.get("meta_nca", [])) if hasattr(self, "pfs0_map") else 0
            total_all = cnmt_count + total
            self.log_adv(self.T("log_nca_queue").format(total_all, cnmt_count, total))
            if getattr(self, "sv_nca_fat", ""):
                self.log_adv(self.T("log_nca_fat").format(self.sv_nca_fat))
            if self.config.get("exclude_exfat", False):
                self.log_adv(self.T("log_nca_exfat_excluded"))
            elif getattr(self, "sv_nca_exfat", ""):
                self.log_adv(self.T("log_nca_exfat").format(self.sv_nca_exfat))

        dl_tmp_path = os.path.join(self.config["output_dir"], "dl.tmp")

        if getattr(self, "aria2c_enabled", False):
            try:
                with open(dl_tmp_path, "w", encoding="utf-8") as f:
                    for url, dirc, fname, fhash in dltable:
                        f.write(
                            f"{url}\n\tout={fname}\n\tdir={dirc}\n\tchecksum=sha-256={fhash}\n"
                        )

                max_concurrent = str(min(16, max(8, (os.cpu_count() or 4) * 2)))

                if not adv:
                    self.log("")
                    self.update_text_progress(
                        0, 100, self.T("log_dl_ncas"), is_first=True
                    )
                else:
                    self.log_adv(
                        self.T("log_aria_invoke").format(total, max_concurrent)
                    )

                proc = subprocess.Popen(
                    [
                        self.aria2c_path,
                        "--no-conf",
                        "--console-log-level=notice",
                        "--file-allocation=none",
                        "--summary-interval=1",
                        "--download-result=hide",
                        "--auto-file-renaming=false",
                        "--allow-overwrite=true",
                        f"--certificate={self.req_cert_crt}",
                        f"--private-key={self.req_cert_key}",
                        f"--header=User-Agent: {self.user_agent}",
                        "--check-certificate=false",
                        "--min-split-size=1M",
                        "-j",
                        max_concurrent,
                        "-x",
                        "8",
                        "-s",
                        "8",
                        "-i",
                        dl_tmp_path,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    **SUBPROCESS_FLAGS,
                )
                self._register_proc(proc)

                try:
                    last_pct = 0
                    for line in proc.stdout:
                        if not self.is_running:
                            proc.kill()
                            proc.wait()
                            raise RuntimeError("STOPPED")

                        if adv and "Download complete:" in line:
                            self.log_adv(line.strip(), raw=True)

                        m = RE_ARIA_PCT.search(line)
                        if m:
                            pct = int(m.group(1))
                            if pct >= last_pct:
                                last_pct = pct
                                if not adv:
                                    self.update_text_progress(pct, 100, self.T("log_dl_ncas"))
                                self._emit_progress_throttled(10 + int(pct * 0.70), 100)
                    proc.wait()
                    if not self.is_running:
                        raise RuntimeError("STOPPED")
                    if proc.returncode != 0:
                        raise RuntimeError(self.T("err_nx_aria_code").format(proc.returncode))
                finally:
                    self._unregister_proc(proc)
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()

                if not adv and last_pct < 100:
                    self.update_text_progress(100, 100, self.T("log_dl_ncas"))
                elif adv:
                    self.log_adv(self.T("log_aria_exit").format(proc.returncode))

                for _, dirc, fname, _ in dltable:
                    full_p = os.path.join(dirc, fname)
                    exp_sz = self.expected_sizes.get(full_p, 0) if hasattr(self, "expected_sizes") else 0
                    if os.path.exists(full_p):
                        actual_sz = os.path.getsize(full_p)
                        if actual_sz > 0 and (exp_sz == 0 or actual_sz == exp_sz):
                            self._mark_verified(full_p)
                return
            except Exception as e:
                if str(e) == "STOPPED" or not self.is_running:
                    raise RuntimeError("STOPPED")
                self.log_adv(self.T("log_aria_fail").format(str(e)))
            finally:
                if os.path.exists(dl_tmp_path):
                    self._safe_unlink(dl_tmp_path)

        completed = 0
        workers = min(20, max(8, (os.cpu_count() or 4) * 2))

        if not adv:
            self.log("")
            self.update_text_progress(0, total, self.T("log_dl_ncas"), is_first=True)
        else:
            self.log_adv(
                self.T("log_tp_start").format(workers, total)
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = []
            for url, dirc, fname, fhash in dltable:
                os.makedirs(dirc, exist_ok=True)
                full_dst = os.path.join(dirc, fname)
                exp_sz = self.expected_sizes.get(full_dst) if hasattr(self, "expected_sizes") else None
                futs.append(
                    ex.submit(self.dlfile, url, full_dst, fhash, False, exp_sz)
                )
            try:
                for f in concurrent.futures.as_completed(futs):
                    if not self.is_running:
                        for fut in futs:
                            fut.cancel()
                        raise RuntimeError("STOPPED")
                    f.result()
                    completed += 1
                    if not adv:
                        self.update_text_progress(completed, total, self.T("log_dl_ncas"))
                    self._emit_progress_throttled(10 + int((completed / total) * 70), 100)
            except Exception:
                for fut in futs:
                    fut.cancel()
                raise

    def _verify_single_file(self, path, expected_hash):
        exp_sz = self.expected_sizes.get(path, 0) if hasattr(self, "expected_sizes") else 0
        if self._is_verified(path) and os.path.exists(path):
            actual_sz = os.path.getsize(path)
            if actual_sz > 0 and (exp_sz == 0 or actual_sz == exp_sz):
                return path, expected_hash.lower(), expected_hash.lower()

        if hasattr(hashlib, "file_digest"):
            with open(path, "rb") as f:
                computed_hash = hashlib.file_digest(f, "sha256").hexdigest()
        else:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                    h.update(chunk)
            computed_hash = h.hexdigest()

        if computed_hash == expected_hash.lower():
            self._mark_verified(path)

        return path, computed_hash, expected_hash
