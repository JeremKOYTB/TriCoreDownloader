import os
import struct
import hashlib
import binascii
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

class Content:
    def __init__(self):
        self.id = 0
        self.index = 0
        self.type = 0
        self.size = 0
        self.hash = b""

class TMD:
    def __init__(self):
        self.title_id = 0
        self.title_id_bin = b""
        self.version = 0
        self.title_version = 0
        self.content_count = 0
        self.contents = []

def parse_tmd(data, T_cb, log_cb=lambda x: None):
    print(T_cb("log_core_tmd_bytes").format(len(data)))
    log_cb(T_cb("log_debug_tmd_parse"))
    
    if len(data) < 0x200: 
        print(T_cb("err_core_tmd_short"))
        raise ValueError(T_cb("err_tmd_invalid"))
        
    tmd = TMD()
    tmd.version = data[0x180]
    tmd.title_id_bin = data[0x18C:0x18C+8]
    tmd.title_id = struct.unpack(">Q", tmd.title_id_bin)[0]
    tmd.title_version = struct.unpack(">H", data[0x1DC:0x1DC+2])[0]
    tmd.content_count = struct.unpack(">H", data[0x1DE:0x1DE+2])[0]

    print(T_cb("log_core_tmd_parsed").format(f"{tmd.title_id:016X}", tmd.title_version, tmd.content_count))
    log_cb(T_cb("log_debug_tmd_info").format(tmd.title_id, tmd.title_version, tmd.content_count))

    content_offset = 0xB04 if tmd.version == 1 else 0x1E4
    
    for i in range(tmd.content_count):
        off = content_offset + (i * (0x30 if tmd.version == 1 else 0x24))
        if len(data) < off + 20: 
            print(T_cb("err_core_tmd_eof"))
            break
            
        c = Content()
        c.id = struct.unpack(">I", data[off:off+4])[0]
        c.index = struct.unpack(">H", data[off+4:off+6])[0]
        c.type = struct.unpack(">H", data[off+6:off+8])[0]
        c.size = struct.unpack(">Q", data[off+8:off+16])[0]
        c.hash = data[off+16:off+36] 
        tmd.contents.append(c)
        
        log_cb(T_cb("log_debug_content").format(c.id, c.index, c.type, c.size))
        
    return tmd

def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()

def get_common_key(otp_input, T_cb, log_cb=lambda x: None):
    print(T_cb("log_core_key_extract"))
    log_cb(T_cb("log_debug_key_check"))
    
    if len(otp_input) == 32:
        try:
            key = binascii.unhexlify(otp_input)
            print(T_cb("log_core_key_hex_shape"))
            return key
        except binascii.Error:
            print(T_cb("err_core_key_hex_invalid"))
            pass
            
    if os.path.isfile(otp_input):
        try:
            with open(otp_input, "rb") as f:
                otp = f.read()
                if len(otp) >= 0x0F0:
                    key = otp[0x0E0 : 0x0E0 + 0x10]
                    print(T_cb("log_core_key_file_shape"))
                    return key
        except Exception as e:
            print(T_cb("err_core_key_file_read").format(str(e)))
            pass
            
    print(T_cb("err_core_key_exhausted"))
    raise ValueError(T_cb("err_common_key_format"))