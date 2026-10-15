import os
import sys
import re
import ssl
import shutil
import subprocess
import traceback
import json
import platform
import urllib.request
import urllib.error
from pathlib import Path
from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QLabel,
    QCheckBox, QHBoxLayout, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor

from .config import save_config, APPDATA_DIR
from .app_utils_dialogs import OtpInputDialog
from .NX.worker import DownloaderWorker
from .CAFE.worker import CafeDownloaderWorker
from .CTR.worker import CtrDownloaderWorker
from .logos import CHECK_SVG, CROSS_SVG

RE_VER = re.compile(r"(\d+(?:\.\d+)+)")
RE_BUILD_VER = re.compile(r"\((\d+\.\d+\.\d+\.\d+)\)")
RE_R_ALREADY = re.compile(r"\bR(\d+)\b")
RE_RB = re.compile(r"[\[\(]?\b(?:rebootless(?:\s+update)?|r\.+te(?:\s*update)?)\s*(\d+)?[\]\)]?", re.IGNORECASE)
RE_TAG_R = re.compile(r"(?:[._-]r|(?:\d+\.\d+\.\d+)r)(\d*)\b", re.IGNORECASE)
RE_CHN = re.compile(r"\bchina\??\b|\[china\??\]|\(china\??\)", re.IGNORECASE)
RE_BETA = re.compile(r"\[pre-release\]|\bpre-release\b|\bprerelease\b|\bbeta\b", re.IGNORECASE)
RE_HEX32 = re.compile(r"^[A-Fa-f0-9]{32}$")
RE_NX_VER = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?$")
RE_CAFE_VER = re.compile(r"^\d+\.\d+\.\d+[EUJ]$")
RE_CTR_VER = re.compile(r"^(\d+\.\d+\.\d+-\d+)([EUJKCTA])?$", re.IGNORECASE)


def _urlopen_safe(req, timeout=10):
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except Exception:
        pass
    try:
        ctx = ssl.create_default_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except Exception:
        unverified_ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=unverified_ctx)


def format_fw_display_title(raw_title, tag_name="", body="", is_prerelease=False):
    if not raw_title:
        return ""
    m_ver = RE_VER.search(raw_title)
    if not m_ver and tag_name:
        m_ver = RE_VER.search(tag_name)
    if not m_ver:
        return raw_title
    ver_str = m_ver.group(1)
    base = f"Firmware {ver_str}"

    combined = f"{raw_title} {tag_name} {body[:300]}"
    tags = []

    m_r_already = RE_R_ALREADY.search(raw_title)
    if m_r_already:
        tags.append(f"R{m_r_already.group(1)}")
    else:
        m_rb = RE_RB.search(combined)
        if m_rb and m_rb.group(0).strip().lower() not in ["", "r"]:
            num = m_rb.group(1)
            tags.append(f"R{num}" if num else "R1")
        else:
            m_tag = RE_TAG_R.search(tag_name)
            if m_tag:
                num = m_tag.group(1)
                tags.append(f"R{num}" if num else "R1")

    if "[CHN]" in raw_title:
        tags.append("[CHN]")
    elif RE_CHN.search(combined) or "chn" in tag_name.lower():
        tags.append("[CHN]")

    if "Beta" in raw_title.split():
        tags.append("Beta")
    elif is_prerelease or RE_BETA.search(combined):
        tags.append("Beta")

    if tags:
        return f"{base} {' '.join(tags)}"
    return base


class NxFirmwareListThread(QThread):
    firmwares_loaded_signal = pyqtSignal(list)

    def __init__(self, cache_file):
        super().__init__()
        self.cache_file = cache_file

    def run(self):
        etag = ""
        cached_firmwares = []
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    if cache_data.get("cache_version") == 5:
                        etag = cache_data.get("etag", "")
                    cached_firmwares = cache_data.get("firmwares", [])
            except Exception:
                pass

        headers = {
            "User-Agent": "TriCoreDownloader",
            "Accept": "application/vnd.github.v3+json"
        }
        if etag:
            headers["If-None-Match"] = etag

        url = "https://api.github.com/repos/JeremKOYTB/NX_Firmware/releases?per_page=100"
        req = urllib.request.Request(url, headers=headers)
        try:
            with _urlopen_safe(req, timeout=10) as response:
                new_etag = response.headers.get("ETag", "")
                raw_data = response.read().decode("utf-8")
                releases = json.loads(raw_data)

            firmwares = []
            for rel in releases:
                title = rel.get("name") or rel.get("tag_name", "")
                tag = rel.get("tag_name", "").strip()
                body = rel.get("body") or ""
                title_lower = title.lower()
                is_pre = bool(
                    rel.get("prerelease", False)
                    or "[pre-release]" in title_lower
                    or "pre-release" in title_lower
                    or "prerelease" in title_lower
                )

                if "cartridge" in title_lower or "cartridge" in tag.lower():
                    continue

                m_ver = RE_VER.search(title) or RE_VER.search(tag)
                if m_ver and m_ver.group(1) in ["1.0.0", "8.1.1"]:
                    continue

                build_match = RE_BUILD_VER.findall(body)
                build_ver = build_match[-1] if build_match else ""

                if not build_ver:
                    tag_clean = tag.lstrip("v")
                    tag_parts = tag_clean.split(".")
                    if len(tag_parts) == 3:
                        build_ver = f"{tag_clean}.0"
                    elif len(tag_parts) == 4:
                        build_ver = tag_clean

                if build_ver == "8.1.1.0030":
                    continue

                if build_ver:
                    clean_display = format_fw_display_title(title, tag, body, is_pre)
                    firmwares.append({
                        "title": clean_display,
                        "raw_title": title.strip(),
                        "build_version": build_ver,
                        "tag_name": tag,
                        "is_prerelease": is_pre
                    })

            if firmwares:
                try:
                    os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                    with open(self.cache_file, "w", encoding="utf-8") as f:
                        json.dump({"cache_version": 5, "etag": new_etag, "firmwares": firmwares}, f, indent=2)
                except Exception:
                    pass
                self.firmwares_loaded_signal.emit(firmwares)

        except urllib.error.HTTPError as e:
            if cached_firmwares:
                self.firmwares_loaded_signal.emit(cached_firmwares)
        except Exception:
            if cached_firmwares:
                self.firmwares_loaded_signal.emit(cached_firmwares)


class DownloadManagerMixin:
    def init_nx_firmware_list(self):
        try:
            appdata_dir = str(APPDATA_DIR)
        except Exception:
            appdata_dir = os.path.expanduser(
                "~/.config/TriCoreDownloader" if sys.platform != "win32" else "~\\AppData\\Roaming\\TriCoreDownloader"
            )

        os.makedirs(appdata_dir, exist_ok=True)
        self.nx_fw_cache_file = os.path.join(appdata_dir, "nx_firmwares_cache.json")

        if os.path.exists(self.nx_fw_cache_file):
            try:
                with open(self.nx_fw_cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    fws = cache_data.get("firmwares", [])
                    if fws:
                        self.populate_nx_firmware_list(fws)
            except Exception:
                pass

        self.nx_fw_thread = NxFirmwareListThread(self.nx_fw_cache_file)
        self.nx_fw_thread.firmwares_loaded_signal.connect(self.populate_nx_firmware_list)
        self.nx_fw_thread.start()

    def populate_nx_firmware_list(self, firmwares):
        if not hasattr(self, "combo_nx_fw") or not firmwares:
            return
        current_data = self.combo_nx_fw.currentData()
        self.combo_nx_fw.blockSignals(True)
        self.combo_nx_fw.clear()

        for fw in firmwares:
            raw_title = fw.get("raw_title") or fw.get("title", "")
            tag_name = fw.get("tag_name", "")
            is_pre = fw.get("is_prerelease", False)

            if "cartridge" in raw_title.lower() or "cartridge" in tag_name.lower():
                continue
            m_ver = RE_VER.search(raw_title) or RE_VER.search(tag_name)
            if m_ver and m_ver.group(1) in ["1.0.0", "8.1.1"]:
                continue
            if fw.get("build_version") == "8.1.1.0030":
                continue

            display_title = format_fw_display_title(raw_title, tag_name, is_prerelease=is_pre)
            self.combo_nx_fw.addItem(display_title, user_data=fw["build_version"])

        if current_data:
            idx = self.combo_nx_fw.findData(current_data)
            if idx >= 0:
                self.combo_nx_fw.setCurrentIndex(idx)
        self.combo_nx_fw.blockSignals(False)

    def append_log(self, text):
        if hasattr(self, "console"):
            self.console.appendPlainText(text)
            sb = self.console.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())
        if self.config.get("advanced_logs", False) and sys.__stderr__ is not None:
            try:
                print(text, file=sys.__stderr__)
            except Exception:
                pass

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
        sb = self.console.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def update_progress(self, current, total):
        if hasattr(self, "progress_bar"):
            if self.progress_bar.maximum() != total:
                self.progress_bar.setMaximum(total)
            if self.progress_bar.value() != current:
                self.progress_bar.setValue(current)

        if hasattr(self, "lbl_progress_pct"):
            pct = int((current / total) * 100) if total > 0 else 0
            if getattr(self, "_last_rendered_pct", None) != pct:
                self._last_rendered_pct = pct
                self.lbl_progress_pct.setText(f"{pct}%")

    def show_centered_msg(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(35, 20, 35, 25)
        layout.setSpacing(16)

        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setFixedWidth(380)
        lbl.setStyleSheet("line-height: 22px; font-size: 10.5pt;")
        layout.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn = QPushButton(self.T("btn_ok", "OK"))
        btn.setFixedWidth(140)
        btn.setMinimumHeight(36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(dialog.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        dialog.adjustSize()
        dialog.exec()

    def handle_overwrite_prompt(self, version):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("overwrite_title"))
        msg_box.setText(self.T("overwrite_msg").format(version))
        btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
        msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
        msg_box.exec()

        if getattr(self, "worker", None) is not None and hasattr(self.worker, "receive_overwrite_choice"):
            choice = (msg_box.clickedButton() == btn_yes)
            self.worker.receive_overwrite_choice(choice)

    def handle_skip_prompt(self, title_id):
        if getattr(self, "_always_skip_404", False):
            if getattr(self, "worker", None) is not None and hasattr(self.worker, "receive_skip_choice"):
                try:
                    self.worker.receive_skip_choice(True, True)
                except TypeError:
                    self.worker.receive_skip_choice(True)
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("skip_404_title", "Titre manquant"))
        msg_box.setText(self.T("skip_404_msg").format(title_id))

        btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
        btn_always_yes = msg_box.addButton(self.T("btn_always_yes"), QMessageBox.ButtonRole.ActionRole)
        btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)

        msg_box.setDefaultButton(btn_no)
        msg_box.exec()

        clicked_btn = msg_box.clickedButton()
        always = False
        if clicked_btn == btn_always_yes:
            self._always_skip_404 = True
            choice = True
            always = True
        else:
            choice = (clicked_btn == btn_yes)

        if getattr(self, "worker", None) is not None and hasattr(self.worker, "receive_skip_choice"):
            try:
                self.worker.receive_skip_choice(choice, always)
            except TypeError:
                self.worker.receive_skip_choice(choice)

    def perform_security_cleanup(self):
        root = os.path.dirname(os.path.abspath(sys.argv[0]))
        files_to_purge = ["switch_client.crt", "switch_client.key"]
        dirs_to_purge = ["temp_dl"]

        for f in files_to_purge:
            p = os.path.join(root, f)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        for d in dirs_to_purge:
            p = os.path.join(root, d)
            if os.path.exists(p):
                try:
                    shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass

        if hasattr(self, "keys_dir") and os.path.exists(self.keys_dir):
            try:
                shutil.rmtree(self.keys_dir, ignore_errors=True)
            except Exception:
                pass

        try:
            appdata_dir = str(APPDATA_DIR)
            temp_updater_path = os.path.join(appdata_dir, "TempUpdater.py")
            if os.path.exists(temp_updater_path):
                os.remove(temp_updater_path)
        except Exception:
            pass

    def _cleanup_previous_worker(self):
        if getattr(self, "worker", None) is not None:
            try:
                if self.worker.isRunning():
                    self.worker.stop()
                    self.worker.wait(1000)
                self.worker.deleteLater()
            except Exception:
                pass
            self.worker = None

    def _log_advanced_environment_header(self):
        if not self.config.get("advanced_logs", False):
            return
        if self.config.get("console_mode", "NX") == "NX":
            return
        if hasattr(self, "get_runtime_env_summary"):
            try:
                os_name, arch_name, build_edition, py_edition = self.get_runtime_env_summary()
                self.append_log("==================================================")
                self.append_log(self.T("log_adv_banner_pre"))
                self.append_log("==================================================")
                self.append_log(self.T("log_env_hw"))
                self.append_log(self.T("log_env_os").format(os_name))
                self.append_log(self.T("log_env_plat").format(platform.platform()))
                self.append_log(self.T("log_env_arch").format(f"{arch_name} ({platform.architecture()[0]})"))
                self.append_log(self.T("log_env_mode").format(f"{build_edition} ({py_edition})"))
                self.append_log(self.T("log_env_py").format(f"{platform.python_version()} ({py_edition})"))
                self.append_log(self.T("log_env_outdir").format(self.config.get("output_dir", "NOT SET")))
                self.append_log("==================================================\n")
            except Exception:
                pass

    def setup_ui_for_download(self):
        self.set_ui_locked(True)
        self.console.clear()
        self.progress_bar.setValue(0)
        self.lbl_progress_pct.setText("0%")
        self._last_rendered_pct = 0
        self.btn_action.setText(self.T("btn_stop"))
        self.btn_action.setObjectName("btnStop")
        self.btn_action.style().unpolish(self.btn_action)
        self.btn_action.style().polish(self.btn_action)

        if hasattr(self, "symbol_reset_timer"):
            self.symbol_reset_timer.stop()

        self.spinner_idx = 0
        self.spinner_timer.start(100)
        self._always_skip_404 = False
        self._log_advanced_environment_header()

    def connect_worker_and_start(self):
        if not getattr(self, "worker", None):
            return

        try:
            self.worker.log_signal.connect(self.append_log)
            self.worker.log_replace_signal.connect(self.replace_last_log)
            self.worker.progress_signal.connect(self.update_progress)

            if hasattr(self.worker, "ask_overwrite_signal"):
                self.worker.ask_overwrite_signal.connect(self.handle_overwrite_prompt)
            if hasattr(self.worker, "ask_skip_signal"):
                self.worker.ask_skip_signal.connect(self.handle_skip_prompt)

            self.worker.finished_signal.connect(self.on_download_finished)
            self.worker.start()

        except Exception:
            err_txt = self.T("err_worker_init", "Échec de l'initialisation du processus de téléchargement.")
            error_msg = f"\n[!] {err_txt}\n{traceback.format_exc()}"
            if hasattr(self, "console"):
                self.console.appendPlainText(error_msg)
            self.on_download_finished(False, err_txt)

    def toggle_download(self):
        if getattr(self, "_is_toggling", False):
            return

        self._is_toggling = True
        QTimer.singleShot(500, lambda: setattr(self, "_is_toggling", False))

        mode = self.config.get("console_mode", "NX")

        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            self.append_log(f"\n[!] {self.T('btn_stop')} ...")
            self.worker.stop()
            self.btn_action.setEnabled(False)

            self.audio.play_stop(self.current_console)

            self.spinner_timer.stop()
            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CROSS_SVG).scaled(
                    18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)
            return

        out_dir = self.input_output.text().strip() if hasattr(self, "input_output") else self.config.get("output_dir", "")
        if out_dir and not os.path.exists(out_dir):
            if not self.verify_and_create_export_folder(out_dir):
                self.audio.play_result(self.current_console, False)
                self.switch_tab_animated(1)
                return

        if hasattr(self, "input_output"):
            self.config["output_dir"] = out_dir
            self.config[f"output_dir_{mode.lower()}"] = out_dir

        if mode == "NX":
            if hasattr(self, "input_hactool"):
                self.config["hactool"] = self.input_hactool.text().strip()
            if hasattr(self, "input_keys"):
                self.config["prod_keys"] = self.input_keys.text().strip()
            if hasattr(self, "input_prodinfo"):
                self.config["prodinfo"] = self.input_prodinfo.text().strip()
        elif mode == "CTR":
            if hasattr(self, "input_boot9"):
                self.config["boot9_path"] = self.input_boot9.text().strip()
            if hasattr(self, "chk_ctr_decrypt"):
                self.config["decrypt_cia"] = self.chk_ctr_decrypt.isChecked()
        elif mode == "CAFE":
            if hasattr(self, "input_otp"):
                self.config["otp_path"] = self.input_otp.text().strip()

        if mode == "NX":
            version = ""
            if hasattr(self, "radio_group"):
                if hasattr(self, "radio_manual") and self.radio_manual.isChecked():
                    version = self.input_manual.text().strip()
                    if not RE_NX_VER.match(version):
                        self.audio.play_result(self.current_console, False)
                        self.show_centered_msg(self.T("err_format_title"), self.T("err_format_msg"))
                        return
                elif hasattr(self, "radio_list") and self.radio_list.isChecked():
                    if hasattr(self, "combo_nx_fw"):
                        version = self.combo_nx_fw.currentData() or ""
                    if not version or not RE_NX_VER.match(version):
                        self.audio.play_result(self.current_console, False)
                        self.show_centered_msg(self.T("msg_error_title"), self.T("err_no_fw_selected"))
                        return

            req = ["hactool", "prod_keys", "prodinfo", "output_dir"]
            label_map = {"hactool": "lbl_hactool", "prod_keys": "lbl_keys", "prodinfo": "lbl_prodinfo", "output_dir": "lbl_out"}
            errs = [
                f"  {self.T(label_map[k])}"
                for k in req
                if not self.config.get(k, "").strip() or not os.path.exists(self.config.get(k, "").strip())
            ]

            if errs:
                self.audio.play_result(self.current_console, False)
                err_text = self.T("msg_err_cfg") + "\n" + "\n".join(errs)
                self.show_centered_msg(self.T("msg_error_title"), err_text)
                self.switch_tab_animated(1)
                return

            self.setup_ui_for_download()
            self.audio.play_start_sequence(self.current_console)
            self._cleanup_previous_worker()

            try:
                self.worker = DownloaderWorker(version, self.config.copy())
                self.connect_worker_and_start()
            except Exception:
                err_txt = self.T("err_worker_nx", "Échec de l'initialisation du moteur Switch (NX).")
                error_msg = f"\n[!] {err_txt}\n{traceback.format_exc()}"
                if hasattr(self, "console"):
                    self.console.appendPlainText(error_msg)
                self.on_download_finished(False, err_txt)

        elif mode == "CAFE":
            if not out_dir or not os.path.exists(out_dir):
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
                if not RE_CAFE_VER.match(target_fw):
                    self.audio.play_result(self.current_console, False)
                    self.show_centered_msg(self.T("err_format_title"), self.T("err_format_msg_cafe"))
                    return

                region_char = target_fw[-1]
                if region_char == "E":
                    region = "EUR"
                elif region_char == "U":
                    region = "USA"
                elif region_char == "J":
                    region = "JPN"
            else:
                if self.radio_usa.isChecked():
                    region = "USA"
                elif self.radio_jpn.isChecked():
                    region = "JPN"
                else:
                    region = "EUR"

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
            is_key_valid = (RE_HEX32.match(otp_key) is not None) if not force_prompt else False

            if is_file:
                try:
                    if os.path.getsize(otp_path) == 0:
                        is_file = False
                except Exception:
                    is_file = False

            if is_file:
                otp_input = otp_path
                is_key = False
            elif is_key_valid:
                otp_input = otp_key
                is_key = True
            else:
                title = self.T("title_input_otp")
                msg = self.T("msg_input_otp")
                chk_txt = self.T("chk_remember_key")
                btn_ok_txt = self.T("btn_ok")
                btn_cancel_txt = self.T("btn_cancel")

                while True:
                    dialog = OtpInputDialog(self, title, msg, chk_txt, btn_ok_txt, btn_cancel_txt, otp_key)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        key, remember = dialog.get_data()
                        if RE_HEX32.match(key):
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
                            self.audio.play_result(self.current_console, False)
                            self.show_centered_msg(self.T("msg_error_title"), self.T("err_invalid_key"))
                    else:
                        self.audio.play_result(self.current_console, False)
                        return

            if self.radio_mlc.isChecked():
                partitions = ["MLC"]
            elif self.radio_slc.isChecked():
                partitions = ["SLC"]
            else:
                partitions = ["MLC", "SLC"]

            self.config["cafe_partitions"] = partitions
            self.config["cafe_region"] = region
            self.setup_ui_for_download()
            self.audio.play_start_sequence(self.current_console)

            if self.config.get("advanced_logs", False):
                self.append_log(self.T("log_mode_cafe"))
                self.append_log(self.T("log_target_region").format(region))
                self.append_log(self.T("log_target_parts").format(" + ".join(partitions)))
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

            self._cleanup_previous_worker()

            try:
                self.worker = CafeDownloaderWorker(region, worker_config)
                self.connect_worker_and_start()
            except Exception:
                err_txt = self.T("err_worker_cafe", "Échec de l'initialisation du moteur Wii U (CAFE).")
                error_msg = f"\n[!] {err_txt}\n{traceback.format_exc()}"
                if hasattr(self, "console"):
                    self.console.appendPlainText(error_msg)
                self.on_download_finished(False, err_txt)

        elif mode == "CTR":
            if not out_dir or not os.path.exists(out_dir):
                self.audio.play_result(self.current_console, False)
                errs = [f"  {self.T('lbl_out')}"]
                err_text = self.T("msg_err_cfg") + "\n" + "\n".join(errs)
                self.show_centered_msg(self.T("msg_error_title"), err_text)
                self.switch_tab_animated(1)
                return

            is_new_3ds = bool(hasattr(self, "radio_new_3ds") and self.radio_new_3ds.isChecked())
            self.config["ctr_model"] = "NEW" if is_new_3ds else "OLD"

            if hasattr(self, "radio_ctr_usa") and self.radio_ctr_usa.isChecked():
                self.config["ctr_region"] = "USA"
            elif hasattr(self, "radio_ctr_jpn") and self.radio_ctr_jpn.isChecked():
                self.config["ctr_region"] = "JPN"
            elif hasattr(self, "radio_ctr_aus") and self.radio_ctr_aus.isChecked():
                self.config["ctr_region"] = "AUS"
            elif hasattr(self, "radio_ctr_kor") and self.radio_ctr_kor.isChecked():
                self.config["ctr_region"] = "KOR"
            elif hasattr(self, "radio_ctr_chn") and self.radio_ctr_chn.isChecked():
                self.config["ctr_region"] = "CHN"
            elif hasattr(self, "radio_ctr_twn") and self.radio_ctr_twn.isChecked():
                self.config["ctr_region"] = "TWN"
            else:
                self.config["ctr_region"] = "EUR"

            target_fw = "LATEST"
            if hasattr(self, "radio_group") and self.radio_group.checkedButton() != getattr(self, "radio_latest", None):
                raw_manual_fw = self.input_manual.text().strip().upper()
                m_ctr = RE_CTR_VER.match(raw_manual_fw)
                if not m_ctr:
                    self.audio.play_result(self.current_console, False)
                    self.show_centered_msg(self.T("err_format_title"), self.T("err_format_msg_ctr"))
                    return
                target_fw = m_ctr.group(1)
                suffix_letter = m_ctr.group(2)
                if suffix_letter:
                    letter_map = {"U": "USA", "J": "JPN", "K": "KOR", "C": "CHN", "T": "TWN", "A": "AUS", "E": "EUR"}
                    if suffix_letter in letter_map and not (suffix_letter == "E" and self.config["ctr_region"] == "AUS"):
                        self.config["ctr_region"] = letter_map[suffix_letter]

            self.setup_ui_for_download()
            self.audio.play_start_sequence(self.current_console)

            if self.config.get("advanced_logs", False):
                self.append_log(self.T("log_mode_ctr"))
                model_str = "New 3DS / 2DS" if is_new_3ds else "Old 3DS / 2DS"
                self.append_log(self.T("log_target_model").format(model_str))
                self.append_log(self.T("log_target_fw").format(target_fw))
            else:
                self.append_log(self.T("log_latest_dl"))

            self._cleanup_previous_worker()

            worker_config = self.config.copy()
            try:
                self.worker = CtrDownloaderWorker(target_fw, is_new_3ds, worker_config)
                self.connect_worker_and_start()
            except Exception:
                err_txt = self.T("err_worker_ctr", "Échec de l'initialisation du moteur 3DS (CTR).")
                error_msg = f"\n[!] {err_txt}\n{traceback.format_exc()}"
                if hasattr(self, "console"):
                    self.console.appendPlainText(error_msg)
                self.on_download_finished(False, err_txt)

    def open_export_folder(self, folder_path):
        if folder_path and os.path.exists(folder_path):
            try:
                if sys.platform == "win32":
                    os.startfile(folder_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder_path])
                else:
                    subprocess.Popen(["xdg-open", folder_path])
            except Exception as e:
                if sys.__stderr__ is not None:
                    print(f"[DOWNLOADER ERROR] Failed to open folder: {e}", file=sys.__stderr__)

    def on_download_finished(self, success, message):
        is_crypto_failure = False
        if not success and self.current_console == "CAFE" and message:
            msg_upper = str(message).upper()
            translated_err = self.T("err_common_key_invalid").upper()

            if "ERR_COMMON_KEY_INVALID" in msg_upper or "ERR_COMMON_KEY_FORMAT" in msg_upper:
                is_crypto_failure = True
            elif translated_err in msg_upper:
                is_crypto_failure = True
            elif "DECRYPTION CHALLENGE" in msg_upper or "HEURISTIC" in msg_upper:
                is_crypto_failure = True

        if is_crypto_failure:
            self.set_ui_locked(False)
            self.btn_action.setEnabled(True)
            self.btn_action.setText(self.T("btn_start"))
            self.btn_action.setObjectName("btnDownload")
            self.btn_action.style().unpolish(self.btn_action)
            self.btn_action.style().polish(self.btn_action)
            self.perform_security_cleanup()
            self.spinner_timer.stop()

            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CROSS_SVG).scaled(
                    18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)

            if hasattr(self, "progress_bar"):
                self.progress_bar.setValue(0)
            if hasattr(self, "lbl_progress_pct"):
                self.lbl_progress_pct.setText("0%")
            self._last_rendered_pct = 0

            self.config["otp_key"] = ""
            self.config["otp_path"] = ""
            save_config(self.config)

            if hasattr(self, "input_otp"):
                self.input_otp.clear()

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
            self.audio.play_result(self.current_console, True)

            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CHECK_SVG).scaled(
                    18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)

            mode_lower = self.current_console.lower()
            ask_key = f"ask_open_folder_{mode_lower}"
            auto_key = f"auto_open_folder_{mode_lower}"
            msg_desc_key = f"msg_open_folder_desc_{self.current_console}"
            target_open_dir = self.config.get("output_dir") or (message if message and os.path.isdir(str(message)) else "")

            if self.config.get(ask_key, True):
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
                    self.open_export_folder(target_open_dir)
            else:
                if self.config.get(auto_key, False):
                    self.open_export_folder(target_open_dir)
                else:
                    self.show_centered_msg(self.T("msg_success_title"), self.T("msg_success"))
        else:
            if hasattr(self, "lbl_dl_mode"):
                pixmap = self.get_svg_icon(CROSS_SVG).scaled(
                    18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.lbl_dl_mode.setPixmap(pixmap)
                self.symbol_reset_timer.start(10000)

            if hasattr(self, "progress_bar"):
                self.progress_bar.setValue(0)
            if hasattr(self, "lbl_progress_pct"):
                self.lbl_progress_pct.setText("0%")
            self._last_rendered_pct = 0

            msg_incomplete = self.T("err_incomplete_msg")

            if message == "INCOMPLETE_FIRMWARE" or message == msg_incomplete:
                self.audio.play_result(self.current_console, False)
                self.show_centered_msg(self.T("err_incomplete_title"), msg_incomplete)

            elif message != "STOPPED" and message != self.T("msg_aborted") and message != "Annulé proprement.":
                self.audio.play_result(self.current_console, False)

                if self.current_console == "CAFE" and "OTP" in str(message).upper():
                    otp_key = self.config.get("otp_key", "").strip()
                    if not getattr(self, "_fallback_key_used", False) and RE_HEX32.match(otp_key):
                        self._ignore_otp_file_once = True
                        self._fallback_key_used = True
                        QTimer.singleShot(100, self.toggle_download)
                        return

                    self._fallback_key_used = False
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle(self.T("msg_fail_title"))
                    msg_box.setText(self.T("msg_aborted") + f"\n\n{self.T('msg_tech_err')} {message}")
                    msg_box.addButton(self.T("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
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
