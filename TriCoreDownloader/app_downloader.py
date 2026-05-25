import os
import sys
import re
import shutil
import subprocess
import traceback
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QLabel, QCheckBox, QHBoxLayout, QPushButton, QApplication, QSizePolicy
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor

from .config import save_config
from .app_utils_dialogs import OtpInputDialog
from .NX.worker import DownloaderWorker
from .CAFE.worker import CafeDownloaderWorker
from .CTR.worker import CtrDownloaderWorker
from .logos import CHECK_SVG, CROSS_SVG

class DownloadManagerMixin:
    def append_log(self, text):
        if hasattr(self, "console"):
            self.console.appendPlainText(text)
            self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
            print(f"[WORKER LOG] {text}")

    def replace_last_log(self, text):
        if not hasattr(self, "console"): 
            return
        cursor = self.console.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.console.setTextCursor(cursor)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def update_progress(self, current, total):
        if hasattr(self, "progress_bar"):
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.lbl_progress_pct.setText(f"{int((current / total) * 100)}%" if total > 0 else "0%")

    def show_centered_msg(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(35, 15, 35, 25)
        layout.setSpacing(0)
        
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setFixedWidth(380)
        lbl.setStyleSheet("line-height: 22px; font-size: 10.5pt;")
        layout.addWidget(lbl)
        
        layout.addStretch(1)
        layout.addSpacing(30)
        
        btn_layout = QHBoxLayout()
        btn = QPushButton(self.T("btn_ok") if hasattr(self, "T") else "OK")
        btn.setFixedWidth(140)
        btn.setMinimumHeight(36)
        btn.clicked.connect(dialog.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        dialog.adjustSize()
        dialog.exec()

    def handle_overwrite_prompt(self, version):
        print(f"[DOWNLOADER] Prompting overwrite for version: {version}")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("overwrite_title"))
        msg_box.setText(self.T("overwrite_msg").format(version))
        btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
        msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
        msg_box.exec()
        
        if getattr(self, "worker", None) is not None:
            choice = (msg_box.clickedButton() == btn_yes)
            print(f"[DOWNLOADER] Overwrite choice: {choice}")
            self.worker.receive_overwrite_choice(choice)

    def handle_skip_prompt(self, title_id):
        print(f"[DOWNLOADER] Prompting skip 404 for Title ID: {title_id}")
        if getattr(self, "_always_skip_404", False):
            if getattr(self, "worker", None) is not None and hasattr(self.worker, 'receive_skip_choice'):
                print("[DOWNLOADER] Auto-skipping 404 due to persistent user preference.")
                self.worker.receive_skip_choice(True)
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("skip_404_title"))
        msg_box.setText(self.T("skip_404_msg").format(title_id))
        
        btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
        btn_always_yes = msg_box.addButton(self.T("btn_always_yes"), QMessageBox.ButtonRole.ActionRole)
        btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
        
        msg_box.setDefaultButton(btn_no)
        msg_box.exec()
        
        clicked_btn = msg_box.clickedButton()
        if clicked_btn == btn_always_yes:
            self._always_skip_404 = True
            choice = True
        else:
            choice = (clicked_btn == btn_yes)
            
        print(f"[DOWNLOADER] Skip 404 choice: {choice} (Always: {self._always_skip_404})")
        if getattr(self, "worker", None) is not None and hasattr(self.worker, 'receive_skip_choice'):
            self.worker.receive_skip_choice(choice)

    def perform_security_cleanup(self):
        print("[DOWNLOADER] Executing memory and file security cleanup...")
        root = os.path.dirname(os.path.abspath(sys.argv[0]))
        files_to_purge = ["switch_client.crt", "switch_client.key"]
        dirs_to_purge = ["temp_dl"]
        
        for f in files_to_purge:
            p = os.path.join(root, f)
            if os.path.exists(p):
                try: 
                    os.remove(p)
                    print(f"[DOWNLOADER] Purged runtime certificate artifact: {f}")
                except Exception as e: 
                    print(f"[DOWNLOADER ERROR] Failed to purge {f}: {e}")
                    
        for d in dirs_to_purge:
            p = os.path.join(root, d)
            if os.path.exists(p):
                try: 
                    shutil.rmtree(p, ignore_errors=True)
                    print(f"[DOWNLOADER] Purged temporary workspace: {d}")
                except Exception as e: 
                    print(f"[DOWNLOADER ERROR] Failed to purge folder {d}: {e}")

    def setup_ui_for_download(self):
        print("[DOWNLOADER] Locking interface inputs.")
        self.set_ui_locked(True)
        self.console.clear()
        self.progress_bar.setValue(0)
        self.lbl_progress_pct.setText("0%")
        self.btn_action.setText(self.T("btn_stop"))
        self.btn_action.setObjectName("btnStop")
        self.btn_action.style().unpolish(self.btn_action)
        self.btn_action.style().polish(self.btn_action)
        
        if hasattr(self, "symbol_reset_timer"):
            self.symbol_reset_timer.stop()
            
        self.spinner_idx = 0
        self.spinner_timer.start(100)
        self._always_skip_404 = False

    def connect_worker_and_start(self):
        if not getattr(self, "worker", None): 
            return
            
        print("[DOWNLOADER] Mapping background thread async communication slots.")
        try:
            self.worker.log_signal.connect(self.append_log)
            self.worker.log_replace_signal.connect(self.replace_last_log)
            self.worker.progress_signal.connect(self.update_progress)
            
            if hasattr(self.worker, 'ask_overwrite_signal'): 
                self.worker.ask_overwrite_signal.connect(self.handle_overwrite_prompt)
            if hasattr(self.worker, 'ask_skip_signal'): 
                self.worker.ask_skip_signal.connect(self.handle_skip_prompt)
                
            self.worker.finished_signal.connect(self.on_download_finished)
            self.worker.start()
            print("[DOWNLOADER] Thread processing subsystem active.")
            
        except Exception as e:
            print(f"[DOWNLOADER FATAL] Signal linkage exception crashed worker: {e}")
            error_msg = f"\n[!] {self.T('err_worker_init')}\n{traceback.format_exc()}"
            if hasattr(self, "console"): 
                self.console.appendPlainText(error_msg)
            self.on_download_finished(False, self.T("err_worker_init"))

    def toggle_download(self):
        if getattr(self, "_is_toggling", False): 
            print("[DOWNLOADER] Prevented rapid activation toggle spam.")
            return
            
        self._is_toggling = True
        QTimer.singleShot(1000, lambda: setattr(self, "_is_toggling", False))
        
        mode = self.config.get("console_mode", "NX")
        print(f"[DOWNLOADER] Processing execution toggle for matrix mode: {mode}")
        
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            print("[DOWNLOADER] Terminating ongoing task request thread.")
            self.append_log(f"\n[!] {self.T('btn_stop')} ...")
            self.worker.stop()
            self.btn_action.setEnabled(False)
            
            QApplication.processEvents()
            self.audio.play_stop(self.current_console)
            
            self.spinner_timer.stop()
            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CROSS_SVG).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)
            return
            
        out_dir = self.input_output.text().strip()
        if out_dir and not os.path.exists(out_dir):
            if not self.verify_and_create_export_folder(out_dir):
                print("[DOWNLOADER] Root target validation rejected.")
                QApplication.processEvents()
                self.audio.play_result(self.current_console, False)
                self.switch_tab_animated(1)
                return

        if hasattr(self, "input_output"):
            self.config["output_dir"] = self.input_output.text().strip()
            
        if mode == "NX":
            if hasattr(self, "input_hactool"): self.config["hactool"] = self.input_hactool.text().strip()
            if hasattr(self, "input_keys"): self.config["prod_keys"] = self.input_keys.text().strip()
            if hasattr(self, "input_prodinfo"): self.config["prodinfo"] = self.input_prodinfo.text().strip()
            if hasattr(self, "input_cert"): self.config["cert_pem"] = self.input_cert.text().strip()
        elif mode == "CTR":
            if hasattr(self, "input_boot9"): self.config["boot9_path"] = self.input_boot9.text().strip()
            if hasattr(self, "chk_ctr_decrypt"): self.config["decrypt_cia"] = self.chk_ctr_decrypt.isChecked()
        elif mode == "CAFE":
            if hasattr(self, "input_otp"): self.config["otp_path"] = self.input_otp.text().strip()
            
        if mode == "NX":
            version = ""
            if hasattr(self, "radio_group") and self.radio_group.checkedButton() != getattr(self, "radio_latest", None):
                version = self.input_manual.text().strip()
                if not re.match(r"^\d+\.\d+\.\d+\.\d+$", version):
                    print(f"[DOWNLOADER ERROR] Bad payload syntax for manual Horizon version target: {version}")
                    QApplication.processEvents()
                    self.audio.play_result(self.current_console, False)
                    self.show_centered_msg(self.T("err_format_title"), self.T("err_format_msg"))
                    return
                    
            req = ["hactool", "prod_keys", "prodinfo", "cert_pem", "output_dir"]
            label_map = {"hactool": "lbl_hactool", "prod_keys": "lbl_keys", "prodinfo": "lbl_prodinfo", "cert_pem": "lbl_cert", "output_dir": "lbl_out"}
            errs = [f"  {self.T(label_map[k])}" for k in req if not self.config.get(k, "").strip() or not os.path.exists(self.config.get(k, "").strip())]
            
            if errs:
                print("[DOWNLOADER ERROR] Cryptographic extraction dependencies missing.")
                QApplication.processEvents()
                self.audio.play_result(self.current_console, False)
                err_text = self.T("msg_err_cfg") + "\n" + "\n".join(errs)
                self.show_centered_msg(self.T("msg_error_title"), err_text)
                self.switch_tab_animated(1)
                return
                
            self.setup_ui_for_download()
            QApplication.processEvents()
            self.audio.play_start_sequence(self.current_console)
            
            if getattr(self, "worker", None) is not None:
                self.worker.wait()
                self.worker.deleteLater()
                self.worker = None
                
            try:
                print(f"[DOWNLOADER] Instantiating Horizon environment task runtime targeting v{version if version else 'LATEST'}")
                self.worker = DownloaderWorker(version, self.config)
                self.connect_worker_and_start()
            except Exception as e:
                print(f"[DOWNLOADER FATAL] Horizon environment thread failed critical setup: {e}")
                error_msg = f"\n[!] {self.T('err_worker_nx')}\n{traceback.format_exc()}"
                if hasattr(self, "console"): 
                    self.console.appendPlainText(error_msg)
                self.on_download_finished(False, self.T("err_worker_nx"))
                
        elif mode == "CAFE":
            if not out_dir or not os.path.exists(out_dir):
                QApplication.processEvents()
                self.audio.play_result(self.current_console, False)
                errs = [f"  {self.T('lbl_out')}"]
                err_text = self.T("msg_err_cfg") + "\n" + "\n".join(errs)
                self.show_centered_msg(self.T("msg_error_title"), err_text)
                self.switch_tab_animated(1)
                return
                
            target_fw = ""
            region = "EUR"
            
            if hasattr(self, "radio_group") and self.radio_group.checkedButton() != getattr(self, "radio_latest", None):
                target_fw = self.input_manual.text().strip().upper()
                if not re.match(r"^\d+\.\d+\.\d+[EUJ]$", target_fw):
                    print(f"[DOWNLOADER ERROR] Manual Cafe identifier pattern violation: {target_fw}")
                    QApplication.processEvents()
                    self.audio.play_result(self.current_console, False)
                    self.show_centered_msg(self.T("err_format_title"), self.T("err_format_msg_cafe"))
                    return
                    
                region_char = target_fw[-1]
                if region_char == 'E': region = "EUR"
                elif region_char == 'U': region = "USA"
                elif region_char == 'J': region = "JPN"
            else:
                if self.radio_usa.isChecked(): region = "USA"
                elif self.radio_jpn.isChecked(): region = "JPN"
                else: region = "EUR"
                
            otp_path = self.config.get("otp_path", "").strip()
            if not otp_path and os.path.isfile("otp.bin"): 
                otp_path = os.path.abspath("otp.bin")
                
            otp_key = self.config.get("otp_key", "").strip()
            force_prompt = getattr(self, "_force_key_prompt", False)
            self._force_key_prompt = False
            ignore_file = getattr(self, "_ignore_otp_file_once", False)
            self._ignore_otp_file_once = False
            
            if not ignore_file: 
                self._fallback_key_used = False
                
            is_file = os.path.isfile(otp_path) if not (force_prompt or ignore_file) else False
            is_key_valid = (re.match(r"^[A-Fa-f0-9]{32}$", otp_key) is not None) if not force_prompt else False
            
            if is_file:
                try:
                    if os.path.getsize(otp_path) == 0: 
                        is_file = False
                except: 
                    is_file = False
                    
            if is_file:
                otp_input = otp_path
                is_key = False
            elif is_key_valid:
                otp_input = otp_key
                is_key = True
            else:
                print("[DOWNLOADER] Prompting interactive entry window for hardware decrypt security token.")
                title = self.T("title_input_otp")
                msg = self.T("msg_input_otp")
                chk_txt = self.T("chk_remember_key")
                btn_ok_txt = self.T("btn_ok")
                btn_cancel_txt = self.T("btn_cancel")
                
                while True:
                    dialog = OtpInputDialog(self, title, msg, chk_txt, btn_ok_txt, btn_cancel_txt, otp_key)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        key, remember = dialog.get_data()
                        if re.match(r"^[A-Fa-f0-9]{32}$", key):
                            otp_input = key
                            is_key = True
                            if remember:
                                self.config["otp_key"] = key
                                save_config(self.config)
                            else:
                                if "otp_key" in self.config:
                                    self.config["otp_key"] = ""
                                    save_config(self.config)
                            break
                        else:
                            print("[DOWNLOADER ERROR] Hardware context encryption token verification pattern error.")
                            QApplication.processEvents()
                            self.audio.play_result(self.current_console, False)
                            self.show_centered_msg(self.T("msg_error_title"), self.T("err_invalid_key"))
                    else:
                        print("[DOWNLOADER] Runtime execution canceled at security gate context.")
                        QApplication.processEvents()
                        self.audio.play_result(self.current_console, False)
                        return
                        
            if self.radio_mlc.isChecked(): partitions = ["MLC"]
            elif self.radio_slc.isChecked(): partitions = ["SLC"]
            else: partitions = ["MLC", "SLC"]
            
            self.config["cafe_partitions"] = partitions
            self.config["cafe_region"] = region
            self.setup_ui_for_download()
            
            QApplication.processEvents()
            self.audio.play_start_sequence(self.current_console)
            
            if self.config.get("advanced_logs", False):
                self.append_log(self.T("log_mode_cafe"))
                self.append_log(self.T("log_target_region").format(region))
                self.append_log(self.T("log_target_parts").format(' + '.join(partitions)))
                if is_key: 
                    self.append_log(self.T("log_manual_key").format(otp_input[:6], otp_input[-4:]))
                else: 
                    self.append_log(self.T("log_otp_detected").format(otp_input))
            else:
                self.append_log(self.T("log_latest_dl"))
                
            worker_config = self.config.copy()
            if is_key: 
                worker_config["otp_path"] = otp_input
            if target_fw: 
                worker_config["target_firmware"] = target_fw
            
            if getattr(self, "worker", None) is not None:
                self.worker.wait()
                self.worker.deleteLater()
                self.worker = None
                
            try:
                print(f"[DOWNLOADER] Instantiating Cafe task worker interface targeting region={region}, firmware={target_fw}")
                self.worker = CafeDownloaderWorker(region, worker_config)
                self.connect_worker_and_start()
            except Exception as e:
                print(f"[DOWNLOADER FATAL] Cafe background engine context instantiation failure: {e}")
                error_msg = f"\n[!] {self.T('err_worker_cafe')}\n{traceback.format_exc()}"
                if hasattr(self, "console"): 
                    self.console.appendPlainText(error_msg)
                self.on_download_finished(False, self.T("err_worker_cafe"))
                
        elif mode == "CTR":
            if not out_dir or not os.path.exists(out_dir):
                QApplication.processEvents()
                self.audio.play_result(self.current_console, False)
                errs = [f"  {self.T('lbl_out')}"]
                err_text = self.T("msg_err_cfg") + "\n" + "\n".join(errs)
                self.show_centered_msg(self.T("msg_error_title"), err_text)
                self.switch_tab_animated(1)
                return

            target_fw = ""
            is_new_3ds = False
            
            if hasattr(self, "radio_new_3ds") and self.radio_new_3ds.isChecked(): 
                is_new_3ds = True
            self.config["ctr_model"] = "NEW" if is_new_3ds else "OLD"
            
            if hasattr(self, "radio_group") and self.radio_group.checkedButton() != getattr(self, "radio_latest", None):
                target_fw = self.input_manual.text().strip().upper()
                if not re.match(r"^\d+\.\d+\.\d+-\d+$", target_fw):
                    print(f"[DOWNLOADER ERROR] Manual metadata syntax formatting error for CTR target: {target_fw}")
                    QApplication.processEvents()
                    self.audio.play_result(self.current_console, False)
                    self.show_centered_msg(self.T("err_format_title"), self.T("err_format_msg_ctr"))
                    return
            else:
                if hasattr(self, "radio_ctr_usa") and self.radio_ctr_usa.isChecked(): self.config["ctr_region"] = "USA"
                elif hasattr(self, "radio_ctr_jpn") and self.radio_ctr_jpn.isChecked(): self.config["ctr_region"] = "JPN"
                elif hasattr(self, "radio_ctr_aus") and self.radio_ctr_aus.isChecked(): self.config["ctr_region"] = "AUS"
                elif hasattr(self, "radio_ctr_kor") and self.radio_ctr_kor.isChecked(): self.config["ctr_region"] = "KOR"
                elif hasattr(self, "radio_ctr_chn") and self.radio_ctr_chn.isChecked(): self.config["ctr_region"] = "CHN"
                elif hasattr(self, "radio_ctr_twn") and self.radio_ctr_twn.isChecked(): self.config["ctr_region"] = "TWN"
                else: self.config["ctr_region"] = "EUR"
                
                target_fw = "LATEST"
                
            self.setup_ui_for_download()
            QApplication.processEvents()
            self.audio.play_start_sequence(self.current_console)
            
            if self.config.get("advanced_logs", False):
                self.append_log(self.T("log_mode_ctr"))
                model_str = "New 3DS / 2DS" if is_new_3ds else "Old 3DS / 2DS"
                self.append_log(self.T("log_target_model").format(model_str))
                self.append_log(self.T("log_target_fw").format(target_fw))
            else:
                self.append_log(self.T("log_latest_dl"))
                
            if getattr(self, "worker", None) is not None:
                self.worker.wait()
                self.worker.deleteLater()
                self.worker = None
                
            worker_config = self.config.copy()
            try:
                print(f"[DOWNLOADER] Initializing CTR operational thread architecture targeting hardware variant={self.config['ctr_model']}, firmware={target_fw}")
                self.worker = CtrDownloaderWorker(target_fw, is_new_3ds, worker_config)
                self.connect_worker_and_start()
            except Exception as e:
                print(f"[DOWNLOADER FATAL] CTR processing module threw instant instantiation error: {e}")
                error_msg = f"\n[!] {self.T('err_worker_ctr')}\n{traceback.format_exc()}"
                if hasattr(self, "console"): 
                    self.console.appendPlainText(error_msg)
                self.on_download_finished(False, self.T("err_worker_ctr"))

    def open_export_folder(self, folder_path):
        print(f"[DOWNLOADER] Sending request to open directory window layout: {folder_path}")
        if folder_path and os.path.exists(folder_path):
            if sys.platform == "win32": 
                os.startfile(folder_path)
            elif sys.platform == "darwin": 
                subprocess.Popen(["open", folder_path])
            else: 
                subprocess.Popen(["xdg-open", folder_path])

    def on_download_finished(self, success, message):
        print(f"[DOWNLOADER] Thread processing session terminated. success={success}, metadata={message}")
        
        is_crypto_failure = False
        if not success and self.current_console == "CAFE" and message:
            msg_upper = message.upper()
            translated_err = self.T("err_common_key_invalid").upper()
            
            if "ERR_COMMON_KEY_INVALID" in msg_upper or "ERR_COMMON_KEY_FORMAT" in msg_upper:
                is_crypto_failure = True
            elif translated_err in msg_upper:
                is_crypto_failure = True
            elif "DECRYPTION CHALLENGE" in msg_upper or "HEURISTIC" in msg_upper:
                is_crypto_failure = True
                
        if is_crypto_failure:
            print("[SECURITY ROUTINE] Decryption validation checks failed. Performing emergency key workspace purge.")
            self.set_ui_locked(False)
            self.btn_action.setEnabled(True)
            self.btn_action.setText(self.T("btn_start"))
            self.btn_action.setObjectName("btnDownload")
            self.btn_action.style().unpolish(self.btn_action)
            self.btn_action.style().polish(self.btn_action)
            self.perform_security_cleanup()
            self.spinner_timer.stop()
            
            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CROSS_SVG).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)
                
            if hasattr(self, "progress_bar"): self.progress_bar.setValue(0)
            if hasattr(self, "lbl_progress_pct"): self.lbl_progress_pct.setText("0%")
            
            self.config["otp_key"] = ""
            self.config["otp_path"] = ""
            save_config(self.config)
            
            if hasattr(self, "input_otp"):
                self.input_otp.clear()
                
            QApplication.processEvents()
            self.audio.play_result(self.current_console, False)
            self.show_centered_msg(self.T("msg_error_title"), self.T("err_common_key_invalid"))
            QTimer.singleShot(100, self.toggle_download)
            return

        self.set_ui_locked(False)
        self.btn_action.setEnabled(True)
        self.btn_action.setText(self.T("btn_start"))
        self.btn_action.setObjectName("btnDownload")
        self.btn_action.style().unpolish(self.btn_action)
        self.btn_action.style().polish(self.btn_action)
        self.perform_security_cleanup()
        
        self.spinner_timer.stop()
        if success:
            QApplication.processEvents()
            self.audio.play_result(self.current_console, True)
            
            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CHECK_SVG).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)
                
            mode_lower = self.current_console.lower()
            ask_key = f"ask_open_folder_{mode_lower}"
            auto_key = f"auto_open_folder_{mode_lower}"
            msg_desc_key = f"msg_open_folder_desc_{self.current_console}"
            
            if self.config.get(ask_key, True):
                print("[DOWNLOADER] Prompting choice dialog interface to show exported contents.")
                dialog = QDialog(self)
                dialog.setWindowTitle(self.T("msg_open_folder_title"))
                dialog.setMinimumWidth(450)
                layout = QVBoxLayout(dialog)
                layout.setContentsMargins(25, 25, 25, 20)
                layout.setSpacing(15)
                
                lbl_desc = QLabel(self.T(msg_desc_key))
                lbl_desc.setWordWrap(True)
                layout.addWidget(lbl_desc)
                
                cb_never = QCheckBox(self.T("chk_never_ask"))
                layout.addWidget(cb_never)
                layout.addSpacing(10)
                
                btn_yes, btn_no = QPushButton(self.T("btn_yes")), QPushButton(self.T("btn_no"))
                btn_yes.clicked.connect(dialog.accept)
                btn_no.clicked.connect(dialog.reject)
                
                btn_layout = QHBoxLayout()
                btn_layout.addStretch()
                btn_layout.addWidget(btn_yes)
                btn_layout.addWidget(btn_no)
                btn_layout.addStretch()
                layout.addLayout(btn_layout)
                
                is_yes = (dialog.exec() == QDialog.DialogCode.Accepted)
                
                if cb_never.isChecked():
                    self.config[ask_key] = False
                    self.config[auto_key] = is_yes
                    save_config(self.config)
                    
                if is_yes: 
                    self.open_export_folder(self.config.get("output_dir"))
            else:
                if self.config.get(auto_key, False): 
                    self.open_export_folder(self.config.get("output_dir"))
                else:
                    self.show_centered_msg(self.T("msg_success_title"), self.T("msg_success"))
        else:
            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CROSS_SVG).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)
                
            if hasattr(self, "progress_bar"): 
                self.progress_bar.setValue(0)
            if hasattr(self, "lbl_progress_pct"): 
                self.lbl_progress_pct.setText("0%")
                
            msg_incomplete = self.T("err_incomplete_msg")
            
            if message == "INCOMPLETE_FIRMWARE" or message == msg_incomplete:
                print("[DOWNLOADER ERROR] Extracted payload structural footprint is missing system package dependencies.")
                QApplication.processEvents()
                self.audio.play_result(self.current_console, False)
                self.show_centered_msg(self.T("err_incomplete_title"), msg_incomplete)
                
            elif message != "STOPPED" and message != self.T("msg_aborted") and message != "Annulé proprement.":
                QApplication.processEvents()
                self.audio.play_result(self.current_console, False)
                
                if self.current_console == "CAFE" and "OTP" in message.upper():
                    otp_key = self.config.get("otp_key", "").strip()
                    if not getattr(self, "_fallback_key_used", False) and re.match(r"^[A-Fa-f0-9]{32}$", otp_key):
                        self._ignore_otp_file_once = True
                        self._fallback_key_used = True
                        QTimer.singleShot(100, self.toggle_download)
                        return
                        
                    self._fallback_key_used = False
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle(self.T("msg_fail_title"))
                    msg_box.setText(self.T("msg_aborted") + f"\n\n{self.T('msg_tech_err')} {message}")
                    btn_ok = msg_box.addButton(self.T("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
                    btn_file = msg_box.addButton(self.T("btn_cfg_otp_file"), QMessageBox.ButtonRole.ActionRole)
                    btn_key = msg_box.addButton(self.T("btn_enter_new_key"), QMessageBox.ButtonRole.ActionRole)
                    msg_box.exec()
                    
                    if msg_box.clickedButton() == btn_file: 
                        self.switch_tab_animated(1)
                    elif msg_box.clickedButton() == btn_key:
                        self._force_key_prompt = True
                        QTimer.singleShot(100, self.toggle_download)
                else:
                    raw_msg = self.T("msg_aborted") + f"\n\n{self.T('msg_tech_err')} {message}"
                    self.show_centered_msg(self.T("msg_fail_title"), raw_msg)