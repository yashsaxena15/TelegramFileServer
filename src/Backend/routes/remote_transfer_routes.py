# src/Backend/routes/remote_transfer_routes.py

from fastapi import APIRouter, Request, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..security.credentials import require_auth, User
from ..modules.remote_transfer_manager import remote_transfer_manager
from src.Database import database

router = APIRouter(prefix="/transfers/remote", tags=["Remote Transfers"])

class EnqueueRemoteTransferModel(BaseModel):
    url: str
    destination_path: Optional[str] = "/Home"

class CancelRemoteTransferModel(BaseModel):
    task_id: str

@router.post("/add")
async def add_remote_transfer(
    request: Request,
    body: EnqueueRemoteTransferModel,
    user: User = Depends(require_auth)
):
    """Enqueue a Google Drive (file/folder) or direct URL server-to-server download."""
    if not user.telegram_user_id:
        raise HTTPException(
            status_code=400,
            detail="TELEGRAM_NOT_VERIFIED: Please connect your Telegram account before initiating cloud transfers."
        )

    user_data = database.Users.find_one({"telegram_user_id": user.telegram_user_id})
    if not user_data or "index_chat_id" not in user_data:
        raise HTTPException(status_code=400, detail="User index chat not configured.")

    chat_id = user_data["index_chat_id"]
    user_id = str(user.telegram_user_id)

    # Ensure background processor is running
    remote_transfer_manager.start_worker(request.app)

    try:
        tasks = await remote_transfer_manager.enqueue_transfer(
            user_id=user_id,
            url=body.url,
            destination_path=body.destination_path or "/Home",
            chat_id=chat_id
        )
        return {
            "success": True,
            "message": f"Enqueued {len(tasks)} item(s) for server transfer.",
            "count": len(tasks),
            "tasks": tasks
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue transfer: {str(e)}")

@router.get("/tasks")
async def get_remote_tasks(
    request: Request,
    user: User = Depends(require_auth)
):
    """Retrieve all active, queued, and recently completed remote transfers for the current user."""
    # Ensure worker running
    remote_transfer_manager.start_worker(request.app)
    user_id = str(user.telegram_user_id or user.username)
    tasks = remote_transfer_manager.get_user_tasks(user_id)
    return {"tasks": tasks}

@router.post("/cancel")
async def cancel_remote_task(
    body: CancelRemoteTransferModel,
    user: User = Depends(require_auth)
):
    """Cancel an ongoing or queued background server transfer."""
    user_id = str(user.telegram_user_id or user.username)
    success = remote_transfer_manager.cancel_task(body.task_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or already terminated.")
    return {"success": True, "message": "Transfer cancelled."}

@router.post("/clear-completed")
async def clear_completed_remote_tasks(
    user: User = Depends(require_auth)
):
    """Clear completed and cancelled tasks from history."""
    user_id = str(user.telegram_user_id or user.username)
    deleted_count = remote_transfer_manager.clear_completed(user_id)
    return {"success": True, "cleared_count": deleted_count}
