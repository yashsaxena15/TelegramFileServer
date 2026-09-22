# src/Backend/modules/byte_streamer.py

import asyncio
import math
from typing import Dict
from pyrogram import Client
from pyrogram import raw
from pyrogram import utils
from pyrogram.errors import AuthBytesInvalid
from pyrogram.session import Session, Auth
from pyrogram.file_id import FileId, FileType, ThumbnailSource

from d4rk.Logs import setup_logger
from .streaming_utils import get_file_ids

from collections import OrderedDict
import threading
from .disk_cache_manager import DISK_CACHE_MANAGER

LOGGER = setup_logger(__name__)


class InvalidHash(Exception):
    message = 'Invalid hash!'


class FIleNotFound(Exception):
    message = 'File not found!'


class MediaChunkCache:
    """
    High-performance in-memory LRU cache for media chunks (e.g. 1MB MTProto blocks).
    Caches recent chunks so seeking back 10s or replaying scenes has 0ms latency.
    Also caches container cues/headers at the start and end of media files.
    """
    def __init__(self, max_size_bytes: int = 250 * 1024 * 1024):  # 250 MB in RAM
        self.max_size_bytes = max_size_bytes
        self.current_size_bytes = 0
        self.cache: OrderedDict = OrderedDict()
        self.lock = threading.Lock()

    def get(self, chat_id: int, message_id: int, chunk_offset: int, chunk_size: int):
        key = (int(chat_id), int(message_id), int(chunk_offset), int(chunk_size))
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def put(self, chat_id: int, message_id: int, chunk_offset: int, chunk_size: int, data: bytes):
        if not data:
            return
        key = (int(chat_id), int(message_id), int(chunk_offset), int(chunk_size))
        data_len = len(data)
        with self.lock:
            if key in self.cache:
                old_data = self.cache.pop(key)
                self.current_size_bytes -= len(old_data)

            while self.current_size_bytes + data_len > self.max_size_bytes and self.cache:
                _, evicted = self.cache.popitem(last=False)
                self.current_size_bytes -= len(evicted)

            self.cache[key] = data
            self.current_size_bytes += data_len

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.current_size_bytes = 0


GLOBAL_CHUNK_CACHE = MediaChunkCache(max_size_bytes=250 * 1024 * 1024)

_BYTE_STREAMER_INSTANCES: Dict[object, "ByteStreamer"] = {}


def get_byte_streamer(client: Client) -> "ByteStreamer":
    if client not in _BYTE_STREAMER_INSTANCES:
        _BYTE_STREAMER_INSTANCES[client] = ByteStreamer(client)
    return _BYTE_STREAMER_INSTANCES[client]


class ByteStreamer:
    def __init__(self, client: Client):
        self.clean_timer = 30 * 60
        self.client: Client = client
        self.__cached_file_ids: Dict[int, FileId] = {}
        asyncio.create_task(self.clean_cache())
        try:
            DISK_CACHE_MANAGER.start_background_cleaner()
        except Exception:
            pass

    async def get_file_properties(self, chat_id: int, message_id: int, client: Client = None) -> FileId:
        c = client or self.client
        key = (getattr(c, 'name', 'default'), int(chat_id), int(message_id))
        if key not in self.__cached_file_ids:
            file_id = await get_file_ids(c, int(chat_id), int(message_id))
            if not file_id:
                if client is None:
                    LOGGER.info('Message with ID %s not found!', message_id)
                    raise FIleNotFound
                return None
            self.__cached_file_ids[key] = file_id
        return self.__cached_file_ids[key]

    async def yield_parts(self, parts_to_stream: list, chunk_size: int, client_list: list = None):
        """
        Stream one or more parts of a file seamlessly across multiple Telegram messages.
        Each item in parts_to_stream is a dict with:
        {
            'chat_id': int,
            'message_id': int,
            'part_from_byte': int,
            'part_until_byte': int,
            'part_index': int
        }
        """
        active_clients = client_list or [self.client]

        for part_info in parts_to_stream:
            chat_id = part_info["chat_id"]
            message_id = part_info["message_id"]
            part_from = part_info["part_from_byte"]
            part_until = part_info["part_until_byte"]
            part_idx_num = part_info.get("part_index", 1)

            if part_until < part_from:
                continue

            offset = part_from - (part_from % chunk_size)
            first_part_cut = part_from - offset
            last_part_cut = (part_until % chunk_size) + 1
            part_count = math.ceil((part_until + 1) / chunk_size) - math.floor(offset / chunk_size)

            # Instant Multi-Tier Cache Fast-Path: L1 (RAM) -> L2 (SSD Disk)
            all_cached = True
            cached_chunks = {}
            for seq in range(1, part_count + 1):
                p_offset = offset + (seq - 1) * chunk_size
                # 1. Check L1 RAM Cache
                c_data = GLOBAL_CHUNK_CACHE.get(chat_id, message_id, p_offset, chunk_size)
                if c_data is None:
                    # 2. Check L2 SSD Disk Cache
                    c_data = DISK_CACHE_MANAGER.get(chat_id, message_id, p_offset, chunk_size)
                    if c_data is not None:
                        GLOBAL_CHUNK_CACHE.put(chat_id, message_id, p_offset, chunk_size, c_data)

                if c_data is not None:
                    cached_chunks[seq] = c_data
                else:
                    all_cached = False
                    break

            if all_cached:
                LOGGER.debug(f"Part {part_idx_num} (bytes {part_from}-{part_until}) served instantly from L1/L2 Cache")
                for seq in range(1, part_count + 1):
                    chunk = cached_chunks[seq]
                    if part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                    elif seq == 1:
                        yield chunk[first_part_cut:]
                    elif seq == part_count:
                        yield chunk[:last_part_cut]
                    else:
                        yield chunk
                continue

            # Cache miss: Gather workers in parallel (limit to max 4 needed workers for speed)
            max_needed = min(len(active_clients), max(2, min(part_count, 4)))
            workers = []

            # Check primary client first (usually warm in cache)
            try:
                fid = await self.get_file_properties(chat_id=chat_id, message_id=message_id, client=self.client)
                if fid:
                    workers.append((self.client, fid))
            except Exception as ex:
                LOGGER.debug(f"Primary client error: {ex}")

            # Gather additional workers in parallel if needed
            if len(workers) < max_needed:
                candidates = [c for c in active_clients if c != self.client and getattr(c, 'is_connected', False)][:max_needed - len(workers)]
                if candidates:
                    async def _resolve_w(c):
                        try:
                            w_fid = await self.get_file_properties(chat_id=chat_id, message_id=message_id, client=c)
                            return (c, w_fid) if w_fid else None
                        except Exception:
                            return None

                    extra_workers = await asyncio.gather(*[_resolve_w(c) for c in candidates])
                    for w in extra_workers:
                        if w:
                            workers.append(w)

            if not workers:
                LOGGER.error(f"No active workers found for part {part_idx_num} (chat {chat_id}, msg {message_id})")
                return

            LOGGER.info(f"Yielding part {part_idx_num} (bytes {part_from}-{part_until}) with {len(workers)} worker(s)")

            # Prepare media sessions in parallel
            async def _prepare_session(w_c, w_fid):
                try:
                    sess = await self.generate_media_session(w_c, w_fid)
                    loc = await self.get_location(w_fid)
                    if sess and loc:
                        return (w_c, sess, loc)
                except Exception as ex:
                    LOGGER.debug(f"Session creation failed for {getattr(w_c, 'name', str(w_c))}: {ex}")
                return None

            worker_sessions = [s for s in await asyncio.gather(*[_prepare_session(w_c, w_fid) for w_c, w_fid in workers]) if s]

            if not worker_sessions:
                LOGGER.error(f"No valid media sessions for part {part_idx_num}")
                return

            for w_c, _ in workers:
                if hasattr(w_c, 'add_workload'):
                    w_c.add_workload(1)

            num_workers = len(worker_sessions)
            PREFETCH_COUNT = max(2, min(num_workers, 4))

            async def fetch_part_chunk(chunk_seq: int, chunk_offset: int) -> bytes:
                # 1. Check L1 RAM Chunk Cache for 0ms instant seeking/rewind
                cached = GLOBAL_CHUNK_CACHE.get(chat_id, message_id, chunk_offset, chunk_size)
                if cached is not None:
                    return cached

                # 2. Check L2 SSD Disk Cache
                disk_cached = DISK_CACHE_MANAGER.get(chat_id, message_id, chunk_offset, chunk_size)
                if disk_cached is not None:
                    GLOBAL_CHUNK_CACHE.put(chat_id, message_id, chunk_offset, chunk_size, disk_cached)
                    return disk_cached

                # 3. Fetch from Telegram MTProto
                for attempt in range(min(3, num_workers)):
                    w_c, sess, loc = worker_sessions[(chunk_seq - 1 + attempt) % num_workers]
                    try:
                        r = await sess.send(
                            raw.functions.upload.GetFile(
                                location=loc, offset=chunk_offset, limit=chunk_size
                            ),
                            timeout=15,
                        )
                        if isinstance(r, raw.types.upload.File):
                            chunk_data = r.bytes
                            if chunk_data:
                                # Save to L1 RAM Cache
                                GLOBAL_CHUNK_CACHE.put(chat_id, message_id, chunk_offset, chunk_size, chunk_data)
                                # Asynchronously persist to L2 SSD cache in background
                                is_header = (chunk_offset == 0 or chunk_seq == 1 or chunk_seq == part_count)
                                asyncio.create_task(
                                    DISK_CACHE_MANAGER.put_async(
                                        chat_id, message_id, chunk_offset, chunk_size, chunk_data, is_header=is_header
                                    )
                                )
                            return chunk_data
                    except (TimeoutError, OSError, asyncio.TimeoutError) as e:
                        if attempt == min(3, num_workers) - 1:
                            LOGGER.warning(f"Timeout fetching chunk {chunk_seq} from {getattr(w_c, 'name', str(w_c))}: {e}")
                        await asyncio.sleep(0.1)
                    except Exception as e:
                        if attempt == min(3, num_workers) - 1:
                            LOGGER.warning(f"Error fetching chunk {chunk_seq} from {getattr(w_c, 'name', str(w_c))}: {e}")
                        await asyncio.sleep(0.1)
                return b""

            tasks: Dict[int, asyncio.Task] = {}
            next_to_schedule = 1
            current_chunk = 1

            try:
                # Schedule chunk 1 first for lowest initial TTFB
                p_offset = offset
                tasks[1] = asyncio.create_task(fetch_part_chunk(1, p_offset))
                next_to_schedule = 2

                # Pre-fill rest of the sliding window
                while next_to_schedule <= min(part_count, PREFETCH_COUNT):
                    p_offset = offset + (next_to_schedule - 1) * chunk_size
                    tasks[next_to_schedule] = asyncio.create_task(fetch_part_chunk(next_to_schedule, p_offset))
                    next_to_schedule += 1

                for current_chunk in range(1, part_count + 1):
                    if next_to_schedule <= part_count:
                        p_offset = offset + (next_to_schedule - 1) * chunk_size
                        tasks[next_to_schedule] = asyncio.create_task(fetch_part_chunk(next_to_schedule, p_offset))
                        next_to_schedule += 1

                    task = tasks.pop(current_chunk, None)
                    if not task:
                        break

                    chunk = await task
                    if not chunk:
                        LOGGER.warning(f"Empty chunk at {current_chunk}/{part_count} for part {part_idx_num}")
                        break

                    if part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                    elif current_chunk == 1:
                        yield chunk[first_part_cut:]
                    elif current_chunk == part_count:
                        yield chunk[:last_part_cut]
                    else:
                        yield chunk

            except (asyncio.CancelledError, GeneratorExit):
                LOGGER.debug("Client cancelled streaming/download.")
                return
            except Exception as e:
                LOGGER.error(f"Error during part streaming: {e}")
                return
            finally:
                for t in tasks.values():
                    if not t.done():
                        t.cancel()
                for w_c, _ in workers:
                    if hasattr(w_c, 'add_workload'):
                        w_c.add_workload(-1)

    async def yield_file(self, file_id: FileId, client, offset: int, first_part_cut: int, last_part_cut: int, part_count: int, chunk_size: int, workers: list = None):
        # Workload tracking
        active_workers = workers or [(client, file_id)]
        for w_c, _ in active_workers:
            if hasattr(w_c, 'add_workload'):
                w_c.add_workload(1)

        LOGGER.info(f"Starting to yield file with {len(active_workers)} bot worker(s). Total parts: {part_count}, chunk_size: {chunk_size}")

        # Prepare sessions and locations for each worker
        worker_sessions = []
        for w_c, w_fid in active_workers:
            sess = await self.generate_media_session(w_c, w_fid)
            loc = await self.get_location(w_fid)
            if sess and loc:
                worker_sessions.append((w_c, sess, loc))

        if not worker_sessions:
            LOGGER.error("No valid media sessions for streaming")
            for w_c, _ in active_workers:
                if hasattr(w_c, 'add_workload'):
                    w_c.add_workload(-1)
            return

        num_workers = len(worker_sessions)
        PREFETCH_COUNT = max(2, min(num_workers, 4))

        async def fetch_chunk(part_idx: int, part_offset: int) -> bytes:
            # 1. Check L1 RAM Chunk Cache for 0ms instant seeking/rewind
            fid_id = getattr(file_id, 'media_id', 0)
            cached = GLOBAL_CHUNK_CACHE.get(fid_id, 0, part_offset, chunk_size)
            if cached is not None:
                return cached

            # 2. Check L2 SSD Disk Cache
            disk_cached = DISK_CACHE_MANAGER.get(fid_id, 0, part_offset, chunk_size)
            if disk_cached is not None:
                GLOBAL_CHUNK_CACHE.put(fid_id, 0, part_offset, chunk_size, disk_cached)
                return disk_cached

            # 3. Fetch from Telegram MTProto
            for attempt in range(min(3, num_workers)):
                w_c, sess, loc = worker_sessions[(part_idx - 1 + attempt) % num_workers]
                try:
                    r = await sess.send(
                        raw.functions.upload.GetFile(
                            location=loc, offset=part_offset, limit=chunk_size
                        ),
                        timeout=15,
                    )
                    if isinstance(r, raw.types.upload.File):
                        chunk_data = r.bytes
                        if chunk_data:
                            GLOBAL_CHUNK_CACHE.put(fid_id, 0, part_offset, chunk_size, chunk_data)
                            is_header = (part_offset == 0 or part_idx == 1 or part_idx == part_count)
                            asyncio.create_task(
                                DISK_CACHE_MANAGER.put_async(
                                    fid_id, 0, part_offset, chunk_size, chunk_data, is_header=is_header
                                )
                            )
                        return chunk_data
                except (TimeoutError, OSError, asyncio.TimeoutError) as e:
                    if attempt == min(3, num_workers) - 1:
                        LOGGER.warning(f"Timeout fetching part {part_idx} from {getattr(w_c, 'name', str(w_c))}: {e}")
                    await asyncio.sleep(0.1)
                except Exception as e:
                    if attempt == min(3, num_workers) - 1:
                        LOGGER.error(f"Error fetching part {part_idx} from {getattr(w_c, 'name', str(w_c))}: {e}")
                    await asyncio.sleep(0.1)
            return b""

        tasks: Dict[int, asyncio.Task] = {}
        next_to_schedule = 1
        current_part = 1

        try:
            # Schedule chunk 1 first for lowest initial TTFB
            p_offset = offset
            tasks[1] = asyncio.create_task(fetch_chunk(1, p_offset))
            next_to_schedule = 2

            # Pre-fill rest of the sliding window
            while next_to_schedule <= min(part_count, PREFETCH_COUNT):
                p_offset = offset + (next_to_schedule - 1) * chunk_size
                tasks[next_to_schedule] = asyncio.create_task(fetch_chunk(next_to_schedule, p_offset))
                next_to_schedule += 1

            for current_part in range(1, part_count + 1):
                # Schedule the next chunk ahead in background to keep window full
                if next_to_schedule <= part_count:
                    p_offset = offset + (next_to_schedule - 1) * chunk_size
                    tasks[next_to_schedule] = asyncio.create_task(fetch_chunk(next_to_schedule, p_offset))
                    next_to_schedule += 1

                task = tasks.pop(current_part, None)
                if not task:
                    break

                chunk = await task
                if not chunk:
                    break

                if part_count == 1:
                    yield chunk[first_part_cut:last_part_cut]
                elif current_part == 1:
                    yield chunk[first_part_cut:]
                elif current_part == part_count:
                    yield chunk[:last_part_cut]
                else:
                    yield chunk

        except (asyncio.CancelledError, GeneratorExit):
            LOGGER.debug("Client cancelled streaming/download.")
        except Exception as e:
            LOGGER.error(f"Error during yield_file: {e}")
        finally:
            LOGGER.debug(f"Finished yielding file at part {current_part}/{part_count}.")
            # Cancel all unconsumed prefetch tasks
            for t in tasks.values():
                if not t.done():
                    t.cancel()
            # Remove workload for all workers
            for w_c, _ in active_workers:
                if hasattr(w_c, 'add_workload'):
                    w_c.add_workload(-1)

    async def yield_multipart_file(
        self,
        overlapping_parts: list,
        from_bytes: int,
        until_bytes: int,
        chunk_size: int = 1024 * 1024,
    ):
        """
        Stream a virtual multi-part file across multiple Telegram messages seamlessly.
        Each item in overlapping_parts:
        {
            "part": part_dict,
            "file_id": FileId,
            "workers": [(client, fid), ...]
        }
        """
        LOGGER.info(f"yield_multipart_file: range {from_bytes}-{until_bytes} across {len(overlapping_parts)} overlapping part(s)")
        for item in overlapping_parts:
            part = item["part"]
            p_start = part["start_byte"]
            p_end = part["end_byte"]
            if p_end < from_bytes or p_start > until_bytes:
                continue

            # Calculate byte range relative to this part
            p_from = max(from_bytes, p_start) - p_start
            p_until = min(until_bytes, p_end) - p_start

            p_offset = p_from - (p_from % chunk_size)
            p_first_part_cut = p_from - p_offset
            p_last_part_cut = (p_until % chunk_size) + 1
            p_part_count = math.ceil((p_until + 1) / chunk_size) - math.floor(p_offset / chunk_size)

            workers = item.get("workers") or []
            primary_client = workers[0][0] if workers else self.client
            file_id = item["file_id"]

            LOGGER.info(
                f"Streaming multi-part slice: Part {part.get('part_index', '?')}, "
                f"local range {p_from}-{p_until}, offset {p_offset}, "
                f"parts={p_part_count}, workers={len(workers)}"
            )

            async for chunk in self.yield_file(
                file_id=file_id,
                client=primary_client,
                offset=p_offset,
                first_part_cut=p_first_part_cut,
                last_part_cut=p_last_part_cut,
                part_count=p_part_count,
                chunk_size=chunk_size,
                workers=workers
            ):
                yield chunk

    async def generate_media_session(self, client: Client, file_id: FileId) -> Session:
        media_session = client.media_sessions.get(file_id.dc_id, None)
        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await Auth(client, file_id.dc_id,
                               await client.storage.test_mode()).create(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
                for _ in range(6):
                    exported_auth = await client.invoke(
                        raw.functions.auth.ExportAuthorization(
                            dc_id=file_id.dc_id)
                    )
                    try:
                        await media_session.send(
                            raw.functions.auth.ImportAuthorization(
                                id=exported_auth.id, bytes=exported_auth.bytes)
                        )
                        break
                    except AuthBytesInvalid:
                        LOGGER.debug(
                            f"Invalid authorization bytes for DC {file_id.dc_id}, retrying...")
                    except OSError:
                        LOGGER.debug(f"Connection error, retrying...")
                        await asyncio.sleep(2)
                else:
                    await media_session.stop()
                    LOGGER.debug(
                        f"Failed to establish media session for DC {file_id.dc_id} after multiple retries")
                    return None
            else:
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await client.storage.auth_key(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()
            LOGGER.debug(f"Created media session for DC {file_id.dc_id}")
            client.media_sessions[file_id.dc_id] = media_session
        else:
            LOGGER.debug(f"Using cached media session for DC {file_id.dc_id}")
        return media_session

    @staticmethod
    async def get_location(file_id: FileId) -> raw.types.InputPhotoFileLocation | raw.types.InputDocumentFileLocation | raw.types.InputPeerPhotoFileLocation:
        file_type = file_id.file_type
        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id, access_hash=file_id.chat_access_hash)
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(
                        chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(
                            file_id.chat_id), access_hash=file_id.chat_access_hash)
            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG)
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size)
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size)
        return location

    async def clean_cache(self) -> None:
        while True:
            await asyncio.sleep(self.clean_timer)
            self.__cached_file_ids.clear()
            LOGGER.debug("Cleaned the cache")