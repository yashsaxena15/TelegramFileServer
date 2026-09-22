# src/Backend/routes/archive_routes.py

from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..security.credentials import require_auth, User
from src.Database import database
from d4rk.Logs import setup_logger
from ..modules.byte_streamer import ByteStreamer
from ..modules.cloud_archive import inspect_archive
from ..modules.archive_task_manager import archive_task_manager, check_disk_safety

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
    """Inspects the files and folders inside an archive without extracting it (supports .zip, .rar, .7z, .tar)."""
    try:
        doc = database.Files.find_one({"_id": ObjectId(file_id)})
    except Exception:
        doc = None

    if not doc:
        doc = database.Files.find_one({"$or": [{"file_unique_id": file_id}, {"file_name": file_id}]})

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
        active_clients=active_clients,
        parts_list=doc.get("parts") if doc.get("is_split") else None
    )

    if not result.get("is_valid", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Invalid or corrupted archive"))

    return result


@router.post("/extract")
async def extract_archive_endpoint(
    body: ExtractRequest,
    request: Request,
    user: User = Depends(require_auth)
):
    """
    Initiates asynchronous cloud extraction.
    Runs preflight 25 GB safety check first, then enqueues background task.
    """
    try:
        doc = database.Files.find_one({"_id": ObjectId(body.file_id)})
    except Exception:
        doc = None

    if not doc:
        doc = database.Files.find_one({"$or": [{"file_unique_id": body.file_id}, {"file_name": body.file_id}]})

    if not doc:
        raise HTTPException(status_code=404, detail="Archive file not found")

    archive_size = int(doc.get("file_size") or 0)
    # Estimated peak disk space: archive size on disk + 2 GB buffer for single currently uploading file
    estimated_peak = archive_size + (2 * 1024 * 1024 * 1024)

    # 1. PREFLIGHT DISK SAFETY GUARD (Strict 25 GB reserve)
    is_safe, err_msg, disk_info = check_disk_safety(estimated_peak)
    if not is_safe:
        raise HTTPException(status_code=400, detail=err_msg)

    bot_manager = getattr(request.app.state, 'bot_manager', None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot manager not available")

    uid = str(user.telegram_user_id) if user.telegram_user_id else user.username
    archive_name = doc.get("file_name", "archive.zip")

    task_id = archive_task_manager.create_task(
        task_type="extract",
        user_id=uid,
        target_name=archive_name,
        payload={
            "file_doc": doc,
            "target_path": body.target_path,
            "user_id": uid,
            "bot_manager": bot_manager
        }
    )

    return {
        "success": True,
        "task_id": task_id,
        "status": "queued",
        "archive_name": archive_name,
        "message": f"Extraction of '{archive_name}' queued in background."
    }


@router.post("/compress")
async def compress_archive_endpoint(
    body: CompressRequest,
    request: Request,
    user: User = Depends(require_auth)
):
    """
    Initiates asynchronous cloud compression into a ZIP archive.
    Runs preflight 25 GB safety check first, then enqueues background task.
    """
    if not body.item_ids:
        raise HTTPException(status_code=400, detail="No items selected for compression")

    # Fast sub-millisecond calculation of total source size
    total_size = 0
    for item_id in body.item_ids:
        doc = None
        try:
            doc = database.Files.find_one({"_id": ObjectId(item_id)})
        except Exception:
            pass
        if not doc:
            doc = database.Files.find_one({"$or": [{"file_unique_id": item_id}, {"file_name": item_id}]})
        if not doc:
            continue

        if doc.get("file_type") == "folder":
            f_name = doc.get("file_name")
            f_path = doc.get("file_path", "/")
            regex_pat = f"^{f_path.rstrip('/')}/{f_name}(/.*)?$"
            cursor = database.Files.find({
                "file_path": {"$regex": regex_pat},
                "file_type": {"$ne": "folder"},
                "trashed": {"$ne": True}
            }, {"file_size": 1})
            for c in cursor:
                total_size += int(c.get("file_size") or 0)
        else:
            total_size += int(doc.get("file_size") or 0)

    # Estimated peak disk space: created archive size + 2 GB buffer
    estimated_peak = total_size + (2 * 1024 * 1024 * 1024)

    # 1. PREFLIGHT DISK SAFETY GUARD (Strict 25 GB reserve)
    is_safe, err_msg, disk_info = check_disk_safety(estimated_peak)
    if not is_safe:
        raise HTTPException(status_code=400, detail=err_msg)

    bot_manager = getattr(request.app.state, 'bot_manager', None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot manager not available")

    uid = str(user.telegram_user_id) if user.telegram_user_id else user.username

    task_id = archive_task_manager.create_task(
        task_type="compress",
        user_id=uid,
        target_name=body.zip_name,
        payload={
            "item_ids": body.item_ids,
            "destination_path": body.destination_path,
            "zip_name": body.zip_name,
            "user_id": uid,
            "bot_manager": bot_manager
        }
    )

    return {
        "success": True,
        "task_id": task_id,
        "status": "queued",
        "archive_name": body.zip_name,
        "message": f"Compression into '{body.zip_name}' queued in background."
    }


@router.get("/tasks")
async def list_archive_tasks_endpoint(
    request: Request,
    user: User = Depends(require_auth)
):
    """Lists recent and active archive tasks for the current user."""
    uid = str(user.telegram_user_id) if user.telegram_user_id else user.username
    tasks = archive_task_manager.list_tasks(user_id=uid)
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_archive_task_endpoint(
    task_id: str,
    request: Request,
    user: User = Depends(require_auth)
):
    """Returns status and real-time progress for a specific archive task."""
    uid = str(user.telegram_user_id) if user.telegram_user_id else user.username
    task = archive_task_manager.get_task(task_id, user_id=uid)
    if not task:
        raise HTTPException(status_code=404, detail="Archive task not found")
    return task


@router.post("/tasks/{task_id}/cancel")
async def cancel_archive_task_endpoint(
    task_id: str,
    request: Request,
    user: User = Depends(require_auth)
):
    """Cancels an active or queued archive task."""
    uid = str(user.telegram_user_id) if user.telegram_user_id else user.username
    success = archive_task_manager.cancel_task(task_id, user_id=uid)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task (not found, already finished, or unauthorized)")
    return {"success": True, "message": "Archive task cancelled successfully"}
