# src/Backend/modules/zip_streamer.py

import asyncio
import os
import struct
import time
import zlib
from typing import List, Dict, Any, AsyncGenerator, Optional
from pyrogram import Client

from d4rk.Logs import setup_logger
from .byte_streamer import ByteStreamer

logger = setup_logger("zip_streamer")

MAX_ZIP_PART_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB per part (Google Drive style)


def create_dos_datetime() -> tuple[int, int]:
    """Returns (dos_time, dos_date) for the current local time."""
    t = time.localtime()
    dos_time = (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2)
    dos_date = ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday
    return dos_time, dos_date


def partition_files_for_zip(files: List[Dict[str, Any]], max_part_size: int = MAX_ZIP_PART_SIZE) -> List[List[Dict[str, Any]]]:
    """
    Partitions a list of file documents into chunks each not exceeding max_part_size,
    unless an individual file itself exceeds max_part_size (in which case it gets its own part).
    """
    if not files:
        return []

    parts: List[List[Dict[str, Any]]] = []
    current_part: List[Dict[str, Any]] = []
    current_size = 0

    for f in files:
        f_size = int(f.get("file_size") or 0)
        if current_part and (current_size + f_size > max_part_size):
            parts.append(current_part)
            current_part = [f]
            current_size = f_size
        else:
            current_part.append(f)
            current_size += f_size

    if current_part:
        parts.append(current_part)

    return parts


async def generate_zip_stream(
    files_with_arcnames: List[Dict[str, Any]],
    byte_streamer: ByteStreamer,
    active_clients: Optional[List[Client]] = None
) -> AsyncGenerator[bytes, None]:
    """
    Asynchronously streams a complete, valid ZIP archive on-the-fly directly to the HTTP client.
    Each item in files_with_arcnames is:
    {
        'arcname': str,  # Path inside zip, e.g. 'Movies/clip.mp4'
        'doc': dict      # MongoDB document for the file
    }
    """
    dos_time, dos_date = create_dos_datetime()
    cd_entries = []
    current_offset = 0

    for item in files_with_arcnames:
        arcname = item["arcname"].replace("\\", "/").strip("/")
        doc = item["doc"]
        name_bytes = arcname.encode("utf-8")
        local_header_offset = current_offset

        # Local file header (bit 3 set in general purpose flag means CRC-32 and sizes are in data descriptor)
        # 4s (magic), H (ver 20), H (flags 0x08), H (comp 0=stored), H (time), H (date),
        # I (crc 0), I (comp 0), I (uncomp 0), H (name len), H (extra len 0)
        local_header = struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04",
            20,            # version 2.0
            0x08,          # bit 3: data descriptor follows
            0,             # ZIP_STORED (no re-compression, instant Telegram streaming)
            dos_time,
            dos_date,
            0, 0, 0,
            len(name_bytes),
            0
        ) + name_bytes

        current_offset += len(local_header)
        yield local_header

        crc = 0
        file_bytes_written = 0
        file_size = int(doc.get("file_size") or 0)

        # Prepare Telegram streaming parts
        chat_id = doc.get("chat_id")
        message_id = doc.get("message_id")
        is_split = doc.get("is_split", False)
        parts_list = doc.get("parts") if is_split else None

        if file_size > 0 and chat_id and (message_id or parts_list):
            if not parts_list:
                parts_to_stream = [{
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "part_from_byte": 0,
                    "part_until_byte": file_size - 1,
                    "part_index": 1,
                }]
            else:
                parts_to_stream = []
                for p in parts_list:
                    p_size = p.get("part_size", 0)
                    if p_size > 0:
                        parts_to_stream.append({
                            "chat_id": p.get("chat_id", chat_id),
                            "message_id": p.get("message_id"),
                            "part_from_byte": 0,
                            "part_until_byte": p_size - 1,
                            "part_index": p.get("part_index", 1),
                        })

            try:
                chunk_size = 1024 * 1024  # 1MB chunks
                async for chunk in byte_streamer.yield_parts(parts_to_stream, chunk_size, client_list=active_clients):
                    if not chunk:
                        continue
                    crc = zlib.crc32(chunk, crc)
                    file_bytes_written += len(chunk)
                    current_offset += len(chunk)
                    yield chunk
            except (asyncio.CancelledError, ConnectionResetError):
                logger.info(f"Client aborted download while streaming {arcname}")
                raise
            except Exception as e:
                logger.error(f"Error streaming file {arcname} from Telegram: {e}")
                # We do not crash the entire zip; data descriptor will finalize whatever was written

        # Data descriptor
        # If size < 4GB: struct '<4sIII' (magic, crc, comp_size, uncomp_size)
        # If size >= 4GB (Zip64 descriptor): struct '<4sIQQ'
        if file_bytes_written < 0xFFFFFFFF and local_header_offset < 0xFFFFFFFF:
            descriptor = struct.pack(
                "<4sIII",
                b"PK\x07\x08",
                crc,
                file_bytes_written,
                file_bytes_written
            )
            extra_cd = b""
        else:
            # Zip64 data descriptor
            descriptor = struct.pack(
                "<4sIQQ",
                b"PK\x07\x08",
                crc,
                file_bytes_written,
                file_bytes_written
            )
            extra_cd = struct.pack(
                "<HHQQ",
                0x0001,
                16,
                file_bytes_written,
                file_bytes_written
            )

        current_offset += len(descriptor)
        yield descriptor

        cd_entries.append({
            "name_bytes": name_bytes,
            "crc": crc,
            "size": file_bytes_written,
            "offset": local_header_offset,
            "extra_cd": extra_cd,
            "dos_time": dos_time,
            "dos_date": dos_date,
        })

    # Write Central Directory at the end
    cd_start_offset = current_offset
    cd_buffer = bytearray()

    for entry in cd_entries:
        extra = entry["extra_cd"]
        size_field = min(entry["size"], 0xFFFFFFFF)
        offset_field = min(entry["offset"], 0xFFFFFFFF)
        version_needed = 45 if extra else 20

        cd_header = struct.pack(
            "<4sHHHHHHIIIHHHHHII",
            b"PK\x01\x02",
            version_needed, # version made by
            version_needed, # version needed to extract
            0x08,           # general purpose bit flag
            0,              # compression method: stored
            entry["dos_time"],
            entry["dos_date"],
            entry["crc"],
            size_field,
            size_field,
            len(entry["name_bytes"]),
            len(extra),
            0,              # comment len
            0,              # disk number start
            0,              # internal file attributes
            0o644 << 16,    # external file attributes
            offset_field
        ) + entry["name_bytes"] + extra
        cd_buffer.extend(cd_header)

    cd_size = len(cd_buffer)
    current_offset += cd_size

    # Check if Zip64 End of Central Directory is needed
    needs_zip64 = (
        current_offset >= 0xFFFFFFFF
        or cd_start_offset >= 0xFFFFFFFF
        or cd_size >= 0xFFFFFFFF
        or len(cd_entries) >= 0xFFFF
    )

    if needs_zip64:
        # Zip64 End of Central Directory Record
        z64_eocd = struct.pack(
            "<4sQHHIIQQQQ",
            b"PK\x06\x06",
            44,             # size of remaining record
            45, 45,         # version made by & needed
            0, 0,           # disk numbers
            len(cd_entries),
            len(cd_entries),
            cd_size,
            cd_start_offset
        )
        z64_eocd_offset = current_offset
        cd_buffer.extend(z64_eocd)
        current_offset += len(z64_eocd)

        # Zip64 End of Central Directory Locator
        z64_locator = struct.pack(
            "<4sIIQ",
            b"PK\x06\x07",
            0,              # disk with Zip64 EOCD
            z64_eocd_offset,
            1               # total disks
        )
        cd_buffer.extend(z64_locator)
        current_offset += len(z64_locator)

        # Standard EOCD with 0xFFFF / 0xFFFFFFFF placeholders
        eocd = struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0, 0,
            0xFFFF, 0xFFFF,
            0xFFFFFFFF, 0xFFFFFFFF,
            0
        )
        cd_buffer.extend(eocd)
    else:
        # Standard EOCD
        eocd = struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0, 0,
            len(cd_entries),
            len(cd_entries),
            cd_size,
            cd_start_offset,
            0
        )
        cd_buffer.extend(eocd)

    yield bytes(cd_buffer)
