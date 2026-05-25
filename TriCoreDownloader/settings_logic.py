import os
import sys
import random
import subprocess
from shutil import which
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QFileDialog, QDialog, QVBoxLayout, QLabel, QCheckBox, QHBoxLayout, QPushButton, QApplication
from PyQt6.QtCore import Qt, QTimer, QLocale

from .config import CONFIG_FILE, EULA_FILE, save_config
from .custom_widgets import AutoCloseDialog

class SettingsMixin:
    def show_aria_info_popup(self, checked):
        if checked and not getattr(self, "_is_loading_ui", True):
            print("[SETTINGS] Displaying Aria2c info popup.")
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("msg_aria_info_title"))
            msg_box.setText(self.T("msg_aria_info_desc"))
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.addButton(self.T("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()

    def on_aria_toggle(self, checked):
        print(f"[SETTINGS] Aria2c usage toggled: {checked}")
        self.trigger_auto_save()

    def on_adv_mode_toggle(self, checked):
        print(f"[SETTINGS] Advanced mode toggled: {checked}")
        if not checked:
            self._is_loading_ui = True
            self.chk_adv_logs.setChecked(False)
            self.chk_use_aria2c.setChecked(False)
            self.chk_resize.setChecked(False)
            if hasattr(self, "chk_exfat"): self.chk_exfat.setChecked(False)
            if hasattr(self, "chk_hide_warn"): self.chk_hide_warn.setChecked(False)
            if hasattr(self, "chk_cafe_extract"): self.chk_cafe_extract.setChecked(False)
            if hasattr(self, "chk_cemu_layout"): self.chk_cemu_layout.setChecked(False)
            self._is_loading_ui = False
            
            print("[SETTINGS] Automatically disabled advanced sub-options.")
            self.on_adv_logs_toggle(False)
            self.on_aria_toggle(False)
            
        self.trigger_auto_save()

    def suggest_export_folder(self):
        base_dir = Path(sys.argv[0]).resolve().parent
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX"))
        
        folders = {
            "NX": ["NX_Firmware", "NX_Updates", "NX", "Switch1", "Daybreak", "NCAs", "NX_CDN", "NX_Stock_FW"],
            "CAFE": ["Cafe_Firmware", "Cafe_Updates", "Cafe", "WiiU", "ISFSHax", "wafel_install", "CAFE_NUS", "CAFE_Stock_FW"],
            "CTR": ["CTR_Firmware", "CTR_Updates", "CTR", "3DS", "sysUpdater", "CIAs", "CTR_NUS", "CTR_Stock_FW"]
        }
        
        names = folders.get(mode, ["Firmwares"])
        current_path = self.input_output.text().strip()
        suggested_path = current_path
        
        for _ in range(10):
            suggested_path = str(base_dir / random.choice(names))
            if suggested_path != current_path:
                break
                
        print(f"[SETTINGS] Suggested new export folder: {suggested_path}")
        self.input_output.setText(suggested_path)
        self.trigger_auto_save()

    def on_output_dir_changed(self, text):
        print(f"[SETTINGS] Output directory changed to: {text}")
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).lower()
        self.config[f"output_dir_{mode}"] = text
        self.config["output_dir"] = text

    def verify_and_create_export_folder(self, out_dir):
        if not out_dir: 
            return True 
        
        out_path = Path(out_dir)
        if not out_path.exists():
            print(f"[SETTINGS] Export folder does not exist: {out_path}")
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("folder_not_found_title"))
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setTextFormat(Qt.TextFormat.RichText)
            
            breakable_path = str(out_path).replace("\\", "\\\u200b").replace("/", "/\u200b")
            path_display = f"<br><br><code style='color: #4da8da;'>{breakable_path}</code><br><br>"
            texte_formate = self.T("folder_not_found_msg").format(path_display)
            msg_box.setText(f"<div style='width: 420px;'>{texte_formate}</div>")
            
            btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
            btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
            msg_box.setDefaultButton(btn_yes)
            msg_box.exec()
            
            if msg_box.clickedButton() == btn_yes:
                try:
                    out_path.mkdir(parents=True, exist_ok=True)
                    print(f"[SETTINGS] Successfully created export folder: {out_path}")
                    return True
                except Exception as e:
                    print(f"[SETTINGS ERROR] Failed to create folder: {e}")
                    QMessageBox.critical(self, self.T("msg_error_title"), f"{self.T('msg_folder_err')}\n{e}")
                    return False
            else: 
                print("[SETTINGS] User cancelled folder creation.")
                return False 
        return True

    def on_adv_logs_toggle(self, checked):
        print(f"[SETTINGS] Advanced logs toggled: {checked}")
        if not checked:
            self._is_loading_ui = True
            self.chk_hide_warn.setChecked(False)
            self.config["redact_privacy_info"] = False
            self._is_loading_ui = False
        self.trigger_auto_save()
        
    def on_hide_warn_toggle(self, checked):
        print(f"[SETTINGS] Privacy warning toggle clicked: {checked}")
        if checked and not getattr(self, "_is_loading_ui", True):
            dialog = QDialog(self)
            dialog.setWindowTitle(self.T("hide_warn_title"))
            dialog.setMinimumWidth(500)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(16)
            
            lbl_msg = QLabel(self.T("hide_warn_msg"))
            lbl_msg.setWordWrap(True)
            layout.addWidget(lbl_msg)
            
            cb_redact = QCheckBox(self.T("chk_redact_logs"))
            cb_redact.setChecked(self.config.get("redact_privacy_info", False))
            layout.addWidget(cb_redact)
            
            btn_yes, btn_no = QPushButton(self.T("btn_yes")), QPushButton(self.T("btn_no"))
            btn_yes.clicked.connect(dialog.accept)
            btn_no.clicked.connect(dialog.reject)
            
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_layout.addWidget(btn_yes)
            btn_layout.addWidget(btn_no)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.config["redact_privacy_info"] = cb_redact.isChecked()
                print(f"[SETTINGS] Privacy options accepted. Redact: {cb_redact.isChecked()}")
            else:
                print("[SETTINGS] Privacy options rejected. Reverting toggle.")
                self._is_loading_ui = True
                self.chk_hide_warn.setChecked(False)
                self.config["redact_privacy_info"] = False
                self._is_loading_ui = False
        elif not checked and not getattr(self, "_is_loading_ui", True):
            self.config["redact_privacy_info"] = False
        self.trigger_auto_save()

    def on_exfat_toggle(self, checked):
        print(f"[SETTINGS] exFAT filter toggled: {checked}")
        if checked and not getattr(self, "_is_loading_ui", True):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("exfat_warn_title"))
            msg_box.setText(self.T("exfat_warn_msg"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
            btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
            msg_box.setDefaultButton(btn_no)
            msg_box.exec()
            
            if msg_box.clickedButton() == btn_no:
                print("[SETTINGS] exFAT warning cancelled by user.")
                self._is_loading_ui = True
                self.chk_exfat.setChecked(False)
                self._is_loading_ui = False

    def browse_file(self, line_edit, expected_name):
        print(f"[SETTINGS] Opening file browser for expected file: {expected_name}")
        while True:
            file_path, _ = QFileDialog.getOpenFileName(self, self.T("dialog_select_file"))
            if not file_path: 
                print("[SETTINGS] File browsing cancelled.")
                break
            
            filename = Path(file_path).name
            if filename.lower() != expected_name.lower():
                print(f"[SETTINGS] Filename mismatch. Expected: {expected_name}, Got: {filename}")
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(self.T("warn_filename_title"))
                msg_box.setText(self.T("warn_filename_msg").format(expected_name, filename))
                msg_box.setIcon(QMessageBox.Icon.Question)
                msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
                btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
                msg_box.setDefaultButton(btn_no)
                msg_box.exec()
                if msg_box.clickedButton() == btn_no: 
                    continue
                
            line_edit.setText(os.path.normpath(file_path))
            print(f"[SETTINGS] File selected: {file_path}")
            break

    def browse_folder(self, line_edit):
        print("[SETTINGS] Opening directory browser.")
        folder_path = QFileDialog.getExistingDirectory(self, self.T("dialog_select_folder"))
        if folder_path: 
            line_edit.setText(os.path.normpath(folder_path))
            print(f"[SETTINGS] Directory selected: {folder_path}")

    def auto_detect_aria(self):
        print("[SETTINGS] Starting auto-detection for aria2c and openssl.")
        script_dir = Path(sys.argv[0]).resolve().parent
        aria_path = which("aria2c")
        
        if not aria_path and os.name == "nt":
            local_aria = script_dir / "aria2c.exe"
            if local_aria.is_file():
                aria_path = str(local_aria)
                
        ssl_path = which("openssl")
        if not ssl_path and os.name == "nt":
            local_ssl = script_dir / "openssl.exe"
            system_ssl = Path(r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe")
            
            if local_ssl.is_file():
                ssl_path = str(local_ssl)
            elif system_ssl.is_file():
                ssl_path = str(system_ssl)
        
        if aria_path: 
            self.input_aria2c.setText(os.path.abspath(aria_path))
            print(f"[SETTINGS] Detected aria2c at: {aria_path}")
        if ssl_path: 
            self.input_openssl.setText(os.path.abspath(ssl_path))
            print(f"[SETTINGS] Detected openssl at: {ssl_path}")
            
        self.trigger_auto_save()
        
        if not aria_path or not ssl_path:
            print("[SETTINGS] One or both external tools were not found during auto-detection.")
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.T("btn_auto_detect"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setTextFormat(Qt.TextFormat.RichText)
            if not aria_path and not ssl_path: msg_box.setText(self.T("msg_both_missing"))
            elif not aria_path: msg_box.setText(self.T("msg_aria_only_missing"))
            elif not ssl_path: msg_box.setText(self.T("msg_ssl_only_missing"))
            msg_box.exec()

    def reset_config(self):
        print("[SETTINGS] Reset configuration requested.")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.T("msg_reset_title"))
        msg_box.setText(self.T("msg_reset_warn"))
        msg_box.setIcon(QMessageBox.Icon.Question)
        btn_yes = msg_box.addButton(self.T("btn_yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = msg_box.addButton(self.T("btn_no"), QMessageBox.ButtonRole.NoRole)
        msg_box.setDefaultButton(btn_no)
        msg_box.exec()
        
        if msg_box.clickedButton() == btn_yes:
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                print("[SETTINGS] Shift modifier detected. Performing hard environment wipe.")
                
                if getattr(self, "save_timer", None) and self.save_timer.isActive():
                    self.save_timer.stop()
                
                self._is_loading_ui = True
                if hasattr(self, "chk_auto_save"):
                    self.chk_auto_save.blockSignals(True)
                    self.chk_auto_save.setChecked(False)

                try:
                    from . import config
                    config._HARD_RESET_LOCK = True
                except Exception as e:
                    print(f"[RESET WARN] Could not engage config lock: {e}")

                if hasattr(self, "config") and isinstance(self.config, dict):
                    self.config.clear()
                    self.config.update({
                        "version": "5.1.5",
                        "console_mode": "WELCOME",
                        "first_launch": True,
                        "theme": "auto"
                    })

                if getattr(self, "worker", None) and self.worker.isRunning(): 
                    self.worker.stop()
                
                for file_to_remove in [CONFIG_FILE, EULA_FILE]:
                    if isinstance(file_to_remove, Path) and file_to_remove.exists():
                        try: file_to_remove.unlink()
                        except: pass
                    elif isinstance(file_to_remove, str) and os.path.exists(file_to_remove):
                        try: os.remove(file_to_remove)
                        except: pass
                        
                if hasattr(self, "perform_security_cleanup"):
                    self.perform_security_cleanup()

                subprocess.Popen([sys.executable] + sys.argv)
                QApplication.quit()
                os._exit(0)
            else:
                print("[SETTINGS] Soft reset: Activating dynamic key scanning heuristic cleaner.")
                self._is_loading_ui = True
                
                path_keywords = ["path", "dir", "keys", "prodinfo", "hactool", "cert_pem"]
                for key in list(self.config.keys()):
                    if any(kw in key.lower() for kw in path_keywords):
                        self.config[key] = ""
                
                if hasattr(self, "input_hactool"): self.input_hactool.clear()
                if hasattr(self, "input_keys"): self.input_keys.clear()
                if hasattr(self, "input_prodinfo"): self.input_prodinfo.clear()
                if hasattr(self, "input_cert"): self.input_cert.clear()
                if hasattr(self, "input_aria2c"): self.input_aria2c.clear()
                if hasattr(self, "input_openssl"): self.input_openssl.clear()
                if hasattr(self, "input_output"): self.input_output.clear()
                if hasattr(self, "input_otp"): self.input_otp.clear()
                if hasattr(self, "input_boot9"): self.input_boot9.clear()
                
                self._is_loading_ui = False
                
                self.update_config_from_ui()
                self.commit_save_to_disk()

    def trigger_auto_save(self, *args):
        if getattr(self, "_is_loading_ui", True): 
            return
        
        self.update_config_from_ui()
        
        if not hasattr(self, "save_timer"):
            self.save_timer = QTimer(self)
            self.save_timer.setSingleShot(True)
            self.save_timer.timeout.connect(self.commit_save_to_disk)
        
        self.save_timer.start(20000)
        print("[SETTINGS] Auto-save timer started (20s).")

    def _get_fallback_language(self):
        try:
            from .Languages.locales import STRINGS
            if not STRINGS:
                print("[SETTINGS] No STRINGS found. Defaulting to 'en'.")
                return "en"
            
            sys_lang = QLocale.system().name()[:2].lower()
            if sys_lang in STRINGS:
                print(f"[SETTINGS] Fallback matched system locale: {sys_lang}")
                return sys_lang
            else:
                first_lang = list(STRINGS.keys())[0]
                print(f"[SETTINGS] Fallback defaulted to first available: {first_lang}")
                return first_lang
        except ImportError:
            print("[SETTINGS ERROR] Locale fallback crash. Defaulting to 'en'.")
            return "en"

    def update_config_from_ui(self):
        print("[SETTINGS] Updating configuration dictionary from UI elements.")
        out_dir = self.input_output.text().strip()
        
        self.config["hactool"] = self.input_hactool.text().strip()
        self.config["prod_keys"] = self.input_keys.text().strip()
        self.config["prodinfo"] = self.input_prodinfo.text().strip()
        self.config["cert_pem"] = self.input_cert.text().strip()
        
        if hasattr(self, "input_otp"):
            self.config["otp_path"] = self.input_otp.text().strip()
            
        mode = getattr(self, "current_console", self.config.get("console_mode", "NX")).lower()
        self.config[f"output_dir_{mode}"] = out_dir
        self.config["output_dir"] = out_dir

        self.config["advanced_mode"] = self.chk_adv_mode.isChecked()
        
        if not self.config["advanced_mode"]:
            self._is_loading_ui = True
            self.chk_adv_logs.setChecked(False)
            self.chk_use_aria2c.setChecked(False)
            self.chk_resize.setChecked(False)
            if hasattr(self, "chk_exfat"): self.chk_exfat.setChecked(False)
            if hasattr(self, "chk_hide_warn"): self.chk_hide_warn.setChecked(False)
            if hasattr(self, "chk_cafe_extract"): self.chk_cafe_extract.setChecked(False)
            if hasattr(self, "chk_cemu_layout"): self.chk_cemu_layout.setChecked(False)
            self._is_loading_ui = False
            
            self.config["advanced_logs"] = False
            self.config["use_aria2c"] = False
            self.config["allow_resize"] = False
            self.config["exclude_exfat"] = False
            self.config["hide_privacy_warning"] = False
            self.config["cafe_extract"] = False
            self.config["cafe_cemu_layout"] = False
        else:
            self.config["advanced_logs"] = self.chk_adv_logs.isChecked()
            self.config["use_aria2c"] = self.chk_use_aria2c.isChecked()
            self.config["allow_resize"] = self.chk_resize.isChecked()
            self.config["exclude_exfat"] = self.chk_exfat.isChecked()
            self.config["hide_privacy_warning"] = self.chk_hide_warn.isChecked()
            if hasattr(self, "chk_cafe_extract"):
                self.config["cafe_extract"] = self.chk_cafe_extract.isChecked()
            if hasattr(self, "chk_cemu_layout"):
                self.config["cafe_cemu_layout"] = self.chk_cemu_layout.isChecked()

        self.config["aria2c_path"] = self.input_aria2c.text().strip()
        self.config["openssl_path"] = self.input_openssl.text().strip()
        
        selected_lang = self.combo_lang.currentData()
        if selected_lang:
            self.config["lang"] = selected_lang
        else:
            self.config["lang"] = self._get_fallback_language()
        
        self.config["accent_color"] = getattr(self, "pending_color", self.config.get("accent_color", ""))
        self.config["rainbow_mode"] = self.chk_rainbow.isChecked()
        self.config["rainbow_speed"] = self.slider_speed.value()
        self.config["theme"] = ["auto", "light", "dark", "oled"][self.combo_theme.currentIndex()]

        if hasattr(self, "rainbow_target_cbs"):
            self.config["rainbow_targets"] = {k: cb.isChecked() for k, cb in self.rainbow_target_cbs.items()}

        if not getattr(self, "_is_loading_ui", True):
            self.retranslate_ui()
            if hasattr(self, "apply_visual_settings"):
                self.apply_visual_settings()
            self.update_dl_mode_label()
            self.lbl_sys_info.setVisible(self.config.get("advanced_logs", False))
            if hasattr(self, "apply_window_constraints"):
                self.apply_window_constraints()

    def commit_save_to_disk(self):
        print("[SETTINGS] Committing configuration save to disk.")
        out_dir = self.config.get("output_dir", "")
        if out_dir and not os.path.exists(out_dir):
            self.verify_and_create_export_folder(out_dir)
            
        save_config(self.config)