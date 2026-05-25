import os
import subprocess
from struct import unpack
from binascii import hexlify
from glob import glob
import shutil

SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}

class SwitchCore:
    def __init__(self, config, device_id, env, user_agent, log_adv_callback, tr_callback):
        self.config = config
        self.device_id = device_id
        self.env = env
        self.user_agent = user_agent
        self.log_adv = log_adv_callback
        self.T = tr_callback
        print("[SWITCH CORE] Initialized SwitchCore engine.")

    @staticmethod
    def readdata(f, addr, size): 
        f.seek(addr)
        return f.read(size)
        
    @staticmethod
    def readshort(f, addr=None):
        if addr is not None: f.seek(addr)
        return unpack("<H", f.read(2))[0]
        
    @staticmethod
    def hexify(s): 
        return hexlify(s).decode("utf-8")
        
    @staticmethod
    def ihexify(n, b): 
        return hex(n)[2:].zfill(b * 2)

    def parse_cnmt(self, nca_path, raw_dir):
        ncaf = os.path.basename(nca_path)
        self.log_adv(self.T("log_parse_cnmt").format(ncaf))
        print(f"[SWITCH CORE] Parsing CNMT NCA: {ncaf}")
        cnmt_temp_dir = os.path.join(raw_dir, f"cnmt_tmp_{ncaf}")
        
        hactool_bin = self.config.get("hactool", "hactool.exe" if os.name == "nt" else "./hactool")
        cmd = [hactool_bin, "-k", self.config["prod_keys"], nca_path, "--section0dir", cnmt_temp_dir]
        
        cmd_str = " ".join(cmd)
        self.log_adv(self.T("log_exec_cmd").format(cmd_str))
        print(f"[SWITCH CORE] Executing hactool: {cmd_str}")
        
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SUBPROCESS_FLAGS)
        
        if res.returncode != 0 and not os.path.exists(cnmt_temp_dir): 
            err_msg_raw = res.stderr.decode(errors="ignore") if res.stderr else "Unknown error"
            filtered_err_lines = [line for line in err_msg_raw.split("\n") if "[WARN]: Failed to match key" not in line]
            print(f"[SWITCH CORE ERROR] Hactool execution failed: {err_msg_raw}")
            raise RuntimeError(self.T("err_hactool").format(chr(10).join(filtered_err_lines).strip()))

        cnmt_files = glob(f"{cnmt_temp_dir}/*.cnmt")
        if not cnmt_files: 
            err_msg = self.T("log_err_cnmt_missing").format(ncaf)
            print(f"[SWITCH CORE ERROR] No CNMT files found in extracted directory for {ncaf}")
            raise RuntimeError(err_msg)

        entries = []
        with open(cnmt_files[0], "rb") as c:
            c_type = self.readdata(c, 0xc, 1)
            self.log_adv(self.T("log_val_cnmt_hdr").format(f"{c_type[0]:#04x}"))
            
            if c_type[0] == 0x3:
                n_entries, offset = self.readshort(c, 0x12), self.readshort(c, 0xe)
                self.log_adv(self.T("log_su_meta").format(n_entries, f"{offset:#06x}"))
                base = 0x20 + offset
                for i in range(n_entries):
                    c.seek(base + i * 0x10)
                    title_id, version = unpack("<Q", c.read(8))[0], unpack("<I", c.read(4))[0]
                    entries.append((self.ihexify(title_id, 8), version))
            else:
                n_entries, offset = self.readshort(c, 0x10), self.readshort(c, 0xe)
                self.log_adv(self.T("log_co_meta").format(n_entries, f"{offset:#06x}"))
                base = 0x20 + offset
                for i in range(n_entries):
                    c.seek(base + i * 0x38)
                    h, nid = c.read(32), self.hexify(c.read(16))
                    entries.append((nid, self.hexify(h)))
        
        shutil.rmtree(cnmt_temp_dir, ignore_errors=True)
        print(f"[SWITCH CORE] Successfully parsed {len(entries)} entries from CNMT.")
        return entries