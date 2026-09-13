# src/Backend/routes/archive_routes.py

from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..security.credentials import require_auth, User
from src.Database import database
from d4rk.Logs import setup_logger
from ..modules.byte_streamer import ByteStreamer
from ..modules.cloud_archive import inspect_archive, extract_archive_in_cloud, compress_items_to_zip

logger = setup_logger("archive_routes")

router = APIRouter(prefix="/archive", tags=["Archive"])


class CompressRequest(BaseModel):
    item_ids: List[str]
    destination_path: str
    zip_name: str


class ExtractRequest(BaseModel):
    file_id: str
    target_path: str


@router.get("/inspect/{file_id}")
async def inspect_archive_endpoint(
    file_id: str,
    request: Request,
    user: User = Depends(require_auth)
):
    """Inspects the files and folders inside an archive without extracting it."""
    try:
        doc = database.Files.find_one({"_id": ObjectId(file_id)})
    except Exception:
        doc = None

    if not doc:
        raise HTTPException(status_code=404, detail="Archive file not found")

    bot_manager = getattr(request.app.state, 'bot_manager', None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot manager not available")

    client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
    if not client:
        raise HTTPException(status_code=503, detail="No available bot clients")

    active_clients = bot_manager.client_list if (hasattr(bot_manager, 'client_list') and bot_manager.client_list) else [client]
    byte_streamer = ByteStreamer(client)

    result = await inspect_archive(
        chat_id=int(doc["chat_id"]),
        message_id=int(doc["message_id"]),
        file_size=int(doc.get("file_size") or 0),
        byte_streamer=byte_streamer,
        active_clients=active_clients
    )

    if not result.get("is_valid", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Invalid or corrupted archive"))

    return result


@router.post("/compress")
async def compress_archive_endpoint(
    body: CompressRequest,
    request: Request,
    user: User = Depends(require_auth)
):
    """Compresses selected files/folders into a new ZIP archive directly in Telegram cloud."""
    if not body.item_ids:
        raise HTTPException(status_code=400, detail="No items selected for compression")

    bot_manager = getattr(request.app.state, 'bot_manager', None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot manager not available")

    client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
    if not client:
        raise HTTPException(status_code=503, detail="No available bot clients")

    byte_streamer = ByteStreamer(client)

    try:
        result = await compress_items_to_zip(
            item_ids=body.item_ids,
            destination_path=body.destination_path,
            zip_name=body.zip_name,
            byte_streamer=byte_streamer,
            bot_manager=bot_manager,
            user_id=str(user.telegram_user_id)
        )
        return result
    except Exception as e:
        logger.error(f"Compression failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract")
async def extract_archive_endpoint(
    body: ExtractRequest,
    request: Request,
    user: User = Depends(require_auth)
):
    """Extracts a ZIP archive in the cloud, storing each file directly into Telegram under target_path."""
    try:
        doc = database.Files.find_one({"_id": ObjectId(body.file_id)})
    except Exception:
        doc = None

    if not doc:
        raise HTTPException(status_code=404, detail="Archive file not found")

    bot_manager = getattr(request.app.state, 'bot_manager', None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot manager not available")

    client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
    if not client:
        raise HTTPException(status_code=503, detail="No available bot clients")

    byte_streamer = ByteStreamer(client)

    try:
        result = await extract_archive_in_cloud(
            file_doc=doc,
            target_path=body.target_path,
            byte_streamer=byte_streamer,
            bot_manager=bot_manager,
            user_id=str(user.telegram_user_id)
        )
        return result
    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
