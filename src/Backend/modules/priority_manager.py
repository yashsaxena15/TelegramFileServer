# src/Backend/modules/priority_manager.py

import time
import asyncio
import threading
import logging
from typing import Set, Optional, Callable, Dict

logger = logging.getLogger("priority_manager")

class UploadPriorityManager:
    """
    Quality-of-Service (QoS) Bandwidth Coordinator.
    Tracks active user-to-server uploads. When a user is uploading:
    - Signals all background Server-to-Server (Remote Transfer / Cloud Leech) tasks to PAUSE.
    - Yields 100% VM bandwidth and Telegram bot capacity to the user.
    - When all user uploads complete, signals paused Server-to-Server tasks to automatically RESUME.
    """
    def __init__(self):
        self._active_upload_ids: Dict[str, float] = {}  # upload_id -> last_activity_timestamp
        self._lock = threading.Lock()
        
        # Threading event: Set when remote transfers are ALLOWED to run (no active user upload).
        # Cleared when a user upload is active (remote transfers MUST pause).
        self._can_run_event = threading.Event()
        self._can_run_event.set()

        # Asyncio event for async loops
        self._async_can_run_event: Optional[asyncio.Event] = None
        self._listeners: list[Callable[[bool], None]] = []

    def get_async_event(self) -> asyncio.Event:
        if self._async_can_run_event is None:
            self._async_can_run_event = asyncio.Event()
            if self._can_run_event.is_set():
                self._async_can_run_event.set()
            else:
                self._async_can_run_event.clear()
        return self._async_can_run_event

    def register_listener(self, cb: Callable[[bool], None]):
        """Register a callback for pause state changes: cb(is_paused: bool)"""
        with self._lock:
            self._listeners.append(cb)

    def touch_user_upload(self, upload_id: str):
        """Update last activity timestamp for an ongoing upload session."""
        with self._lock:
            if upload_id in self._active_upload_ids:
                self._active_upload_ids[upload_id] = time.time()

    def notify_user_upload_started(self, upload_id: str):
        """Called when a user starts uploading a file."""
        with self._lock:
            was_idle = len(self._active_upload_ids) == 0
            self._active_upload_ids[upload_id] = time.time()

            if was_idle:
                logger.info(
                    f"[PRIORITY_MANAGER] User upload '{upload_id}' started. "
                    f"Prioritizing User-to-Server bandwidth. Signaling Cloud Leech transfers to PAUSE ⏸️."
                )
                self._can_run_event.clear()
                if self._async_can_run_event:
                    self._async_can_run_event.clear()
                self._notify_listeners(is_paused=True)

    def notify_user_upload_finished(self, upload_id: str):
        """Called when a user upload completes, fails, or is aborted."""
        with self._lock:
            if upload_id in self._active_upload_ids:
                del self._active_upload_ids[upload_id]
            
            # Clean up any stale sessions (> 30 mins with no activity)
            now = time.time()
            stale_keys = [uid for uid, t in self._active_upload_ids.items() if now - t > 1800]
            for uid in stale_keys:
                del self._active_upload_ids[uid]

            if len(self._active_upload_ids) == 0 and not self._can_run_event.is_set():
                logger.info(
                    f"[PRIORITY_MANAGER] All user uploads finished (released '{upload_id}'). "
                    f"Resuming Cloud Leech transfers ▶️."
                )
                self._can_run_event.set()
                if self._async_can_run_event:
                    self._async_can_run_event.set()
                self._notify_listeners(is_paused=False)

    def is_user_upload_active(self) -> bool:
        """Returns True if any user upload is currently in progress."""
        with self._lock:
            # Check for stale sessions
            now = time.time()
            active_count = 0
            stale_keys = []
            for uid, last_t in self._active_upload_ids.items():
                if now - last_t > 1800:
                    stale_keys.append(uid)
                else:
                    active_count += 1
            for uid in stale_keys:
                del self._active_upload_ids[uid]

            if active_count == 0 and not self._can_run_event.is_set():
                self._can_run_event.set()
                if self._async_can_run_event:
                    self._async_can_run_event.set()
                self._notify_listeners(is_paused=False)

            return active_count > 0

    def wait_if_user_upload_active(self, timeout: Optional[float] = None) -> bool:
        """
        Blocks current thread if a user upload is active until user finishes or timeout expires.
        Returns True if unblocked (safe to transfer), False if timed out while still paused.
        """
        return self._can_run_event.wait(timeout=timeout)

    async def async_wait_if_user_upload_active(self):
        """Asynchronously waits until no user upload is active."""
        ev = self.get_async_event()
        await ev.wait()

    def _notify_listeners(self, is_paused: bool):
        for cb in list(self._listeners):
            try:
                cb(is_paused)
            except Exception as e:
                logger.warning(f"Error executing priority manager listener: {e}")

priority_manager = UploadPriorityManager()
