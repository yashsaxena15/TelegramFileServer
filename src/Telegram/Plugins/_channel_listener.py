# src/Telegram/Plugins/_channel_listener.py

import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from d4rk.Logs import setup_logger

from src.Database import database
from src.Config import OWNER, LOGS, MOVIE, GROUP, FILTER_CHAT

logger = setup_logger(__name__)

# Concurrency lock to prevent race conditions across parallel bot tasks
_listener_lock = asyncio.Lock()
_startup_sync_done = False


def extract_media_info(message: Message):
    """
    Extract file details, thumbnail, and sanitized clean filename from a Telegram Message.
    If Telegram did not provide a filename (common for forwarded videos), it intelligently
    uses the first line of the caption.
    """
    media = message.document or message.video or message.photo or message.voice or message.audio
    if not media:
        return None

    caption = (message.caption or "").strip()
    first_caption_line = caption.split('\n')[0].strip() if caption else ""
    clean_caption_title = re.sub(r'[\\/*?:"<>|]', "", first_caption_line)[:80].strip()

    file_type = "document"
    thumbnail = None
    file_name = "N/A"

    if message.document:
        file_type = "document"
        doc_name = getattr(media, 'file_name', None)
        if not doc_name or doc_name == "N/A":
            file_name = f"{clean_caption_title}.pdf" if clean_caption_title else f"Doc_{getattr(media, 'file_unique_id', message.id)}"
        else:
            file_name = doc_name
        thumbnail = media.thumbs[0].file_id if (hasattr(media, 'thumbs') and media.thumbs) else None
    elif message.video:
        file_type = "video"
        vid_name = getattr(media, 'file_name', None)
        if not vid_name or vid_name == "N/A":
            if clean_caption_title:
                file_name = clean_caption_title if clean_caption_title.lower().endswith(('.mp4', '.mkv', '.avi', '.webm')) else f"{clean_caption_title}.mp4"
            else:
                file_name = f"Video_{getattr(media, 'file_unique_id', message.id)}.mp4"
        else:
            file_name = vid_name
        thumbnail = media.thumbs[0].file_id if (hasattr(media, 'thumbs') and media.thumbs) else None
    elif message.photo:
        file_type = "photo"
        if clean_caption_title:
            file_name = clean_caption_title if clean_caption_title.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) else f"{clean_caption_title}.jpg"
        else:
            file_name = f"Photo_{getattr(media, 'file_unique_id', message.id)}.jpg"
        thumbnail = media.file_id
    elif message.voice:
        file_type = "voice"
        file_name = f"Voice_{getattr(media, 'file_unique_id', message.id)}.ogg"
        thumbnail = None
    elif message.audio:
        file_type = "audio"
        aud_name = getattr(media, 'file_name', None)
        if not aud_name or aud_name == "N/A":
            if clean_caption_title:
                file_name = clean_caption_title if clean_caption_title.lower().endswith(('.mp3', '.wav', '.flac', '.m4a')) else f"{clean_caption_title}.mp3"
            else:
                file_name = f"Audio_{getattr(media, 'file_unique_id', message.id)}.mp3"
        else:
            file_name = aud_name
        thumbnail = media.thumbs[0].file_id if (hasattr(media, 'thumbs') and media.thumbs) else None

    # Determine file type based on extension if it was tagged as document
    if file_type == "document" and '.' in file_name:
        ext = file_name.split('.')[-1].lower()
        video_exts = ['mp4', 'mkv', 'avi', 'mov', 'webm']
        image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        audio_exts = ['mp3', 'wav', 'ogg', 'flac', 'm4a']
        if ext in video_exts:
            file_type = "video"
        elif ext in image_exts:
            file_type = "photo"
        elif ext in audio_exts:
            file_type = "audio"

    file_unique_id = getattr(media, 'file_unique_id', f"tg_{message.id}")
    file_size = getattr(media, 'file_size', 0)

    return {
        "file_name": file_name,
        "file_type": file_type,
        "file_size": file_size,
        "file_unique_id": file_unique_id,
        "thumbnail": thumbnail,
        "file_caption": caption or "N/A"
    }


@Client.on_message(
    (filters.document | filters.video | filters.photo | filters.voice | filters.audio) &
    ~filters.service
)
async def auto_channel_file_listener(client: Client, message: Message):
    """
    Automatically capture any file manually uploaded or forwarded directly into the Telegram channel
    and store it in the user's 'Telegram Inbox' so it appears in the Web Drive sidebar in real time.
    """
    try:
        chat_id = message.chat.id
        msg_id = message.id

        # 1. Skip if message is outgoing or sent by the bot itself
        if getattr(message, 'outgoing', False):
            return
        if client.me and message.from_user and message.from_user.id == client.me.id:
            return
        
        # Skip web app uploads
        caption = (message.caption or "").strip()
        if caption.startswith("Uploaded file:") or caption.startswith("Uploaded multi-part file:"):
            return

        async with _listener_lock:
            # 2. Check if file already exists in database for this chat and message_id
            existing = database.Files.find_one({"chat_id": chat_id, "message_id": msg_id})
            if existing:
                return

            # 3. Find the owner for this channel/group/chat
            user_data = database.Users.find_one({
                "$or": [
                    {"index_chat_id": chat_id},
                    {"index_chat_id": str(chat_id)},
                    {"index_chat_id": int(chat_id)}
                ]
            })
            
            # Also check if it's sent in private chat to the bot by a registered user
            if not user_data and getattr(message.chat, 'type', None) and str(message.chat.type).lower().endswith("private") and message.from_user:
                user_data = database.Users.find_one({
                    "$or": [
                        {"telegram_user_id": message.from_user.id},
                        {"telegram_user_id": str(message.from_user.id)},
                        {"telegram_user_id": int(message.from_user.id)}
                    ]
                })

            if not user_data:
                configured_chats = [c for c in [LOGS, MOVIE, GROUP, FILTER_CHAT] if c is not None]
                if chat_id in configured_chats:
                    user_data = database.Users.find_one({"telegram_user_id": OWNER}) or database.Users.find_one({"username": "admin"})
            
            if not user_data:
                return

            owner_id = str(user_data.get("telegram_user_id") or user_data.get("username") or OWNER)

            # 4. Extract media details
            media_info = extract_media_info(message)
            if not media_info:
                return

            # Check if already exists by unique id and owner
            if database.Files.check_if_exists(chat_id, msg_id, media_info["file_unique_id"]):
                return

            # 5. Save file with file_path="/Telegram Inbox"
            logger.info(f"[CHANNEL_LISTENER] Auto-captured direct file: '{media_info['file_name']}' ({media_info['file_size']} bytes) in chat {chat_id} for owner {owner_id}")
            database.Files.add_file(
                chat_id=chat_id,
                message_id=msg_id,
                thumbnail=media_info["thumbnail"],
                file_type=media_info["file_type"],
                file_unique_id=media_info["file_unique_id"],
                file_size=media_info["file_size"],
                file_name=media_info["file_name"],
                file_caption=media_info["file_caption"],
                file_path="/Telegram Inbox",
                owner_id=owner_id
            )
    except Exception as e:
        logger.error(f"[CHANNEL_LISTENER] Error in auto_channel_file_listener: {e}", exc_info=True)


async def catchup_channel_inbox(client: Client, chat_id: int, owner_id: str, max_lookahead: int = 500):
    """
    Catch up any messages that were posted to the channel while the bot/server was offline.
    Scans in batches of 50 starting from the highest known message_id in the database.
    """
    try:
        chat_id_int = int(chat_id)
        latest = database.Files.find_one(
            {"chat_id": {"$in": [chat_id_int, str(chat_id_int)]}},
            sort=[("message_id", -1)]
        )
        start_id = (latest.get("message_id") if latest else 0) + 1
        if start_id <= 1:
            start_id = 1

        batch_size = 50
        current_id = start_id
        synced_count = 0

        while current_id < start_id + max_lookahead:
            batch_ids = list(range(current_id, current_id + batch_size))
            try:
                msgs = await client.get_messages(chat_id_int, batch_ids)
            except Exception as e:
                logger.warning(f"[CHANNEL_SYNC] Failed to get messages {current_id}..{current_id+batch_size}: {e}")
                break

            valid_msgs = [m for m in msgs if m and not getattr(m, 'empty', False)]
            if not valid_msgs:
                # Reached end of channel
                break

            for m in valid_msgs:
                media_info = extract_media_info(m)
                if not media_info:
                    continue

                caption = (m.caption or "").strip()
                if caption.startswith("Uploaded file:") or caption.startswith("Uploaded multi-part file:"):
                    continue

                if database.Files.check_if_exists(chat_id_int, m.id, media_info["file_unique_id"]):
                    continue

                database.Files.add_file(
                    chat_id=chat_id_int,
                    message_id=m.id,
                    thumbnail=media_info["thumbnail"],
                    file_type=media_info["file_type"],
                    file_unique_id=media_info["file_unique_id"],
                    file_size=media_info["file_size"],
                    file_name=media_info["file_name"],
                    file_caption=media_info["file_caption"],
                    file_path="/Telegram Inbox",
                    owner_id=str(owner_id)
                )
                synced_count += 1
                logger.info(f"[CHANNEL_SYNC] Auto-synced missed file {m.id}: {media_info['file_name']}")

            if max(m.id for m in valid_msgs) < batch_ids[-1]:
                # Reached the tip of the channel
                break

            current_id += batch_size

        if synced_count > 0:
            logger.info(f"[CHANNEL_SYNC] Completed catchup for chat {chat_id}. Synced {synced_count} missed files.")
        return synced_count
    except Exception as e:
        logger.error(f"[CHANNEL_SYNC] Error in catchup_channel_inbox: {e}", exc_info=True)
        return 0


async def on_startup_inbox_sync(bot_manager):
    """
    Called automatically on server startup to scan all channels for files sent during downtime.
    """
    global _startup_sync_done
    if _startup_sync_done:
        return
    _startup_sync_done = True

    try:
        # Wait until at least one bot client is active and connected
        client = None
        for _ in range(25):
            await asyncio.sleep(2)
            client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
            if not client and getattr(bot_manager, 'client_list', None):
                client = bot_manager.client_list[0]
            if client and getattr(client, 'is_connected', False):
                break

        if not client or not getattr(client, 'is_connected', False):
            logger.warning("[STARTUP_SYNC] No active connected bot client available after waiting")
            return

        logger.info("[STARTUP_SYNC] Bot client ready. Checking all channels for files uploaded during downtime...")

        users = list(database.Users.find({"index_chat_id": {"$exists": True}}))
        for u in users:
            chat_id = u.get("index_chat_id")
            owner_id = str(u.get("telegram_user_id") or u.get("username") or OWNER)
            if chat_id:
                await catchup_channel_inbox(client, chat_id, owner_id)
        logger.info("[STARTUP_SYNC] Startup sync check completed.")
    except Exception as e:
        logger.error(f"[STARTUP_SYNC] Error in on_startup_inbox_sync: {e}", exc_info=True)
