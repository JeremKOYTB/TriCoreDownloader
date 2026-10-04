import io
import math
import os
import random
import shutil
import subprocess
import sys
from struct import pack, unpack

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


class SwitchCore:

    def __init__(
        self, config, device_id, env, user_agent, log_adv_callback, tr_callback
    ):
        self.config = config
        self.device_id = device_id
        self.env = env
        self.user_agent = user_agent
        self.log_adv = log_adv_callback
        self.T = tr_callback
        print("[SWITCH CORE] Initialized SwitchCore engine.")

    @staticmethod
    def recover_rsa_private_key(n, e, d):
        k = d * e - 1
        t = (k & -k).bit_length() - 1
        r = k >> t

        cracked = False
        y = 0
        for _ in range(100):
            g = random.randrange(2, n - 1)
            y = pow(g, r, n)
            if y == 1 or y == n - 1:
                continue

            for _ in range(1, t):
                x = pow(y, 2, n)
                if x == 1:
                    cracked = True
                    break
                if x == n - 1:
                    break
                y = x

            if cracked:
                break

        if not cracked:
            raise RuntimeError("Mathematical factorization of the RSA key failed.")

        p = math.gcd(y - 1, n)
        q = n // p

        if p < q:
            p, q = q, p

        dp = d % (p - 1)
        dq = d % (q - 1)
        iqmp = pow(q, -1, p)

        public_numbers = rsa.RSAPublicNumbers(e, n)
        private_numbers = rsa.RSAPrivateNumbers(
            p=p,
            q=q,
            d=d,
            dmp1=dp,
            dmq1=dq,
            iqmp=iqmp,
            public_numbers=public_numbers,
        )
        return private_numbers.private_key(default_backend())

    @classmethod
    def extract_client_cert_and_key(cls, cal0_data, ssl_rsa_kek):
        cert_size = unpack("<I", cal0_data[0x0AD0:0x0AD4])[0]
        if cert_size == 0 or cert_size > 0x1000:
            raise ValueError(
                "Invalid certificate size. PRODINFO might be blank or wiped (e.g.,"
                " Incognito)."
            )

        cert_data = cal0_data[0x0AE0 : 0x0AE0 + cert_size]
        cert = x509.load_der_x509_certificate(cert_data, default_backend())

        pub_numbers = cert.public_key().public_numbers()
        n = pub_numbers.n
        e = pub_numbers.e

        ssl_ext_key = cal0_data[0x3AE0 : 0x3AE0 + 0x110]
        iv = ssl_ext_key[:0x10]
        encrypted_d = ssl_ext_key[0x10:]

        cipher = Cipher(
            algorithms.AES(ssl_rsa_kek), modes.CTR(iv), backend=default_backend()
        )
        decryptor = cipher.decryptor()
        decrypted_d_bytes = decryptor.update(encrypted_d) + decryptor.finalize()

        d = int.from_bytes(decrypted_d_bytes, "big")
        private_key = cls.recover_rsa_private_key(n, e, d)

        clean_key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        clean_cert = cert.public_bytes(serialization.Encoding.PEM)

        return clean_cert, clean_key

    @staticmethod
    def _extract_cnmt_from_pfs0(pfs0_bytes):
        total_len = len(pfs0_bytes)
        if total_len < 0x10 or pfs0_bytes[:4] != b"PFS0":
            return None

        num_files = unpack("<I", pfs0_bytes[4:8])[0]
        string_table_size = unpack("<I", pfs0_bytes[8:12])[0]
        str_table_start = 0x10 + num_files * 0x18
        header_size = str_table_start + string_table_size

        if total_len < header_size:
            return None

        str_table = pfs0_bytes[str_table_start:header_size]

        for i in range(num_files):
            entry_off = 0x10 + i * 0x18
            offset, size, str_off = unpack("<QQI", pfs0_bytes[entry_off : entry_off + 20])
            if str_off < string_table_size:
                null_pos = str_table.find(b"\x00", str_off)
                filename = (
                    str_table[str_off:null_pos].decode("utf-8", errors="ignore")
                    if null_pos != -1
                    else str_table[str_off:].decode("utf-8", errors="ignore")
                )
                if filename.endswith(".cnmt"):
                    data_start = header_size + offset
                    if data_start + size <= total_len:
                        return pfs0_bytes[data_start : data_start + size]
        return None

    def _parse_cnmt_bytes(self, c):
        c_type = c[0xC]
        self.log_adv(self.T("log_val_cnmt_hdr").format(f"{c_type:#04x}"))

        entries = []
        if c_type == 0x3:
            offset = unpack("<H", c[0xE:0x10])[0]
            n_entries = unpack("<H", c[0x12:0x14])[0]
            self.log_adv(self.T("log_su_meta").format(n_entries, f"{offset:#06x}"))
            base = 0x20 + offset
            for i in range(n_entries):
                entry_off = base + i * 0x10
                title_id, version = unpack("<QI", c[entry_off : entry_off + 12])
                entries.append((f"{title_id:016x}", version, None))
        else:
            offset = unpack("<H", c[0xE:0x10])[0]
            n_entries = unpack("<H", c[0x10:0x12])[0]
            self.log_adv(self.T("log_co_meta").format(n_entries, f"{offset:#06x}"))
            base = 0x20 + offset
            for i in range(n_entries):
                entry_off = base + i * 0x38
                entry_type = c[entry_off + 0x36]
                if entry_type == 6:
                    continue
                h = c[entry_off : entry_off + 32].hex()
                nid = c[entry_off + 32 : entry_off + 48].hex()
                entries.append((nid, h, entry_type))

        print(f"[SWITCH CORE] Successfully parsed {len(entries)} entries from CNMT.")
        return entries

    def parse_cnmt(self, nca_path, raw_dir):
        ncaf = os.path.basename(nca_path)
        self.log_adv(self.T("log_parse_cnmt").format(ncaf))
        print(f"[SWITCH CORE] Parsing CNMT NCA: {ncaf}")

        configured_hactool = self.config.get("hactool", "").strip()
        if configured_hactool:
            hactool_bin = configured_hactool
        else:
            default_bin = "hactool.exe" if sys.platform == "win32" else "hactool"
            hactool_bin = shutil.which(default_bin) or default_bin

        if sys.platform != "win32" and os.path.isfile(hactool_bin):
            try:
                st = os.stat(hactool_bin)
                if not (st.st_mode & 0o111):
                    os.chmod(hactool_bin, st.st_mode | 0o111)
            except OSError:
                pass

        temp_sec0 = os.path.join(raw_dir, f"_sec0_{ncaf}.tmp")

        cmd = [
            hactool_bin,
            "-k",
            self.config["prod_keys"],
            nca_path,
            f"--section0={temp_sec0}",
        ]

        try:
            res = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SUBPROCESS_FLAGS
            )

            if not os.path.exists(temp_sec0) or os.path.getsize(temp_sec0) == 0:
                err_msg_raw = (
                    res.stderr.decode(errors="ignore") if res.stderr else "Unknown error"
                )
                filtered_err_lines = [
                    line
                    for line in err_msg_raw.split("\n")
                    if "[WARN]: Failed to match key" not in line
                ]
                print(f"[SWITCH CORE ERROR] Hactool execution failed: {err_msg_raw}")
                raise RuntimeError(
                    self.T("err_hactool").format("\n".join(filtered_err_lines).strip())
                )

            with open(temp_sec0, "rb") as f:
                pfs0_bytes = f.read()

            cnmt_bytes = self._extract_cnmt_from_pfs0(pfs0_bytes)
            if not cnmt_bytes:
                err_msg = self.T("log_err_cnmt_missing").format(ncaf)
                print(f"[SWITCH CORE ERROR] No CNMT data found in PFS0 for {ncaf}")
                raise RuntimeError(err_msg)

            return self._parse_cnmt_bytes(cnmt_bytes)
        finally:
            if os.path.exists(temp_sec0):
                try:
                    os.remove(temp_sec0)
                except OSError:
                    pass


class NSPRepacker:

    def __init__(
        self, out_path, file_map, log_callback=None, progress_callback=None
    ):
        self.path = out_path
        self.file_map = file_map
        self.sorted_files = []
        self.expected_total_size = 0
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self._file_size_cache = {}

    def _get_size(self, filepath):
        if filepath not in self._file_size_cache:
            self._file_size_cache[filepath] = os.path.getsize(filepath)
        return self._file_size_cache[filepath]

    def _sort_pfs0_order(self):
        order_list = []
        order_keys = ["tik", "cert", "meta_nca", "meta_xml", 3, 1, 2, 4, 5, 6]
        for key in order_keys:
            if key in self.file_map:
                items = self.file_map[key]
                if isinstance(items, list) and items:
                    order_list.extend(sorted(items, key=lambda x: os.path.basename(x)))
        self.sorted_files = order_list

    def repack(self):
        self._sort_pfs0_order()
        hd = self._gen_header()
        self.expected_total_size = len(hd) + sum(
            self._get_size(file) for file in self.sorted_files
        )

        if (
            os.path.exists(self.path)
            and self._get_size(self.path) == self.expected_total_size
        ):
            if self.log_callback:
                self.log_callback(
                    f"[NSPRepacker] Target {self.path} already exists with correct"
                    " size."
                )
            return self.path

        with open(self.path, "wb") as outf:
            outf.write(hd)
            if self.log_callback:
                self.log_callback(
                    f"[NSPRepacker] Header written. Total size expected:"
                    f" {self.expected_total_size} bytes."
                )
            total_files = len(self.sorted_files)

            for i, file in enumerate(self.sorted_files, 1):
                if self.log_callback:
                    self.log_callback(
                        f"[NSPRepacker] Packing {os.path.basename(file)}"
                        f" ({i}/{total_files})..."
                    )
                with open(file, "rb") as inf:
                    shutil.copyfileobj(inf, outf, length=2 * 1024 * 1024)
                if self.progress_callback:
                    self.progress_callback(i, total_files)

        return self.path

    def verify_integrity(self):
        try:
            if self.log_callback:
                self.log_callback(
                    "[NSPRepacker] Starting integrity verification..."
                )
            with open(self.path, "rb") as f:
                header_start = f.read(16)
                if len(header_start) < 16 or header_start[:4] != b"PFS0":
                    if self.log_callback:
                        self.log_callback("[NSPRepacker] Verification failed: Bad magic.")
                    return False

                file_count = unpack("<I", header_start[4:8])[0]
                if file_count != len(self.sorted_files):
                    if self.log_callback:
                        self.log_callback(
                            "[NSPRepacker] Verification failed: File count mismatch"
                            f" ({file_count} vs {len(self.sorted_files)})."
                        )
                    return False

                string_table_size = unpack("<I", header_start[8:12])[0]
                header_size = 0x10 + (file_count * 0x18) + string_table_size

                entries_bytes = f.read(file_count * 0x18)
                if len(entries_bytes) != file_count * 0x18:
                    return False

                for i in range(file_count):
                    offset, size = unpack("<QQ", entries_bytes[i * 24 : i * 24 + 16])
                    if (header_size + offset + size) > self.expected_total_size:
                        if self.log_callback:
                            self.log_callback(
                                "[NSPRepacker] Verification failed: Entry exceeds file size."
                            )
                        return False

                f.seek(0, 2)
                actual_size = f.tell()
                if actual_size != self.expected_total_size:
                    if self.log_callback:
                        self.log_callback(
                            "[NSPRepacker] Verification failed: Size mismatch"
                            f" ({actual_size} vs {self.expected_total_size})."
                        )
                    return False

            if self.log_callback:
                self.log_callback("[NSPRepacker] Integrity verification passed.")
            return True
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"[NSPRepacker] Verification crashed: {e}")
            return False

    def _gen_header(self):
        files_nb = len(self.sorted_files)
        encoded_names = [os.path.basename(f).encode("utf-8") + b"\x00" for f in self.sorted_files]
        string_table = b"".join(encoded_names)

        raw_header_size = 0x10 + files_nb * 0x18 + len(string_table)
        remainder = (0x20 - (raw_header_size % 0x20)) % 0x20
        padded_string_table_size = len(string_table) + remainder

        file_sizes = [self._get_size(file) for file in self.sorted_files]
        file_offsets = []
        current_offset = 0
        for size in file_sizes:
            file_offsets.append(current_offset)
            current_offset += size

        string_table_offsets = []
        current_str_offset = 0
        for name in encoded_names:
            string_table_offsets.append(current_str_offset)
            current_str_offset += len(name)

        header = bytearray(0x10 + files_nb * 0x18)
        header[0:4] = b"PFS0"
        header[4:8] = pack("<I", files_nb)
        header[8:12] = pack("<I", padded_string_table_size)

        for n in range(files_nb):
            entry_start = 0x10 + n * 0x18
            header[entry_start : entry_start + 8] = pack("<Q", file_offsets[n])
            header[entry_start + 8 : entry_start + 16] = pack("<Q", file_sizes[n])
            header[entry_start + 16 : entry_start + 20] = pack("<I", string_table_offsets[n])

        header.extend(string_table)
        if remainder:
            header.extend(b"\x00" * remainder)

        return bytes(header)