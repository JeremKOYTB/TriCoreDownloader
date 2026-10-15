import hashlib
import math
import os
import random
import re
import shutil
import stat
import subprocess
import sys
from struct import pack, unpack

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if sys.platform == "win32" or os.name == "nt" else {}
RE_SDK_BYTES = re.compile(rb"NintendoSDK Firmware for NX [0-9.\-]+")


def _write_bytes_fast(dst_path, data):
    mv = data if isinstance(data, memoryview) else memoryview(data)
    total = len(mv)
    try:
        with open(dst_path, "wb", buffering=0) as f:
            written = 0
            while written < total:
                n = f.write(mv[written:])
                if not n:
                    break
                written += n
    except PermissionError:
        if os.path.exists(dst_path):
            try:
                os.chmod(dst_path, stat.S_IWRITE | stat.S_IREAD)
                os.remove(dst_path)
            except Exception:
                pass
        with open(dst_path, "wb", buffering=0) as f:
            written = 0
            while written < total:
                n = f.write(mv[written:])
                if not n:
                    break
                written += n


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
        self.system_update_ver_raw = 0
        self.nca_sizes = {}
        self._backend = default_backend()
        self._hactool_bin = self._resolve_hactool_bin()
        self._keys = {}
        self._load_nca_keys()

    def _resolve_hactool_bin(self):
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
        return hactool_bin

    def _load_nca_keys(self):
        keys_path = self.config.get("prod_keys", "")
        if not keys_path or not os.path.isfile(keys_path):
            return
        try:
            mk_count = 0
            kak_count = 0
            with open(keys_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k_str = k.strip().lower()
                    v_str = v.strip()
                    if (
                        k_str == "header_key"
                        or k_str.startswith("key_area_key_")
                        or k_str.startswith("master_key_")
                        or k_str in ("aes_kek_generation_source", "aes_key_generation_source")
                    ):
                        try:
                            self._keys[k_str] = bytes.fromhex(v_str)
                            if k_str.startswith("master_key_"):
                                mk_count += 1
                            elif k_str.startswith("key_area_key_") and not k_str.endswith("_source"):
                                kak_count += 1
                        except ValueError:
                            pass

            has_hdr = "OK" if ("header_key" in self._keys and len(self._keys["header_key"]) == 32) else "MISSING"
            self.log_adv(
                self.T("log_adv_nca_keys_detail").format(has_hdr, mk_count, kak_count)
            )
        except Exception:
            pass

    def _ecb_decrypt(self, key, data):
        decryptor = Cipher(algorithms.AES(key), modes.ECB(), backend=self._backend).decryptor()
        return decryptor.update(data) + decryptor.finalize()

    def _get_key_area_key(self, kaek_index, mk_index):
        type_names = {0: "application", 1: "ocean", 2: "system"}
        t_name = type_names.get(kaek_index)
        if not t_name:
            return None

        for fmt in (f"key_area_key_{t_name}_{mk_index:02x}", f"key_area_key_{t_name}_{mk_index:x}"):
            if fmt in self._keys and len(self._keys[fmt]) == 16:
                return self._keys[fmt]

        mk = self._keys.get(f"master_key_{mk_index:02x}") or self._keys.get(f"master_key_{mk_index:x}")
        kek_src = self._keys.get("aes_kek_generation_source")
        key_src = self._keys.get("aes_key_generation_source")
        kak_src = self._keys.get(f"key_area_key_{t_name}_source")

        if mk and kek_src and key_src and kak_src and len(mk) == 16:
            try:
                kek = self._ecb_decrypt(mk, kek_src)
                kak_kek = self._ecb_decrypt(kek, kak_src)
                kak = self._ecb_decrypt(kak_kek, key_src)
                self._keys[f"key_area_key_{t_name}_{mk_index:02x}"] = kak
                self.log_adv(self.T("log_adv_kak_derived").format(t_name, mk_index))
                return kak
            except Exception:
                return None
        return None

    def _decrypt_nca_section0_in_ram(self, nca_path, nca_bytes=None):
        header_key = self._keys.get("header_key")
        if not header_key or len(header_key) != 32:
            return None, None

        if nca_bytes is None:
            try:
                with open(nca_path, "rb") as f:
                    nca_bytes = f.read(512 * 1024)
            except Exception:
                return None, None

        if len(nca_bytes) < 0xC00:
            return None, None

        try:
            hdr = bytearray(0xC00)
            for s in range(6):
                off = s * 0x200
                tweak = s.to_bytes(16, "big")
                dec = Cipher(algorithms.AES(header_key), modes.XTS(tweak), backend=self._backend).decryptor()
                hdr[off : off + 0x200] = dec.update(nca_bytes[off : off + 0x200])

            if hdr[0x200:0x204] not in (b"NCA3", b"NCA2"):
                return None, None

            if any(hdr[0x230:0x240]):
                return None, None

            if hashlib.sha256(hdr[0x400:0x600]).digest() != bytes(hdr[0x280:0x2A0]):
                return None, None

            crypto_type = hdr[0x206]
            kaek_index = hdr[0x207]
            crypto_type2 = hdr[0x220]
            keygen = max(crypto_type, crypto_type2)
            mk_index = max(0, keygen - 1)

            kak = self._get_key_area_key(kaek_index, mk_index)
            if not kak:
                return None, None

            dec_ka = self._ecb_decrypt(kak, bytes(hdr[0x300:0x340]))
            ctr_key = dec_ka[0x20:0x30]

            media_start = unpack("<I", hdr[0x240:0x244])[0] * 0x200
            media_end = unpack("<I", hdr[0x244:0x248])[0] * 0x200
            if media_start < 0xC00 or media_start >= media_end:
                return None, None

            fs_version = unpack("<H", hdr[0x400:0x402])[0]
            if fs_version != 2:
                return None, None

            fs_type = hdr[0x402]
            hash_type = hdr[0x403]
            crypt_type = hdr[0x404]
            section_ctr_be = bytes(hdr[0x540:0x548])[::-1]

            if fs_type == 1 and hash_type == 2:
                master_hash = bytes(hdr[0x408:0x428])
                block_size, layer_count = unpack("<II", hdr[0x428:0x430])
                ht_offset, ht_size, pfs0_offset, pfs0_size = unpack("<QQQQ", hdr[0x430:0x450])
                if layer_count != 2 or pfs0_size == 0:
                    return None, None
                abs_ht_start = media_start + ht_offset
                abs_start = media_start + pfs0_offset
                abs_end = abs_start + pfs0_size
                if abs_end > len(nca_bytes) or abs_start >= abs_end:
                    return None, None

                if crypt_type == 1:
                    ht_bytes = nca_bytes[abs_ht_start : abs_ht_start + ht_size]
                    pfs0_raw = nca_bytes[abs_start:abs_end]
                elif crypt_type == 3:
                    full_start = min(abs_ht_start, abs_start) & ~0xF
                    iv = section_ctr_be + (full_start >> 4).to_bytes(8, "big")
                    dec_ctr = Cipher(algorithms.AES(ctr_key), modes.CTR(iv), backend=self._backend).decryptor()
                    dec_sec = dec_ctr.update(nca_bytes[full_start:abs_end]) + dec_ctr.finalize()
                    ht_rel = abs_ht_start - full_start
                    pfs0_rel = abs_start - full_start
                    ht_bytes = dec_sec[ht_rel : ht_rel + ht_size]
                    pfs0_raw = dec_sec[pfs0_rel : pfs0_rel + pfs0_size]
                else:
                    return None, None

                if ht_size >= 0x20 and hashlib.sha256(ht_bytes).digest() == master_hash:
                    first_blk_len = min(len(pfs0_raw), block_size if block_size > 0 else len(pfs0_raw))
                    if hashlib.sha256(pfs0_raw[:first_blk_len]).digest() != ht_bytes[:0x20]:
                        return None, None
                return fs_type, pfs0_raw

            abs_start = media_start
            abs_end = min(media_end, len(nca_bytes))
            if abs_start >= abs_end:
                return None, None

            if crypt_type == 1:
                return fs_type, nca_bytes[abs_start:abs_end]
            if crypt_type != 3:
                return None, None

            aligned_start = abs_start & ~0xF
            pad_head = abs_start - aligned_start
            iv = section_ctr_be + (aligned_start >> 4).to_bytes(8, "big")

            dec_ctr = Cipher(algorithms.AES(ctr_key), modes.CTR(iv), backend=self._backend).decryptor()
            decrypted_chunk = dec_ctr.update(nca_bytes[aligned_start:abs_end]) + dec_ctr.finalize()
            return fs_type, decrypted_chunk[pad_head : pad_head + (abs_end - abs_start)]
        except Exception:
            return None, None

    def extract_romfs_identity_in_ram(self, nca_path):
        fs_type, dec_data = self._decrypt_nca_section0_in_ram(nca_path)
        if fs_type != 0 or not dec_data:
            return None, None

        for m in RE_SDK_BYTES.finditer(dec_data):
            sdk_pos = m.start()
            if sdk_pos >= 0x80 and dec_data[sdk_pos - 0x78 : sdk_pos - 0x75] == b"NX\x00":
                sdk_title = dec_data[sdk_pos : sdk_pos + 0x80].split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                ver_slice = dec_data[sdk_pos - 0x18 : sdk_pos]
                comm_ver = ver_slice.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                return comm_ver, sdk_title

        m = RE_SDK_BYTES.search(dec_data)
        if not m:
            return None, None

        sdk_title = m.group(0).decode("utf-8", errors="ignore").strip()
        sdk_pos = m.start()
        comm_ver = ""
        if sdk_pos >= 0x18:
            ver_slice = dec_data[sdk_pos - 0x18 : sdk_pos]
            comm_ver = ver_slice.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
        return comm_ver, sdk_title

    @staticmethod
    def recover_rsa_private_key(n, e, d, tr_cb=None):
        T = tr_cb or (lambda k, d_val=None: d_val or k)
        k = d * e - 1
        if k <= 0 or k % 2 != 0:
            raise ValueError(T("err_nx_rsa_d_invalid"))

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
            raise RuntimeError(T("err_nx_rsa_factor_fail"))

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
    def extract_client_cert_and_key(cls, cal0_data, ssl_rsa_kek, log_cb=None, tr_cb=None):
        T = tr_cb or (lambda k, d_val=None: d_val or k)
        body_size = unpack("<I", cal0_data[0x08:0x0C])[0]
        if 0 < body_size <= len(cal0_data) - 0x40:
            expected_body_hash = cal0_data[0x20:0x40]
            if expected_body_hash != b"\x00" * 32:
                try:
                    if hashlib.sha256(cal0_data[0x40 : 0x40 + body_size]).digest() != expected_body_hash:
                        if log_cb:
                            log_cb("cal0_hash_warn", ())
                except Exception:
                    pass

        cert_size = unpack("<I", cal0_data[0x0AD0:0x0AD4])[0]
        if cert_size == 0 or cert_size > 0x0800:
            raise ValueError(T("err_nx_cal0_cert_size"))

        if len(cal0_data) >= 0x1300:
            cert_block_hash = cal0_data[0x12E0:0x1300]
            if any(cert_block_hash):
                try:
                    if hashlib.sha256(cal0_data[0x0AE0:0x12E0]).digest() != cert_block_hash:
                        if log_cb:
                            log_cb("cert_hash_warn", ())
                except Exception:
                    pass

        cert_data = cal0_data[0x0AE0 : 0x0AE0 + cert_size]
        cert = x509.load_der_x509_certificate(cert_data, default_backend())

        pub_numbers = cert.public_key().public_numbers()
        n = pub_numbers.n
        e = pub_numbers.e

        if log_cb:
            log_cb("cert_der", (cert_size, n.bit_length()))

        ssl_ext_key = cal0_data[0x3AE0 : 0x3AE0 + 0x110]
        iv = ssl_ext_key[:0x10]
        encrypted_d = ssl_ext_key[0x10:]

        if log_cb:
            log_cb("rsa_recover", ())

        keks = ssl_rsa_kek if isinstance(ssl_rsa_kek, list) else [ssl_rsa_kek]
        last_error = None
        backend = default_backend()

        for kek in keks:
            try:
                cipher = Cipher(
                    algorithms.AES(kek), modes.CTR(iv), backend=backend
                )
                decryptor = cipher.decryptor()
                decrypted_d_bytes = decryptor.update(encrypted_d) + decryptor.finalize()

                d = int.from_bytes(decrypted_d_bytes, "big")
                private_key = cls.recover_rsa_private_key(n, e, d, tr_cb=T)

                clean_key = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
                clean_cert = cert.public_bytes(serialization.Encoding.PEM)

                return clean_cert, clean_key
            except Exception as ex:
                last_error = ex
                continue

        raise ValueError(T("err_nx_rsa_decrypt_fail").format(last_error))

    @staticmethod
    def _extract_cnmt_from_pfs0(pfs0_bytes):
        total_len = len(pfs0_bytes)
        if total_len < 0x10 or pfs0_bytes[:4] != b"PFS0":
            return None

        num_files, string_table_size = unpack("<II", pfs0_bytes[4:12])
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
        if len(c) < 0x20:
            return []

        tid_hdr, ver_hdr, c_type, _, ext_hdr_size, content_count, content_meta_count = unpack(
            "<QIBBHHH", c[:0x14]
        )
        self.log_adv(
            self.T("log_val_cnmt_hdr").format(f"{c_type:#04x}", f"{tid_hdr:016x}", ver_hdr)
        )

        entries = []
        if c_type == 0x3:
            self.log_adv(self.T("log_su_meta").format(content_meta_count, f"{ext_hdr_size:#06x}"))
            base = 0x20 + ext_hdr_size + (content_count * 0x38)
            for i in range(content_meta_count):
                entry_off = base + i * 0x10
                if entry_off + 12 > len(c):
                    break
                title_id, version = unpack("<QI", c[entry_off : entry_off + 12])
                entries.append((f"{title_id:016x}", version, None))
        else:
            self.log_adv(self.T("log_co_meta").format(content_count, f"{ext_hdr_size:#06x}"))
            base = 0x20 + ext_hdr_size
            for i in range(content_count):
                entry_off = base + i * 0x38
                if entry_off + 0x38 > len(c):
                    break
                entry_type = c[entry_off + 0x36]
                if entry_type == 6:
                    continue
                h_bytes = c[entry_off : entry_off + 32]
                nid_bytes = c[entry_off + 32 : entry_off + 48]
                sz_low, sz_high = unpack("<IH", c[entry_off + 48 : entry_off + 54])
                nca_sz = sz_low | (sz_high << 32)
                nid_hex = nid_bytes.hex()
                h_hex = h_bytes.hex()
                if nca_sz > 0:
                    self.nca_sizes[nid_hex] = nca_sz
                entries.append((nid_hex, h_hex, entry_type))

        return entries

    def parse_cnmt(self, nca_path, raw_dir, nca_bytes=None):
        ncaf = os.path.basename(nca_path)
        self.log_adv(self.T("log_parse_cnmt").format(ncaf))

        fs_type, pfs0_bytes = self._decrypt_nca_section0_in_ram(nca_path, nca_bytes=nca_bytes)
        if fs_type == 1 and pfs0_bytes:
            cnmt_bytes = self._extract_cnmt_from_pfs0(pfs0_bytes)
            if cnmt_bytes:
                self.log_adv(self.T("log_adv_nca_ram_ok").format(len(pfs0_bytes), ncaf))
                if len(cnmt_bytes) >= 12:
                    tid, ver = unpack("<QI", cnmt_bytes[0:12])
                    if tid == 0x0100000000000816:
                        self.system_update_ver_raw = ver
                return self._parse_cnmt_bytes(cnmt_bytes)

        self.log_adv(self.T("log_adv_nca_hactool_fb").format(ncaf))
        temp_sec0 = os.path.join(raw_dir, f"_sec0_{ncaf}.tmp")

        cmd = [
            self._hactool_bin,
            "-k",
            self.config["prod_keys"],
            nca_path,
            f"--section0={temp_sec0}",
        ]
        self.log_adv(self.T("log_exec_cmd").format(" ".join(cmd)))

        try:
            res = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SUBPROCESS_FLAGS
            )

            if not os.path.exists(temp_sec0) or os.path.getsize(temp_sec0) == 0:
                err_msg_raw = (
                    res.stderr.decode(errors="ignore") if res.stderr else ""
                )
                filtered_err_lines = [
                    line
                    for line in err_msg_raw.split("\n")
                    if "[WARN]: Failed to match key" not in line
                ]
                raise RuntimeError(
                    self.T("err_hactool").format("\n".join(filtered_err_lines).strip())
                )

            with open(temp_sec0, "rb") as f:
                pfs0_bytes = f.read()

            cnmt_bytes = self._extract_cnmt_from_pfs0(pfs0_bytes)
            if not cnmt_bytes:
                raise RuntimeError(self.T("log_err_cnmt_missing").format(ncaf))

            if len(cnmt_bytes) >= 12:
                tid, ver = unpack("<QI", cnmt_bytes[0:12])
                if tid == 0x0100000000000816:
                    self.system_update_ver_raw = ver

            return self._parse_cnmt_bytes(cnmt_bytes)
        finally:
            if os.path.exists(temp_sec0):
                try:
                    os.remove(temp_sec0)
                except OSError:
                    pass


class NSPRepacker:
    def __init__(
        self, out_path, file_map, log_callback=None, progress_callback=None, tr_callback=None
    ):
        self.path = out_path
        self.file_map = file_map
        self.sorted_files = []
        self.expected_total_size = 0
        self.sha256_hash = ""
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.T = tr_callback or (lambda k, d=None: d or k)
        self._file_size_cache = {}

    def _get_size(self, filepath):
        if filepath not in self._file_size_cache:
            self._file_size_cache[filepath] = os.path.getsize(filepath)
        return self._file_size_cache[filepath]

    def _sort_pfs0_order(self):
        order_list = []
        seen = set()
        order_keys = ["tik", "cert", "meta_nca", "meta_xml", 3, 1, 2, 4, 5, 6]
        for key in order_keys:
            if key in self.file_map:
                items = self.file_map[key]
                if isinstance(items, list) and items:
                    for item in sorted(items, key=lambda x: os.path.basename(x)):
                        norm = os.path.normcase(os.path.abspath(item))
                        if norm not in seen and os.path.exists(item):
                            seen.add(norm)
                            order_list.append(item)
        self.sorted_files = order_list

    def repack(self):
        self._sort_pfs0_order()
        hd = self._gen_header()
        self.expected_total_size = len(hd) + sum(
            self._get_size(file) for file in self.sorted_files
        )

        if self.log_callback:
            self.log_callback(
                self.T("log_adv_nsp_header").format(
                    len(hd), len(self.sorted_files), self.expected_total_size
                )
            )

        if (
            os.path.exists(self.path)
            and self._get_size(self.path) == self.expected_total_size
        ):
            if self.log_callback:
                self.log_callback(
                    self.T("log_adv_nsp_exists").format(
                        os.path.basename(self.path), self.expected_total_size
                    )
                )
            return self.path

        hasher = hashlib.sha256()
        io_buf_sz = 4 * 1024 * 1024
        buf = bytearray(io_buf_sz)
        mv = memoryview(buf)

        with open(self.path, "wb", buffering=io_buf_sz) as outf:
            outf.write(hd)
            hasher.update(hd)
            total_files = len(self.sorted_files)

            for i, file in enumerate(self.sorted_files, 1):
                with open(file, "rb", buffering=io_buf_sz) as inf:
                    while True:
                        n = inf.readinto(mv)
                        if not n:
                            break
                        chunk = mv[:n]
                        outf.write(chunk)
                        hasher.update(chunk)
                if self.progress_callback:
                    self.progress_callback(i, total_files)

        self.sha256_hash = hasher.hexdigest()
        return self.path

    def verify_integrity(self):
        try:
            with open(self.path, "rb") as f:
                header_start = f.read(16)
                if len(header_start) < 16 or header_start[:4] != b"PFS0":
                    return False

                file_count, string_table_size, reserved_zero = unpack("<III", header_start[4:16])
                if file_count != len(self.sorted_files) or reserved_zero != 0:
                    return False

                header_size = 0x10 + (file_count * 0x18) + string_table_size

                entries_bytes = f.read(file_count * 0x18)
                if len(entries_bytes) != file_count * 0x18:
                    return False

                expected_offset = 0
                for i in range(file_count):
                    offset, size, str_off = unpack("<QQI", entries_bytes[i * 24 : i * 24 + 20])
                    if offset != expected_offset or str_off >= string_table_size:
                        return False
                    expected_offset += size
                    if (header_size + offset + size) > self.expected_total_size:
                        return False

                if (header_size + expected_offset) != self.expected_total_size:
                    return False

                f.seek(0, 2)
                actual_size = f.tell()
                if actual_size != self.expected_total_size:
                    return False

            if self.log_callback:
                self.log_callback(self.T("log_adv_nsp_verified"))
            return True
        except Exception:
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
