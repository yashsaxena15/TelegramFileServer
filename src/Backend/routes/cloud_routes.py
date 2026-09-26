# src/Backend/routes/cloud_routes.py

import os
import json
import base64
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ..security.credentials import require_auth, User
from ..modules.google_drive_manager import GoogleDriveManager
from ..modules.remote_transfer_manager import remote_transfer_manager
from src.Database import database
from src.Config import WEB_APP

logger = logging.getLogger("cloud_routes")

router = APIRouter(prefix="/cloud", tags=["Cloud Storage"])

class AuthUrlRequest(BaseModel):
    redirect_uri: Optional[str] = None
    custom_client_id: Optional[str] = None
    custom_client_secret: Optional[str] = None

class DeleteFileRequest(BaseModel):
    file_id: str
    permanent: Optional[bool] = False

class RenameFileRequest(BaseModel):
    file_id: str
    new_name: str

class CreateFolderRequest(BaseModel):
    parent_id: Optional[str] = "root"
    folder_name: str

class TransferToTelegramRequest(BaseModel):
    source_file_id: str
    destination_path: Optional[str] = "/Home"
    operation: Optional[str] = "copy"  # "copy" or "cut"

def _get_base_redirect_uri(request: Request, provided_uri: Optional[str] = None) -> str:
    if provided_uri and provided_uri.strip():
        return provided_uri.strip()
    
    # Try WEB_APP config or request base url
    base = WEB_APP.rstrip("/") if WEB_APP else str(request.base_url).rstrip("/")
    # Check headers for reverse proxy proto and host
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    if host:
        base = f"{proto}://{host}"
    return f"{base}/api/cloud/gdrive/callback"

@router.get("/accounts")
async def list_cloud_accounts(user: User = Depends(require_auth)):
    """List all connected cloud accounts for the current user."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    accounts = database.CloudAccounts.get_user_accounts(user_id=user_id)
    return {"accounts": accounts}

@router.post("/gdrive/auth-url")
async def generate_gdrive_auth_url(
    request: Request,
    body: AuthUrlRequest,
    user: User = Depends(require_auth)
):
    """Generate the Google OAuth 2.0 authorization consent URL."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    redirect_uri = _get_base_redirect_uri(request, body.redirect_uri)

    # Encode state containing user_id and custom client credentials if any
    state_payload = {
        "user_id": user_id,
        "custom_client_id": body.custom_client_id or "",
        "custom_client_secret": body.custom_client_secret or "",
        "redirect_uri": redirect_uri,
        "timestamp": int(datetime.now(timezone.utc).timestamp())
    }
    state_token = base64.urlsafe_b64encode(json.dumps(state_payload).encode()).decode()

    try:
        auth_url = GoogleDriveManager.generate_auth_url(
            redirect_uri=redirect_uri,
            state=state_token,
            client_id=body.custom_client_id
        )
        return {"auth_url": auth_url, "redirect_uri": redirect_uri}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[GDRIVE_AUTH] Error generating auth URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate Google Drive authorization URL.")

@router.get("/gdrive/callback")
async def gdrive_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Handle OAuth 2.0 callback redirect from Google."""
    if error:
        logger.warning(f"[GDRIVE_OAUTH] Google returned error: {error}")
        html_error = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Authorization Failed</title></head>
        <body style="font-family:sans-serif; text-align:center; padding:50px;">
          <h2 style="color:#ef4444;">Google Drive Authorization Cancelled</h2>
          <p>Reason: {error}</p>
          <script>
            if (window.opener) {{
              window.opener.postMessage({{ type: 'GDRIVE_AUTH_ERROR', error: '{error}' }}, '*');
              setTimeout(() => window.close(), 2500);
            }} else {{
              setTimeout(() => {{ window.location.href = '/'; }}, 2500);
            }}
          </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html_error, status_code=400)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter.")

    try:
        raw_state = base64.urlsafe_b64decode(state.encode()).decode()
        state_data = json.loads(raw_state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid state parameter: {e}")

    user_id = state_data.get("user_id")
    custom_cid = state_data.get("custom_client_id")
    custom_sec = state_data.get("custom_client_secret")
    redirect_uri = state_data.get("redirect_uri")

    try:
        exchanged = await GoogleDriveManager.exchange_code(
            code=code,
            redirect_uri=redirect_uri,
            client_id=custom_cid,
            client_secret=custom_sec
        )

        tokens = exchanged["tokens"]
        user_info = exchanged["user_info"]
        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            # If Google didn't return a refresh_token, it means the user was already authorized
            # We log a warning
            logger.warning("[GDRIVE_OAUTH] Google did not return a refresh_token (consent might have been cached).")

        email = user_info.get("email", "unknown@gmail.com")
        name = user_info.get("name") or email.split("@")[0]
        account_name = f"Google Drive ({name})"

        credentials = {
            "refresh_token": refresh_token,
            "client_id": custom_cid or "",
            "client_secret": custom_sec or ""
        }

        # If refresh_token is missing, try to preserve previous one from existing record
        if not refresh_token:
            existing = database.CloudAccounts.find_one({
                "user_id": str(user_id),
                "provider": "google_drive",
                "account_email": email
            })
            if existing and existing.get("credentials", {}).get("refresh_token"):
                credentials["refresh_token"] = existing["credentials"]["refresh_token"]

        account_id = database.CloudAccounts.save_account(
            user_id=user_id,
            provider="google_drive",
            account_name=account_name,
            account_email=email,
            credentials=credentials
        )

        success_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <title>Google Drive Connected</title>
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
            .card {{ background: #1e293b; padding: 32px 40px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; border: 1px solid #334155; max-width: 400px; }}
            h2 {{ color: #38bdf8; margin-top: 0; }}
            p {{ color: #94a3b8; font-size: 14px; }}
          </style>
        </head>
        <body>
          <div class="card">
            <h2>Connected Successfully!</h2>
            <p><strong>{email}</strong> has been linked to your Telegram Drive.</p>
            <p>This window will close automatically...</p>
          </div>
          <script>
            if (window.opener) {{
              window.opener.postMessage({{ type: 'GDRIVE_AUTH_SUCCESS', account_id: '{account_id}', email: '{email}' }}, '*');
              setTimeout(() => window.close(), 1200);
            }} else {{
              setTimeout(() => {{ window.location.href = '/?cloud_connected=true'; }}, 1500);
            }}
          </script>
        </body>
        </html>
        """
        return HTMLResponse(content=success_html, status_code=200)

    except Exception as e:
        logger.error(f"[GDRIVE_OAUTH] Callback handling error: {e}", exc_info=True)
        return HTMLResponse(content=f"<h3>Authentication error: {e}</h3>", status_code=500)

@router.delete("/accounts/{account_id}")
async def disconnect_cloud_account(account_id: str, user: User = Depends(require_auth)):
    """Disconnect and unlink a cloud storage account."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    deleted = database.CloudAccounts.delete_account(account_id=account_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cloud account not found or access denied.")
    return {"success": True, "message": "Cloud account disconnected successfully."}

@router.get("/{account_id}/files")
async def list_cloud_files(
    account_id: str,
    folder_id: Optional[str] = Query(default="root"),
    page_size: Optional[int] = Query(default=50, ge=1, le=200),
    page_token: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    sort_by: Optional[str] = Query(default="name"),
    sort_order: Optional[str] = Query(default="asc"),
    user: User = Depends(require_auth)
):
    """List files and folders in a Google Drive directory."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    account = database.CloudAccounts.get_account_raw(account_id=account_id, user_id=user_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cloud account not found.")

    try:
        access_token = await GoogleDriveManager.get_valid_access_token(account)
        res = await GoogleDriveManager.list_folder(
            access_token=access_token,
            folder_id=folder_id or "root",
            page_size=page_size or 50,
            page_token=page_token,
            search_query=query,
            sort_by=sort_by,
            sort_order=sort_order
        )
        return {
            "account_id": account_id,
            "provider": account.get("provider", "google_drive"),
            "account_name": account.get("account_name"),
            "account_email": account.get("account_email"),
            "folder_id": res.get("folder_id"),
            "items": res.get("items", []),
            "nextPageToken": res.get("nextPageToken")
        }
    except Exception as e:
        logger.error(f"[GDRIVE_LIST] Error listing files for {account_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{account_id}/files/delete")
async def delete_cloud_file(
    account_id: str,
    body: DeleteFileRequest,
    user: User = Depends(require_auth)
):
    """Trash or delete a file/folder in Google Drive."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    account = database.CloudAccounts.get_account_raw(account_id=account_id, user_id=user_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cloud account not found.")

    try:
        access_token = await GoogleDriveManager.get_valid_access_token(account)
        success = await GoogleDriveManager.delete_file(
            access_token=access_token,
            file_id=body.file_id,
            permanent=bool(body.permanent)
        )
        return {"success": success, "message": "File deleted in Google Drive."}
    except Exception as e:
        logger.error(f"[GDRIVE_DELETE] Error deleting {body.file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{account_id}/files/rename")
async def rename_cloud_file(
    account_id: str,
    body: RenameFileRequest,
    user: User = Depends(require_auth)
):
    """Rename a file or folder in Google Drive."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    account = database.CloudAccounts.get_account_raw(account_id=account_id, user_id=user_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cloud account not found.")

    try:
        access_token = await GoogleDriveManager.get_valid_access_token(account)
        updated = await GoogleDriveManager.rename_file(
            access_token=access_token,
            file_id=body.file_id,
            new_name=body.new_name
        )
        return {"success": True, "file": updated}
    except Exception as e:
        logger.error(f"[GDRIVE_RENAME] Error renaming {body.file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{account_id}/files/mkdir")
async def create_cloud_folder(
    account_id: str,
    body: CreateFolderRequest,
    user: User = Depends(require_auth)
):
    """Create a new folder in Google Drive."""
    user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
    account = database.CloudAccounts.get_account_raw(account_id=account_id, user_id=user_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cloud account not found.")

    try:
        access_token = await GoogleDriveManager.get_valid_access_token(account)
        created = await GoogleDriveManager.create_folder(
            access_token=access_token,
            parent_id=body.parent_id or "root",
            folder_name=body.folder_name
        )
        return {"success": True, "folder": created}
    except Exception as e:
        logger.error(f"[GDRIVE_MKDIR] Error creating folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{account_id}/transfer-to-telegram")
async def transfer_to_telegram(
    account_id: str,
    body: TransferToTelegramRequest,
    request: Request,
    user: User = Depends(require_auth)
):
    """
    Stream and copy/cut a file directly from Google Drive into Telegram storage.
    Enqueues the transfer into RemoteTransferManager with Zero-Disk footprint.
    """
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

    account = database.CloudAccounts.get_account_raw(account_id=account_id, user_id=user_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cloud account not found.")

    try:
        access_token = await GoogleDriveManager.get_valid_access_token(account)
        file_info = await GoogleDriveManager.get_file_info(access_token, body.source_file_id)
        
        file_name = file_info.get("name", "Google_Drive_File")
        file_size = int(file_info.get("size", 0))

        # Build direct streaming REST download URL
        media_url = GoogleDriveManager.get_download_url(body.source_file_id)

        # Make sure background worker is alive
        remote_transfer_manager.start_worker(request.app)

        # Enqueue task
        tasks = await remote_transfer_manager.enqueue_transfer(
            user_id=user_id,
            url=media_url,
            destination_path=body.destination_path or "/Home",
            chat_id=chat_id,
            custom_headers={"Authorization": f"Bearer {access_token}"},
            custom_filename=file_name,
            custom_filesize=file_size,
            post_action_delete=(body.operation == "cut"),
            cloud_account_id=account_id,
            cloud_file_id=body.source_file_id
        )

        return {
            "success": True,
            "message": f"Transfer queued for '{file_name}' to {body.destination_path}.",
            "tasks": tasks
        }
    except Exception as e:
        logger.error(f"[GDRIVE_TRANSFER] Error enqueueing transfer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
