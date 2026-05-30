import os
import subprocess
from struct import unpack, pack
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
                    entries.append((self.ihexify(title_id, 8).lower(), version, None))
            else:
                n_entries, offset = self.readshort(c, 0x10), self.readshort(c, 0xe)
                self.log_adv(self.T("log_co_meta").format(n_entries, f"{offset:#06x}"))
                base = 0x20 + offset
                for i in range(n_entries):
                    c.seek(base + i * 0x38)
                    h, nid = c.read(32), self.hexify(c.read(16)).lower()
                    c.seek(base + i * 0x38 + 0x36)
                    entry_type = unpack("<B", c.read(1))[0]
                    
                    if entry_type == 6:
                        continue
                        
                    entries.append((nid, self.hexify(h).lower(), entry_type))
        
        shutil.rmtree(cnmt_temp_dir, ignore_errors=True)
        print(f"[SWITCH CORE] Successfully parsed {len(entries)} entries from CNMT.")
        return entries


class NSPRepacker:
    def __init__(self, out_path, file_map, log_callback=None, progress_callback=None):
        self.path = out_path
        self.file_map = file_map
        self.sorted_files = []
        self.expected_total_size = 0
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        
    def _sort_pfs0_order(self):
        order_list = []
        order_keys = ["tik", "cert", "meta_nca", 1, 3, 5, 4, 2]
        for key in order_keys:
            if key in self.file_map:
                items = self.file_map[key]
                if isinstance(items, list) and items:
                    order_list.extend(sorted(items, key=lambda x: os.path.basename(x)))
        self.sorted_files = order_list

    def repack(self):
        self._sort_pfs0_order()
        hd = self._gen_header()
        self.expected_total_size = len(hd) + sum(os.path.getsize(file) for file in self.sorted_files)
        
        if os.path.exists(self.path) and os.path.getsize(self.path) == self.expected_total_size:
            if self.log_callback: self.log_callback(f"[NSPRepacker] Target {self.path} already exists with correct size.")
            return self.path
            
        with open(self.path, 'wb') as outf:
            outf.write(hd)
            if self.log_callback: self.log_callback(f"[NSPRepacker] Header written. Total size expected: {self.expected_total_size} bytes.")
            total_files = len(self.sorted_files)
            
            for i, file in enumerate(self.sorted_files, 1):
                if self.log_callback: self.log_callback(f"[NSPRepacker] Packing {os.path.basename(file)} ({i}/{total_files})...")
                with open(file, 'rb') as inf:
                    while True:
                        buf = inf.read(4096 * 1024)
                        if not buf:
                            break
                        outf.write(buf)
                if self.progress_callback:
                    self.progress_callback(i, total_files)
                            
        return self.path

    def verify_integrity(self):
        try:
            if self.log_callback: self.log_callback("[NSPRepacker] Starting integrity verification...")
            with open(self.path, "rb") as f:
                magic = f.read(4)
                if magic != b'PFS0':
                    if self.log_callback: self.log_callback("[NSPRepacker] Verification failed: Bad magic.")
                    return False
                file_count = unpack('<I', f.read(4))[0]
                if file_count != len(self.sorted_files):
                    if self.log_callback: self.log_callback(f"[NSPRepacker] Verification failed: File count mismatch ({file_count} vs {len(self.sorted_files)}).")
                    return False
                string_table_size = unpack('<I', f.read(4))[0]
                f.read(4)
                header_size = 0x10 + (file_count * 0x18) + string_table_size
                remainder = 0x10 - (header_size % 0x10)
                if remainder == 0x10: remainder = 0
                header_size += remainder
                
                for i in range(file_count):
                    offset = unpack('<Q', f.read(8))[0]
                    size = unpack('<Q', f.read(8))[0]
                    f.read(4)
                    f.read(4)
                    if (header_size + offset + size) > self.expected_total_size:
                        if self.log_callback: self.log_callback(f"[NSPRepacker] Verification failed: Entry exceeds file size.")
                        return False
                        
                f.seek(0, 2)
                actual_size = f.tell()
                if actual_size != self.expected_total_size:
                    if self.log_callback: self.log_callback(f"[NSPRepacker] Verification failed: Size mismatch ({actual_size} vs {self.expected_total_size}).")
                    return False
                    
            if self.log_callback: self.log_callback("[NSPRepacker] Integrity verification passed.")
            return True
        except Exception as e:
            if self.log_callback: self.log_callback(f"[NSPRepacker] Verification crashed: {e}")
            return False
            
    def _gen_header(self):
        files_nb = len(self.sorted_files)
        string_table = b'\x00'.join(os.path.basename(file).encode('utf-8') for file in self.sorted_files) + b'\x00'
        header_size = 0x10 + files_nb * 0x18 + len(string_table)
        remainder = 0x10 - (header_size % 0x10)
        if remainder == 0x10: remainder = 0
        header_size += remainder
        
        file_sizes = [os.path.getsize(file) for file in self.sorted_files]
        file_offsets = [sum(file_sizes[:n]) for n in range(files_nb)]
        file_names_lengths = [len(os.path.basename(file).encode('utf-8')) + 1 for file in self.sorted_files]
        string_table_offsets = [sum(file_names_lengths[:n]) for n in range(files_nb)]
        
        header = b'PFS0'
        header += pack('<I', files_nb)
        header += pack('<I', len(string_table) + remainder)
        header += b'\x00\x00\x00\x00'
        for n in range(files_nb):
            header += pack('<Q', file_offsets[n])
            header += pack('<Q', file_sizes[n])
            header += pack('<I', string_table_offsets[n])
            header += b'\x00\x00\x00\x00'
        header += string_table
        header += remainder * b'\x00'
        return header