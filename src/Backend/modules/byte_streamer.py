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

            # Gather workers for this part's message
            workers = []
            for c in active_clients:
                if getattr(c, 'is_connected', False):
                    try:
                        fid = await self.get_file_properties(chat_id=chat_id, message_id=message_id, client=c)
                        if fid:
                            workers.append((c, fid))
                    except Exception as ex:
                        LOGGER.debug(f"Client {getattr(c, 'name', str(c))} could not get fid for part {part_idx_num}: {ex}")

            if not workers:
                try:
                    fid = await self.get_file_properties(chat_id=chat_id, message_id=message_id, client=self.client)
                    if fid:
                        workers = [(self.client, fid)]
                except Exception as ex:
                    LOGGER.error(f"Fallback client failed for part {part_idx_num}: {ex}")

            if not workers:
                LOGGER.error(f"No active workers found for part {part_idx_num} (chat {chat_id}, msg {message_id})")
                return

            LOGGER.info(f"Yielding part {part_idx_num} (bytes {part_from}-{part_until}) with {len(workers)} worker(s)")

            # Prepare media sessions
            worker_sessions = []
            for w_c, w_fid in workers:
                sess = await self.generate_media_session(w_c, w_fid)
                loc = await self.get_location(w_fid)
                if sess and loc:
                    worker_sessions.append((w_c, sess, loc))

            if not worker_sessions:
                LOGGER.error(f"No valid media sessions for part {part_idx_num}")
                return

            for w_c, _ in workers:
                if hasattr(w_c, 'add_workload'):
                    w_c.add_workload(1)

            offset = part_from - (part_from % chunk_size)
            first_part_cut = part_from - offset
            last_part_cut = (part_until % chunk_size) + 1
            part_count = math.ceil((part_until + 1) / chunk_size) - math.floor(offset / chunk_size)

            num_workers = len(worker_sessions)
            PREFETCH_COUNT = max(4, min(num_workers * 2, 12))

            async def fetch_part_chunk(chunk_seq: int, chunk_offset: int) -> bytes:
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
                            return r.bytes
                    except (TimeoutError, OSError, asyncio.TimeoutError) as e:
                        if attempt == min(3, num_workers) - 1:
                            LOGGER.warning(f"Timeout fetching chunk {chunk_seq} from {getattr(w_c, 'name', str(w_c))}: {e}")
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        if attempt == min(3, num_workers) - 1:
                            LOGGER.warning(f"Error fetching chunk {chunk_seq} from {getattr(w_c, 'name', str(w_c))}: {e}")
                        await asyncio.sleep(0.2)
                return b""

            tasks: Dict[int, asyncio.Task] = {}
            next_to_schedule = 1
            current_chunk = 1

            try:
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
        PREFETCH_COUNT = max(4, min(num_workers * 2, 12))

        async def fetch_chunk(part_idx: int, part_offset: int) -> bytes:
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
                        return r.bytes
                except (TimeoutError, OSError, asyncio.TimeoutError) as e:
                    if attempt == min(3, num_workers) - 1:
                        LOGGER.warning(f"Timeout fetching part {part_idx} from {getattr(w_c, 'name', str(w_c))}: {e}")
                    await asyncio.sleep(0.2)
                except Exception as e:
                    if attempt == min(3, num_workers) - 1:
                        LOGGER.error(f"Error fetching part {part_idx} from {getattr(w_c, 'name', str(w_c))}: {e}")
                    await asyncio.sleep(0.2)
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