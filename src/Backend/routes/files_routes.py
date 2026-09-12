# src/Backend/routes/files_routes.py

from fastapi import APIRouter, Request, Depends, HTTPException, File, UploadFile, Form, Response , Query
from pydantic import BaseModel
from bson import ObjectId
import os
import datetime
import aiofiles
import re
import secrets
import shutil
from typing import List, Dict, Any, Optional
from dataclasses import asdict

from ..security.credentials import require_auth, User
from src.Database import database
from d4rk.Logs import setup_logger

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
    path: str = Query(default="/", description="Folder path to fetch files from"),
    user: User = Depends(require_auth)
):
    try:
        # Fetch files for the specified path and user
        logger.info(f"Fetching files for path {path} and user {user}")
        # Use the user's Telegram ID as the user identifier
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
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
        # Rename the file/folder with owner validation
        success = database.Files.rename_file(request.file_id, request.new_name, user_id)
        
        if success:
            return {"message": "Item renamed successfully"}
        else:
            raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete")
async def delete_file_route(request: DeleteFileRequest, user: User = Depends(require_auth)):
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
        
        # Check if this is a folder
        if file_data.get("file_type") == "folder":
            # For folders, we also need to delete all files inside the folder
            folder_path = file_data.get("file_path", "/")
            folder_name = file_data.get("file_name", "")
            
            # Construct the full folder paths (handle both /Home and /)
            paths_to_delete = []
            if folder_path in ["/", "/Home", "Home"]:
                paths_to_delete.extend([f"/Home/{folder_name}", f"/{folder_name}"])
            else:
                paths_to_delete.append(f"{folder_path}/{folder_name}")
            
            for f_path in paths_to_delete:
                # Delete all files in the folder (owned by the user)
                database.Files.delete_many({"file_path": f_path, "owner_id": user_id})
                
                # Also delete any subfolders and files inside this folder
                database.Files.delete_many({
                    "file_path": {"$regex": f"^{re.escape(f_path)}/"},
                    "owner_id": user_id
                })
        
        # Delete the file/folder itself
        result = database.Files.delete_one({"_id": ObjectId(request.file_id), "owner_id": user_id})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="File not found")
        
        return {"message": "Item deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
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
        parts = []
        first_thumbnail = None
        first_media_unique_id = None
        
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
                    
                    # Upload this part immediately to Telegram
                    p_client = bot_manager.get_least_busy_client() or client
                    logger.info(f"Uploading part {part_index} ({current_part_written} bytes) for '{file.filename}'...")
                    
                    part_sent_msg = await p_client.send_document(
                        chat_id=chat_id,
                        document=current_part_file,
                        caption=f"{file.filename} (Part {part_index})",
                        force_document=True
                    )
                    p_media = part_sent_msg.document or part_sent_msg.video or part_sent_msg.audio or part_sent_msg.photo
                    if not first_thumbnail and hasattr(p_media, 'thumbs') and p_media.thumbs:
                        first_thumbnail = p_media.thumbs[0].file_id
                    if not first_media_unique_id and hasattr(p_media, 'file_unique_id'):
                        first_media_unique_id = p_media.file_unique_id
                        
                    parts.append({
                        "part_index": part_index,
                        "chat_id": chat_id,
                        "message_id": part_sent_msg.id,
                        "file_unique_id": p_media.file_unique_id,
                        "part_size": current_part_written,
                        "start_byte": total_written - current_part_written,
                        "end_byte": total_written - 1
                    })
                    
                    # Remove disk file immediately
                    if os.path.exists(current_part_file):
                        os.remove(current_part_file)
                        
                    # Start next part
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
            if os.path.exists(current_part_file):
                os.remove(current_part_file)
            raise

        if total_written == 0:
            if os.path.exists(current_part_file):
                os.remove(current_part_file)
            raise HTTPException(status_code=400, detail="Cannot upload empty files")

        file_extension = os.path.splitext(file.filename)[1].lower()
        file_type = "document"
        if file_extension in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']:
            file_type = "video"
        elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
            file_type = "audio"
        elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            file_type = "photo"

        # Case 1: Single-part file (<= 1950MB)
        if len(parts) == 0:
            logger.info(f"File '{file.filename}' ({total_written} bytes) fits in 1 Telegram message. Uploading...")
            sent_message = None
            try:
                if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'] and total_written <= 10 * 1024 * 1024:
                    sent_message = await client.send_photo(chat_id=chat_id, photo=current_part_file, caption=f"Uploaded file: {file.filename}")
                elif file_extension in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']:
                    sent_message = await client.send_video(chat_id=chat_id, video=current_part_file, caption=f"Uploaded file: {file.filename}")
                elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
                    sent_message = await client.send_audio(chat_id=chat_id, audio=current_part_file, caption=f"Uploaded file: {file.filename}")
                else:
                    sent_message = await client.send_document(chat_id=chat_id, document=current_part_file, caption=f"Uploaded file: {file.filename}", force_document=True)
            except Exception as e:
                logger.warning(f"Upload failed as specific media, falling back to document: {e}")
                sent_message = await client.send_document(chat_id=chat_id, document=current_part_file, caption=f"Uploaded file: {file.filename}", force_document=True)
            finally:
                if os.path.exists(current_part_file):
                    os.remove(current_part_file)

            if not sent_message:
                raise HTTPException(status_code=500, detail="Failed to upload file to Telegram")

            media = sent_message.document or sent_message.video or sent_message.audio or sent_message.photo or sent_message.voice
            thumbnail = None
            if hasattr(media, 'thumbs') and media.thumbs:
                thumbnail = media.thumbs[0].file_id
            elif hasattr(media, 'file_id') and sent_message.photo:
                thumbnail = media.file_id

            success = database.Files.add_file(
                chat_id=sent_message.chat.id,
                message_id=sent_message.id,
                thumbnail=thumbnail,
                file_type=file_type,
                file_unique_id=media.file_unique_id,
                file_size=media.file_size,
                file_name=file.filename,
                file_caption=f"Uploaded file: {file.filename}",
                file_path=path,
                owner_id=str(user.telegram_user_id)
            )
            return {
                "message": "File uploaded successfully",
                "file": {
                    "id": str(sent_message.id),
                    "file_unique_id": media.file_unique_id,
                    "file_name": file.filename,
                    "file_path": path,
                    "file_type": file_type,
                    "file_size": media.file_size,
                    "thumbnail": thumbnail,
                    "modified": datetime.datetime.now().isoformat()
                }
            }

        # Case 2: Multi-part file (> 1950MB)
        else:
            if current_part_written > 0:
                p_client = bot_manager.get_least_busy_client() or client
                logger.info(f"Uploading final part {part_index} ({current_part_written} bytes) for '{file.filename}'...")
                part_sent_msg = await p_client.send_document(
                    chat_id=chat_id,
                    document=current_part_file,
                    caption=f"{file.filename} (Part {part_index}/{part_index})",
                    force_document=True
                )
                p_media = part_sent_msg.document or part_sent_msg.video or part_sent_msg.audio or part_sent_msg.photo
                if not first_thumbnail and hasattr(p_media, 'thumbs') and p_media.thumbs:
                    first_thumbnail = p_media.thumbs[0].file_id
                if not first_media_unique_id and hasattr(p_media, 'file_unique_id'):
                    first_media_unique_id = p_media.file_unique_id

                parts.append({
                    "part_index": part_index,
                    "chat_id": chat_id,
                    "message_id": part_sent_msg.id,
                    "file_unique_id": p_media.file_unique_id,
                    "part_size": current_part_written,
                    "start_byte": total_written - current_part_written,
                    "end_byte": total_written - 1
                })
                if os.path.exists(current_part_file):
                    os.remove(current_part_file)

            final_unique_id = first_media_unique_id or f"mp_{upload_id}"
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

    upload_id = secrets.token_hex(12)
    tg_files_dir = os.path.join(os.getcwd(), "tg_files", f"chunk_{upload_id}")
    os.makedirs(tg_files_dir, exist_ok=True)

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
        "dir": tg_files_dir
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
            logger.info(f"Chunked upload {upload_id}: Part {part_idx} reached {session['current_part_written']} bytes. Uploading to Telegram...")
            sent_msg = await client.send_document(
                chat_id=chat_id,
                document=part_file_path,
                caption=f"{session['filename']} (Part {part_idx})",
                force_document=True
            )
            media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo
            if not session["first_thumbnail"] and hasattr(media, 'thumbs') and media.thumbs:
                session["first_thumbnail"] = media.thumbs[0].file_id
            if not session["first_unique_id"] and hasattr(media, 'file_unique_id'):
                session["first_unique_id"] = media.file_unique_id

            session["parts"].append({
                "part_index": part_idx,
                "chat_id": chat_id,
                "message_id": sent_msg.id,
                "file_unique_id": media.file_unique_id,
                "part_size": session["current_part_written"],
                "start_byte": session["total_written"] - session["current_part_written"],
                "end_byte": session["total_written"] - 1
            })

            if os.path.exists(part_file_path):
                os.remove(part_file_path)

            session["current_part_index"] += 1
            session["current_part_written"] = 0

    return {
        "status": "ok",
        "chunk_index": chunk_index,
        "total_written": session["total_written"],
        "parts_uploaded": len(session["parts"])
    }

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

    part_idx = session["current_part_index"]
    part_file_path = os.path.join(session["dir"], f"part_{part_idx}.tmp")

    file_extension = os.path.splitext(session["filename"])[1].lower()
    file_type = "document"
    if file_extension in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']:
        file_type = "video"
    elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
        file_type = "audio"
    elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
        file_type = "photo"

    if len(session["parts"]) == 0:
        if not os.path.exists(part_file_path):
            raise HTTPException(status_code=400, detail="No file chunks received")

        try:
            if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'] and session["total_written"] <= 10 * 1024 * 1024:
                sent_msg = await client.send_photo(chat_id=chat_id, photo=part_file_path, caption=f"Uploaded file: {session['filename']}")
            elif file_extension in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']:
                sent_msg = await client.send_video(chat_id=chat_id, video=part_file_path, caption=f"Uploaded file: {session['filename']}")
            elif file_extension in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
                sent_msg = await client.send_audio(chat_id=chat_id, audio=part_file_path, caption=f"Uploaded file: {session['filename']}")
            else:
                sent_msg = await client.send_document(chat_id=chat_id, document=part_file_path, caption=f"Uploaded file: {session['filename']}", force_document=True)
        except Exception as ex:
            logger.warning(f"Fallback upload as document: {ex}")
            sent_msg = await client.send_document(chat_id=chat_id, document=part_file_path, caption=f"Uploaded file: {session['filename']}", force_document=True)
        finally:
            if os.path.exists(part_file_path):
                os.remove(part_file_path)

        media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo or sent_msg.voice
        thumbnail = None
        if hasattr(media, 'thumbs') and media.thumbs:
            thumbnail = media.thumbs[0].file_id
        elif hasattr(media, 'file_id') and sent_msg.photo:
            thumbnail = media.file_id

        database.Files.add_file(
            chat_id=chat_id,
            message_id=sent_msg.id,
            thumbnail=thumbnail,
            file_type=file_type,
            file_unique_id=media.file_unique_id,
            file_size=session["total_written"],
            file_name=session["filename"],
            file_caption=f"Uploaded file: {session['filename']}",
            file_path=session["path"],
            owner_id=session["user_id"]
        )

        shutil.rmtree(session["dir"], ignore_errors=True)
        _active_upload_sessions.pop(upload_id, None)

        return {
            "message": "File uploaded successfully",
            "file": {
                "id": str(sent_msg.id),
                "file_unique_id": media.file_unique_id,
                "file_name": session["filename"],
                "file_path": session["path"],
                "file_type": file_type,
                "file_size": session["total_written"],
                "thumbnail": thumbnail,
                "modified": datetime.datetime.now().isoformat()
            }
        }
    else:
        if os.path.exists(part_file_path) and session["current_part_written"] > 0:
            logger.info(f"Uploading final part {part_idx} ({session['current_part_written']} bytes)...")
            sent_msg = await client.send_document(
                chat_id=chat_id,
                document=part_file_path,
                caption=f"{session['filename']} (Part {part_idx}/{part_idx})",
                force_document=True
            )
            media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo
            if not session["first_thumbnail"] and hasattr(media, 'thumbs') and media.thumbs:
                session["first_thumbnail"] = media.thumbs[0].file_id
            if not session["first_unique_id"] and hasattr(media, 'file_unique_id'):
                session["first_unique_id"] = media.file_unique_id

            session["parts"].append({
                "part_index": part_idx,
                "chat_id": chat_id,
                "message_id": sent_msg.id,
                "file_unique_id": media.file_unique_id,
                "part_size": session["current_part_written"],
                "start_byte": session["total_written"] - session["current_part_written"],
                "end_byte": session["total_written"] - 1
            })
            if os.path.exists(part_file_path):
                os.remove(part_file_path)

        final_unique_id = session["first_unique_id"] or f"mp_{upload_id}"
        database.Files.add_multipart_file(
            chat_id=chat_id,
            thumbnail=session["first_thumbnail"],
            file_type=file_type,
            file_unique_id=final_unique_id,
            file_size=session["total_written"],
            file_name=session["filename"],
            file_caption=f"Uploaded multi-part file: {session['filename']}",
            parts=session["parts"],
            file_path=session["path"],
            owner_id=session["user_id"],
            part_size=1950 * 1024 * 1024
        )

        shutil.rmtree(session["dir"], ignore_errors=True)
        _active_upload_sessions.pop(upload_id, None)

        return {
            "message": f"Multi-part file uploaded successfully ({len(session['parts'])} parts)",
            "file": {
                "id": str(session["parts"][0]["message_id"]),
                "file_unique_id": final_unique_id,
                "file_name": session["filename"],
                "file_path": session["path"],
                "file_type": file_type,
                "file_size": session["total_written"],
                "thumbnail": session["first_thumbnail"],
                "is_split": True,
                "total_parts": len(session["parts"]),
                "modified": datetime.datetime.now().isoformat()
            }
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