# src/Backend/modules/archive_task_manager.py

import os
import shutil
import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from pymongo import MongoClient

from src.Config import DATABASE_URL, APP_NAME
from src.Database import database
from d4rk.Logs import setup_logger
from .priority_manager import priority_manager

logger = setup_logger("archive_task_manager")

TEMP_ARCHIVE_DIR = "/home/ubuntu/projects/TelegramFileServer/src/Backend/temp_archives"
os.makedirs(TEMP_ARCHIVE_DIR, exist_ok=True)

# Mandatory safety buffer: 25 GB
SAFETY_RESERVE_BYTES = 25 * 1024 * 1024 * 1024


def check_disk_safety(estimated_peak_bytes: int) -> Tuple[bool, str, Dict[str, float]]:
    """
    Checks whether the estimated peak disk space requirement for an archive task
    leaves at least 25 GB of free disk space on the server.
    Takes sub-millisecond to execute.
    """
    try:
        stat = shutil.disk_usage(TEMP_ARCHIVE_DIR)
        free_bytes = stat.free
    except Exception:
        stat = shutil.disk_usage("/")
        free_bytes = stat.free

    remaining_after_peak = free_bytes - estimated_peak_bytes
    free_gb = round(free_bytes / (1024**3), 2)
    peak_gb = round(estimated_peak_bytes / (1024**3), 2)
    buffer_gb = round(SAFETY_RESERVE_BYTES / (1024**3), 2)
    projected_remaining_gb = round(remaining_after_peak / (1024**3), 2)

    if remaining_after_peak < SAFETY_RESERVE_BYTES:
        detail = (
            f"Operation blocked for server safety: This task requires ~{peak_gb} GB peak disk space, "
            f"leaving only {projected_remaining_gb} GB free. The server requires a mandatory safety reserve "
            f"of at least {buffer_gb} GB to maintain system stability. Current free space: {free_gb} GB."
        )
        logger.warning(f"[DISK_GUARD] {detail}")
        return False, detail, {
            "required_peak_gb": peak_gb,
            "free_gb": free_gb,
            "safety_buffer_gb": buffer_gb,
            "projected_remaining_gb": projected_remaining_gb
        }

    return True, "", {
        "required_peak_gb": peak_gb,
        "free_gb": free_gb,
        "safety_buffer_gb": buffer_gb,
        "projected_remaining_gb": projected_remaining_gb
    }


class ArchiveTaskManager:
    """
    Manages asynchronous background compression and extraction tasks.
    Ensures concurrency limits (1 heavy task at a time for 1 vCPU preservation),
    real-time progress reporting, low CPU priority execution, and clean cancellation.
    """
    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._initialized = False

    def ensure_started(self):
        if not self._initialized:
            self._worker_task = asyncio.create_task(self._worker_loop())
            self._initialized = True
            logger.info("ArchiveTaskManager background worker initialized.")

    def get_db(self):
        if hasattr(database, "db") and database.db is not None:
            return database.db
        client = MongoClient(DATABASE_URL)
        return client[APP_NAME]

    def create_task(
        self,
        task_type: str,  # 'extract' or 'compress'
        user_id: str,
        target_name: str,
        payload: Dict[str, Any]
    ) -> str:
        self.ensure_started()
        task_id = f"arch_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        task_data = {
            "task_id": task_id,
            "task_type": task_type,
            "user_id": str(user_id),
            "target_name": target_name,
            "status": "queued",
            "stage": "queued",
            "progress_percent": 0.0,
            "current_file": "",
            "processed_files": 0,
            "total_files": 0,
            "processed_bytes": 0,
            "total_bytes": 0,
            "error": None,
            "payload": payload,
            "created_at": now,
            "updated_at": now
        }

        self._tasks[task_id] = task_data
        self._cancel_events[task_id] = asyncio.Event()

        # Persist to MongoDB
        try:
            db = self.get_db()
            db.archive_tasks.insert_one(dict(task_data))
        except Exception as e:
            logger.warning(f"Failed to persist archive task {task_id} in Mongo: {e}")

        self._queue.put_nowait(task_id)
        logger.info(f"Enqueued archive task {task_id} ({task_type}) for user {user_id}")
        return task_id

    def get_task(self, task_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # Check in-memory cache first
        task = self._tasks.get(task_id)
        if task:
            if user_id and task.get("user_id") != str(user_id):
                return None
            return {k: v for k, v in task.items() if k != "payload"}

        # Check MongoDB
        try:
            db = self.get_db()
            doc = db.archive_tasks.find_one({"task_id": task_id})
            if doc:
                doc["_id"] = str(doc["_id"])
                if user_id and doc.get("user_id") != str(user_id):
                    return None
                doc.pop("payload", None)
                return doc
        except Exception:
            pass

        return None

    def list_tasks(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        # Filter from memory + mongo
        results = []
        seen = set()

        for t_id, t in list(self._tasks.items()):
            if t.get("user_id") == str(user_id):
                results.append({k: v for k, v in t.items() if k != "payload"})
                seen.add(t_id)

        try:
            db = self.get_db()
            cursor = db.archive_tasks.find({"user_id": str(user_id)}).sort("created_at", -1).limit(limit)
            for doc in cursor:
                t_id = doc.get("task_id")
                if t_id and t_id not in seen:
                    doc["_id"] = str(doc["_id"])
                    doc.pop("payload", None)
                    results.append(doc)
                    seen.add(t_id)
        except Exception:
            pass

        # Sort newest first
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    def update_task_progress(
        self,
        task_id: str,
        stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
        current_file: Optional[str] = None,
        processed_files: Optional[int] = None,
        total_files: Optional[int] = None,
        processed_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        status: Optional[str] = None,
        error: Optional[str] = None
    ):
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        now = datetime.now(timezone.utc).isoformat()
        task["updated_at"] = now

        if stage is not None:
            task["stage"] = stage
        if progress_percent is not None:
            task["progress_percent"] = round(min(100.0, max(0.0, progress_percent)), 1)
        if current_file is not None:
            task["current_file"] = current_file
        if processed_files is not None:
            task["processed_files"] = processed_files
        if total_files is not None:
            task["total_files"] = total_files
        if processed_bytes is not None:
            task["processed_bytes"] = processed_bytes
        if total_bytes is not None:
            task["total_bytes"] = total_bytes
        if status is not None:
            task["status"] = status
        if error is not None:
            task["error"] = error

        # Periodic update to MongoDB
        try:
            db = self.get_db()
            update_fields = {
                "updated_at": now,
                "stage": task["stage"],
                "progress_percent": task["progress_percent"],
                "current_file": task["current_file"],
                "processed_files": task["processed_files"],
                "total_files": task["total_files"],
                "processed_bytes": task["processed_bytes"],
                "total_bytes": task["total_bytes"],
                "status": task["status"],
                "error": task["error"]
            }
            db.archive_tasks.update_one({"task_id": task_id}, {"$set": update_fields})
        except Exception:
            pass

    def cancel_task(self, task_id: str, user_id: Optional[str] = None) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            try:
                db = self.get_db()
                doc = db.archive_tasks.find_one({"task_id": task_id})
                if doc:
                    if user_id and doc.get("user_id") != str(user_id):
                        return False
                    db.archive_tasks.update_one({"task_id": task_id}, {"$set": {"status": "cancelled", "stage": "cancelled"}})
                    return True
            except Exception:
                pass
            return False

        if user_id and task.get("user_id") != str(user_id):
            return False

        if task["status"] in ["completed", "failed", "cancelled"]:
            return False

        ev = self._cancel_events.get(task_id)
        if ev:
            ev.set()

        self.update_task_progress(task_id, status="cancelled", stage="cancelled")
        logger.info(f"Cancelled archive task {task_id}")
        return True

    def is_cancelled(self, task_id: str) -> bool:
        ev = self._cancel_events.get(task_id)
        return ev.is_set() if ev else False

    async def _worker_loop(self):
        """Processes archive tasks one by one to avoid CPU and disk I/O contention on 1 vCPU."""
        while True:
            try:
                task_id = await self._queue.get()
                task = self._tasks.get(task_id)
                if not task:
                    self._queue.task_done()
                    continue

                if self.is_cancelled(task_id):
                    self._queue.task_done()
                    continue

                self.update_task_progress(task_id, status="running", stage="starting")

                task_type = task["task_type"]
                payload = task["payload"]

                try:
                    from .cloud_archive import execute_task_extract, execute_task_compress

                    if task_type == "extract":
                        await execute_task_extract(task_id=task_id, payload=payload, manager=self)
                    elif task_type == "compress":
                        await execute_task_compress(task_id=task_id, payload=payload, manager=self)
                    else:
                        raise ValueError(f"Unknown task type: {task_type}")

                    if not self.is_cancelled(task_id):
                        self.update_task_progress(task_id, status="completed", stage="completed", progress_percent=100.0)
                except asyncio.CancelledError:
                    self.update_task_progress(task_id, status="cancelled", stage="cancelled")
                except Exception as e:
                    logger.error(f"Archive task {task_id} failed: {e}", exc_info=True)
                    self.update_task_progress(task_id, status="failed", stage="error", error=str(e))
                finally:
                    self._queue.task_done()
            except Exception as loop_err:
                logger.error(f"Unexpected error in archive worker loop: {loop_err}", exc_info=True)
                await asyncio.sleep(1)


archive_task_manager = ArchiveTaskManager()
