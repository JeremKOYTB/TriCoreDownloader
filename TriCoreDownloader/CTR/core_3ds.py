import os
import struct
import hashlib
import stat
import threading
import traceback
from pathlib import Path

CIA_HEADER_SIZE = 0x2020
PADDING_ALIGNMENT = 64
PAD_ZEROS = b"\x00" * PADDING_ALIGNMENT
IO_BUFFER_SIZE = 4 * 1024 * 1024

STRUCT_BE_I = struct.Struct(">I")
STRUCT_BE_H = struct.Struct(">H")
STRUCT_BE_HH = struct.Struct(">HH")
STRUCT_BE_Q = struct.Struct(">Q")
STRUCT_LE_CIA_HDR = struct.Struct("<IHHIIIIQ")

SIG_LENS = {
    0x00010000: 0x240,
    0x00010003: 0x240,
    0x00010001: 0x140,
    0x00010004: 0x140,
    0x00010002: 0x080,
    0x00010005: 0x080,
}

_THREAD_LOCAL = threading.local()


class Content:
    __slots__ = ("id_hex", "index", "type", "size", "is_encrypted", "sha256")

    def __init__(self):
        self.id_hex = ""
        self.index = 0
        self.type = 0
        self.size = 0
        self.is_encrypted = False
        self.sha256 = b""


class TMD:
    __slots__ = ("title_id", "title_version", "content_count", "contents")

    def __init__(self):
        self.title_id = 0
        self.title_version = 0
        self.content_count = 0
        self.contents = []


def get_sig_len(sig_type: int) -> int:
    return SIG_LENS.get(sig_type, 0x240)


def get_cert_len(data: bytes, offset: int) -> int:
    try:
        if offset < 0 or offset + 4 > len(data):
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


def validate_tmd_and_tik(title_id: str, tmd_data: bytes, cetk_data: bytes, T_cb) -> tuple[TMD, bytes, bytes]:
    if not tmd_data or len(tmd_data) < 0x200:
        raise ValueError(T_cb("err_tmd_invalid"))
    if not cetk_data or len(cetk_data) < 0x200:
        raise ValueError(T_cb("err_tmd_invalid"))

    tik_sig_type = STRUCT_BE_I.unpack_from(cetk_data, 0)[0]
    tik_sig_len = get_sig_len(tik_sig_type)
    tik_chunk_size = tik_sig_len + 0x210
    if len(cetk_data) < tik_chunk_size:
        raise ValueError(T_cb("err_tmd_invalid"))
    tik_chunk = cetk_data[:tik_chunk_size]

    xs_len = get_cert_len(cetk_data, tik_chunk_size)
    xs_cert = cetk_data[tik_chunk_size : tik_chunk_size + xs_len]
    ca_len = get_cert_len(cetk_data, tik_chunk_size + xs_len)
    ca_cert = cetk_data[tik_chunk_size + xs_len : tik_chunk_size + xs_len + ca_len]

    tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
    tmd_sig_len = get_sig_len(tmd_sig_type)
    if len(tmd_data) < tmd_sig_len + 0x9C4:
        raise ValueError(T_cb("err_tmd_invalid"))

    tmd_tid = STRUCT_BE_Q.unpack_from(tmd_data, tmd_sig_len + 0x4C)[0]
    tmd_ver, content_count = STRUCT_BE_HH.unpack_from(tmd_data, tmd_sig_len + 0x9C)
    if content_count <= 0:
        raise ValueError(T_cb("err_tmd_invalid"))

    c_offset = tmd_sig_len + 0x9C4
    tmd_chunk_size = c_offset + (content_count * 0x30)
    if len(tmd_data) < tmd_chunk_size:
        raise ValueError(T_cb("err_tmd_invalid"))

    cp_len = get_cert_len(tmd_data, tmd_chunk_size)
    cp_cert = tmd_data[tmd_chunk_size : tmd_chunk_size + cp_len]
    cert_chain = ca_cert + xs_cert + cp_cert
    if not cert_chain:
        raise ValueError(T_cb("err_tmd_invalid"))

    tmd_obj = TMD()
    tmd_obj.title_id = tmd_tid
    tmd_obj.title_version = tmd_ver
    tmd_obj.content_count = content_count

    for i in range(content_count):
        off = c_offset + (i * 0x30)
        c = Content()
        c.id_hex = tmd_data[off : off + 4].hex().lower()
        c.index, c.type = STRUCT_BE_HH.unpack_from(tmd_data, off + 4)
        c.is_encrypted = bool(c.type & 0x0001)
        c.size = STRUCT_BE_Q.unpack_from(tmd_data, off + 8)[0]
        c.sha256 = tmd_data[off + 0x10 : off + 0x30]
        tmd_obj.contents.append(c)

    return tmd_obj, tik_chunk, cert_chain


def pad_64(f):
    rem = f.tell() & (PADDING_ALIGNMENT - 1)
    if rem:
        f.write(PAD_ZEROS[: PADDING_ALIGNMENT - rem])


def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except Exception:
        pass


def _get_thread_crypto_engine(boot9_path, T_cb, log_cb=None):
    from pyctr.crypto import CryptoEngine
    from pyctr.crypto.engine import BootromNotFoundError

    b9_clean = str(boot9_path).strip("\"'") if boot9_path else ""
    if b9_clean and b9_clean.lower() != "none":
        b9_resolved = str(Path(b9_clean).resolve())
        if not os.path.isfile(b9_resolved):
            if log_cb:
                log_cb(T_cb("err_boot9_missing").format(b9_resolved))
            return None
    else:
        b9_resolved = None

    cached_b9 = getattr(_THREAD_LOCAL, "boot9_path", "__UNSET__")
    cached_engine = getattr(_THREAD_LOCAL, "crypto_engine", None)
    if cached_engine is not None and cached_b9 == b9_resolved:
        return cached_engine

    try:
        engine = CryptoEngine(boot9=b9_resolved) if b9_resolved else CryptoEngine()
        _THREAD_LOCAL.boot9_path = b9_resolved
        _THREAD_LOCAL.crypto_engine = engine
        return engine
    except BootromNotFoundError:
        if log_cb:
            log_cb(T_cb("err_boot9_missing_fatal"))
        return None
    except Exception as e:
        if log_cb:
            log_cb(T_cb("log_3ds_err_pyctr").format(e))
        return None


def _decrypt_cia_with_pyctr(
    input_cia_path: Path,
    output_cia_path: Path,
    T_cb,
    boot9_path=None,
    log_cb=None,
    advanced_logs: bool = False,
    is_stopped_cb=None,
) -> bool:
    try:
        from pyctr.type.cia import CIAReader, CIASection
        from pyctr.type.ncch import NCCHSection
        from pyctr.crypto import Keyslot

        crypto = _get_thread_crypto_engine(boot9_path, T_cb, log_cb)
        if crypto is None:
            return False

        with CIAReader(str(input_cia_path), crypto=crypto) as reader:
            with reader.open_raw_section(CIASection.CertificateChain) as c:
                cert_chain = c.read()
            with reader.open_raw_section(CIASection.Ticket) as c:
                ticket = bytearray(c.read())
            with reader.open_raw_section(CIASection.TitleMetadata) as c:
                tmd_data = bytearray(c.read())

            tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
            tmd_sig_len = get_sig_len(tmd_sig_type)
            tmd_title_ver, content_count = STRUCT_BE_HH.unpack_from(
                tmd_data, tmd_sig_len + 0x9C
            )
            c_offset = tmd_sig_len + 0x9C4

            if log_cb and advanced_logs:
                try:
                    log_cb(
                        T_cb("log_3ds_crypt_proc").format(
                            reader.tmd.title_id.upper(), tmd_title_ver
                        )
                    )
                except IndexError:
                    log_cb(T_cb("log_3ds_crypt_proc").format(reader.tmd.title_id.upper()))

            tik_sig_type = STRUCT_BE_I.unpack_from(ticket, 0)[0]
            tik_sig_len = get_sig_len(tik_sig_type)
            tk_offset = tik_sig_len + 0x7F
            ck_idx_offset = tik_sig_len + 0xB1

            if tk_offset + 16 <= len(ticket):
                if log_cb and advanced_logs:
                    enc_tk_hex = ticket[tk_offset : tk_offset + 16].hex().upper()
                    ck_index = ticket[ck_idx_offset] if ck_idx_offset < len(ticket) else 0
                    try:
                        dec_tk_hex = crypto._normal_keys[Keyslot.DecryptedTitleKey].hex().upper()
                    except Exception:
                        dec_tk_hex = enc_tk_hex

                    try:
                        log_cb(
                            T_cb("log_3ds_title_key").format(
                                ck_index, enc_tk_hex, dec_tk_hex
                            )
                        )
                    except IndexError:
                        log_cb(T_cb("log_3ds_title_key").format(enc_tk_hex))
                ticket[tk_offset : tk_offset + 16] = b"\x00" * 16

            new_hashes = {}
            content_size_total = 0
            content_index = bytearray(0x2000)
            header = bytearray(CIA_HEADER_SIZE)

            with open(output_cia_path, "wb", buffering=IO_BUFFER_SIZE) as f_out:
                f_out.write(header)
                pad_64(f_out)
                f_out.write(cert_chain)
                pad_64(f_out)
                f_out.write(ticket)
                pad_64(f_out)
                tmd_file_offset = f_out.tell()
                f_out.write(tmd_data)
                pad_64(f_out)

                for record in reader.content_info:
                    if is_stopped_cb and is_stopped_cb():
                        return False

                    idx = record.cindex
                    is_ncch = idx in reader.contents
                    sha = hashlib.sha256()
                    bytes_written = 0

                    if is_ncch:
                        content_reader = reader.contents[idx]
                        flags_7_val = 0x04
                        with content_reader.open_raw_section(NCCHSection.FullDecrypted) as f_in:
                            header_chunk = bytearray(f_in.read(0x200))
                            if len(header_chunk) >= 0x200 and header_chunk[0x100:0x104] == b"NCCH":
                                flags_7 = header_chunk[0x18F]
                                flags_7 |= 0x04
                                flags_7 &= ~0x21
                                header_chunk[0x18F] = flags_7
                                header_chunk[0x18B] = 0x00
                                flags_7_val = flags_7

                            f_out.write(header_chunk)
                            sha.update(header_chunk)
                            bytes_written += len(header_chunk)

                            while True:
                                if is_stopped_cb and is_stopped_cb():
                                    return False
                                chunk = f_in.read(IO_BUFFER_SIZE)
                                if not chunk:
                                    break
                                f_out.write(chunk)
                                sha.update(chunk)
                                bytes_written += len(chunk)

                        digest = sha.digest()
                        if log_cb and advanced_logs:
                            try:
                                log_cb(
                                    T_cb("log_3ds_ncch_dec").format(
                                        idx, flags_7_val, bytes_written, digest[:8].hex().upper()
                                    )
                                )
                            except IndexError:
                                pass
                    else:
                        with reader.open_raw_section(idx) as f_in:
                            while True:
                                if is_stopped_cb and is_stopped_cb():
                                    return False
                                chunk = f_in.read(IO_BUFFER_SIZE)
                                if not chunk:
                                    break
                                f_out.write(chunk)
                                sha.update(chunk)
                                bytes_written += len(chunk)

                        digest = sha.digest()
                        if log_cb and advanced_logs:
                            try:
                                log_cb(
                                    T_cb("log_3ds_twl_raw").format(
                                        idx, bytes_written, digest[:8].hex().upper()
                                    )
                                )
                            except IndexError:
                                log_cb(T_cb("log_3ds_twl_raw").format(idx))

                    pad_64(f_out)
                    new_hashes[idx] = (digest, bytes_written)
                    content_size_total += bytes_written
                    content_index[idx >> 3] |= 0x80 >> (idx & 7)

                for i in range(content_count):
                    off = c_offset + (i * 0x30)
                    idx, ctype = STRUCT_BE_HH.unpack_from(tmd_data, off + 4)

                    if idx in new_hashes:
                        ctype &= ~0x0001
                        STRUCT_BE_H.pack_into(tmd_data, off + 6, ctype)
                        STRUCT_BE_Q.pack_into(tmd_data, off + 8, new_hashes[idx][1])
                        tmd_data[off + 0x10 : off + 0x30] = new_hashes[idx][0]

                info_records_offset = tmd_sig_len + 0xC4
                for i in range(64):
                    info_off = info_records_offset + (i * 0x24)
                    cmd_index_offset, cmd_count = STRUCT_BE_HH.unpack_from(tmd_data, info_off)
                    if cmd_count > 0:
                        chunk_start = c_offset + (cmd_index_offset * 0x30)
                        chunk_end = chunk_start + (cmd_count * 0x30)
                        tmd_data[info_off + 4 : info_off + 36] = hashlib.sha256(
                            tmd_data[chunk_start:chunk_end]
                        ).digest()

                info_records_data = tmd_data[info_records_offset : info_records_offset + 0x900]
                tmd_data[tmd_sig_len + 0xA4 : tmd_sig_len + 0xC4] = hashlib.sha256(
                    info_records_data
                ).digest()

                STRUCT_LE_CIA_HDR.pack_into(
                    header,
                    0,
                    CIA_HEADER_SIZE,
                    0,
                    0,
                    len(cert_chain),
                    len(ticket),
                    len(tmd_data),
                    0,
                    content_size_total,
                )
                header[0x20:CIA_HEADER_SIZE] = content_index

                f_out.seek(0)
                f_out.write(header)
                f_out.seek(tmd_file_offset)
                f_out.write(tmd_data)

            if log_cb and advanced_logs:
                try:
                    log_cb(
                        T_cb("log_3ds_tmd_rehashed").format(
                            content_count, output_cia_path.name
                        )
                    )
                except IndexError:
                    pass

        return True

    except Exception as e:
        if log_cb:
            msg = T_cb("log_3ds_err_pyctr").format(str(e)) + f"\n{traceback.format_exc()}"
            log_cb(msg)
        return False


def build_cia(
    title_id: str,
    tmd_data: bytes,
    cetk_data: bytes,
    app_folder: Path,
    out_cia_path: Path,
    T_cb,
    decrypt: bool = False,
    boot9_path=None,
    is_stopped_cb=None,
    log_cb=None,
    advanced_logs: bool = False,
) -> bool:
    target_build_path = out_cia_path.with_suffix(".tmp.cia") if decrypt else out_cia_path

    try:
        reused_existing_cia = False
        if decrypt and out_cia_path.is_file() and out_cia_path.stat().st_size > CIA_HEADER_SIZE:
            try:
                if target_build_path.exists():
                    target_build_path.unlink()
                os.replace(out_cia_path, target_build_path)
                reused_existing_cia = True
            except OSError:
                reused_existing_cia = False

        if not reused_existing_cia:
            tmd, tik_chunk, cert_chain = validate_tmd_and_tik(
                title_id, tmd_data, cetk_data, T_cb
            )

            tmd_sig_type = STRUCT_BE_I.unpack_from(tmd_data, 0)[0]
            tmd_sig_len = get_sig_len(tmd_sig_type)
            tmd_chunk_size = tmd_sig_len + 0x9C4 + (tmd.content_count * 0x30)
            tmd_mutable = tmd_data[:tmd_chunk_size]

            content_index = bytearray(0x2000)
            content_size = 0
            valid_contents = []

            for c in tmd.contents:
                app_path = app_folder / c.id_hex
                try:
                    st_size = app_path.stat().st_size
                    idx = c.index
                    content_index[idx >> 3] |= 0x80 >> (idx & 7)
                    content_size += st_size
                    valid_contents.append((c, app_path))
                except OSError:
                    continue

            if not valid_contents:
                return False

            valid_contents.sort(key=lambda x: x[0].index)

            header = bytearray(CIA_HEADER_SIZE)
            STRUCT_LE_CIA_HDR.pack_into(
                header,
                0,
                CIA_HEADER_SIZE,
                0,
                0,
                len(cert_chain),
                len(tik_chunk),
                len(tmd_mutable),
                0,
                content_size,
            )
            header[0x20:CIA_HEADER_SIZE] = content_index

            if log_cb and advanced_logs:
                try:
                    log_cb(
                        T_cb("log_3ds_assembling_enc").format(
                            target_build_path.name,
                            len(cert_chain),
                            len(tik_chunk),
                            len(tmd_mutable),
                            len(valid_contents),
                            content_size,
                        )
                    )
                except IndexError:
                    log_cb(T_cb("log_3ds_assembling_enc").format(target_build_path.name))

            buf = bytearray(IO_BUFFER_SIZE)
            mv = memoryview(buf)

            with open(target_build_path, "wb", buffering=IO_BUFFER_SIZE) as f_out:
                f_out.write(header)
                pad_64(f_out)
                f_out.write(cert_chain)
                pad_64(f_out)
                f_out.write(tik_chunk)
                pad_64(f_out)
                f_out.write(tmd_mutable)
                pad_64(f_out)

                for _, app_path in valid_contents:
                    with open(app_path, "rb", buffering=IO_BUFFER_SIZE) as f_app:
                        while True:
                            if is_stopped_cb and is_stopped_cb():
                                return False
                            n_read = f_app.readinto(mv)
                            if not n_read:
                                break
                            f_out.write(mv[:n_read])
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
                is_stopped_cb=is_stopped_cb,
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


def verify_built_cia(
    cia_path: Path, T_cb, log_cb=None, advanced_logs: bool = False
) -> tuple[bool, str]:
    if not cia_path.exists():
        return False, T_cb("err_cia_not_found_core")
    try:
        actual_file_size = cia_path.stat().st_size
        with open(cia_path, "rb") as f:
            header = f.read(CIA_HEADER_SIZE)

        if len(header) < CIA_HEADER_SIZE:
            return False, T_cb("err_incomplete_header_core")

        (
            header_size,
            _,
            _,
            cert_chain_size,
            ticket_size,
            tmd_size,
            meta_size,
            content_size,
        ) = STRUCT_LE_CIA_HDR.unpack_from(header, 0)

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
            return (
                False,
                T_cb("err_size_mismatch_core").format(
                    actual_file_size, expected_total_size
                ),
            )

        return True, T_cb("msg_valid_structure_core")
    except Exception as e:
        return False, T_cb("err_read_fail_core").format(str(e))
