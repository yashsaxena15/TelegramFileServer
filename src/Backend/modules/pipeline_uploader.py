import os
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


async def upload_part_task(
    part_file_path: str,
    part_index: int,
    file_name: str,
    start_byte: int,
    part_size: int,
    chat_id: int,
    bot_manager: Any,
    fallback_client: Any,
    caption: Optional[str] = None,
    semaphore: Optional[asyncio.Semaphore] = None,
    is_single_part: bool = False,
    file_type: str = "document",
    progress: Optional[Any] = None,
    progress_args: Optional[tuple] = ()
) -> Dict[str, Any]:
    """
    Asynchronously uploads a file part to Telegram using the least busy bot,
    extracts metadata, deletes the temporary file from VM disk immediately,
    and releases backpressure semaphore.
    """
    try:
        client = (bot_manager.get_least_busy_client() if bot_manager else None) or fallback_client
        if not client:
            raise RuntimeError("No Telegram client available for upload")

        client_name = getattr(client, "name", "unknown_bot")
        logger.info(
            f"[PIPELINE_UPLOAD] Starting upload of part {part_index} ({part_size} bytes) "
            f"for '{file_name}' via bot '{client_name}'..."
        )

        if caption is None:
            caption = file_name if is_single_part else f"{file_name} (Part {part_index})"

        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        msg = None
        target_file_name = file_name if is_single_part else f"{file_name}.part{part_index}"

        upload_kwargs = {}
        if progress:
            upload_kwargs["progress"] = progress
            if progress_args:
                upload_kwargs["progress_args"] = progress_args

        if is_single_part:
            try:
                if ext in ["jpg", "jpeg", "png", "gif", "webp"] and part_size <= 10 * 1024 * 1024:
                    msg = await client.send_photo(chat_id=chat_id, photo=part_file_path, caption=caption, **upload_kwargs)
                elif ext in ["mp4", "mkv", "avi", "mov", "webm"]:
                    msg = await client.send_video(chat_id=chat_id, video=part_file_path, caption=caption, file_name=target_file_name, **upload_kwargs)
                elif ext in ["mp3", "wav", "ogg", "flac", "m4a"]:
                    msg = await client.send_audio(chat_id=chat_id, audio=part_file_path, caption=caption, file_name=target_file_name, **upload_kwargs)
                else:
                    msg = await client.send_document(chat_id=chat_id, document=part_file_path, caption=caption, file_name=target_file_name, force_document=True, **upload_kwargs)
            except Exception as e:
                logger.warning(f"[PIPELINE_UPLOAD] Specialized upload fallback to document: {e}")
                msg = await client.send_document(chat_id=chat_id, document=part_file_path, caption=caption, file_name=target_file_name, force_document=True, **upload_kwargs)
        else:
            # Multi-part chunk parts MUST always be sent as raw documents so Telegram does not re-encode them
            msg = await client.send_document(
                chat_id=chat_id,
                document=part_file_path,
                caption=caption,
                file_name=target_file_name,
                force_document=True,
                **upload_kwargs
            )

        media = msg.document or msg.video or msg.audio or msg.photo or msg.voice
        file_unique_id = getattr(media, "file_unique_id", f"part_{part_index}")
        thumbnail = media.thumbs[0].file_id if (hasattr(media, "thumbs") and media.thumbs) else None

        logger.info(
            f"[PIPELINE_UPLOAD] Part {part_index} for '{file_name}' uploaded successfully (msg_id: {msg.id})."
        )

        return {
            "part_index": part_index,
            "chat_id": chat_id,
            "message_id": msg.id,
            "file_unique_id": file_unique_id,
            "part_size": part_size,
            "start_byte": start_byte,
            "end_byte": start_byte + part_size - 1,
            "thumbnail": thumbnail,
        }
    finally:
        # Immediate cleanup of temporary part file from VM disk
        if os.path.exists(part_file_path):
            try:
                os.remove(part_file_path)
                logger.debug(f"[PIPELINE_UPLOAD] Cleaned up temporary part file: {part_file_path}")
            except Exception as e:
                logger.warning(f"[PIPELINE_UPLOAD] Failed to remove {part_file_path}: {e}")

        # Release semaphore slot for next part buffer on disk
        if semaphore:
            semaphore.release()
