import os
import struct
import hashlib
import binascii
from dataclasses import dataclass, field
from typing import List
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

STRUCT_Q = struct.Struct(">Q")
STRUCT_I = struct.Struct(">I")
STRUCT_H = struct.Struct(">H")
STRUCT_HH = struct.Struct(">HH")
STRUCT_HHH = struct.Struct(">HHH")
STRUCT_CONTENT = struct.Struct(">IHHQ")
_BACKEND = default_backend()

WIIU_COMMON_KEY_SHA1 = "6a0b87fc98b306ae3366f0e0a88d0b06a2813313"
OTP_SIZE = 0x400
OTP_COMMON_KEY_OFFSET = 0x0E0

HIGH_TID_CATEGORIES = {
    "00050010": "System Application",
    "0005001b": "Shared Data",
    "00050030": "Overlay Application",
    "0005000b": "Shared User Data",
    "00050000": "Application",
    "0005000e": "Update",
    "0005000c": "DLC",
    "00050002": "Demo",
}


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
    system_version: int = 0
    title_type: int = 0
    group_id: int = 0
    access_rights: int = 0
    title_version: int = 0
    content_count: int = 0
    boot_index: int = 0
    contents: List[Content] = field(default_factory=list)


def get_title_category(title_id_hex: str) -> str:
    clean = title_id_hex.replace("-", "").strip().lower()
    if len(clean) >= 8:
        return HIGH_TID_CATEGORIES.get(clean[:8], "System")
    return "System"


def _is_log_active(log_cb) -> bool:
    return bool(log_cb and getattr(log_cb, "_is_enabled", True))


def parse_tmd(data: bytes, T_cb, log_cb=None) -> TMD:
    data_len = len(data)
    log_active = _is_log_active(log_cb)

    if log_active:
        log_cb(T_cb("log_core_tmd_bytes").format(data_len))

    if data_len < 0x200:
        if log_active:
            log_cb(T_cb("err_core_tmd_short").format(data_len))
        raise ValueError(T_cb("err_tmd_invalid"))

    version = data[0x180]
    system_version = STRUCT_Q.unpack_from(data, 0x184)[0]
    title_id_bin = data[0x18C:0x194]
    title_id = STRUCT_Q.unpack_from(data, 0x18C)[0]
    title_type = STRUCT_I.unpack_from(data, 0x194)[0]
    group_id = STRUCT_H.unpack_from(data, 0x198)[0]
    access_rights = STRUCT_I.unpack_from(data, 0x1D8)[0]
    title_version, content_count, boot_index = STRUCT_HHH.unpack_from(data, 0x1DC)

    if content_count <= 0:
        raise ValueError(T_cb("err_tmd_invalid"))

    content_offset = 0xB04 if version == 1 else 0x1E4
    entry_size = 0x30 if version == 1 else 0x24

    tmd = TMD(
        title_id=title_id,
        title_id_bin=title_id_bin,
        version=version,
        system_version=system_version,
        title_type=title_type,
        group_id=group_id,
        access_rights=access_rights,
        title_version=title_version,
        content_count=content_count,
        boot_index=boot_index,
    )

    if log_active:
        log_cb(
            T_cb("log_core_tmd_parsed").format(
                f"{title_id:016X}", title_version, content_count
            )
        )

    unpack_content = STRUCT_CONTENT.unpack_from
    contents_list = tmd.contents
    Content_cls = Content
    dbg_template = T_cb("log_debug_content") if log_active else ""

    for i in range(content_count):
        off = content_offset + (i * entry_size)
        if data_len < off + 36:
            if log_active:
                log_cb(T_cb("err_core_tmd_eof"))
            break

        c_id, c_index, c_type, c_size = unpack_content(data, off)
        c_hash = data[off + 16 : off + 36]
        contents_list.append(Content_cls(c_id, c_index, c_type, c_size, c_hash))

        if log_active:
            mode_label = "H3 Hashed" if (c_type & 0x02) else "Linear"
            hash_short = binascii.hexlify(c_hash[:8]).decode("ascii")
            try:
                log_cb(
                    dbg_template.format(
                        c_id, c_index, c_type, c_size, mode_label, hash_short
                    )
                )
            except IndexError:
                log_cb(dbg_template.format(c_id, c_index, c_type, c_size))

    return tmd


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes, aes_algo=None) -> bytes:
    algo = aes_algo if aes_algo is not None else algorithms.AES(key)
    decryptor = Cipher(algo, modes.CBC(iv), backend=_BACKEND).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def get_common_key(otp_input: str, T_cb, log_cb=None) -> bytes:
    log_active = _is_log_active(log_cb)
    if log_active:
        log_cb(T_cb("log_core_key_extract"))

    otp_clean = str(otp_input).strip().strip('"').strip("'")

    if len(otp_clean) == 32:
        try:
            key = binascii.unhexlify(otp_clean)
            if log_active:
                log_cb(T_cb("log_core_key_hex_shape"))
            return key
        except (binascii.Error, ValueError):
            if log_active:
                log_cb(T_cb("err_core_key_hex_invalid"))

    if os.path.isfile(otp_clean):
        try:
            file_size = os.path.getsize(otp_clean)
            with open(otp_clean, "rb") as f:
                if file_size == 16:
                    key = f.read(16)
                    if log_active:
                        try:
                            log_cb(T_cb("log_core_key_file_shape").format(16, 0x00))
                        except IndexError:
                            log_cb(T_cb("log_core_key_file_shape"))
                    return key
                elif file_size in (32, 33, 34):
                    text_content = f.read().decode("ascii", errors="ignore").strip()
                    if len(text_content) == 32:
                        key = binascii.unhexlify(text_content)
                        if log_active:
                            log_cb(T_cb("log_core_key_hex_shape"))
                        return key
                elif file_size >= OTP_COMMON_KEY_OFFSET + 0x10:
                    f.seek(OTP_COMMON_KEY_OFFSET)
                    key = f.read(0x10)
                    if len(key) == 0x10:
                        if log_active:
                            try:
                                log_cb(
                                    T_cb("log_core_key_file_shape").format(
                                        16, OTP_COMMON_KEY_OFFSET
                                    )
                                )
                            except IndexError:
                                log_cb(T_cb("log_core_key_file_shape"))
                        return key
        except Exception as e:
            if log_active:
                log_cb(T_cb("err_core_key_file_read").format(str(e)))

    if log_active:
        log_cb(T_cb("err_core_key_exhausted"))
    raise ValueError(T_cb("err_common_key_format"))
