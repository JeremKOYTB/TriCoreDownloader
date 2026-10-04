import os
import shutil
import struct
import hashlib
import traceback
from pathlib import Path

CIA_HEADER_SIZE = 0x2020
PADDING_ALIGNMENT = 64
PAD_ZEROS = b"\x00" * PADDING_ALIGNMENT

STRUCT_BE_I = struct.Struct(">I")
STRUCT_BE_H = struct.Struct(">H")
STRUCT_BE_Q = struct.Struct(">Q")
STRUCT_LE_CIA_HDR = struct.Struct("<IHHIIIIQ")
STRUCT_BE_HH = struct.Struct(">HH")

SIG_LENS = {
    0x00010000: 0x240,
    0x00010003: 0x240,
    0x00010001: 0x140,
    0x00010004: 0x140,
    0x00010002: 0x080,
    0x00010005: 0x080,
}

class Content:
    __slots__ = ('id_hex', 'index', 'size', 'is_encrypted')
    def __init__(self):
        self.id_hex = ""
        self.index = 0
        self.size = 0
        self.is_encrypted = False

class TMD:
    __slots__ = ('title_version', 'contents')
    def __init__(self):
        self.title_version = 0
        self.contents = []

def get_sig_len(sig_type: int) -> int:
    return SIG_LENS.get(sig_type, 0x240)

def get_cert_len(data: bytes, offset: int) -> int:
    try:
        if offset + 4 > len(data):
            return 0
        sig_type = STRUCT_BE_I.unpack_from(data, offset)[0]
        sig_len = SIG_LENS.get(sig_type, 0x240)
        key_type_offset = offset + sig_len + 0x40
        
        if key_type_offset + 4 > len(data):
            return 0
        key_type = STRUCT_BE_I.unpack_from(data, key_type_offset)[0]
        pub_len = 0x238 if key_type == 0 else (0x138 if key_type == 1 else 0x78)
        
        return sig_len + 0x88 + pub_len
    except Exception:
        return 0

def pad_64(f):
    rem = f.tell() & (PADDING_ALIGNMENT - 1)
    if rem:
        f.write(PAD_ZEROS[:PADDING_ALIGNMENT - rem])

def _decrypt_cia_with_pyctr(input_cia_path: Path, output_cia_path: Path, T_cb, boot9_path=None, log_cb=None, advanced_logs: bool = False, is_stopped_cb=None) -> bool:
    try:
        from pyctr.type.cia import CIAReader, CIASection
        from pyctr.type.ncch import NCCHSection
        from pyctr.crypto import CryptoEngine
        from pyctr.crypto.engine import BootromNotFoundError
        
        try:
            if boot9_path and str(boot9_path).strip('\"\'') != "" and str(boot9_path).lower() != "none":
                b9_path = Path(str(boot9_path).strip('\"\'')).resolve()
                if not b9_path.is_file():
                    if log_cb:
                        log_cb(T_cb("err_boot9_missing").format(str(b9_path)))
                    return False
                crypto = CryptoEngine(boot9=str(b9_path))
            else:
                crypto = CryptoEngine()
        except BootromNotFoundError:
            if log_cb:
                log_cb(T_cb("err_boot9_missing_fatal"))
            return False
        except Exception as e:
            if log_cb:
                log_cb(T_cb("log_3ds_err_pyctr").format(e))
            return False
            
        with CIAReader(str(input_cia_path), crypto=crypto) as reader:
            if log_cb and advanced_logs: 
                log_cb(T_cb("log_3ds_crypt_proc").format(reader.tmd.title_id.upper()))
            
            with reader.open_raw_section(CIASection.CertificateChain) as c:
                cert_chain = c.read()
            with reader.open_raw_section(CIASection.Ticket) as c:
                ticket = bytearray(c.read())
            with reader.open_raw_section(CIASection.TitleMetadata) as c:
                tmd_data = bytearray(c.read())
                
            tik_sig_type = STRUCT_BE_I.unpack_from(ticket, 0)[0]
            tik_sig_len = get_sig_len(tik_sig_type)
            tk_offset = tik_sig_len + 0x7F
            
            if tk_offset + 16 <= len(ticket):
                if log_cb and advanced_logs:
                    extracted_tk = ticket[tk_offset : tk_offset + 16].hex().upper()
                    log_cb(T_cb("log_3ds_title_key").format(extracted_tk))
                ticket[tk_offset : tk_offset + 16] = b'\x00' * 16

            tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
            tmd_sig_len = get_sig_len(tmd_sig_type)
            c_offset = tmd_sig_len + 0x9C4
            content_count = STRUCT_BE_H.unpack_from(tmd_data, tmd_sig_len + 0x9E)[0]

            tmp_dec_dir = output_cia_path.parent / f"_dec_tmp_{input_cia_path.stem}"
            tmp_dec_dir.mkdir(parents=True, exist_ok=True)

            new_hashes = {}
            content_size_total = 0
            content_index = bytearray(0x2000)
            written_files = {}

            try:
                for record in reader.content_info:
                    if is_stopped_cb and is_stopped_cb():
                        return False
                    
                    idx = record.cindex
                    is_ncch = idx in reader.contents
                    out_content_path = tmp_dec_dir / f"dec_{idx}.bin"
                    sha = hashlib.sha256()
                    bytes_written = 0

                    with open(out_content_path, "wb") as f_out:
                        if is_ncch:
                            content_reader = reader.contents[idx]
                            with content_reader.open_raw_section(NCCHSection.FullDecrypted) as f_in:
                                header_chunk = bytearray(f_in.read(0x200))
                                if len(header_chunk) >= 0x200 and header_chunk[0x100:0x104] == b'NCCH':
                                    flags_7 = header_chunk[0x18F]
                                    flags_7 |= 0x04   
                                    flags_7 &= ~0x21  
                                    header_chunk[0x18F] = flags_7
                                    header_chunk[0x18B] = 0x00 
                                
                                f_out.write(header_chunk)
                                sha.update(header_chunk)
                                bytes_written += len(header_chunk)

                                while True:
                                    if is_stopped_cb and is_stopped_cb():
                                        return False
                                    chunk = f_in.read(2097152)
                                    if not chunk:
                                        break
                                    f_out.write(chunk)
                                    sha.update(chunk)
                                    bytes_written += len(chunk)
                        else:
                            if log_cb and advanced_logs:
                                log_cb(T_cb("log_3ds_twl_raw").format(idx))
                            with reader.open_raw_section(idx) as f_in:
                                while True:
                                    if is_stopped_cb and is_stopped_cb():
                                        return False
                                    chunk = f_in.read(2097152)
                                    if not chunk:
                                        break
                                    f_out.write(chunk)
                                    sha.update(chunk)
                                    bytes_written += len(chunk)

                    written_files[idx] = out_content_path
                    new_hashes[idx] = (sha.digest(), bytes_written)
                    content_size_total += bytes_written
                    content_index[idx >> 3] |= (0x80 >> (idx & 7))

                for i in range(content_count):
                    off = c_offset + (i * 0x30)
                    idx = STRUCT_BE_H.unpack_from(tmd_data, off + 4)[0]
                    ctype = STRUCT_BE_H.unpack_from(tmd_data, off + 6)[0]
                    
                    if idx in new_hashes:
                        ctype &= ~0x0001
                        STRUCT_BE_H.pack_into(tmd_data, off + 6, ctype)
                        STRUCT_BE_Q.pack_into(tmd_data, off + 8, new_hashes[idx][1])
                        tmd_data[off + 0x10 : off + 0x30] = new_hashes[idx][0]

                info_records_offset = tmd_sig_len + 0xC4
                for i in range(64):
                    info_off = info_records_offset + (i * 0x24)
                    cmd_index_offset = STRUCT_BE_H.unpack_from(tmd_data, info_off)[0]
                    cmd_count = STRUCT_BE_H.unpack_from(tmd_data, info_off + 2)[0]
                    if cmd_count > 0:
                        chunk_start = c_offset + (cmd_index_offset * 0x30)
                        chunk_end = chunk_start + (cmd_count * 0x30)
                        tmd_data[info_off + 4 : info_off + 36] = hashlib.sha256(tmd_data[chunk_start:chunk_end]).digest()

                info_records_data = tmd_data[info_records_offset : info_records_offset + 0x900]
                tmd_data[tmd_sig_len + 0xA4 : tmd_sig_len + 0xC4] = hashlib.sha256(info_records_data).digest()

                header = bytearray(CIA_HEADER_SIZE)
                STRUCT_LE_CIA_HDR.pack_into(
                    header, 0, CIA_HEADER_SIZE, 0, 0,
                    len(cert_chain), len(ticket), len(tmd_data), 0, content_size_total
                )
                header[0x20:CIA_HEADER_SIZE] = content_index

                with open(output_cia_path, 'wb') as f_out:
                    f_out.write(header)
                    pad_64(f_out)
                    f_out.write(cert_chain)
                    pad_64(f_out)
                    f_out.write(ticket)
                    pad_64(f_out)
                    f_out.write(tmd_data)
                    pad_64(f_out)
                    
                    for record in reader.content_info:
                        idx = record.cindex
                        file_p = written_files[idx]
                        with open(file_p, "rb") as f_in:
                            while True:
                                chunk = f_in.read(2097152)
                                if not chunk:
                                    break
                                f_out.write(chunk)
                        pad_64(f_out)

            finally:
                shutil.rmtree(tmp_dec_dir, ignore_errors=True)

        return True

    except Exception as e:
        if log_cb: 
            msg = T_cb("log_3ds_err_pyctr").format(str(e)) + f"\n{traceback.format_exc()}"
            log_cb(msg)
        return False

def build_cia(title_id: str, tmd_data: bytes, cetk_data: bytes, app_folder: Path, out_cia_path: Path, T_cb, decrypt: bool = False, boot9_path=None, is_stopped_cb=None, log_cb=None, advanced_logs: bool = False) -> bool:
    target_build_path = out_cia_path.with_suffix(".tmp.cia") if decrypt else out_cia_path
    
    try:
        tik_sig_type = STRUCT_BE_I.unpack_from(cetk_data, 0)[0]
        tik_sig_len = get_sig_len(tik_sig_type)
        tik_chunk_size = tik_sig_len + 0x210
        tik_chunk = cetk_data[:tik_chunk_size]

        xs_len = get_cert_len(cetk_data, tik_chunk_size)
        xs_cert = cetk_data[tik_chunk_size : tik_chunk_size + xs_len]
        ca_len = get_cert_len(cetk_data, tik_chunk_size + xs_len)
        ca_cert = cetk_data[tik_chunk_size + xs_len : tik_chunk_size + xs_len + ca_len]

        tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
        tmd_sig_len = get_sig_len(tmd_sig_type)
        content_count = STRUCT_BE_H.unpack_from(tmd_data, tmd_sig_len + 0x9E)[0]
        tmd_chunk_size = tmd_sig_len + 0x9C4 + (content_count * 0x30)
        
        tmd_mutable = bytearray(tmd_data[:tmd_chunk_size])
        tmd = TMD()
        c_offset = tmd_sig_len + 0x9C4
        
        for i in range(content_count):
            off = c_offset + (i * 0x30)
            c = Content()
            c.id_hex = tmd_data[off : off + 4].hex().lower()
            c.index = STRUCT_BE_H.unpack_from(tmd_data, off + 4)[0]
            ctype = STRUCT_BE_H.unpack_from(tmd_data, off + 6)[0]
            c.is_encrypted = bool(ctype & 0x0001)
            c.size = STRUCT_BE_Q.unpack_from(tmd_data, off + 8)[0]
            tmd.contents.append(c)

        cp_len = get_cert_len(tmd_data, tmd_chunk_size)
        cp_cert = tmd_data[tmd_chunk_size : tmd_chunk_size + cp_len]
        cert_chain = ca_cert + xs_cert + cp_cert 
        
        content_index = bytearray(0x2000)
        content_size = 0
        valid_contents = []
        
        for c in tmd.contents:
            app_path = app_folder / c.id_hex
            try:
                st_size = app_path.stat().st_size
                idx = c.index
                content_index[idx >> 3] |= (0x80 >> (idx & 7))
                content_size += st_size
                valid_contents.append((c, app_path))
            except OSError:
                continue

        valid_contents.sort(key=lambda x: x[0].index)

        header = bytearray(CIA_HEADER_SIZE)
        STRUCT_LE_CIA_HDR.pack_into(
            header, 0, CIA_HEADER_SIZE, 0, 0,
            len(cert_chain), len(tik_chunk), len(tmd_mutable), 0, content_size
        )
        header[0x20:CIA_HEADER_SIZE] = content_index

        if log_cb and advanced_logs: 
            log_cb(T_cb("log_3ds_assembling_enc").format(target_build_path.name))

        with open(target_build_path, "wb") as f_out:
            f_out.write(header)
            pad_64(f_out)
            f_out.write(cert_chain)
            pad_64(f_out)
            f_out.write(tik_chunk)
            pad_64(f_out)
            f_out.write(tmd_mutable)
            pad_64(f_out)
            
            for c, app_path in valid_contents:
                with open(app_path, "rb") as f_app:
                    while True:
                        if is_stopped_cb and is_stopped_cb():
                            return False
                        chunk = f_app.read(2097152)
                        if not chunk:
                            break
                        f_out.write(chunk)
                pad_64(f_out)
                
        if decrypt:
            if log_cb and advanced_logs: 
                log_cb(T_cb("log_3ds_start_decrypt"))
            return _decrypt_cia_with_pyctr(
                input_cia_path=target_build_path, 
                output_cia_path=out_cia_path, 
                T_cb=T_cb,
                boot9_path=boot9_path, 
                log_cb=log_cb,
                advanced_logs=advanced_logs,
                is_stopped_cb=is_stopped_cb
            )

        return True

    except Exception as e:
        if log_cb: 
            msg = T_cb("log_3ds_crash_build").format(str(e)) + f"\n{traceback.format_exc()}"
            log_cb(msg)
        return False

    finally:
        if decrypt and target_build_path.exists():
            try:
                target_build_path.unlink()
            except OSError as cleanup_error:
                if log_cb:
                    log_cb(T_cb("log_3ds_err_purge").format(str(cleanup_error)))

def verify_built_cia(cia_path: Path, T_cb, log_cb=None, advanced_logs: bool = False) -> tuple[bool, str]:
    if not cia_path.exists():
        return False, T_cb("err_cia_not_found_core")
    try:
        actual_file_size = cia_path.stat().st_size
        with open(cia_path, "rb") as f:
            header = f.read(CIA_HEADER_SIZE)

        if len(header) < CIA_HEADER_SIZE:
            return False, T_cb("err_incomplete_header_core")
        header_size, _, _, cert_chain_size, ticket_size, tmd_size, meta_size, content_size = STRUCT_LE_CIA_HDR.unpack_from(header, 0)

        if header_size != CIA_HEADER_SIZE:
            return False, T_cb("err_header_size_core")

        def pad_size(size: int) -> int:
            return (size + 63) & ~63

        expected_total_size = (
            pad_size(header_size)
            + pad_size(cert_chain_size)
            + pad_size(ticket_size)
            + pad_size(tmd_size)
            + pad_size(meta_size)
            + pad_size(content_size)
        )

        if expected_total_size != actual_file_size: 
            return False, T_cb("err_size_mismatch_core").format(actual_file_size, expected_total_size)

        return True, T_cb("msg_valid_structure_core")
    except Exception as e:
        return False, T_cb("err_read_fail_core").format(str(e))