# src/Backend/modules/disk_cache_manager.py

import os
import time
import shutil
import sqlite3
import asyncio
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from d4rk.Logs import setup_logger

LOGGER = setup_logger(__name__)

# Constants & Defaults
DEFAULT_CACHE_DIR = os.getenv("MEDIA_CACHE_DIR", "/app/cache/media")
DEFAULT_MAX_CACHE_BYTES = int(os.getenv("MEDIA_CACHE_MAX_BYTES", 25 * 1024 * 1024 * 1024))  # 25 GB Hard Cap
DEFAULT_TARGET_PURGE_BYTES = int(os.getenv("MEDIA_CACHE_TARGET_BYTES", 20 * 1024 * 1024 * 1024))  # 20 GB Target
DEFAULT_SAFETY_FREE_BYTES = int(os.getenv("MEDIA_CACHE_SAFETY_FREE", 25 * 1024 * 1024 * 1024))  # 25 GB Safety Guard
DEFAULT_TTL_SECONDS = int(os.getenv("MEDIA_CACHE_TTL_SECONDS", 7 * 86400))  # 7 Days


class DiskCacheManager:
    """
    Tier-2 Persistent SSD/Disk Cache for Telegram Media Chunks.
    Guarantees:
    1. Strict 25 GB hard cap (configurable).
    2. LRU eviction when limit is reached.
    3. 7-day TTL inactivity auto-purge.
    4. Global Disk Safety Guard: Emergency purge if VM free disk space drops below 25 GB.
    5. Permanent protection for file headers & seek cues (0ms instant playback).
    6. Non-blocking asynchronous writes to avoid slowing down client downloads.
    """

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        target_purge_bytes: int = DEFAULT_TARGET_PURGE_BYTES,
        safety_free_bytes: int = DEFAULT_SAFETY_FREE_BYTES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self.cache_dir = Path(cache_dir)
        self.max_cache_bytes = max_cache_bytes
        self.target_purge_bytes = target_purge_bytes
        self.global_safety_free_bytes = safety_free_bytes
        self.ttl_seconds = ttl_seconds

        self.db_path = self.cache_dir / "cache_index.db"
        self._lock = threading.Lock()

        # Metrics
        self.hits_disk = 0
        self.misses_disk = 0

        # Initialize storage
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._init_db()
            LOGGER.info(
                f"DiskCacheManager initialized at {self.cache_dir} "
                f"(Max: {self.max_cache_bytes / (1024**3):.1f} GB, "
                f"Safety Free Guard: {self.global_safety_free_bytes / (1024**3):.1f} GB)"
            )
        except Exception as e:
            LOGGER.error(f"Failed to initialize DiskCacheManager: {e}")

        # Start background maintenance loop
        self._cleaner_task: Optional[asyncio.Task] = None

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS chunks (
                            chat_id INTEGER,
                            message_id INTEGER,
                            chunk_offset INTEGER,
                            chunk_size INTEGER,
                            file_path TEXT,
                            bytes_length INTEGER,
                            last_accessed REAL,
                            is_header INTEGER DEFAULT 0,
                            PRIMARY KEY (chat_id, message_id, chunk_offset, chunk_size)
                        );
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_chunks_lru
                        ON chunks (is_header, last_accessed);
                    """)
            finally:
                conn.close()

    def start_background_cleaner(self):
        """Start periodic maintenance task in running event loop."""
        if self._cleaner_task is None or self._cleaner_task.done():
            self._cleaner_task = asyncio.create_task(self._periodic_cleaner())

    async def _periodic_cleaner(self):
        """Runs every 30 minutes to clean expired TTL chunks and verify disk limits."""
        while True:
            try:
                await asyncio.sleep(1800)  # 30 minutes
                await asyncio.to_thread(self.maintenance_cycle)
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.error(f"Error in DiskCacheManager periodic cleaner: {e}")

    def maintenance_cycle(self):
        """Run standard maintenance: check safety guard, purge expired TTL, enforce size cap."""
        LOGGER.debug("Running DiskCacheManager maintenance cycle...")
        self.check_emergency_purge()
        self.purge_expired()
        self.enforce_max_size()

    def get_chunk_file_path(self, chat_id: int, message_id: int, chunk_offset: int, chunk_size: int) -> Path:
        shard_dir = self.cache_dir / f"{chat_id}_{message_id}"
        return shard_dir / f"{chunk_offset}_{chunk_size}.bin"

    def get(self, chat_id: int, message_id: int, chunk_offset: int, chunk_size: int) -> Optional[bytes]:
        """
        Retrieve chunk from disk. Returns bytes if present and valid, else None.
        Updates last_accessed timestamp on hit.
        """
        key = (int(chat_id), int(message_id), int(chunk_offset), int(chunk_size))
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT file_path, bytes_length FROM chunks WHERE chat_id=? AND message_id=? AND chunk_offset=? AND chunk_size=?",
                    key,
                )
                row = cur.fetchone()
                if not row:
                    self.misses_disk += 1
                    return None

                file_path_str, expected_len = row
                p = Path(file_path_str)
                if not p.is_file():
                    # Orphaned record, delete
                    cur.execute(
                        "DELETE FROM chunks WHERE chat_id=? AND message_id=? AND chunk_offset=? AND chunk_size=?",
                        key,
                    )
                    conn.commit()
                    self.misses_disk += 1
                    return None

                try:
                    data = p.read_bytes()
                    if len(data) != expected_len:
                        p.unlink(missing_ok=True)
                        cur.execute(
                            "DELETE FROM chunks WHERE chat_id=? AND message_id=? AND chunk_offset=? AND chunk_size=?",
                            key,
                        )
                        conn.commit()
                        self.misses_disk += 1
                        return None

                    # Update last accessed time
                    now = time.time()
                    cur.execute(
                        "UPDATE chunks SET last_accessed=? WHERE chat_id=? AND message_id=? AND chunk_offset=? AND chunk_size=?",
                        (now, *key),
                    )
                    conn.commit()
                    self.hits_disk += 1
                    return data
                except Exception as ex:
                    LOGGER.warning(f"Error reading chunk file {p}: {ex}")
                    self.misses_disk += 1
                    return None
            finally:
                conn.close()

    def put(
        self,
        chat_id: int,
        message_id: int,
        chunk_offset: int,
        chunk_size: int,
        data: bytes,
        is_header: bool = False,
    ):
        """
        Synchronously write chunk to disk and index in SQLite.
        Atomic write with .tmp rename to guarantee data integrity.
        """
        if not data:
            return

        data_len = len(data)
        # Check global safety guard before writing
        if self.check_emergency_purge():
            LOGGER.warning("Skipping disk cache write: Global Disk Safety Guard is active (<25GB free)")
            return

        # Enforce LRU cap if needed
        self.enforce_max_size(incoming_bytes=data_len)

        target_file = self.get_chunk_file_path(chat_id, message_id, chunk_offset, chunk_size)
        tmp_file = target_file.with_suffix(".tmp")

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file.write_bytes(data)
            tmp_file.replace(target_file)
        except Exception as e:
            LOGGER.warning(f"Failed to write chunk file to disk: {e}")
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)
            return

        now = time.time()
        is_hdr_val = 1 if (is_header or chunk_offset == 0) else 0

        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO chunks 
                        (chat_id, message_id, chunk_offset, chunk_size, file_path, bytes_length, last_accessed, is_header)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            int(chat_id),
                            int(message_id),
                            int(chunk_offset),
                            int(chunk_size),
                            str(target_file),
                            data_len,
                            now,
                            is_hdr_val,
                        ),
                    )
            except Exception as ex:
                LOGGER.warning(f"Failed to index chunk in SQLite: {ex}")
            finally:
                conn.close()

    async def put_async(
        self,
        chat_id: int,
        message_id: int,
        chunk_offset: int,
        chunk_size: int,
        data: bytes,
        is_header: bool = False,
    ):
        """Non-blocking asynchronous write to SSD cache."""
        try:
            await asyncio.to_thread(
                self.put,
                chat_id,
                message_id,
                chunk_offset,
                chunk_size,
                data,
                is_header,
            )
        except Exception as e:
            LOGGER.debug(f"Async put error in disk cache: {e}")

    def get_total_cache_size(self) -> int:
        """Returns total bytes used by cache according to SQLite index."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT SUM(bytes_length) FROM chunks")
                row = cur.fetchone()
                return int(row[0] or 0)
            finally:
                conn.close()

    def get_free_disk_space(self) -> int:
        """Returns free bytes on the filesystem hosting the cache."""
        try:
            usage = shutil.disk_usage(str(self.cache_dir))
            return usage.free
        except Exception:
            return 100 * 1024 * 1024 * 1024

    def check_emergency_purge(self) -> bool:
        """
        Global Disk Safety Guard:
        If VM free space is less than 25 GB, purge non-header media cache
        to guarantee archive extraction and uploads never hit 'Disk Full'.
        Returns True if emergency purge was triggered or is active.
        """
        free_bytes = self.get_free_disk_space()
        if free_bytes < self.global_safety_free_bytes:
            LOGGER.warning(
                f"[Safety Guard Triggered] Free disk space ({free_bytes / (1024**3):.2f} GB) "
                f"< safety limit ({self.global_safety_free_bytes / (1024**3):.2f} GB). Purging media disk cache!"
            )
            self._purge_to_target(target_bytes=0, purge_headers=False)
            return True
        return False

    def purge_expired(self):
        """Purge chunks that haven't been accessed in ttl_seconds (7 days default)."""
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                # Find expired non-header chunks
                cur.execute(
                    "SELECT chat_id, message_id, chunk_offset, chunk_size, file_path FROM chunks WHERE is_header=0 AND last_accessed < ?",
                    (cutoff,),
                )
                rows = cur.fetchall()
                if not rows:
                    return

                LOGGER.info(f"Purging {len(rows)} expired media chunks (inactive > {self.ttl_seconds // 86400} days)...")
                for c_id, m_id, c_off, c_sz, f_path in rows:
                    p = Path(f_path)
                    p.unlink(missing_ok=True)
                    # Clean up parent shard directory if empty
                    try:
                        p.parent.rmdir()
                    except OSError:
                        pass

                cur.execute("DELETE FROM chunks WHERE is_header=0 AND last_accessed < ?", (cutoff,))
                conn.commit()
            except Exception as e:
                LOGGER.error(f"Error purging expired chunks: {e}")
            finally:
                conn.close()

    def enforce_max_size(self, incoming_bytes: int = 0):
        """
        LRU Eviction Engine:
        If total size exceeds 25 GB, delete oldest-accessed chunks down to target_purge_bytes (20 GB).
        """
        current_size = self.get_total_cache_size()
        if current_size + incoming_bytes > self.max_cache_bytes:
            LOGGER.info(
                f"[LRU Eviction] Cache size ({(current_size + incoming_bytes) / (1024**3):.2f} GB) "
                f"> limit ({self.max_cache_bytes / (1024**3):.2f} GB). Evicting down to {self.target_purge_bytes / (1024**3):.2f} GB..."
            )
            self._purge_to_target(target_bytes=self.target_purge_bytes, purge_headers=False)

    def _purge_to_target(self, target_bytes: int, purge_headers: bool = False):
        """Iteratively evict oldest non-header chunks until total size is <= target_bytes."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                while True:
                    cur.execute("SELECT SUM(bytes_length) FROM chunks")
                    total = cur.fetchone()[0] or 0
                    if total <= target_bytes:
                        break

                    # Fetch batch of oldest chunks
                    query = (
                        "SELECT chat_id, message_id, chunk_offset, chunk_size, file_path FROM chunks "
                        + ("" if purge_headers else "WHERE is_header=0 ")
                        + "ORDER BY last_accessed ASC LIMIT 100"
                    )
                    cur.execute(query)
                    batch = cur.fetchall()
                    if not batch:
                        # Only headers left or no chunks left
                        break

                    for c_id, m_id, c_off, c_sz, f_path in batch:
                        p = Path(f_path)
                        p.unlink(missing_ok=True)
                        try:
                            p.parent.rmdir()
                        except OSError:
                            pass
                        cur.execute(
                            "DELETE FROM chunks WHERE chat_id=? AND message_id=? AND chunk_offset=? AND chunk_size=?",
                            (c_id, m_id, c_off, c_sz),
                        )
                    conn.commit()
            except Exception as e:
                LOGGER.error(f"Error in _purge_to_target: {e}")
            finally:
                conn.close()

    def clear_all(self) -> int:
        """Manually clear entire media disk cache. Returns number of bytes cleared."""
        freed_bytes = self.get_total_cache_size()
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT file_path FROM chunks")
                for (f_path,) in cur.fetchall():
                    Path(f_path).unlink(missing_ok=True)

                # Remove shard directories
                for item in self.cache_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)

                cur.execute("DELETE FROM chunks")
                conn.commit()
                self.hits_disk = 0
                self.misses_disk = 0
                LOGGER.info(f"DiskCacheManager: Cleared all cache ({freed_bytes / (1024**2):.2f} MB freed)")
            except Exception as e:
                LOGGER.error(f"Error clearing cache: {e}")
            finally:
                conn.close()
        return freed_bytes

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics for API & Frontend Storage Analytics."""
        current_size = self.get_total_cache_size()
        free_disk = self.get_free_disk_space()

        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*), SUM(CASE WHEN is_header=1 THEN 1 ELSE 0 END) FROM chunks")
                row = cur.fetchone()
                chunk_count = row[0] or 0
                header_count = row[1] or 0
            finally:
                conn.close()

        def _fmt(b: int) -> str:
            if b >= 1024**3:
                return f"{b / (1024**3):.2f} GB"
            elif b >= 1024**2:
                return f"{b / (1024**2):.2f} MB"
            elif b >= 1024:
                return f"{b / 1024:.2f} KB"
            return f"{b} B"

        return {
            "total_size_bytes": current_size,
            "total_size_formatted": _fmt(current_size),
            "max_size_bytes": self.max_cache_bytes,
            "max_size_formatted": _fmt(self.max_cache_bytes),
            "usage_percent": round((current_size / self.max_cache_bytes) * 100, 1) if self.max_cache_bytes else 0,
            "chunk_count": chunk_count,
            "header_count": header_count,
            "free_disk_space_bytes": free_disk,
            "free_disk_space_formatted": _fmt(free_disk),
            "safety_guard_bytes": self.global_safety_free_bytes,
            "safety_guard_formatted": _fmt(self.global_safety_free_bytes),
            "ttl_days": self.ttl_seconds // 86400,
            "hits_disk": self.hits_disk,
            "misses_disk": self.misses_disk,
        }


# Global Singleton Instance
DISK_CACHE_MANAGER = DiskCacheManager()
