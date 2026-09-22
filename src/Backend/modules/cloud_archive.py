# src/Backend/modules/cloud_archive.py

import os
import io
import uuid
import shutil
import zipfile
import tempfile
import asyncio
from typing import List, Dict, Any, Optional
from bson import ObjectId
from pyrogram import Client

from d4rk.Logs import setup_logger
from src.Database import database
from src.Config import LOGS, MOVIE
from .byte_streamer import ByteStreamer

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
    parts_list: Optional[List[Dict[str, Any]]] = None
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

    with open(dest_path, "wb") as f:
        async for chunk in byte_streamer.yield_parts(parts_to_stream, chunk_size=1024 * 1024, client_list=active_clients):
            if chunk:
                f.write(chunk)


async def inspect_archive(
    chat_id: int,
    message_id: int,
    file_size: int,
    byte_streamer: ByteStreamer,
    active_clients: Optional[List[Client]] = None,
    parts_list: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Inspects the contents of a ZIP file without extracting to Telegram.
    Returns list of files and folders inside with metadata.
    """
    temp_zip = os.path.join(TEMP_ARCHIVE_DIR, f"inspect_{uuid.uuid4().hex}.zip")
    try:
        # Download file to temp
        await download_file_to_temp(chat_id, message_id, file_size, byte_streamer, temp_zip, active_clients, parts_list)
        
        if not zipfile.is_zipfile(temp_zip):
            return {"is_valid": False, "error": "Not a valid ZIP archive", "files": []}

        files_list = []
        total_uncompressed = 0
        with zipfile.ZipFile(temp_zip, "r") as zf:
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
    except Exception as e:
        logger.error(f"Error inspecting archive: {e}", exc_info=True)
        return {"is_valid": False, "error": str(e), "files": []}
    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass


async def extract_archive_in_cloud(
    file_doc: Dict[str, Any],
    target_path: str,
    byte_streamer: ByteStreamer,
    bot_manager: Any,
    user_id: str
) -> Dict[str, Any]:
    """
    Extracts a ZIP archive in the cloud. Each entry is extracted locally then uploaded
    directly to Telegram storage and indexed under target_path in MongoDB.
    """
    chat_id = int(file_doc["chat_id"])
    message_id = int(file_doc["message_id"])
    file_size = int(file_doc.get("file_size") or 0)
    archive_name = file_doc.get("file_name", "archive.zip")

    clean_target = target_path.rstrip("/")
    if not clean_target:
        clean_target = "/Home"

    temp_zip = os.path.join(TEMP_ARCHIVE_DIR, f"extract_{uuid.uuid4().hex}.zip")
    extract_dir = os.path.join(TEMP_ARCHIVE_DIR, f"dir_{uuid.uuid4().hex}")
    os.makedirs(extract_dir, exist_ok=True)

    extracted_files_count = 0
    extracted_folders_count = 0

    try:
        active_clients = [c for c in getattr(bot_manager, 'client_list', []) if getattr(c, 'is_connected', True)]
        if not active_clients and hasattr(bot_manager, 'get_least_busy_client'):
            fallback_c = bot_manager.get_least_busy_client()
            if fallback_c:
                active_clients = [fallback_c]

        primary_client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
        if not primary_client and active_clients:
            primary_client = active_clients[0]

        parts_list = file_doc.get("parts") if file_doc.get("is_split") else None
        await download_file_to_temp(chat_id, message_id, file_size, byte_streamer, temp_zip, active_clients, parts_list)

        if not zipfile.is_zipfile(temp_zip):
            raise ValueError(f"'{archive_name}' is not a valid ZIP file.")

        with zipfile.ZipFile(temp_zip, "r") as zf:
            zf.extractall(extract_dir)

        # Upload and index extracted structure
        storage_chat_id = LOGS or MOVIE or chat_id

        # Walk extracted directory
        for root, dirs, files in os.walk(extract_dir):
            rel_dir = os.path.relpath(root, extract_dir)
            if rel_dir == ".":
                current_cloud_path = clean_target
            else:
                current_cloud_path = f"{clean_target}/{rel_dir.replace(os.sep, '/')}"

            # Create folder in MongoDB if not at root
            if rel_dir != ".":
                folder_name = os.path.basename(root)
                parent_path = os.path.dirname(current_cloud_path) or "/"
                existing = database.Files.find_one({
                    "file_name": folder_name,
                    "file_path": parent_path,
                    "file_type": "folder",
                    "owner_id": user_id
                })
                if not existing:
                    database.Files.insert_one({
                        "file_name": folder_name,
                        "file_path": parent_path,
                        "file_type": "folder",
                        "owner_id": user_id,
                        "file_size": 0
                    })
                    extracted_folders_count += 1

            for fname in files:
                full_path = os.path.join(root, fname)
                file_sz = os.path.getsize(full_path)
                ext = os.path.splitext(fname)[1].lower()

                file_type = "document"
                if ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv']:
                    file_type = "video"
                elif ext in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
                    file_type = "audio"
                elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
                    file_type = "photo"

                c = bot_manager.get_least_busy_client() or primary_client
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
                    logger.warning(f"Failed to upload {fname} as {file_type}, sending as document: {ex}")
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
                        file_path=current_cloud_path,
                        owner_id=user_id
                    )
                    extracted_files_count += 1

        return {
            "success": True,
            "extracted_files": extracted_files_count,
            "extracted_folders": extracted_folders_count,
            "target_path": clean_target
        }

    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass
        if os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass


async def compress_items_to_zip(
    item_ids: List[str],
    destination_path: str,
    zip_name: str,
    byte_streamer: ByteStreamer,
    bot_manager: Any,
    user_id: str
) -> Dict[str, Any]:
    """
    Compresses selected files and folders directly into a new ZIP file,
    uploads it to Telegram, and registers it in MongoDB.
    """
    if not zip_name.lower().endswith(".zip"):
        zip_name += ".zip"

    clean_dest = destination_path.rstrip("/")
    if not clean_dest:
        clean_dest = "/Home"

    temp_zip = os.path.join(TEMP_ARCHIVE_DIR, f"create_{uuid.uuid4().hex}_{zip_name}")
    active_clients = [c for c in getattr(bot_manager, 'client_list', []) if getattr(c, 'is_connected', True)]
    if not active_clients and hasattr(bot_manager, 'get_least_busy_client'):
        fallback_c = bot_manager.get_least_busy_client()
        if fallback_c:
            active_clients = [fallback_c]

    primary_client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
    if not primary_client and active_clients:
        primary_client = active_clients[0]

    # Collect all file documents to compress
    files_to_compress: List[Dict[str, Any]] = []

    for item_id in item_ids:
        try:
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

                # Find all files inside this folder recursively
                regex_pattern = f"^{folder_path.rstrip('/')}/{folder_name}(/.*)?$"
                child_files = list(database.Files.find({
                    "file_path": {"$regex": regex_pattern},
                    "file_type": {"$ne": "folder"}
                }))

                for cf in child_files:
                    cf_path = cf.get("file_path", "").lstrip("/")
                    # Relative path within the folder
                    rel_prefix = cf_path[len(target_base):].lstrip("/")
                    arcname = os.path.join(folder_name, rel_prefix, cf.get("file_name", "file"))
                    files_to_compress.append({"doc": cf, "arcname": arcname.replace("\\", "/")})
            else:
                files_to_compress.append({"doc": doc, "arcname": doc.get("file_name", "file")})
        except Exception as e:
            logger.error(f"Error querying item {item_id}: {e}")

    if not files_to_compress:
        raise ValueError("No valid files found to compress.")

    try:
        # Create the ZIP archive
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for item in files_to_compress:
                f_doc = item["doc"]
                arcname = item["arcname"]
                f_size = int(f_doc.get("file_size") or 0)
                c_id = int(f_doc["chat_id"])
                m_id = int(f_doc["message_id"])

                temp_f = os.path.join(TEMP_ARCHIVE_DIR, f"part_{uuid.uuid4().hex}")
                try:
                    p_list = f_doc.get("parts") if f_doc.get("is_split") else None
                    await download_file_to_temp(c_id, m_id, f_size, byte_streamer, temp_f, active_clients, p_list)
                    zf.write(temp_f, arcname)
                finally:
                    if os.path.exists(temp_f):
                        try:
                            os.remove(temp_f)
                        except Exception:
                            pass

        # Upload the created ZIP archive to Telegram
        total_zip_size = os.path.getsize(temp_zip)
        storage_chat_id = LOGS or MOVIE or files_to_compress[0]["doc"].get("chat_id")

        if total_zip_size > 1950 * 1024 * 1024:
            # Multi-part split upload for large ZIP archives (> 1.95 GB)
            from .pipeline_uploader import upload_part_task
            chunk_size = 1950 * 1024 * 1024
            upload_tasks = []
            part_index = 1
            start_byte = 0

            with open(temp_zip, "rb") as f_in:
                while start_byte < total_zip_size:
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

        return {
            "success": True,
            "file_name": zip_name,
            "file_size": total_zip_size,
            "file_path": clean_dest,
            "total_items_compressed": len(files_to_compress)
        }

    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass
