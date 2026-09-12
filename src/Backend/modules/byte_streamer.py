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

LOGGER = setup_logger(__name__)


class InvalidHash(Exception):
    message = 'Invalid hash!'


class FIleNotFound(Exception):
    message = 'File not found!'


class ByteStreamer:
    def __init__(self, client: Client):
        self.clean_timer = 30 * 60
        self.client: Client = client
        self.__cached_file_ids: Dict[int, FileId] = {}
        asyncio.create_task(self.clean_cache())

    async def get_file_properties(self, chat_id: int, message_id: int, client: Client = None) -> FileId:
        c = client or self.client
        key = (getattr(c, 'name', 'default'), message_id)
        if key not in self.__cached_file_ids:
            file_id = await get_file_ids(c, int(chat_id), int(message_id))
            if not file_id:
                if client is None:
                    LOGGER.info('Message with ID %s not found!', message_id)
                    raise FIleNotFound
                return None
            self.__cached_file_ids[key] = file_id
        return self.__cached_file_ids[key]

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
        PREFETCH_COUNT = max(4, min(num_workers * 2, 12))

        async def fetch_chunk(part_idx: int, part_offset: int) -> bytes:
            w_c, sess, loc = worker_sessions[(part_idx - 1) % num_workers]
            for attempt in range(3):
                try:
                    r = await sess.send(
                        raw.functions.upload.GetFile(
                            location=loc, offset=part_offset, limit=chunk_size
                        ),
                        timeout=60,
                    )
                    if isinstance(r, raw.types.upload.File):
                        return r.bytes
                    return b""
                except (TimeoutError, OSError) as e:
                    if attempt == 2:
                        LOGGER.warning(f"Timeout fetching part {part_idx} at offset {part_offset}: {e}")
                        return b""
                    await asyncio.sleep(0.3)
                except Exception as e:
                    LOGGER.error(f"Error fetching part {part_idx} at offset {part_offset}: {e}")
                    return b""
            return b""

        tasks: Dict[int, asyncio.Task] = {}
        next_to_schedule = 1
        current_part = 1

        try:
            # Pre-fill the sliding window
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