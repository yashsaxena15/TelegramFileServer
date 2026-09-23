# src/Backend/modules/remote_transfer_manager.py

import os
import re
import time
import shutil
import asyncio
import logging
import secrets
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import aiohttp
import aiofiles
import urllib.parse
from pymongo import MongoClient

from src.Config import DATABASE_URL, APP_NAME
from src.Database import database
from .pipeline_uploader import upload_part_task
from .priority_manager import priority_manager
from .torrent_manager import torrent_manager, parse_torrent_bytes

logger = logging.getLogger("remote_transfers")

def get_remote_db():
    if hasattr(database, "db") and database.db is not None:
        return database.db
    client = MongoClient(DATABASE_URL)
    return client[APP_NAME]

MODERN_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

class PipelinedStreamWriter:
    """
    A file-like streaming buffer that chunks incoming data into 1.95 GB part files.
    As soon as a part reaches 1.95 GB (or stream finishes), it notifies via on_part_ready callback
    which immediately launches an asynchronous background upload to Telegram.
    Uses a semaphore to throttle disk writes (backpressure) so at most 2 parts exist on disk.
    Supports QoS priority auto-pausing when user uploads are active.
    """
    def __init__(
        self,
        tg_dir: str,
        semaphore: threading.Semaphore,
        cancel_event: threading.Event,
        on_part_ready: Any,
        on_pause_state_changed: Optional[Any] = None,
        part_max_size: int = 1950 * 1024 * 1024
    ):
        self.tg_dir = tg_dir
        self.semaphore = semaphore
        self.cancel_event = cancel_event
        self.on_part_ready = on_part_ready
        self.on_pause_state_changed = on_pause_state_changed
        self.part_max_size = part_max_size

        self.current_part_index = 1
        self.current_part_file = None
        self.current_part_path = ""
        self.current_part_bytes = 0
        self.total_bytes = 0
        self.parts: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._closed = False

    def _check_priority_pause(self):
        if priority_manager.is_user_upload_active():
            if self.on_pause_state_changed:
                self.on_pause_state_changed(True)
            while priority_manager.is_user_upload_active():
                if self.cancel_event.is_set():
                    raise InterruptedError("Download cancelled by user")
                priority_manager.wait_if_user_upload_active(timeout=1.0)
            if self.on_pause_state_changed:
                self.on_pause_state_changed(False)

    def _open_next_part(self):
        while not self.cancel_event.is_set():
            self._check_priority_pause()
            acquired = self.semaphore.acquire(timeout=0.5)
            if acquired:
                break
        if self.cancel_event.is_set():
            raise InterruptedError("Download cancelled by user")

        self.current_part_path = os.path.join(self.tg_dir, f"part_{self.current_part_index}.tmp")
        self.current_part_file = open(self.current_part_path, "wb")
        self.current_part_bytes = 0

    def write(self, data: bytes) -> int:
        if self.cancel_event.is_set():
            raise InterruptedError("Download cancelled by user")
        if not data:
            return 0

        self._check_priority_pause()

        with self._lock:
            written = 0
            data_len = len(data)

            while written < data_len:
                if self.cancel_event.is_set():
                    raise InterruptedError("Download cancelled by user")

                self._check_priority_pause()

                if self.current_part_file is None:
                    self._open_next_part()

                space_in_part = self.part_max_size - self.current_part_bytes
                chunk = data[written : written + space_in_part]
                self.current_part_file.write(chunk)
                chunk_len = len(chunk)

                self.current_part_bytes += chunk_len
                self.total_bytes += chunk_len
                written += chunk_len

                if self.current_part_bytes >= self.part_max_size:
                    self._seal_current_part(is_final=False)

            return written

    def _seal_current_part(self, is_final: bool = False):
        if self.current_part_file is None:
            return

        self.current_part_file.flush()
        self.current_part_file.close()
        self.current_part_file = None

        part_size = self.current_part_bytes
        part_index = self.current_part_index
        part_path = self.current_part_path
        start_byte = self.total_bytes - part_size

        is_single_part = is_final and len(self.parts) == 0

        part_info = {
            "part_index": part_index,
            "part_path": part_path,
            "part_size": part_size,
            "start_byte": start_byte,
            "is_single_part": is_single_part
        }
        self.parts.append(part_info)

        self.on_part_ready(
            part_path,
            part_index,
            start_byte,
            part_size,
            is_final,
            is_single_part
        )

        if not is_final:
            self.current_part_index += 1

    def finish(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self.current_part_file is not None and self.current_part_bytes > 0:
                self._seal_current_part(is_final=True)
            elif len(self.parts) == 0 and self.current_part_file is not None:
                self._seal_current_part(is_final=True)

    def flush(self):
        if self.current_part_file:
            self.current_part_file.flush()

    def tell(self) -> int:
        return self.total_bytes

    def cleanup(self):
        with self._lock:
            if self.current_part_file:
                try:
                    self.current_part_file.close()
                except Exception:
                    pass
                self.current_part_file = None

    def close(self):
        self.finish()

class RemoteTransferManager:
    """
    Manages background cloud-to-cloud server transfers (Google Drive, direct URLs).
    Runs independently of browser sessions, persists state to MongoDB, and throttles concurrency.
    """
    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.cancel_events: Dict[str, threading.Event] = {}
        self._running = False
        self._queue_worker_task: Optional[asyncio.Task] = None
        self._bot_manager = None

    def set_bot_manager(self, bot_manager):
        self._bot_manager = bot_manager

    def init_db(self):
        """Reset any interrupted tasks on startup."""
        try:
            coll = get_remote_db()["RemoteTransfers"]
            coll.update_many(
                {"status": {"$in": ["downloading", "uploading_tg"]}},
                {"$set": {
                    "status": "queued",
                    "phase": "Resumed after server restart",
                    "speed_bps": 0,
                    "updated_at": datetime.now(timezone.utc)
                }}
            )
        except Exception as e:
            logger.warning(f"Failed to reset interrupted remote tasks: {e}")

    def start_worker(self, app=None):
        if app and hasattr(app.state, "bot_manager"):
            self._bot_manager = app.state.bot_manager

        if not self._running:
            self._running = True
            self.init_db()
            self._queue_worker_task = asyncio.create_task(self._process_queue_loop())
            logger.info("Remote Transfer Manager background worker loop started.")

    async def _process_queue_loop(self):
        """Continuously checks for queued tasks and launches them up to concurrency limit."""
        while self._running:
            try:
                # If user upload is active, yield bandwidth and pause queue processing
                if priority_manager.is_user_upload_active():
                    await asyncio.sleep(2)
                    continue

                coll = get_remote_db()["RemoteTransfers"]
                # Find queued tasks ordered by created_at ascending
                queued_cursor = coll.find({"status": "queued"}).sort("created_at", 1).limit(5)
                queued_tasks = list(queued_cursor)

                for item in queued_tasks:
                    task_id = item["task_id"]
                    if task_id not in self.active_tasks:
                        # Launch task wrapper
                        t = asyncio.create_task(self._execute_task_wrapper(item))
                        self.active_tasks[task_id] = t

                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in remote transfer queue loop: {e}", exc_info=True)
                await asyncio.sleep(3)

    async def enqueue_transfer(
        self,
        user_id: str,
        url: str,
        destination_path: str,
        chat_id: int
    ) -> List[Dict[str, Any]]:
        """
        Parses the URL (GDrive file, GDrive folder, direct URL) and creates
        queued task documents in MongoDB.
        """
        url = url.strip()
        coll = get_remote_db()["RemoteTransfers"]
        now = datetime.now(timezone.utc)
        clean_dest = destination_path.strip() or "/Home"
        is_vault = clean_dest.startswith("/Vault") or clean_dest == "Vault"

        # Check if Magnet Link
        if url.startswith("magnet:?xt="):
            task_id = f"rt_{secrets.token_hex(6)}"
            dn_match = re.search(r'dn=([^&]+)', url)
            filename = urllib.parse.unquote_plus(dn_match.group(1)) if dn_match else "Resolving Magnet..."
            doc = {
                "task_id": task_id,
                "user_id": str(user_id),
                "chat_id": chat_id,
                "source_url": url,
                "gdrive_id": None,
                "source_type": "magnet",
                "destination_path": clean_dest,
                "filename": filename,
                "filesize": 0,
                "transferred_bytes": 0,
                "speed_bps": 0,
                "peer_count": 0,
                "progress": 0,
                "eta_seconds": 0,
                "status": "queued",
                "phase": "Queued",
                "error_message": None,
                "is_vault": is_vault,
                "created_at": now,
                "updated_at": now
            }
            coll.insert_one(doc)
            doc["_id"] = str(doc["_id"])
            return [doc]

        # Check if Google Drive Folder
        folder_match = re.search(r'/drive/folders/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url) if 'folders' in url else None
        
        created_tasks = []

        if folder_match:
            folder_id = folder_match.group(1)
            logger.info(f"Resolving Google Drive folder: {folder_id}")
            
            # Temporary resolve directory to capture root folder name
            resolve_output_dir = f"/tmp/gdrive_resolve_{secrets.token_hex(4)}/"
            os.makedirs(resolve_output_dir, exist_ok=True)

            def _resolve_folder():
                from gdown.download_folder import download_folder
                return download_folder(id=folder_id, output=resolve_output_dir, skip_download=True, quiet=True, user_agent=MODERN_USER_AGENT)

            try:
                folder_files = await asyncio.to_thread(_resolve_folder)
            except Exception as e:
                logger.error(f"Failed to resolve GDrive folder: {e}")
                raise ValueError(f"Could not access Google Drive folder. Please make sure the folder is public ('Anyone with the link can view'). Error: {e}")
            finally:
                shutil.rmtree(resolve_output_dir, ignore_errors=True)

            if not folder_files:
                raise ValueError("Google Drive folder is empty or not accessible.")

            # Deduplication: Find any existing tasks for this user & destination
            existing_gdrive_ids = set(
                coll.distinct("gdrive_id", {
                    "user_id": str(user_id),
                    "gdrive_id": {"$ne": None},
                    "destination_path": {"$regex": f"^{re.escape(clean_dest)}"},
                    "status": {"$in": ["queued", "downloading", "uploading_tg", "completed"]}
                })
            )

            docs_to_insert = []
            for gfile in folder_files:
                if gfile.id in existing_gdrive_ids:
                    continue  # Skip already queued/downloaded file

                task_id = f"rt_{secrets.token_hex(6)}"
                # gfile.local_path has format: "/tmp/gdrive_resolve_xxx/FolderName/sub/file.ext"
                rel_from_root = os.path.relpath(gfile.local_path, resolve_output_dir).replace("\\", "/").strip("/")
                rel_dir = os.path.dirname(rel_from_root).strip("/")
                fname = os.path.basename(rel_from_root) or f"gdrive_file_{gfile.id}"

                item_dest = f"{clean_dest}/{rel_dir}" if rel_dir else clean_dest

                doc = {
                    "task_id": task_id,
                    "user_id": str(user_id),
                    "chat_id": chat_id,
                    "source_url": f"https://drive.google.com/uc?id={gfile.id}",
                    "gdrive_id": gfile.id,
                    "source_type": "gdrive_file",
                    "destination_path": item_dest,
                    "filename": fname,
                    "filesize": 0,
                    "transferred_bytes": 0,
                    "speed_bps": 0,
                    "progress": 0,
                    "eta_seconds": 0,
                    "status": "queued",
                    "phase": "Queued",
                    "error_message": None,
                    "is_vault": is_vault,
                    "created_at": now,
                    "updated_at": now
                }
                docs_to_insert.append(doc)
                created_tasks.append(doc)

            if docs_to_insert:
                coll.insert_many(docs_to_insert)
                for doc in docs_to_insert:
                    doc["_id"] = str(doc["_id"])

            return created_tasks

        # Check if Google Drive Single File
        gdrive_file_id = None
        file_match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url)
        if file_match and ('drive.google.com' in url or 'docs.google.com' in url):
            gdrive_file_id = file_match.group(1)

        task_id = f"rt_{secrets.token_hex(6)}"
        source_type = "gdrive_file" if gdrive_file_id else "direct_url"
        filename = "Resolving..."

        doc = {
            "task_id": task_id,
            "user_id": str(user_id),
            "chat_id": chat_id,
            "source_url": url,
            "gdrive_id": gdrive_file_id,
            "source_type": source_type,
            "destination_path": clean_dest,
            "filename": filename,
            "filesize": 0,
            "transferred_bytes": 0,
            "speed_bps": 0,
            "progress": 0,
            "eta_seconds": 0,
            "status": "queued",
            "phase": "Queued",
            "error_message": None,
            "is_vault": is_vault,
            "created_at": now,
            "updated_at": now
        }
        coll.insert_one(doc)
        doc["_id"] = str(doc["_id"])
        return [doc]

    async def enqueue_torrent_file(
        self,
        user_id: str,
        torrent_bytes: bytes,
        original_filename: str,
        destination_path: str,
        chat_id: int
    ) -> Dict[str, Any]:
        """
        Validates an uploaded .torrent file, saves it into cache/torrents,
        and creates a queued task document in MongoDB.
        """
        coll = get_remote_db()["RemoteTransfers"]
        now = datetime.now(timezone.utc)
        clean_dest = destination_path.strip() or "/Home"
        is_vault = clean_dest.startswith("/Vault") or clean_dest == "Vault"

        try:
            meta = parse_torrent_bytes(torrent_bytes)
        except Exception as e:
            raise ValueError(f"Invalid .torrent file: {e}")

        torrent_dir = os.path.join(os.getcwd(), "cache", "torrents")
        os.makedirs(torrent_dir, exist_ok=True)

        task_id = f"rt_{secrets.token_hex(6)}"
        torrent_path = os.path.join(torrent_dir, f"{task_id}.torrent")
        with open(torrent_path, "wb") as f:
            f.write(torrent_bytes)

        doc = {
            "task_id": task_id,
            "user_id": str(user_id),
            "chat_id": chat_id,
            "source_url": f"torrent:{original_filename}",
            "torrent_path": torrent_path,
            "gdrive_id": None,
            "source_type": "torrent_file",
            "destination_path": clean_dest,
            "filename": meta.get("name") or original_filename,
            "filesize": meta.get("total_size", 0),
            "transferred_bytes": 0,
            "speed_bps": 0,
            "peer_count": 0,
            "progress": 0,
            "eta_seconds": 0,
            "status": "queued",
            "phase": "Queued",
            "error_message": None,
            "is_vault": is_vault,
            "created_at": now,
            "updated_at": now
        }
        coll.insert_one(doc)
        doc["_id"] = str(doc["_id"])
        return doc

    async def _execute_task_wrapper(self, task_doc: dict):
        task_id = task_doc["task_id"]
        cancel_event = threading.Event()
        self.cancel_events[task_id] = cancel_event

        async with self.semaphore:
            try:
                await self._run_download_and_upload(task_doc, cancel_event)
            except asyncio.CancelledError:
                logger.info(f"Task {task_id} cancelled.")
                self._update_task(task_id, {"status": "cancelled", "phase": "Cancelled by user", "speed_bps": 0})
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
                err_text = str(e)
                if "Cannot retrieve the public link" in err_text or "Check FAQ" in err_text:
                    err_text = "Google Drive file is not accessible (it may be deleted, moved to trash, or restricted by the owner)."
                phase_err = "Failed: " + (err_text[:50] + "..." if len(err_text) > 50 else err_text)
                self._update_task(task_id, {"status": "failed", "error_message": err_text, "phase": phase_err, "speed_bps": 0})
            finally:
                self.active_tasks.pop(task_id, None)
                self.cancel_events.pop(task_id, None)

    async def _run_download_and_upload(self, task_doc: dict, cancel_event: threading.Event):
        task_id = task_doc["task_id"]
        source_url = task_doc["source_url"]
        gdrive_id = task_doc.get("gdrive_id")
        destination_path = task_doc.get("destination_path", "/Home")
        user_id = task_doc["user_id"]
        chat_id = task_doc["chat_id"]
        is_vault = bool(task_doc.get("is_vault", False))

        tg_dir = os.path.join(os.getcwd(), "tg_files", f"remote_{task_id}")
        os.makedirs(tg_dir, exist_ok=True)

        PART_MAX_SIZE = 1950 * 1024 * 1024  # 1.95 GB Part standard

        self._update_task(task_id, {
            "status": "downloading",
            "phase": "Connecting to source...",
            "speed_bps": 0
        })

        # Wait for available Telegram bot client
        bot_manager = self._bot_manager
        client = None
        for _ in range(30):
            if cancel_event.is_set():
                raise InterruptedError("Cancelled by user")
            client = bot_manager.get_least_busy_client() if bot_manager else None
            if client:
                break
            await asyncio.sleep(1)

        if not client:
            raise RuntimeError("No Telegram bot client available for upload.")

        loop = asyncio.get_running_loop()
        upload_tasks = []
        uploaded_bytes_map = {}
        filename_holder = [task_doc.get("filename") or "download.bin"]
        estimated_total = [task_doc.get("filesize", 0)]
        last_progress_time = [time.time()]
        last_dl = [0]
        last_up = [0]
        disk_semaphore = threading.Semaphore(2)  # Cap VM disk buffer to max 2 parts (~3.9GB)

        def get_file_type(fname: str) -> str:
            ext = os.path.splitext(fname)[1].lower()
            if ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm']:
                return "video"
            elif ext in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
                return "audio"
            elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                return "photo"
            return "document"

        def report_combined_progress(cur_dl: int, cur_up: int, total_sz: int):
            if cancel_event.is_set():
                raise InterruptedError("Cancelled by user")

            now_t = time.time()
            dt = now_t - last_progress_time[0]
            if dt >= 0.8 or (total_sz and (cur_dl >= total_sz or cur_up >= total_sz)):
                dl_speed = max(0, (cur_dl - last_dl[0]) / dt) if dt > 0 else 0
                up_speed = max(0, (cur_up - last_up[0]) / dt) if dt > 0 else 0
                last_progress_time[0] = now_t
                last_dl[0] = cur_dl
                last_up[0] = cur_up

                if total_sz and total_sz > 0:
                    dl_pct = (cur_dl / total_sz) * 50.0
                    up_pct = (cur_up / total_sz) * 50.0
                    overall_progress = min(99.5, round(dl_pct + up_pct, 1))
                    active_speed = max(dl_speed, up_speed)
                    eta = int((total_sz - cur_up) / active_speed) if (active_speed > 0 and cur_up < total_sz) else 0

                    if cur_dl < total_sz:
                        phase = f"Streaming Part {writer.current_part_index}: DL {dl_speed/1024/1024:.1f}MB/s | UP {up_speed/1024/1024:.1f}MB/s ({overall_progress}%)"
                    else:
                        phase = f"Uploading to Telegram Cloud ({round((cur_up / total_sz) * 100, 1)}%)"
                else:
                    overall_progress = 0
                    active_speed = max(dl_speed, up_speed)
                    eta = 0
                    phase = f"Streaming: DL {cur_dl/1024/1024:.1f}MB | UP {cur_up/1024/1024:.1f}MB"

                self._update_task(task_id, {
                    "filename": filename_holder[0],
                    "transferred_bytes": cur_up,
                    "filesize": total_sz or cur_dl,
                    "progress": overall_progress,
                    "speed_bps": active_speed,
                    "eta_seconds": eta,
                    "phase": phase,
                    "status": "uploading_tg" if cur_dl >= (total_sz or 1) else "downloading"
                })

        def make_part_progress(p_num: int):
            def _cb(cur: int, tot: int):
                uploaded_bytes_map[p_num] = cur
                tot_up = sum(uploaded_bytes_map.values())
                report_combined_progress(writer.total_bytes, tot_up, estimated_total[0])
            return _cb

        def on_part_ready(part_path: str, p_idx: int, s_byte: int, p_sz: int, is_final: bool, is_single_part: bool):
            ftype = get_file_type(filename_holder[0])
            caption = f"Uploaded file: {filename_holder[0]}" if is_single_part else f"{filename_holder[0]} (Part {p_idx})"

            coro = upload_part_task(
                part_file_path=part_path,
                part_index=p_idx,
                file_name=filename_holder[0],
                start_byte=s_byte,
                part_size=p_sz,
                chat_id=chat_id,
                bot_manager=bot_manager,
                fallback_client=client,
                caption=caption,
                semaphore=disk_semaphore,
                is_single_part=is_single_part,
                file_type=ftype,
                progress=make_part_progress(p_idx)
            )

            # Thread-safe dispatch onto event loop
            if threading.current_thread() is threading.main_thread():
                task = loop.create_task(coro)
            else:
                fut = asyncio.run_coroutine_threadsafe(coro, loop)
                task = asyncio.wrap_future(fut, loop=loop)
            upload_tasks.append(task)

        def on_pause_state_changed(is_paused: bool):
            if is_paused:
                self._update_task(task_id, {
                    "status": "paused",
                    "phase": "Paused: Prioritizing User Upload 👤 (Will auto-resume)",
                    "speed_bps": 0
                })
            else:
                self._update_task(task_id, {
                    "status": "downloading",
                    "phase": f"Resumed: Streaming Part {writer.current_part_index} ▶️",
                    "speed_bps": 0
                })

        # Create Producer-Consumer Pipelined Stream Writer
        writer = PipelinedStreamWriter(
            tg_dir=tg_dir,
            semaphore=disk_semaphore,
            cancel_event=cancel_event,
            on_part_ready=on_part_ready,
            on_pause_state_changed=on_pause_state_changed
        )

        try:
            # --- STEP 1: Stream Data from Source into Writer or BitTorrent Engine ---
            if task_doc.get("source_type") in ["magnet", "torrent_file"]:
                logger.info(f"[REMOTE_TRANSFER] Task {task_id}: Processing BitTorrent/Magnet leech transfer...")

                # Step 1: Obtain .torrent file
                if task_doc.get("source_type") == "magnet":
                    self._update_task(task_id, {
                        "status": "downloading",
                        "phase": "Connecting to swarm & resolving magnet metadata...",
                        "speed_bps": 0
                    })
                    meta_dir = os.path.join(tg_dir, "meta")

                    def _on_meta_prog(msg: str):
                        self._update_task(task_id, {"phase": msg})

                    torrent_file_path = await asyncio.to_thread(
                        torrent_manager.resolve_magnet_metadata,
                        source_url,
                        meta_dir,
                        cancel_event,
                        _on_meta_prog,
                        180
                    )
                else:
                    torrent_file_path = task_doc.get("torrent_path")
                    if not torrent_file_path or not os.path.exists(torrent_file_path):
                        raise FileNotFoundError("Torrent file not found on server.")

                with open(torrent_file_path, "rb") as tf:
                    t_bytes = tf.read()
                meta = parse_torrent_bytes(t_bytes)

                root_name = meta["name"]
                is_multi_file = meta["is_multi_file"]
                files = meta["files"]
                total_torrent_size = meta["total_size"]
                total_files = len(files)

                self._update_task(task_id, {
                    "filename": root_name,
                    "filesize": total_torrent_size,
                    "phase": f"Found {total_files} file(s) in torrent ({round(total_torrent_size / (1024*1024), 1)} MB)"
                })

                completed_bytes = 0
                dl_work_dir = os.path.join(tg_dir, "dl")
                os.makedirs(dl_work_dir, exist_ok=True)

                for file_idx, f_item in enumerate(files, start=1):
                    if cancel_event.is_set():
                        raise InterruptedError("Cancelled by user")

                    f_name = f_item["name"]
                    f_size = f_item["size"]
                    f_rel_path = f_item["rel_path"]
                    f_full_rel_path = f_item["full_rel_path"]

                    # Compute target destination folder preserving nested directory tree
                    if is_multi_file:
                        sub_dir = os.path.dirname(f_rel_path).replace("\\", "/").strip("/")
                        target_folder = f"{destination_path}/{root_name}/{sub_dir}".rstrip("/") if sub_dir else f"{destination_path}/{root_name}"
                    else:
                        target_folder = destination_path

                    database.Files.create_folder_path(target_folder, owner_id=str(user_id))

                    if f_size == 0:
                        # Handle 0-byte file without downloading
                        empty_path = os.path.join(dl_work_dir, f_name)
                        with open(empty_path, "wb"):
                            pass
                        res = await upload_part_task(
                            part_file_path=empty_path,
                            part_index=1,
                            file_name=f_name,
                            start_byte=0,
                            part_size=0,
                            chat_id=chat_id,
                            bot_manager=bot_manager,
                            fallback_client=client,
                            is_single_part=True,
                            file_type="document"
                        )
                        database.Files.add_file(
                            chat_id=chat_id,
                            message_id=res["message_id"],
                            thumbnail=res.get("thumbnail"),
                            file_type="document",
                            file_unique_id=res["file_unique_id"],
                            file_size=0,
                            file_name=f_name,
                            file_caption=f"Uploaded file: {f_name}",
                            file_path=target_folder,
                            owner_id=str(user_id),
                            is_vault=is_vault
                        )
                        continue

                    # Callbacks for aria2c download
                    def _aria_progress(p_info: dict):
                        if cancel_event.is_set():
                            raise InterruptedError("Cancelled by user")
                        pct = p_info["progress"]
                        speed = p_info["speed_bps"]
                        peers = p_info["peers"]
                        cur_f_dl = int((pct / 100.0) * f_size)
                        cur_total_transferred = completed_bytes + int(cur_f_dl * 0.5)
                        total_pct = min(99.0, round((cur_total_transferred / (total_torrent_size or 1)) * 100, 1))

                        self._update_task(task_id, {
                            "status": "downloading",
                            "progress": total_pct,
                            "speed_bps": speed,
                            "peer_count": peers,
                            "transferred_bytes": cur_total_transferred,
                            "phase": f"Leeching [{file_idx}/{total_files}] {f_name} ({pct:.1f}%) | ⚡ {peers} peers"
                        })

                    def _aria_pause(is_p: bool):
                        if is_p:
                            self._update_task(task_id, {
                                "status": "paused",
                                "phase": "Paused: Prioritizing User Upload 👤 (Will auto-resume)",
                                "speed_bps": 0
                            })
                        else:
                            self._update_task(task_id, {
                                "status": "downloading",
                                "phase": f"Resumed: Leeching [{file_idx}/{total_files}] {f_name} ▶️",
                                "speed_bps": 0
                            })

                    logger.info(f"[REMOTE_TRANSFER] Task {task_id}: Leeching file {file_idx}/{total_files}: {f_name} ({f_size} bytes)")
                    await asyncio.to_thread(
                        torrent_manager.download_file_selective,
                        torrent_file_path,
                        f_item["index"],
                        dl_work_dir,
                        cancel_event,
                        _aria_progress,
                        _aria_pause
                    )

                    if cancel_event.is_set():
                        raise InterruptedError("Cancelled by user")

                    # Locate downloaded file
                    downloaded_file = os.path.join(dl_work_dir, f_full_rel_path)
                    if not os.path.exists(downloaded_file):
                        found = False
                        for root, _, files_in_dir in os.walk(dl_work_dir):
                            if f_name in files_in_dir:
                                downloaded_file = os.path.join(root, f_name)
                                found = True
                                break
                        if not found:
                            raise FileNotFoundError(f"Downloaded file '{f_name}' not found at {downloaded_file}")

                    actual_size = os.path.getsize(downloaded_file)
                    ftype = get_file_type(f_name)

                    if actual_size <= PART_MAX_SIZE:
                        # Single-part upload
                        self._update_task(task_id, {
                            "status": "uploading_tg",
                            "phase": f"Uploading [{file_idx}/{total_files}] {f_name} to Telegram..."
                        })

                        def _part_up_prog(cur: int, tot: int):
                            cur_up = completed_bytes + int(f_size * 0.5) + int(cur * 0.5)
                            total_pct = min(99.5, round((cur_up / (total_torrent_size or 1)) * 100, 1))
                            self._update_task(task_id, {
                                "progress": total_pct,
                                "transferred_bytes": cur_up,
                                "phase": f"Uploading [{file_idx}/{total_files}] {f_name} ({round((cur/tot)*100, 1)}%)"
                            })

                        res = await upload_part_task(
                            part_file_path=downloaded_file,
                            part_index=1,
                            file_name=f_name,
                            start_byte=0,
                            part_size=actual_size,
                            chat_id=chat_id,
                            bot_manager=bot_manager,
                            fallback_client=client,
                            caption=f"Uploaded file: {f_name}",
                            is_single_part=True,
                            file_type=ftype,
                            progress=_part_up_prog
                        )

                        database.Files.add_file(
                            chat_id=chat_id,
                            message_id=res["message_id"],
                            thumbnail=res.get("thumbnail"),
                            file_type=ftype,
                            file_unique_id=res["file_unique_id"],
                            file_size=actual_size,
                            file_name=f_name,
                            file_caption=f"Uploaded file: {f_name}",
                            file_path=target_folder,
                            owner_id=str(user_id),
                            is_vault=is_vault
                        )
                    else:
                        # Multi-part chunked upload for > 1.95 GB file
                        logger.info(f"[REMOTE_TRANSFER] Task {task_id}: Chunking large file {f_name} ({actual_size} bytes)")
                        self._update_task(task_id, {
                            "status": "uploading_tg",
                            "phase": f"Chunking & Uploading [{file_idx}/{total_files}] {f_name}..."
                        })

                        mp_upload_tasks = []
                        mp_bytes_map = {}
                        mp_disk_sem = threading.Semaphore(2)

                        def _on_mp_part_ready(part_path, p_idx, s_byte, p_sz, is_fin, is_single):
                            caption = f"{f_name} (Part {p_idx})"
                            def _mp_prog(cur, tot):
                                mp_bytes_map[p_idx] = cur
                                tot_up = sum(mp_bytes_map.values())
                                cur_up = completed_bytes + int(f_size * 0.5) + int(tot_up * 0.5)
                                total_pct = min(99.5, round((cur_up / (total_torrent_size or 1)) * 100, 1))
                                self._update_task(task_id, {
                                    "progress": total_pct,
                                    "transferred_bytes": cur_up,
                                    "phase": f"Uploading [{file_idx}/{total_files}] {f_name} Part {p_idx} ({round((tot_up/actual_size)*100, 1)}%)"
                                })

                            coro = upload_part_task(
                                part_file_path=part_path,
                                part_index=p_idx,
                                file_name=f_name,
                                start_byte=s_byte,
                                part_size=p_sz,
                                chat_id=chat_id,
                                bot_manager=bot_manager,
                                fallback_client=client,
                                caption=caption,
                                semaphore=mp_disk_sem,
                                is_single_part=False,
                                file_type=ftype,
                                progress=_mp_prog
                            )
                            t = loop.create_task(coro)
                            mp_upload_tasks.append(t)

                        mp_writer = PipelinedStreamWriter(
                            tg_dir=tg_dir,
                            semaphore=mp_disk_sem,
                            cancel_event=cancel_event,
                            on_part_ready=_on_mp_part_ready,
                            on_pause_state_changed=on_pause_state_changed
                        )

                        with open(downloaded_file, "rb") as rf:
                            while True:
                                if cancel_event.is_set():
                                    raise InterruptedError("Cancelled by user")
                                chunk = rf.read(2 * 1024 * 1024)
                                if not chunk:
                                    break
                                mp_writer.write(chunk)
                        mp_writer.finish()

                        mp_results = await asyncio.gather(*mp_upload_tasks)
                        mp_results.sort(key=lambda x: x["part_index"])

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
                            for r in mp_results
                        ]

                        database.Files.add_multipart_file(
                            chat_id=chat_id,
                            thumbnail=mp_results[0].get("thumbnail"),
                            file_type=ftype,
                            file_unique_id=mp_results[0]["file_unique_id"],
                            file_size=actual_size,
                            file_name=f_name,
                            file_caption=f"Uploaded multi-part file: {f_name}",
                            parts=parts,
                            file_path=target_folder,
                            owner_id=str(user_id),
                            part_size=PART_MAX_SIZE,
                            is_vault=is_vault
                        )

                    # Immediately clean up downloaded file
                    if os.path.exists(downloaded_file):
                        try:
                            os.remove(downloaded_file)
                        except Exception as e:
                            logger.warning(f"Could not remove {downloaded_file}: {e}")

                    # Remove any .aria2 files and empty dirs in dl_work_dir
                    for root, dirs, d_files in os.walk(dl_work_dir, topdown=False):
                        for df in d_files:
                            if df.endswith(".aria2"):
                                try:
                                    os.remove(os.path.join(root, df))
                                except Exception:
                                    pass
                        for d in dirs:
                            dir_to_check = os.path.join(root, d)
                            try:
                                if not os.listdir(dir_to_check):
                                    os.rmdir(dir_to_check)
                            except Exception:
                                pass

                    completed_bytes += f_size

                # Clean temp directory
                shutil.rmtree(tg_dir, ignore_errors=True)

                self._update_task(task_id, {
                    "status": "completed",
                    "progress": 100.0,
                    "speed_bps": 0,
                    "eta_seconds": 0,
                    "filesize": total_torrent_size,
                    "transferred_bytes": total_torrent_size,
                    "phase": f"Completed ({total_files} file(s) saved to Telegram) ☁️"
                })
                logger.info(f"[REMOTE_TRANSFER] Task {task_id}: BitTorrent transfer finished successfully!")
                return

            elif task_doc.get("source_type") == "gdrive_file":
                import gdown

                # First resolve metadata if filename is generic
                if not task_doc.get("filename") or task_doc["filename"] == "Resolving...":
                    try:
                        def _resolve():
                            return gdown.download(
                                id=gdrive_id,
                                url=source_url if not gdrive_id else None,
                                skip_download=True,
                                quiet=True,
                                user_agent=MODERN_USER_AGENT
                            )
                        resolved = await asyncio.to_thread(_resolve)
                        if resolved and getattr(resolved, 'path', None):
                            filename_holder[0] = os.path.basename(resolved.path)
                    except Exception as e:
                        logger.warning(f"Could not pre-resolve GDrive filename: {e}")

                def _gdown_progress(cur, tot):
                    if tot:
                        estimated_total[0] = tot
                    tot_up = sum(uploaded_bytes_map.values())
                    report_combined_progress(cur, tot_up, estimated_total[0])

                def _do_gdown():
                    if priority_manager.is_user_upload_active():
                        on_pause_state_changed(True)
                        while priority_manager.is_user_upload_active() and not cancel_event.is_set():
                            priority_manager.wait_if_user_upload_active(timeout=1.0)
                        on_pause_state_changed(False)

                    try:
                        return gdown.download(
                            id=gdrive_id,
                            url=source_url if not gdrive_id else None,
                            output=writer,
                            quiet=True,
                            progress=_gdown_progress,
                            cancel=cancel_event,
                            user_agent=MODERN_USER_AGENT
                        )
                    except Exception as gerr:
                        err_str = str(gerr)
                        logger.warning(f"gdown encountered: {err_str}. Attempting direct HTTP fallback for {gdrive_id}...")
                        import requests
                        session = requests.Session()
                        session.headers.update({"User-Agent": MODERN_USER_AGENT})
                        direct_url = f"https://drive.google.com/uc?id={gdrive_id}&export=download" if gdrive_id else source_url
                        
                        resp = session.get(direct_url, stream=True, allow_redirects=True, timeout=60)
                        if resp.status_code == 404:
                            raise FileNotFoundError("Google Drive file not found (HTTP 404). It may have been deleted, moved to trash, or the link is invalid.")
                        
                        # Check for virus scan confirmation page
                        for k, v in resp.cookies.items():
                            if k.startswith('download_warning'):
                                confirm_url = f"https://drive.usercontent.google.com/download?id={gdrive_id}&export=download&confirm={v}"
                                resp = session.get(confirm_url, stream=True, allow_redirects=True, timeout=60)
                                break

                        resp.raise_for_status()
                        tot = resp.headers.get("Content-Length")
                        if tot:
                            try:
                                estimated_total[0] = int(tot)
                            except Exception:
                                pass

                        for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
                            if cancel_event.is_set():
                                raise InterruptedError("Cancelled by user")
                            if chunk:
                                writer.write(chunk)
                                tot_up = sum(uploaded_bytes_map.values())
                                report_combined_progress(writer.total_bytes, tot_up, estimated_total[0])

                logger.info(f"[REMOTE_TRANSFER] Task {task_id}: Streaming download from Google Drive...")
                await asyncio.to_thread(_do_gdown)
                writer.finish()

            else:
                # Direct HTTP / HTTPS stream download via requests with Range resumption
                logger.info(f"[REMOTE_TRANSFER] Task {task_id}: Streaming download from direct URL...")
                def _do_direct_download():
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    max_retries = 15
                    retry = 0

                    while retry < max_retries:
                        if cancel_event.is_set():
                            raise InterruptedError("Cancelled by user")

                        if priority_manager.is_user_upload_active():
                            on_pause_state_changed(True)
                            while priority_manager.is_user_upload_active() and not cancel_event.is_set():
                                priority_manager.wait_if_user_upload_active(timeout=1.0)
                            on_pause_state_changed(False)

                        req_headers = dict(headers)
                        if writer.total_bytes > 0:
                            req_headers["Range"] = f"bytes={writer.total_bytes}-"

                        try:
                            with requests.get(source_url, stream=True, timeout=60, headers=req_headers) as resp:
                                if resp.status_code not in [200, 206]:
                                    resp.raise_for_status()

                                if writer.total_bytes == 0:
                                    tot = resp.headers.get("Content-Length")
                                    if tot:
                                        try:
                                            estimated_total[0] = int(tot)
                                        except Exception:
                                            pass
                                elif resp.status_code == 206:
                                    cr = resp.headers.get("Content-Range", "")
                                    if "/" in cr:
                                        try:
                                            estimated_total[0] = int(cr.split("/")[-1])
                                        except Exception:
                                            pass

                                cd = resp.headers.get("Content-Disposition", "")
                                cd_match = re.search(r'filename=["\']?([^"\';]+)["\']?', cd)
                                if cd_match:
                                    filename_holder[0] = cd_match.group(1)
                                elif not task_doc.get("filename") or task_doc["filename"] == "Resolving...":
                                    filename_holder[0] = os.path.basename(source_url.split("?")[0]) or f"download_{task_id}.bin"

                                for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
                                    if cancel_event.is_set():
                                        raise InterruptedError("Cancelled by user")
                                    if chunk:
                                        writer.write(chunk)
                                        tot_up = sum(uploaded_bytes_map.values())
                                        report_combined_progress(writer.total_bytes, tot_up, estimated_total[0])

                                break
                        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as conn_err:
                            if cancel_event.is_set():
                                raise InterruptedError("Cancelled by user")
                            logger.warning(f"Connection dropped: {conn_err}. Reconnecting from byte {writer.total_bytes}...")
                            retry += 1
                            time.sleep(2)

                await asyncio.to_thread(_do_direct_download)
                writer.finish()

            if not upload_tasks or writer.total_bytes == 0:
                raise ValueError("No data received or transfer was cancelled.")

            # Ensure folder hierarchy exists in MongoDB
            database.Files.create_folder_path(destination_path, owner_id=str(user_id))
            file_type = get_file_type(filename_holder[0])

            # --- STEP 2: Finalize Telegram Storage Registration ---
            if len(upload_tasks) == 1 and writer.parts[0].get("part_index") == 1 and writer.total_bytes <= PART_MAX_SIZE:
                # Single-part file upload complete
                res = await upload_tasks[0]
                database.Files.add_file(
                    chat_id=chat_id,
                    message_id=res["message_id"],
                    thumbnail=res.get("thumbnail"),
                    file_type=file_type,
                    file_unique_id=res["file_unique_id"],
                    file_size=writer.total_bytes,
                    file_name=filename_holder[0],
                    file_caption=f"Uploaded file: {filename_holder[0]}",
                    file_path=destination_path,
                    owner_id=str(user_id),
                    is_vault=is_vault
                )
            else:
                # Multi-part file upload complete
                results = await asyncio.gather(*upload_tasks)
                results.sort(key=lambda x: x["part_index"])

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
                    chat_id=chat_id,
                    thumbnail=results[0].get("thumbnail"),
                    file_type=file_type,
                    file_unique_id=results[0]["file_unique_id"],
                    file_size=writer.total_bytes,
                    file_name=filename_holder[0],
                    file_caption=f"Uploaded multi-part file: {filename_holder[0]}",
                    parts=parts,
                    file_path=destination_path,
                    owner_id=str(user_id),
                    part_size=PART_MAX_SIZE,
                    is_vault=is_vault
                )

            # Cleanup temp directory
            shutil.rmtree(tg_dir, ignore_errors=True)

            self._update_task(task_id, {
                "status": "completed",
                "progress": 100.0,
                "speed_bps": 0,
                "eta_seconds": 0,
                "filesize": writer.total_bytes,
                "transferred_bytes": writer.total_bytes,
                "phase": "Completed & Saved to Telegram ☁️"
            })
            logger.info(f"[REMOTE_TRANSFER] Task {task_id}: Pipelined streaming transfer completed successfully!")

        except (asyncio.CancelledError, InterruptedError):
            for t in upload_tasks:
                if not t.done():
                    t.cancel()
            shutil.rmtree(tg_dir, ignore_errors=True)
            raise
        except Exception:
            for t in upload_tasks:
                if not t.done():
                    t.cancel()
            shutil.rmtree(tg_dir, ignore_errors=True)
            raise
        finally:
            writer.cleanup()

    def _update_task(self, task_id: str, updates: dict):
        try:
            coll = get_remote_db()["RemoteTransfers"]
            updates["updated_at"] = datetime.now(timezone.utc)
            coll.update_one({"task_id": task_id}, {"$set": updates})
        except Exception as e:
            logger.warning(f"Failed to update remote transfer {task_id}: {e}")

    def cancel_task(self, task_id: str, user_id: str) -> bool:
        coll = get_remote_db()["RemoteTransfers"]
        rec = coll.find_one({"task_id": task_id, "user_id": str(user_id)})
        if not rec:
            return False

        # Signal cancellation event if active
        if task_id in self.cancel_events:
            self.cancel_events[task_id].set()

        if task_id in self.active_tasks:
            self.active_tasks[task_id].cancel()

        self._update_task(task_id, {
            "status": "cancelled",
            "phase": "Cancelled by user",
            "speed_bps": 0
        })
        
        # Clean disk buffer
        tg_dir = os.path.join(os.getcwd(), "tg_files", f"remote_{task_id}")
        if os.path.exists(tg_dir):
            shutil.rmtree(tg_dir, ignore_errors=True)

        if rec.get("source_type") == "torrent_file" and rec.get("torrent_path"):
            if os.path.exists(rec["torrent_path"]):
                try:
                    os.remove(rec["torrent_path"])
                except Exception:
                    pass

        return True

    def clear_completed(self, user_id: str) -> int:
        coll = get_remote_db()["RemoteTransfers"]
        cleared_tasks = list(coll.find({
            "user_id": str(user_id),
            "status": {"$in": ["completed", "cancelled", "failed"]},
            "source_type": "torrent_file"
        }))
        for t in cleared_tasks:
            t_path = t.get("torrent_path")
            if t_path and os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except Exception:
                    pass

        res = coll.delete_many({
            "user_id": str(user_id),
            "status": {"$in": ["completed", "cancelled", "failed"]}
        })
        return res.deleted_count

    def get_user_tasks(self, user_id: str) -> List[Dict[str, Any]]:
        coll = get_remote_db()["RemoteTransfers"]
        docs = list(coll.find({"user_id": str(user_id)}).sort("created_at", -1).limit(50))
        for d in docs:
            d["_id"] = str(d["_id"])
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].isoformat()
            if isinstance(d.get("updated_at"), datetime):
                d["updated_at"] = d["updated_at"].isoformat()
        return docs

remote_transfer_manager = RemoteTransferManager(max_concurrent=2)
