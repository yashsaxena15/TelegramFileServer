# src/Backend/routes/files_routes.py

from fastapi import APIRouter, Request, Depends, HTTPException, File, UploadFile, Form, Response , Query
from pydantic import BaseModel
from bson import ObjectId
import os
import asyncio
import datetime
import aiofiles
import re
import secrets
import shutil
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import asdict

from ..security.credentials import require_auth, User
from .folders_routes import validate_folder_name
from src.Database import database
from d4rk.Logs import setup_logger
from ..modules.pipeline_uploader import upload_part_task

# For thumbnail route
from pyrogram import Client

logger = setup_logger("files_routes")

# Create router with updated prefix
router = APIRouter(prefix="/files", tags=["Files"])

# Global variable for auth tokens (should be imported from main app)
_auth_tokens = {}

@router.get("")
@router.get("/")
async def get_all_files_route(
    request: Request,
    path: str = Query(default="/", description="Folder path to fetch files from"),
    user: User = Depends(require_auth)
):
    try:
        # Fetch files for the specified path and user
        logger.info(f"Fetching files for path {path} and user {user}")
        # Use the user's Telegram ID as the user identifier
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username

        # Fast non-blocking catchup check if user is accessing Telegram Inbox
        if path in ["inbox", "/inbox", "Telegram Inbox", "/Telegram Inbox", "/Home/Telegram Inbox"]:
            try:
                bot_manager = getattr(request.app.state, 'bot_manager', None)
                if bot_manager:
                    client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
                    if not client and hasattr(bot_manager, 'client_list') and bot_manager.client_list:
                        client = bot_manager.client_list[0]
                    if client:
                        user_doc = database.Users.find_one({
                            "$or": [
                                {"telegram_user_id": user.telegram_user_id},
                                {"username": user.username}
                            ]
                        }) if hasattr(database, 'Users') else None
                        chat_id = user_doc.get("index_chat_id") if user_doc else None
                        if chat_id:
                            from src.Telegram.Plugins._channel_listener import catchup_channel_inbox
                            # Max 1.2s timeout so the UI request remains instantaneous
                            await asyncio.wait_for(
                                catchup_channel_inbox(client, chat_id, user_id, max_lookahead=100),
                                timeout=1.2
                            )
            except asyncio.TimeoutError:
                logger.info("[FILES_ROUTE] Inbox catchup timed out after 1.2s; loading existing files")
            except Exception as sync_err:
                logger.warning(f"[FILES_ROUTE] Inbox catchup error: {sync_err}")

        files_data = database.Files.get_files_by_path(path, user_id)
        files_list = []
        for f in files_data:
            f_dict = asdict(f)
            f_dict['id'] = str(f_dict['id']) # Convert ObjectId to string
            f_dict['file_unique_id'] = f.file_unique_id  # Include file_unique_id for streaming
            
            files_list.append(f_dict)
        return {"files": files_list}
    except Exception as e:
        logger.error(f"Error fetching files for path {path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class MoveFileRequest(BaseModel):
    file_id: str
    target_path: str

class CopyFileRequest(BaseModel):
    file_id: str
    target_path: str

class DeleteFileRequest(BaseModel):
    file_id: str

class RenameFileRequest(BaseModel):
    file_id: str
    new_name: str

class StarRequest(BaseModel):
    file_id: str
    starred: Optional[bool] = None

class TrashRequest(BaseModel):
    file_id: str

@router.post("/move")
async def move_file_route(request: MoveFileRequest, user: User = Depends(require_auth)):
    try:
        # Use the user's Telegram ID as the user identifier
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        # Check if user owns the file
        if not database.Files.check_file_owner(request.file_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
            
        # Get the file by ID
        file_data = database.Files.find_one({"_id": ObjectId(request.file_id)})
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Update the file's path and modified date
        database.Files.update_one(
            {"_id": ObjectId(request.file_id), "owner_id": user_id},
            {"$set": {"file_path": request.target_path, "modified_date": datetime.datetime.utcnow().isoformat()}}
        )
        
        return {"message": "File moved successfully"}
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/copy")
async def copy_file_route(request: CopyFileRequest, user: User = Depends(require_auth)):
    try:
        # Use the user's Telegram ID as the user identifier
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        # Check if user owns the file
        if not database.Files.check_file_owner(request.file_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
            
        # Get the file by ID
        file_data = database.Files.find_one({"_id": ObjectId(request.file_id)})
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Create a copy of the file with the new path
        new_file_data = file_data.copy()
        new_file_data["_id"] = ObjectId()  # Generate new ID
        new_file_data["file_path"] = request.target_path
        new_file_data["modified_date"] = datetime.datetime.utcnow().isoformat()  # Set new modified date for copied file
        # Preserve the owner when copying
        new_file_data["owner_id"] = user_id
        
        # For copied files, we need to handle the unique ID properly
        # For now, we'll keep the same file_unique_id since it refers to the Telegram file
        # In a real implementation, you might want to duplicate the file in Telegram as well
        
        database.Files.insert_one(new_file_data)
        
        return {"message": "File copied successfully", "new_file_id": str(new_file_data["_id"])}
    except Exception as e:
        logger.error(f"Error copying file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rename")
async def rename_file_route(request: RenameFileRequest, user: User = Depends(require_auth)):
    try:
        # Use the user's Telegram ID as the user identifier
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        
        # Check item existence and type for validation
        item_doc = database.Files.find_one({"_id": ObjectId(request.file_id)})
        if not item_doc:
            raise HTTPException(status_code=404, detail="File or folder not found")

        if item_doc.get("file_type") == "folder":
            validated_name = validate_folder_name(request.new_name)
        else:
            if any(c in request.new_name for c in ['/', '\\']):
                raise HTTPException(status_code=400, detail="Filename cannot contain '/' or '\\'")
            validated_name = request.new_name.strip()
            if not validated_name:
                raise HTTPException(status_code=400, detail="Filename cannot be empty")

        # Rename the file/folder with owner validation
        success = database.Files.rename_file(request.file_id, validated_name, user_id)
        
        if success:
            return {"message": "Item renamed successfully"}
        else:
            raise HTTPException(status_code=404, detail="File not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete")
async def delete_file_route(
    http_request: Request,
    request: DeleteFileRequest,
    user: User = Depends(require_auth)
):
    try:
        # Use the user's Telegram ID as the user identifier
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        # Check if user owns the file
        if not database.Files.check_file_owner(request.file_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
            
        # Get the file by ID to check if it exists
        file_data = database.Files.find_one({"_id": ObjectId(request.file_id), "owner_id": user_id})
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Track Telegram messages to delete: {chat_id: set([message_id, ...])}
        messages_to_delete = defaultdict(set)

        def collect_file_messages(doc):
            if not doc:
                return
            c_id = doc.get("chat_id")
            m_id = doc.get("message_id")
            if c_id and m_id:
                messages_to_delete[c_id].add(m_id)
            if doc.get("is_split"):
                for part in doc.get("parts", []):
                    p_mid = part.get("message_id")
                    if p_mid and c_id:
                        messages_to_delete[c_id].add(p_mid)

        # Check if this is a folder
        if file_data.get("file_type") == "folder":
            folder_path = (file_data.get("file_path") or "/Home").strip()
            folder_name = (file_data.get("file_name") or "").strip()
            
            # ABSOLUTE SAFETY GUARD: Never allow deleting root Home or system folders
            if folder_name.lower() in ["home", "root", "trash", "starred"] and folder_path in ["/", "/Home", "Home", ""]:
                raise HTTPException(status_code=400, detail="Root folder cannot be deleted.")
            
            # Construct the exact folder path safely
            if folder_path in ["/", ""]:
                exact_path = f"/Home/{folder_name}"
            elif folder_path.startswith("/Home"):
                exact_path = f"{folder_path.rstrip('/')}/{folder_name}"
            else:
                exact_path = f"/Home/{folder_path.strip('/')}/{folder_name}"
            
            # Additional safety guard: If exact_path resolves to root, reject
            if exact_path in ["/", "/Home", "Home", ""]:
                raise HTTPException(status_code=400, detail="Cannot delete root path.")
            
            paths_to_delete = [exact_path]
            
            for f_path in paths_to_delete:
                # Double-check: ensure f_path is not root
                if f_path in ["/", "/Home", "Home", ""]:
                    continue
                    
                # Find all files inside to collect their Telegram messages before deleting from DB
                sub_files = database.Files.find({
                    "$or": [
                        {"file_path": f_path},
                        {"file_path": {"$regex": f"^{re.escape(f_path)}/"}}
                    ],
                    "owner_id": user_id
                })
                for sf in sub_files:
                    collect_file_messages(sf)

                # Delete all files in the folder (owned by the user)
                database.Files.delete_many({"file_path": f_path, "owner_id": user_id})
                
                # Also delete any subfolders and files inside this folder
                database.Files.delete_many({
                    "file_path": {"$regex": f"^{re.escape(f_path)}/"},
                    "owner_id": user_id
                })
        else:
            collect_file_messages(file_data)
        
        # Delete the file/folder itself from database
        result = database.Files.delete_one({"_id": ObjectId(request.file_id), "owner_id": user_id})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Delete Telegram message(s) from channel if any exist
        if messages_to_delete:
            try:
                bot_manager = getattr(http_request.app.state, 'bot_manager', None)
                client: Optional[Client] = bot_manager.get_least_busy_client() if (bot_manager and hasattr(bot_manager, 'get_least_busy_client')) else None
                if not client and bot_manager and hasattr(bot_manager, 'client_list') and bot_manager.client_list:
                    client = bot_manager.client_list[0]
                
                if client:
                    for c_id, m_ids in messages_to_delete.items():
                        m_list = list(m_ids)
                        # Telegram allows deleting up to 100 messages per call
                        for i in range(0, len(m_list), 100):
                            batch = m_list[i:i+100]
                            try:
                                await client.delete_messages(chat_id=c_id, message_ids=batch)
                                logger.info(f"Successfully deleted Telegram messages {batch} from chat {c_id}")
                            except Exception as tg_batch_err:
                                logger.warning(f"Failed to delete Telegram messages {batch} from chat {c_id}: {tg_batch_err}")
                else:
                    logger.warning("No Telegram client available to delete message(s)")
            except Exception as client_err:
                logger.warning(f"Error accessing bot client for Telegram message deletion: {client_err}")
        
        return {"message": "Item deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/star")
async def star_file_route(request: StarRequest, user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        new_starred = database.Files.toggle_star(request.file_id, user_id, request.starred)
        return {"starred": new_starred, "message": "Updated star status"}
    except Exception as e:
        logger.error(f"Error toggling star: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trash")
async def trash_file_route(request: TrashRequest, user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        success = database.Files.move_to_trash(request.file_id, user_id)
        if success:
            return {"message": "Moved to trash successfully"}
        raise HTTPException(status_code=404, detail="File or folder not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving to trash: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restore")
async def restore_file_route(request: TrashRequest, user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        success = database.Files.restore_from_trash(request.file_id, user_id)
        if success:
            return {"message": "Restored from trash successfully"}
        raise HTTPException(status_code=404, detail="File or folder not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring from trash: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trash/empty")
async def empty_trash_route(http_request: Request, user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        trashed_items = list(database.Files.find({"trashed": True, "owner_id": user_id}))
        
        messages_to_delete = defaultdict(set)
        for doc in trashed_items:
            c_id = doc.get("chat_id")
            m_id = doc.get("message_id")
            if c_id and m_id:
                messages_to_delete[c_id].add(m_id)
            if doc.get("is_split"):
                for part in doc.get("parts", []):
                    p_mid = part.get("message_id")
                    if p_mid and c_id:
                        messages_to_delete[c_id].add(p_mid)
        
        database.Files.delete_many({"trashed": True, "owner_id": user_id})
        
        if messages_to_delete:
            try:
                bot_manager = getattr(http_request.app.state, 'bot_manager', None)
                client: Optional[Client] = bot_manager.get_least_busy_client() if (bot_manager and hasattr(bot_manager, 'get_least_busy_client')) else None
                if not client and bot_manager and hasattr(bot_manager, 'client_list') and bot_manager.client_list:
                    client = bot_manager.client_list[0]
                if client:
                    for c_id, m_ids in messages_to_delete.items():
                        m_list = list(m_ids)
                        for i in range(0, len(m_list), 100):
                            batch = m_list[i:i+100]
                            try:
                                await client.delete_messages(chat_id=c_id, message_ids=batch)
                            except Exception as tg_err:
                                logger.warning(f"Failed deleting Telegram trash batch: {tg_err}")
            except Exception as ex:
                logger.warning(f"Error accessing bot client for trash deletion: {ex}")
                
        return {"message": f"Emptied {len(trashed_items)} items from trash"}
    except Exception as e:
        logger.error(f"Error emptying trash: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics")
async def get_storage_analytics_route(user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        stats = database.Files.get_storage_analytics(user_id)
        return stats
    except Exception as e:
        logger.error(f"Error getting storage analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Add file upload endpoint
@router.post("/upload")
async def upload_file(
    request: Request,  # Make request parameter required to access bot manager
    file: UploadFile = File(...),
    path: str = Form(default="/", description="Destination path for the uploaded file"),
    user: User = Depends(require_auth)
):
    try:
        # DEBUG: Log the received path and file info
        print(f"Received upload request with path: {path}")
        print(f"File name: {file.filename}, File size: {file.size}, Content type: {file.content_type}")
        print(f"User: {user}")

        # Check if user has verified their Telegram account upfront before writing to disk
        if not user.telegram_user_id:
            raise HTTPException(status_code=400, detail="TELEGRAM_NOT_VERIFIED: Please verify your Telegram account before uploading files")
        
        # Get the user's index chat ID
        user_data = database.Users.find_one({"telegram_user_id": user.telegram_user_id})
        if not user_data or "index_chat_id" not in user_data:
            raise HTTPException(status_code=400, detail="User index chat not found")        
        chat_id = user_data["index_chat_id"]
        
        # Access bot_manager from app state upfront
        if not hasattr(request, 'app') or not hasattr(request.app.state, 'bot_manager'):
            raise HTTPException(status_code=503, detail="Bot manager not available")
        
        bot_manager = request.app.state.bot_manager
        if not bot_manager:
            raise HTTPException(status_code=503, detail="Bot manager not available")
        
        # Get a client to use for uploading
        client: Client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
        if not client:
            raise HTTPException(status_code=500, detail="No available bot clients")

        # Create the tg_files directory if it doesn't exist
        tg_files_dir = os.path.join(os.getcwd(), "tg_files")
        os.makedirs(tg_files_dir, exist_ok=True)
        
        # Max Telegram single file limit for bots: 1950 MB
        PART_MAX_SIZE = 1950 * 1024 * 1024
        upload_id = secrets.token_hex(8)
        
        part_index = 1
        current_part_file = os.path.join(tg_files_dir, f"{upload_id}_part_{part_index}.tmp")
        current_part_written = 0
        total_written = 0
        upload_tasks: List[asyncio.Task] = []
        disk_semaphore = asyncio.Semaphore(2)  # Max 2 active parts on VM disk
        await disk_semaphore.acquire()

        file_extension = os.path.splitext(file.filename)[1].lower()
        file_type = "document"
        if file_extension in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.3gp', '.ogv']:
            file_type = "video"
        elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
            file_type = "audio"
        elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            file_type = "photo"
        
        part_f = await aiofiles.open(current_part_file, 'wb')
        try:
            while chunk := await file.read(4 * 1024 * 1024):  # 4MB chunks
                chunk_len = len(chunk)
                
                # If writing this chunk exceeds the part limit
                if current_part_written + chunk_len > PART_MAX_SIZE:
                    split_point = PART_MAX_SIZE - current_part_written
                    if split_point > 0:
                        await part_f.write(chunk[:split_point])
                        current_part_written += split_point
                        total_written += split_point
                    
                    await part_f.close()
                    
                    # Dispatch to Telegram in background (NON-BLOCKING!)
                    logger.info(
                        f"[DIRECT_UPLOAD] Part {part_index} reached {current_part_written} bytes. "
                        f"Dispatching background upload for '{file.filename}'..."
                    )
                    p_task = asyncio.create_task(
                        upload_part_task(
                            part_file_path=current_part_file,
                            part_index=part_index,
                            file_name=file.filename,
                            start_byte=total_written - current_part_written,
                            part_size=current_part_written,
                            chat_id=chat_id,
                            bot_manager=bot_manager,
                            fallback_client=client,
                            caption=f"{file.filename} (Part {part_index})",
                            semaphore=disk_semaphore,
                            is_single_part=False,
                            file_type=file_type
                        )
                    )
                    upload_tasks.append(p_task)
                    
                    # Acquire next slot (applies backpressure if 2 parts on disk)
                    await disk_semaphore.acquire()

                    # Start next part immediately without pausing client upload!
                    part_index += 1
                    current_part_file = os.path.join(tg_files_dir, f"{upload_id}_part_{part_index}.tmp")
                    part_f = await aiofiles.open(current_part_file, 'wb')
                    remainder = chunk[split_point:]
                    if remainder:
                        await part_f.write(remainder)
                        current_part_written = len(remainder)
                        total_written += len(remainder)
                    else:
                        current_part_written = 0
                else:
                    await part_f.write(chunk)
                    current_part_written += chunk_len
                    total_written += chunk_len
            
            await part_f.close()
        except Exception:
            if not part_f.closed:
                await part_f.close()
            for t in upload_tasks:
                if not t.done():
                    t.cancel()
            if os.path.exists(current_part_file):
                os.remove(current_part_file)
            raise

        if total_written == 0:
            disk_semaphore.release()
            if os.path.exists(current_part_file):
                os.remove(current_part_file)
            raise HTTPException(status_code=400, detail="Cannot upload empty files")

        # Case 1: Single-part file (<= 1950MB)
        if len(upload_tasks) == 0:
            logger.info(f"File '{file.filename}' ({total_written} bytes) fits in 1 Telegram message. Uploading...")
            res = await upload_part_task(
                part_file_path=current_part_file,
                part_index=1,
                file_name=file.filename,
                start_byte=0,
                part_size=total_written,
                chat_id=chat_id,
                bot_manager=bot_manager,
                fallback_client=client,
                caption=f"Uploaded file: {file.filename}",
                semaphore=disk_semaphore,
                is_single_part=True,
                file_type=file_type
            )

            success = database.Files.add_file(
                chat_id=chat_id,
                message_id=res["message_id"],
                thumbnail=res["thumbnail"],
                file_type=file_type,
                file_unique_id=res["file_unique_id"],
                file_size=total_written,
                file_name=file.filename,
                file_caption=f"Uploaded file: {file.filename}",
                file_path=path,
                owner_id=str(user.telegram_user_id)
            )
            return {
                "message": "File uploaded successfully",
                "file": {
                    "id": str(res["message_id"]),
                    "file_unique_id": res["file_unique_id"],
                    "file_name": file.filename,
                    "file_path": path,
                    "file_type": file_type,
                    "file_size": total_written,
                    "thumbnail": res["thumbnail"],
                    "modified": datetime.datetime.now().isoformat()
                }
            }

        # Case 2: Multi-part file (> 1950MB)
        else:
            if current_part_written > 0:
                logger.info(f"Dispatching final part {part_index} ({current_part_written} bytes) for '{file.filename}'...")
                final_task = asyncio.create_task(
                    upload_part_task(
                        part_file_path=current_part_file,
                        part_index=part_index,
                        file_name=file.filename,
                        start_byte=total_written - current_part_written,
                        part_size=current_part_written,
                        chat_id=chat_id,
                        bot_manager=bot_manager,
                        fallback_client=client,
                        caption=f"{file.filename} (Part {part_index}/{part_index})",
                        semaphore=disk_semaphore,
                        is_single_part=False,
                        file_type=file_type
                    )
                )
                upload_tasks.append(final_task)
            else:
                disk_semaphore.release()
                if os.path.exists(current_part_file):
                    try:
                        os.remove(current_part_file)
                    except Exception:
                        pass

            # Await all background upload tasks
            logger.info(f"[DIRECT_UPLOAD] Awaiting completion of {len(upload_tasks)} background upload part(s) for '{file.filename}'...")
            results = await asyncio.gather(*upload_tasks)
            results.sort(key=lambda x: x["part_index"])

            first_res = results[0]
            first_msg_id = first_res["message_id"]
            first_thumbnail = next((r["thumbnail"] for r in results if r.get("thumbnail")), None)
            first_unique_id = first_res["file_unique_id"]

            parts = [
                {
                    "part_index": r["part_index"],
                    "chat_id": r["chat_id"],
                    "message_id": r["message_id"],
                    "file_unique_id": r["file_unique_id"],
                    "part_size": r["part_size"],
                    "start_byte": r["start_byte"],
                    "end_byte": r["end_byte"]
                }
                for r in results
            ]

            final_unique_id = first_unique_id or f"mp_{upload_id}"
            success = database.Files.add_multipart_file(
                chat_id=chat_id,
                thumbnail=first_thumbnail,
                file_type=file_type,
                file_unique_id=final_unique_id,
                file_size=total_written,
                file_name=file.filename,
                file_caption=f"Uploaded multi-part file: {file.filename}",
                parts=parts,
                file_path=path,
                owner_id=str(user.telegram_user_id),
                part_size=PART_MAX_SIZE
            )
            return {
                "message": f"Multi-part file uploaded successfully ({len(parts)} parts)",
                "file": {
                    "id": str(parts[0]["message_id"]),
                    "file_unique_id": final_unique_id,
                    "file_name": file.filename,
                    "file_path": path,
                    "file_type": file_type,
                    "file_size": total_written,
                    "thumbnail": first_thumbnail,
                    "is_split": True,
                    "total_parts": len(parts),
                    "modified": datetime.datetime.now().isoformat()
                }
            }

    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        if 'current_part_file' in locals() and current_part_file and os.path.exists(current_part_file):
            try:
                os.remove(current_part_file)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------
# Chunked Resumable Upload Endpoints (for 2GB+ & large files)
# ----------------------------------------------------
_active_upload_sessions: Dict[str, Dict[str, Any]] = {}

class InitUploadRequest(BaseModel):
    filename: str
    filesize: int
    path: str = "/Home"

@router.post("/upload/init")
async def init_chunked_upload(
    req: InitUploadRequest,
    user: User = Depends(require_auth)
):
    if not user.telegram_user_id:
        raise HTTPException(status_code=400, detail="TELEGRAM_NOT_VERIFIED: Please verify your Telegram account before uploading files")

    # Clean up old upload sessions (> 1 hour old)
    now = datetime.datetime.utcnow()
    expired_uids = [
        uid for uid, s in list(_active_upload_sessions.items())
        if (now - datetime.datetime.fromisoformat(s.get("created_at", now.isoformat()))).total_seconds() > 3600
    ]
    for uid in expired_uids:
        s = _active_upload_sessions.pop(uid, None)
        if s:
            for t in s.get("upload_tasks", []):
                if not t.done():
                    t.cancel()
            if "dir" in s and os.path.exists(s["dir"]):
                shutil.rmtree(s["dir"], ignore_errors=True)

    upload_id = secrets.token_hex(12)
    tg_files_dir = os.path.join(os.getcwd(), "tg_files", f"chunk_{upload_id}")
    os.makedirs(tg_files_dir, exist_ok=True)

    sem = asyncio.Semaphore(2)  # Max 2 active parts on VM disk
    await sem.acquire()

    _active_upload_sessions[upload_id] = {
        "upload_id": upload_id,
        "filename": req.filename,
        "filesize": req.filesize,
        "path": req.path or "/Home",
        "user_id": str(user.telegram_user_id),
        "created_at": datetime.datetime.utcnow().isoformat(),
        "total_written": 0,
        "current_part_index": 1,
        "current_part_written": 0,
        "parts": [],
        "first_thumbnail": None,
        "first_unique_id": None,
        "dir": tg_files_dir,
        "upload_tasks": [],
        "disk_semaphore": sem
    }
    logger.info(f"Initialized chunked upload {upload_id} for '{req.filename}' ({req.filesize} bytes)")
    return {
        "upload_id": upload_id,
        "chunk_size": 20 * 1024 * 1024,
        "part_max_size": 1950 * 1024 * 1024
    }

@router.post("/upload/chunk")
async def upload_file_chunk(
    request: Request,
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk_file: UploadFile = File(...),
    user: User = Depends(require_auth)
):
    session = _active_upload_sessions.get(upload_id)
    if not session or session["user_id"] != str(user.telegram_user_id):
        raise HTTPException(status_code=404, detail="Upload session not found or expired")

    PART_MAX_SIZE = 1950 * 1024 * 1024
    part_idx = session["current_part_index"]
    part_file_path = os.path.join(session["dir"], f"part_{part_idx}.tmp")

    content = await chunk_file.read()
    chunk_len = len(content)

    async with aiofiles.open(part_file_path, 'ab') as f:
        await f.write(content)

    session["current_part_written"] += chunk_len
    session["total_written"] += chunk_len

    if session["current_part_written"] >= PART_MAX_SIZE:
        bot_manager = getattr(request.app.state, 'bot_manager', None)
        user_data = database.Users.find_one({"telegram_user_id": user.telegram_user_id})
        chat_id = user_data.get("index_chat_id")
        client = bot_manager.get_least_busy_client() if bot_manager else None

        if chat_id and client:
            file_extension = os.path.splitext(session["filename"])[1].lower()
            file_type = "document"
            if file_extension in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv']:
                file_type = "video"
            elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
                file_type = "audio"
            elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                file_type = "photo"

            logger.info(
                f"[CHUNKED_UPLOAD] Session {upload_id}: Part {part_idx} reached {session['current_part_written']} bytes. "
                f"Dispatching non-blocking background upload for '{session['filename']}'..."
            )
            # Dispatch background task without blocking the HTTP request!
            # The browser receives HTTP 200 OK immediately and continues uploading next chunks without freezing!
            task = asyncio.create_task(
                upload_part_task(
                    part_file_path=part_file_path,
                    part_index=part_idx,
                    file_name=session["filename"],
                    start_byte=session["total_written"] - session["current_part_written"],
                    part_size=session["current_part_written"],
                    chat_id=chat_id,
                    bot_manager=bot_manager,
                    fallback_client=client,
                    caption=f"{session['filename']} (Part {part_idx})",
                    semaphore=session.get("disk_semaphore"),
                    is_single_part=False,
                    file_type=file_type
                )
            )
            session.setdefault("upload_tasks", []).append(task)

            # Acquire permit for next part buffer (applies backpressure if 2 parts already on disk)
            if "disk_semaphore" in session:
                await session["disk_semaphore"].acquire()

            session["current_part_index"] += 1
            session["current_part_written"] = 0

    return {
        "status": "ok",
        "chunk_index": chunk_index,
        "total_written": session["total_written"],
        "parts_uploaded": len(session.get("upload_tasks", []))
    }

async def _process_upload_completion(upload_id: str, session: dict, bot_manager, chat_id: int):
    try:
        session["status"] = "processing"
        client = bot_manager.get_least_busy_client() if bot_manager else None
        if not client:
            session["status"] = "error"
            session["error"] = "Telegram bot client not available"
            return

        part_idx = session["current_part_index"]
        part_file_path = os.path.join(session["dir"], f"part_{part_idx}.tmp")

        file_extension = os.path.splitext(session["filename"])[1].lower()
        file_type = "document"
        if file_extension in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv']:
            file_type = "video"
        elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
            file_type = "audio"
        elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            file_type = "photo"

        upload_tasks = session.get("upload_tasks", [])

        # Case 1: Single-part file (<= 1950MB) - no background tasks were spawned
        if len(upload_tasks) == 0:
            if not os.path.exists(part_file_path) or session["total_written"] == 0:
                session["status"] = "error"
                session["error"] = "No file chunks received"
                return

            logger.info(f"Uploading single-part file '{session['filename']}' ({session['total_written']} bytes) to Telegram chat {chat_id}...")
            res = await upload_part_task(
                part_file_path=part_file_path,
                part_index=1,
                file_name=session["filename"],
                start_byte=0,
                part_size=session["total_written"],
                chat_id=chat_id,
                bot_manager=bot_manager,
                fallback_client=client,
                caption=f"Uploaded file: {session['filename']}",
                semaphore=session.get("disk_semaphore"),
                is_single_part=True,
                file_type=file_type
            )

            database.Files.add_file(
                chat_id=chat_id,
                message_id=res["message_id"],
                thumbnail=res["thumbnail"],
                file_type=file_type,
                file_unique_id=res["file_unique_id"],
                file_size=session["total_written"],
                file_name=session["filename"],
                file_caption=f"Uploaded file: {session['filename']}",
                file_path=session["path"],
                owner_id=session["user_id"]
            )

            shutil.rmtree(session["dir"], ignore_errors=True)

            session["status"] = "completed"
            session["result_file"] = {
                "id": str(res["message_id"]),
                "file_unique_id": res["file_unique_id"],
                "file_name": session["filename"],
                "file_path": session["path"],
                "file_type": file_type,
                "file_size": session["total_written"],
                "thumbnail": res["thumbnail"],
                "modified": datetime.datetime.now().isoformat()
            }
            session["result_message"] = "File uploaded successfully"
            logger.info(f"Chunked upload {upload_id} for '{session['filename']}' completed successfully.")
        else:
            # Case 2: Multi-part file (> 1950MB)
            if os.path.exists(part_file_path) and session["current_part_written"] > 0:
                logger.info(f"Dispatching final part {part_idx} ({session['current_part_written']} bytes)...")
                final_task = asyncio.create_task(
                    upload_part_task(
                        part_file_path=part_file_path,
                        part_index=part_idx,
                        file_name=session["filename"],
                        start_byte=session["total_written"] - session["current_part_written"],
                        part_size=session["current_part_written"],
                        chat_id=chat_id,
                        bot_manager=bot_manager,
                        fallback_client=client,
                        caption=f"{session['filename']} (Part {part_idx}/{part_idx})",
                        semaphore=session.get("disk_semaphore"),
                        is_single_part=False,
                        file_type=file_type
                    )
                )
                upload_tasks.append(final_task)
            else:
                if "disk_semaphore" in session:
                    session["disk_semaphore"].release()
                if os.path.exists(part_file_path):
                    try:
                        os.remove(part_file_path)
                    except Exception:
                        pass

            # Await all background upload tasks
            logger.info(f"[CHUNKED_UPLOAD] Awaiting completion of {len(upload_tasks)} background upload part(s) for '{session['filename']}'...")
            results = await asyncio.gather(*upload_tasks)
            results.sort(key=lambda x: x["part_index"])

            first_res = results[0]
            first_msg_id = first_res["message_id"]
            first_thumbnail = next((r["thumbnail"] for r in results if r.get("thumbnail")), None)
            first_unique_id = first_res["file_unique_id"]

            parts = [
                {
                    "part_index": r["part_index"],
                    "chat_id": r["chat_id"],
                    "message_id": r["message_id"],
                    "file_unique_id": r["file_unique_id"],
                    "part_size": r["part_size"],
                    "start_byte": r["start_byte"],
                    "end_byte": r["end_byte"]
                }
                for r in results
            ]

            final_unique_id = first_unique_id or f"mp_{upload_id}"
            database.Files.add_multipart_file(
                chat_id=chat_id,
                thumbnail=first_thumbnail,
                file_type=file_type,
                file_unique_id=final_unique_id,
                file_size=session["total_written"],
                file_name=session["filename"],
                file_caption=f"Uploaded multi-part file: {session['filename']}",
                parts=parts,
                file_path=session["path"],
                owner_id=session["user_id"],
                part_size=1950 * 1024 * 1024
            )

            shutil.rmtree(session["dir"], ignore_errors=True)

            session["status"] = "completed"
            session["result_file"] = {
                "id": str(parts[0]["message_id"]),
                "file_unique_id": final_unique_id,
                "file_name": session["filename"],
                "file_path": session["path"],
                "file_type": file_type,
                "file_size": session["total_written"],
                "thumbnail": first_thumbnail,
                "is_split": True,
                "total_parts": len(parts),
                "modified": datetime.datetime.now().isoformat()
            }
            session["result_message"] = f"Multi-part file uploaded successfully ({len(parts)} parts)"
            logger.info(f"Chunked multi-part upload {upload_id} for '{session['filename']}' completed successfully.")
    except Exception as e:
        logger.error(f"Error processing upload completion {upload_id}: {e}", exc_info=True)
        session["status"] = "error"
        session["error"] = str(e)
        if os.path.exists(session.get("dir", "")):
            shutil.rmtree(session["dir"], ignore_errors=True)

@router.post("/upload/complete")
async def complete_chunked_upload(
    request: Request,
    upload_id: str = Form(...),
    user: User = Depends(require_auth)
):
    session = _active_upload_sessions.get(upload_id)
    if not session or session["user_id"] != str(user.telegram_user_id):
        raise HTTPException(status_code=404, detail="Upload session not found or expired")

    bot_manager = getattr(request.app.state, 'bot_manager', None)
    user_data = database.Users.find_one({"telegram_user_id": user.telegram_user_id})
    chat_id = user_data.get("index_chat_id")
    client = bot_manager.get_least_busy_client() if bot_manager else None

    if not chat_id or not client:
        raise HTTPException(status_code=500, detail="Telegram chat or bot client not available")

    # If already processing or completed, return current status immediately
    if session.get("status") in ["processing", "completed"]:
        return {
            "status": session["status"],
            "upload_id": upload_id,
            "message": "Upload is already processing or completed"
        }

    session["status"] = "processing"
    # Run Telegram upload in background task so HTTP connection responds immediately
    asyncio.create_task(_process_upload_completion(upload_id, session, bot_manager, chat_id))

    return {
        "status": "processing",
        "upload_id": upload_id,
        "message": "File received. Processing and saving to Telegram cloud..."
    }

@router.get("/upload/status/{upload_id}")
async def get_upload_status(
    upload_id: str,
    user: User = Depends(require_auth)
):
    session = _active_upload_sessions.get(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found or expired")

    if session.get("user_id") != str(user.telegram_user_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    status = session.get("status", "uploading")
    if status == "completed":
        return {
            "status": "completed",
            "file": session.get("result_file"),
            "message": session.get("result_message", "File uploaded successfully")
        }
    elif status == "error":
        err_msg = session.get("error", "Upload processing failed")
        return {
            "status": "error",
            "error": err_msg
        }
    else:
        return {
            "status": "processing",
            "message": "Saving to Telegram cloud..."
        }

class AbortUploadRequest(BaseModel):
    upload_id: str

@router.post("/upload/abort")
async def abort_chunked_upload(
    req: AbortUploadRequest,
    user: User = Depends(require_auth)
):
    upload_id = req.upload_id
    session = _active_upload_sessions.pop(upload_id, None)
    tg_files_dir = os.path.join(os.getcwd(), "tg_files", f"chunk_{upload_id}")

    if session:
        # Check permissions if user_id present
        if session.get("user_id") and session["user_id"] != str(user.telegram_user_id):
            raise HTTPException(status_code=403, detail="Forbidden")

        # Cancel any ongoing background upload tasks
        for t in session.get("upload_tasks", []):
            if not t.done():
                t.cancel()

        # Release disk semaphore permit if held
        if "disk_semaphore" in session:
            try:
                session["disk_semaphore"].release()
            except Exception:
                pass

        # Purge temporary directory from disk
        if "dir" in session and os.path.exists(session["dir"]):
            shutil.rmtree(session["dir"], ignore_errors=True)

    if os.path.exists(tg_files_dir):
        shutil.rmtree(tg_files_dir, ignore_errors=True)

    logger.info(f"Upload session {upload_id} aborted by user and disk storage purged.")
    return {
        "status": "aborted",
        "upload_id": upload_id,
        "message": "Upload aborted and temporary files cleaned up."
    }

@router.get("/thumbnail/{file_id}")
async def get_file_thumbnail(file_id: str, request: Request, auth_token: str = None):
    # Check authentication - first try the normal auth, then check for token in query params
    try:
        # This will raise an exception if not authenticated via normal means
        user = require_auth(request)
    except HTTPException:
        # If normal auth fails, check for auth_token in query params
        if auth_token:
            # First check in-memory cache
            if auth_token in _auth_tokens:
                # Token is valid, proceed
                pass
            else:
                # Check in database if not found in memory
                try:
                    db_token_data = database.Users.get_auth_token(auth_token)
                    if db_token_data:
                        # Add to in-memory cache for future requests
                        _auth_tokens[auth_token] = {
                            "authenticated": True,
                            "username": db_token_data['username'],
                            "auth_method": db_token_data['auth_method'],
                            "created_at": db_token_data['created_at'].isoformat() if hasattr(db_token_data['created_at'], 'isoformat') else str(db_token_data['created_at'])
                        }
                        # Token is valid, proceed
                        pass
                    else:
                        # No valid authentication method
                        raise HTTPException(status_code=401, detail="Authentication required")
                except Exception as e:
                    logger.error(f"Failed to check auth token in database: {e}")
                    # No valid authentication method
                    raise HTTPException(status_code=401, detail="Authentication required")
        else:
            # No valid authentication method
            raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        bot_manager = request.app.state.bot_manager
        if not bot_manager:
            raise HTTPException(status_code=503, detail="Bot manager not available")

        # Get a client to use for downloading
        client: Client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
        if not client:
            raise HTTPException(status_code=500, detail="No available bot clients")
        
        photo_data = await client.download_media(file_id, in_memory=True)
        if photo_data:
            # Check if it's a BytesIO object
            if hasattr(photo_data, 'getvalue'):
                photo_bytes = photo_data.getvalue()
                if len(photo_bytes) > 0:
                    # Return the photo data
                    return Response(
                        content=photo_bytes,
                        media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"}  # Cache for 1 hour
                    )
            else:
                # If it's already bytes, return directly
                if len(photo_data) > 0:
                    return Response(
                        content=photo_data,
                        media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"}  # Cache for 1 hour
                    )
    except Exception as e:
        logger.error(f"Error downloading file thumbnail: {e}")
        raise HTTPException(status_code=500, detail=str(e))