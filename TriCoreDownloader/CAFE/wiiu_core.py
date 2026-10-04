import os
import struct
import hashlib
import binascii
from dataclasses import dataclass, field
from typing import List
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

STRUCT_Q = struct.Struct(">Q")
STRUCT_H = struct.Struct(">H")
STRUCT_CONTENT = struct.Struct(">IHHQ")

@dataclass(slots=True)
class Content:
    id: int = 0
    index: int = 0
    type: int = 0
    size: int = 0
    hash: bytes = b""

@dataclass(slots=True)
class TMD:
    title_id: int = 0
    title_id_bin: bytes = b""
    version: int = 0
    title_version: int = 0
    content_count: int = 0
    contents: List[Content] = field(default_factory=list)

def parse_tmd(data: bytes, T_cb, log_cb=lambda x: None) -> TMD:
    data_len = len(data)
    print(T_cb("log_core_tmd_bytes").format(data_len))
    log_cb(T_cb("log_debug_tmd_parse"))

    if data_len < 0x200:
        print(T_cb("err_core_tmd_short"))
        raise ValueError(T_cb("err_tmd_invalid"))

    tmd = TMD()
    tmd.version = data[0x180]
    tmd.title_id_bin = data[0x18C : 0x194]
    tmd.title_id = STRUCT_Q.unpack_from(data, 0x18C)[0]
    tmd.title_version = STRUCT_H.unpack_from(data, 0x1DC)[0]
    tmd.content_count = STRUCT_H.unpack_from(data, 0x1DE)[0]

    print(
        T_cb("log_core_tmd_parsed").format(
            f"{tmd.title_id:016X}", tmd.title_version, tmd.content_count
        )
    )
    log_cb(
        T_cb("log_debug_tmd_info").format(
            tmd.title_id, tmd.title_version, tmd.content_count
        )
    )

    content_offset = 0xB04 if tmd.version == 1 else 0x1E4
    entry_size = 0x30 if tmd.version == 1 else 0x24

    for i in range(tmd.content_count):
        off = content_offset + (i * entry_size)
        if data_len < off + 36:
            print(T_cb("err_core_tmd_eof"))
            break

        c_id, c_index, c_type, c_size = STRUCT_CONTENT.unpack_from(data, off)
        c_hash = data[off + 16 : off + 36]
        c = Content(c_id, c_index, c_type, c_size, c_hash)
        tmd.contents.append(c)

        log_cb(
            T_cb("log_debug_content").format(c_id, c_index, c_type, c_size)
        )

    return tmd

def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()

def get_common_key(otp_input: str, T_cb, log_cb=lambda x: None) -> bytes:
    print(T_cb("log_core_key_extract"))
    log_cb(T_cb("log_debug_key_check"))

    otp_clean = str(otp_input).strip().strip('"').strip("'")

    if len(otp_clean) == 32:
        try:
            key = binascii.unhexlify(otp_clean)
            print(T_cb("log_core_key_hex_shape"))
            return key
        except (binascii.Error, ValueError):
            print(T_cb("err_core_key_hex_invalid"))

    if os.path.isfile(otp_clean):
        try:
            file_size = os.path.getsize(otp_clean)
            with open(otp_clean, "rb") as f:
                if file_size == 16:
                    key = f.read(16)
                    print(T_cb("log_core_key_file_shape"))
                    return key
                elif file_size in (32, 33, 34):
                    text_content = f.read().decode("ascii", errors="ignore").strip()
                    if len(text_content) == 32:
                        key = binascii.unhexlify(text_content)
                        print(T_cb("log_core_key_hex_shape"))
                        return key
                elif file_size >= 0x0F0:
                    f.seek(0x0E0)
                    key = f.read(0x10)
                    if len(key) == 0x10:
                        print(T_cb("log_core_key_file_shape"))
                        return key
        except Exception as e:
            print(T_cb("err_core_key_file_read").format(str(e)))

    print(T_cb("err_core_key_exhausted"))
    raise ValueError(T_cb("err_common_key_format"))