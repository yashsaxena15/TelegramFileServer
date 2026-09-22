# src/Backend/modules/cloud_archive.py

import os
import io
import uuid
import shutil
import zipfile
import tarfile
import tempfile
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from bson import ObjectId
from pyrogram import Client

from d4rk.Logs import setup_logger
from src.Database import database
from src.Config import LOGS, MOVIE
from .byte_streamer import ByteStreamer
from .priority_manager import priority_manager

logger = setup_logger("cloud_archive")

TEMP_ARCHIVE_DIR = "/home/ubuntu/projects/TelegramFileServer/src/Backend/temp_archives"
os.makedirs(TEMP_ARCHIVE_DIR, exist_ok=True)


def get_safe_arcname(name: str) -> str:
    """Sanitizes archive member name to prevent directory traversal."""
    clean = os.path.normpath(name).lstrip("/\\")
    if clean.startswith("..") or ".." in clean.split(os.sep):
        return os.path.basename(name)
    return clean


async def download_file_to_temp(
    chat_id: int,
    message_id: int,
    file_size: int,
    byte_streamer: ByteStreamer,
    dest_path: str,
    active_clients: Optional[List[Client]] = None,
    parts_list: Optional[List[Dict[str, Any]]] = None,
    progress_cb: Optional[Any] = None,
    cancel_event: Optional[asyncio.Event] = None
):
    """Downloads a file from Telegram using ByteStreamer chunks into a local temp file."""
    if parts_list:
        parts_to_stream = []
        for p in parts_list:
            p_size = p.get("part_size", 0)
            parts_to_stream.append({
                "chat_id": p.get("chat_id", chat_id),
                "message_id": p.get("message_id", message_id),
                "part_from_byte": 0,
                "part_until_byte": p_size - 1,
                "part_index": p.get("part_index", 1)
            })
    else:
        parts_to_stream = [{
            "chat_id": chat_id,
            "message_id": message_id,
            "part_from_byte": 0,
            "part_until_byte": file_size - 1,
            "part_index": 1
        }]

    downloaded = 0
    with open(dest_path, "wb") as f:
        async for chunk in byte_streamer.yield_parts(parts_to_stream, chunk_size=1024 * 1024, client_list=active_clients):
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Download cancelled by user")
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, file_size)


def parse_7z_list_output(stdout: str) -> List[Dict[str, Any]]:
    """Parses output from '7z l -slt' into structured file information."""
    files_list = []
    current_entry = {}

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            if current_entry and "Path" in current_entry:
                raw_path = current_entry["Path"]
                is_dir = current_entry.get("Folder") == "+"
                safe_name = get_safe_arcname(raw_path)
                size = int(current_entry.get("Size") or 0)
                c_size = int(current_entry.get("Packed Size") or 0)
                dt = current_entry.get("Modified", "")
                files_list.append({
                    "name": safe_name,
                    "is_dir": is_dir,
                    "size": size,
                    "compressed_size": c_size,
                    "date_time": dt
                })
                current_entry = {}
            continue

        if "=" in line:
            parts = line.split("=", 1)
            current_entry[parts[0].strip()] = parts[1].strip()

    if current_entry and "Path" in current_entry:
        raw_path = current_entry["Path"]
        is_dir = current_entry.get("Folder") == "+"
        files_list.append({
            "name": get_safe_arcname(raw_path),
            "is_dir": is_dir,
            "size": int(current_entry.get("Size") or 0),
            "compressed_size": int(current_entry.get("Packed Size") or 0),
            "date_time": current_entry.get("Modified", "")
        })

    return files_list


async def inspect_archive(
    chat_id: int,
    message_id: int,
    file_size: int,
    byte_streamer: ByteStreamer,
    active_clients: Optional[List[Client]] = None,
    parts_list: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Universal archive inspection supporting .zip, .rar, .7z, .tar, .gz, etc.
    Extracts metadata without extracting to Telegram.
    """
    temp_archive = os.path.join(TEMP_ARCHIVE_DIR, f"inspect_{uuid.uuid4().hex}")
    try:
        await download_file_to_temp(chat_id, message_id, file_size, byte_streamer, temp_archive, active_clients, parts_list)

        # 1. Try 7z l -slt (supports .zip, .rar, .7z, .tar, .gz, .bz2, etc.)
        try:
            proc = await asyncio.create_subprocess_exec(
                "7z", "l", "-slt", temp_archive,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                files_list = parse_7z_list_output(stdout.decode("utf-8", errors="replace"))
                if files_list:
                    total_uncompressed = sum(f["size"] for f in files_list if not f["is_dir"])
                    return {
                        "is_valid": True,
                        "total_files": len(files_list),
                        "total_uncompressed_size": total_uncompressed,
                        "files": files_list
                    }
        except Exception as e7:
            logger.warning(f"7z inspect failed: {e7}, falling back to python libraries")

        # 2. Fallback to zipfile
        if zipfile.is_zipfile(temp_archive):
            files_list = []
            total_uncompressed = 0
            with zipfile.ZipFile(temp_archive, "r") as zf:
                for info in zf.infolist():
                    is_dir = info.is_dir() or info.filename.endswith("/")
                    safe_name = get_safe_arcname(info.filename)
                    total_uncompressed += info.file_size
                    files_list.append({
                        "name": safe_name,
                        "is_dir": is_dir,
                        "size": info.file_size,
                        "compressed_size": info.compress_size,
                        "date_time": f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d} {info.date_time[3]:02d}:{info.date_time[4]:02d}:{info.date_time[5]:02d}"
                    })
            return {
                "is_valid": True,
                "total_files": len(files_list),
                "total_uncompressed_size": total_uncompressed,
                "files": files_list
            }

        # 3. Fallback to tarfile
        if tarfile.is_tarfile(temp_archive):
            files_list = []
            total_uncompressed = 0
            with tarfile.open(temp_archive, "r:*") as tf:
                for member in tf.getmembers():
                    is_dir = member.isdir()
                    safe_name = get_safe_arcname(member.name)
                    total_uncompressed += member.size
                    files_list.append({
                        "name": safe_name,
                        "is_dir": is_dir,
                        "size": member.size,
                        "compressed_size": member.size,
                        "date_time": ""
                    })
            return {
                "is_valid": True,
                "total_files": len(files_list),
                "total_uncompressed_size": total_uncompressed,
                "files": files_list
            }

        return {"is_valid": False, "error": "Unsupported or corrupted archive format", "files": []}

    except Exception as e:
        logger.error(f"Error inspecting archive: {e}", exc_info=True)
        return {"is_valid": False, "error": str(e), "files": []}
    finally:
        if os.path.exists(temp_archive):
            try:
                os.remove(temp_archive)
            except Exception:
                pass


async def extract_with_7z_or_fallback(archive_path: str, extract_dir: str) -> bool:
    """
    Extracts an archive using 7z at low CPU priority (nice -n 10) to protect 1 vCPU,
    with fallbacks to Python's zipfile and tarfile modules.
    """
    # 1. Try 7z with nice -n 10
    try:
        proc = await asyncio.create_subprocess_exec(
            "nice", "-n", "10", "7z", "x", "-y", f"-o{extract_dir}", archive_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            logger.info(f"Successfully extracted {archive_path} via 7z")
            return True
        logger.warning(f"7z extraction returned {proc.returncode}: {stderr.decode(errors='ignore')}")
    except Exception as e:
        logger.warning(f"Failed to run 7z: {e}")

    # 2. Fallback: Python zipfile
    if zipfile.is_zipfile(archive_path):
        logger.info(f"Extracting {archive_path} using python zipfile...")
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)
        return True

    # 3. Fallback: Python tarfile
    if tarfile.is_tarfile(archive_path):
        logger.info(f"Extracting {archive_path} using python tarfile...")
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(extract_dir)
        return True

    raise ValueError("Archive extraction failed: Format unrecognized or extraction utility failed.")


async def execute_task_extract(task_id: str, payload: Dict[str, Any], manager: Any):
    """
    Executes a background extraction task:
    1. Downloads archive from Telegram.
    2. Extracts using 7z (nice -n 10).
    3. IMMEDIATELY deletes archive to free 25 GB on disk!
    4. Uploads extracted files one-by-one to Telegram (multi-part if > 1.95 GB).
    5. IMMEDIATELY deletes each extracted file from disk after upload.
    """
    file_doc = payload["file_doc"]
    target_path = payload["target_path"]
    user_id = payload["user_id"]
    bot_manager = payload.get("bot_manager")

    chat_id = int(file_doc["chat_id"])
    message_id = int(file_doc["message_id"])
    file_size = int(file_doc.get("file_size") or 0)
    archive_name = file_doc.get("file_name", "archive.zip")

    clean_target = target_path.rstrip("/")
    if not clean_target:
        clean_target = "/Home"

    temp_archive = os.path.join(TEMP_ARCHIVE_DIR, f"task_{task_id}_archive")
    extract_dir = os.path.join(TEMP_ARCHIVE_DIR, f"task_{task_id}_dir")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        active_clients = [c for c in getattr(bot_manager, 'client_list', []) if getattr(c, 'is_connected', True)]
        if not active_clients and hasattr(bot_manager, 'get_least_busy_client'):
            fallback_c = bot_manager.get_least_busy_client()
            if fallback_c:
                active_clients = [fallback_c]
        primary_client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
        if not primary_client and active_clients:
            primary_client = active_clients[0]

        byte_streamer = ByteStreamer(primary_client)
        parts_list = file_doc.get("parts") if file_doc.get("is_split") else None

        # Stage 1: Downloading
        manager.update_task_progress(
            task_id,
            stage="downloading",
            progress_percent=5.0,
            current_file=archive_name,
            total_bytes=file_size
        )

        def on_dl_progress(downloaded_bytes: int, total_b: int):
            if total_b > 0:
                pct = 5.0 + (downloaded_bytes / total_b) * 35.0  # 5% to 40%
                manager.update_task_progress(task_id, progress_percent=pct, processed_bytes=downloaded_bytes)

        cancel_ev = manager._cancel_events.get(task_id)
        await download_file_to_temp(
            chat_id, message_id, file_size, byte_streamer,
            temp_archive, active_clients, parts_list,
            progress_cb=on_dl_progress, cancel_event=cancel_ev
        )

        if manager.is_cancelled(task_id):
            raise asyncio.CancelledError("Task cancelled by user")

        # Stage 2: Extracting (nice -n 10)
        manager.update_task_progress(task_id, stage="extracting", progress_percent=42.0)
        await extract_with_7z_or_fallback(temp_archive, extract_dir)

        # DISK RESCUE: Immediately delete downloaded archive file right after unpacking!
        if os.path.exists(temp_archive):
            try:
                os.remove(temp_archive)
                logger.info(f"[DISK_OPTIMIZATION] Removed temp archive {temp_archive} after extraction to reclaim disk space.")
            except Exception as e:
                logger.warning(f"Failed to remove temp archive: {e}")

        if manager.is_cancelled(task_id):
            raise asyncio.CancelledError("Task cancelled by user")

        # Stage 3: Uploading & Indexing
        manager.update_task_progress(task_id, stage="uploading", progress_percent=45.0)

        # Collect all extracted files
        all_extracted = []
        for root, dirs, files in os.walk(extract_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                all_extracted.append((root, fname, fpath))

        total_files = len(all_extracted)
        total_extracted_bytes = sum(os.path.getsize(fp) for _, _, fp in all_extracted if os.path.exists(fp))
        manager.update_task_progress(task_id, total_files=total_files, total_bytes=total_extracted_bytes)

        storage_chat_id = LOGS or MOVIE or chat_id
        extracted_files_count = 0
        extracted_folders_count = 0
        uploaded_bytes_total = 0

        # Handle folders first
        for root, dirs, files in os.walk(extract_dir):
            rel_dir = os.path.relpath(root, extract_dir)
            if rel_dir != ".":
                current_cloud_path = f"{clean_target}/{rel_dir.replace(os.sep, '/')}"
                folder_name = os.path.basename(root)
                parent_path = os.path.dirname(current_cloud_path) or "/"
                existing = database.Files.find_one({
                    "file_name": folder_name,
                    "file_path": parent_path,
                    "file_type": "folder",
                    "owner_id": user_id,
                    "trashed": {"$ne": True}
                })
                if not existing:
                    database.Files.insert_one({
                        "file_name": folder_name,
                        "file_path": parent_path,
                        "file_type": "folder",
                        "owner_id": user_id,
                        "file_size": 0,
                        "chat_id": 0,
                        "message_id": 0
                    })
                    extracted_folders_count += 1

        # Upload files one by one with rolling disk deletion
        for idx, (root, fname, full_path) in enumerate(all_extracted, 1):
            if manager.is_cancelled(task_id):
                raise asyncio.CancelledError("Task cancelled by user")

            # QoS pause check
            while priority_manager.is_user_upload_active():
                if manager.is_cancelled(task_id):
                    raise asyncio.CancelledError("Task cancelled by user")
                priority_manager.wait_if_user_upload_active(timeout=1.0)

            if not os.path.exists(full_path):
                continue

            file_sz = os.path.getsize(full_path)
            rel_dir = os.path.relpath(root, extract_dir)
            if rel_dir == ".":
                file_cloud_path = clean_target
            else:
                file_cloud_path = f"{clean_target}/{rel_dir.replace(os.sep, '/')}"

            manager.update_task_progress(
                task_id,
                current_file=fname,
                processed_files=idx - 1,
                progress_percent=45.0 + ((idx - 1) / max(1, total_files)) * 53.0
            )

            c = bot_manager.get_least_busy_client() or primary_client
            ext = os.path.splitext(fname)[1].lower()
            file_type = "document"
            if ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv']:
                file_type = "video"
            elif ext in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
                file_type = "audio"
            elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
                file_type = "photo"

            # Check if file exceeds 1.95 GB (Telegram limit)
            if file_sz > 1950 * 1024 * 1024:
                # Multi-part chunked upload
                from .pipeline_uploader import upload_part_task
                chunk_size = 1950 * 1024 * 1024
                upload_tasks = []
                part_index = 1
                start_byte = 0

                with open(full_path, "rb") as f_in:
                    while start_byte < file_sz:
                        part_file_path = f"{full_path}.part{part_index}"
                        bytes_to_read = min(chunk_size, file_sz - start_byte)
                        read_so_far = 0
                        with open(part_file_path, "wb") as f_out:
                            while read_so_far < bytes_to_read:
                                chunk = f_in.read(min(8 * 1024 * 1024, bytes_to_read - read_so_far))
                                if not chunk:
                                    break
                                f_out.write(chunk)
                                read_so_far += len(chunk)
                        curr_part_size = read_so_far
                        if curr_part_size > 0:
                            task = asyncio.create_task(
                                upload_part_task(
                                    part_file_path=part_file_path,
                                    part_index=part_index,
                                    file_name=fname,
                                    start_byte=start_byte,
                                    part_size=curr_part_size,
                                    chat_id=storage_chat_id,
                                    bot_manager=bot_manager,
                                    fallback_client=primary_client,
                                    caption=f"{fname} (Part {part_index})",
                                    is_single_part=False,
                                    file_type=file_type
                                )
                            )
                            upload_tasks.append(task)
                            start_byte += curr_part_size
                            part_index += 1
                        else:
                            if os.path.exists(part_file_path):
                                try:
                                    os.remove(part_file_path)
                                except Exception:
                                    pass
                            break

                results = await asyncio.gather(*upload_tasks)
                results.sort(key=lambda x: x["part_index"])
                first_res = results[0]
                first_unique_id = first_res["file_unique_id"] or f"ext_{uuid.uuid4().hex}"
                first_thumbnail = next((r["thumbnail"] for r in results if r.get("thumbnail")), None)

                parts = [
                    {
                        "part_index": r["part_index"],
                        "chat_id": r["chat_id"],
                        "message_id": r["message_id"],
                        "file_unique_id": r["file_unique_id"],
                        "part_size": r["part_size"],
                        "start_byte": r["start_byte"],
                        "end_byte": r["end_byte"]
                    }
                    for r in results
                ]

                database.Files.add_multipart_file(
                    chat_id=storage_chat_id,
                    thumbnail=first_thumbnail,
                    file_type=file_type,
                    file_unique_id=first_unique_id,
                    file_size=file_sz,
                    file_name=fname,
                    file_caption=f"Extracted: {fname}",
                    parts=parts,
                    file_path=file_cloud_path,
                    owner_id=user_id,
                    part_size=chunk_size
                )
            else:
                # Single part upload
                sent_msg = None
                try:
                    if file_type == "photo" and file_sz <= 10 * 1024 * 1024:
                        sent_msg = await c.send_photo(chat_id=storage_chat_id, photo=full_path, caption=f"Extracted: {fname}")
                    elif file_type == "video" and file_sz <= 50 * 1024 * 1024:
                        sent_msg = await c.send_video(chat_id=storage_chat_id, video=full_path, caption=f"Extracted: {fname}")
                    elif file_type == "audio" and file_sz <= 50 * 1024 * 1024:
                        sent_msg = await c.send_audio(chat_id=storage_chat_id, audio=full_path, caption=f"Extracted: {fname}")
                    else:
                        sent_msg = await c.send_document(chat_id=storage_chat_id, document=full_path, caption=f"Extracted: {fname}", force_document=True)
                except Exception as ex:
                    logger.warning(f"Failed to upload {fname} as {file_type}, retrying as document: {ex}")
                    sent_msg = await c.send_document(chat_id=storage_chat_id, document=full_path, caption=f"Extracted: {fname}", force_document=True)

                if sent_msg:
                    media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo
                    thumbnail = None
                    if hasattr(media, 'thumbs') and media.thumbs:
                        thumbnail = media.thumbs[0].file_id
                    elif hasattr(media, 'file_id') and sent_msg.photo:
                        thumbnail = media.file_id

                    database.Files.add_file(
                        chat_id=sent_msg.chat.id,
                        message_id=sent_msg.id,
                        thumbnail=thumbnail,
                        file_type=file_type,
                        file_unique_id=media.file_unique_id,
                        file_size=file_sz,
                        file_name=fname,
                        file_caption=f"Extracted: {fname}",
                        file_path=file_cloud_path,
                        owner_id=user_id
                    )

            extracted_files_count += 1
            uploaded_bytes_total += file_sz
            manager.update_task_progress(
                task_id,
                processed_files=extracted_files_count,
                processed_bytes=uploaded_bytes_total
            )

            # DISK RESCUE: Immediately delete each extracted file after it is successfully uploaded!
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception:
                pass

        manager.update_task_progress(task_id, stage="completed", progress_percent=100.0, processed_files=total_files)

    finally:
        if os.path.exists(temp_archive):
            try:
                os.remove(temp_archive)
            except Exception:
                pass
        if os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass


async def execute_task_compress(task_id: str, payload: Dict[str, Any], manager: Any):
    """
    Executes a background compression task:
    1. Collects all items to compress.
    2. Downloads each item and adds to archive (nice -n 10).
    3. Deletes item temp file immediately.
    4. Uploads archive to Telegram (multi-part split with backpressure if > 1.95 GB).
    """
    item_ids = payload["item_ids"]
    destination_path = payload["destination_path"]
    zip_name = payload["zip_name"]
    user_id = payload["user_id"]
    bot_manager = payload.get("bot_manager")

    if not zip_name.lower().endswith((".zip", ".tar.gz", ".tgz", ".7z")):
        zip_name += ".zip"

    clean_dest = destination_path.rstrip("/")
    if not clean_dest:
        clean_dest = "/Home"

    temp_zip = os.path.join(TEMP_ARCHIVE_DIR, f"task_{task_id}_{zip_name}")

    active_clients = [c for c in getattr(bot_manager, 'client_list', []) if getattr(c, 'is_connected', True)]
    if not active_clients and hasattr(bot_manager, 'get_least_busy_client'):
        fallback_c = bot_manager.get_least_busy_client()
        if fallback_c:
            active_clients = [fallback_c]
    primary_client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
    if not primary_client and active_clients:
        primary_client = active_clients[0]

    byte_streamer = ByteStreamer(primary_client)

    # Collect items
    files_to_compress = []
    for item_id in item_ids:
        doc = None
        try:
            doc = database.Files.find_one({"_id": ObjectId(item_id)})
        except Exception:
            pass
        if not doc:
            doc = database.Files.find_one({"$or": [{"file_unique_id": item_id}, {"file_name": item_id}]})
        if not doc:
            continue

        if doc.get("file_type") == "folder":
            folder_name = doc.get("file_name")
            folder_path = doc.get("file_path", "/")
            target_base = f"{folder_path.rstrip('/')}/{folder_name}".lstrip("/")
            regex_pattern = f"^{folder_path.rstrip('/')}/{folder_name}(/.*)?$"
            child_files = list(database.Files.find({
                "file_path": {"$regex": regex_pattern},
                "file_type": {"$ne": "folder"},
                "trashed": {"$ne": True}
            }))
            for cf in child_files:
                cf_path = cf.get("file_path", "").lstrip("/")
                rel_prefix = cf_path[len(target_base):].lstrip("/")
                arcname = os.path.join(folder_name, rel_prefix, cf.get("file_name", "file"))
                files_to_compress.append({"doc": cf, "arcname": arcname.replace("\\", "/")})
        else:
            files_to_compress.append({"doc": doc, "arcname": doc.get("file_name", "file")})

    if not files_to_compress:
        raise ValueError("No files found to compress.")

    total_files = len(files_to_compress)
    total_uncompressed_bytes = sum(int(it["doc"].get("file_size") or 0) for it in files_to_compress)
    manager.update_task_progress(
        task_id,
        stage="compressing",
        progress_percent=5.0,
        total_files=total_files,
        total_bytes=total_uncompressed_bytes
    )

    try:
        # Create ZIP archive
        processed_bytes = 0
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for idx, item in enumerate(files_to_compress, 1):
                if manager.is_cancelled(task_id):
                    raise asyncio.CancelledError("Task cancelled by user")

                f_doc = item["doc"]
                arcname = item["arcname"]
                f_size = int(f_doc.get("file_size") or 0)
                c_id = int(f_doc["chat_id"])
                m_id = int(f_doc["message_id"])

                manager.update_task_progress(
                    task_id,
                    current_file=arcname,
                    processed_files=idx - 1,
                    progress_percent=5.0 + ((idx - 1) / max(1, total_files)) * 45.0
                )

                temp_f = os.path.join(TEMP_ARCHIVE_DIR, f"task_{task_id}_part_{uuid.uuid4().hex}")
                try:
                    p_list = f_doc.get("parts") if f_doc.get("is_split") else None
                    await download_file_to_temp(c_id, m_id, f_size, byte_streamer, temp_f, active_clients, p_list)
                    zf.write(temp_f, arcname)
                    processed_bytes += f_size
                    manager.update_task_progress(task_id, processed_bytes=processed_bytes)
                finally:
                    if os.path.exists(temp_f):
                        try:
                            os.remove(temp_f)
                        except Exception:
                            pass

        if manager.is_cancelled(task_id):
            raise asyncio.CancelledError("Task cancelled by user")

        # Stage 2: Upload archive to Telegram
        total_zip_size = os.path.getsize(temp_zip)
        storage_chat_id = LOGS or MOVIE or files_to_compress[0]["doc"].get("chat_id")
        manager.update_task_progress(task_id, stage="uploading", progress_percent=52.0, total_bytes=total_zip_size)

        if total_zip_size > 1950 * 1024 * 1024:
            # Multi-part split upload with backpressure
            from .pipeline_uploader import upload_part_task
            chunk_size = 1950 * 1024 * 1024
            upload_tasks = []
            part_index = 1
            start_byte = 0

            with open(temp_zip, "rb") as f_in:
                while start_byte < total_zip_size:
                    if manager.is_cancelled(task_id):
                        raise asyncio.CancelledError("Task cancelled by user")

                    while priority_manager.is_user_upload_active():
                        priority_manager.wait_if_user_upload_active(timeout=1.0)

                    part_file_path = f"{temp_zip}.part{part_index}"
                    bytes_to_read = min(chunk_size, total_zip_size - start_byte)
                    read_so_far = 0
                    with open(part_file_path, "wb") as f_out:
                        while read_so_far < bytes_to_read:
                            chunk = f_in.read(min(8 * 1024 * 1024, bytes_to_read - read_so_far))
                            if not chunk:
                                break
                            f_out.write(chunk)
                            read_so_far += len(chunk)

                    curr_part_size = read_so_far
                    if curr_part_size > 0:
                        task = asyncio.create_task(
                            upload_part_task(
                                part_file_path=part_file_path,
                                part_index=part_index,
                                file_name=zip_name,
                                start_byte=start_byte,
                                part_size=curr_part_size,
                                chat_id=storage_chat_id,
                                bot_manager=bot_manager,
                                fallback_client=primary_client,
                                caption=f"{zip_name} (Part {part_index})",
                                is_single_part=False,
                                file_type="document"
                            )
                        )
                        upload_tasks.append(task)
                        start_byte += curr_part_size
                        part_index += 1
                        manager.update_task_progress(
                            task_id,
                            processed_bytes=start_byte,
                            progress_percent=52.0 + (start_byte / total_zip_size) * 45.0
                        )
                    else:
                        if os.path.exists(part_file_path):
                            try:
                                os.remove(part_file_path)
                            except Exception:
                                pass
                        break

            results = await asyncio.gather(*upload_tasks)
            results.sort(key=lambda x: x["part_index"])
            first_res = results[0]
            first_unique_id = first_res["file_unique_id"] or f"archive_{uuid.uuid4().hex}"
            first_thumbnail = next((r["thumbnail"] for r in results if r.get("thumbnail")), None)

            parts = [
                {
                    "part_index": r["part_index"],
                    "chat_id": r["chat_id"],
                    "message_id": r["message_id"],
                    "file_unique_id": r["file_unique_id"],
                    "part_size": r["part_size"],
                    "start_byte": r["start_byte"],
                    "end_byte": r["end_byte"]
                }
                for r in results
            ]

            database.Files.add_multipart_file(
                chat_id=storage_chat_id,
                thumbnail=first_thumbnail,
                file_type="document",
                file_unique_id=first_unique_id,
                file_size=total_zip_size,
                file_name=zip_name,
                file_caption=f"Archive: {zip_name}",
                parts=parts,
                file_path=clean_dest,
                owner_id=user_id,
                part_size=chunk_size
            )
        else:
            sent_msg = await primary_client.send_document(
                chat_id=storage_chat_id,
                document=temp_zip,
                caption=f"Archive: {zip_name}",
                force_document=True
            )

            if not sent_msg or not sent_msg.document:
                raise RuntimeError("Failed to upload created ZIP archive to Telegram.")

            doc_info = sent_msg.document
            thumbnail = doc_info.thumbs[0].file_id if doc_info.thumbs else None

            database.Files.add_file(
                chat_id=sent_msg.chat.id,
                message_id=sent_msg.id,
                thumbnail=thumbnail,
                file_type="document",
                file_unique_id=doc_info.file_unique_id,
                file_size=total_zip_size,
                file_name=zip_name,
                file_caption=f"Archive: {zip_name}",
                file_path=clean_dest,
                owner_id=user_id
            )

        manager.update_task_progress(task_id, stage="completed", progress_percent=100.0)

    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass


# Backward compatibility wrappers
async def extract_archive_in_cloud(
    file_doc: Dict[str, Any],
    target_path: str,
    byte_streamer: ByteStreamer,
    bot_manager: Any,
    user_id: str
) -> Dict[str, Any]:
    from .archive_task_manager import archive_task_manager
    task_id = archive_task_manager.create_task(
        task_type="extract",
        user_id=user_id,
        target_name=file_doc.get("file_name", "archive.zip"),
        payload={
            "file_doc": file_doc,
            "target_path": target_path,
            "user_id": user_id,
            "bot_manager": bot_manager
        }
    )
    return {"task_id": task_id, "status": "queued", "message": "Extraction started in background"}


async def compress_items_to_zip(
    item_ids: List[str],
    destination_path: str,
    zip_name: str,
    byte_streamer: ByteStreamer,
    bot_manager: Any,
    user_id: str
) -> Dict[str, Any]:
    from .archive_task_manager import archive_task_manager
    task_id = archive_task_manager.create_task(
        task_type="compress",
        user_id=user_id,
        target_name=zip_name,
        payload={
            "item_ids": item_ids,
            "destination_path": destination_path,
            "zip_name": zip_name,
            "user_id": user_id,
            "bot_manager": bot_manager
        }
    )
    return {"task_id": task_id, "status": "queued", "message": "Compression started in background"}
