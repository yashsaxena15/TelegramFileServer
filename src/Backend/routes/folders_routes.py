# src/Backend/routes/folders_routes.py

import os
import re
import urllib.parse
from typing import Optional, List, Dict, Any
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..security.credentials import require_auth, User
from src.Database import database
from d4rk.Logs import setup_logger
from ..modules.byte_streamer import ByteStreamer
from ..modules.zip_streamer import (
    generate_zip_stream,
    partition_files_for_zip,
    MAX_ZIP_PART_SIZE,
)

logger = setup_logger("folders_routes")

# Create router with updated prefix
router = APIRouter(prefix="/folders", tags=["Folders"])


class CreateFolderRequest(BaseModel):
    folderName: str
    currentPath: str


class CreateFolderPathRequest(BaseModel):
    fullPath: str


def resolve_folder_info(folder_id: Optional[str], folder_path_param: Optional[str], user_id: str):
    """Resolves folder document, clean folder name, and absolute folder path."""
    folder_doc = None
    if folder_id:
        try:
            folder_doc = database.Files.find_one({"_id": ObjectId(folder_id), "owner_id": user_id})
        except Exception:
            pass
        if not folder_doc:
            try:
                folder_doc = database.Files.find_one({"_id": ObjectId(folder_id)})
            except Exception:
                pass

    if not folder_doc and folder_path_param:
        clean_p = folder_path_param.rstrip("/")
        parts = clean_p.rsplit("/", 1)
        if len(parts) == 2:
            parent_p = parts[0] or "/"
            f_name = parts[1]
            folder_doc = database.Files.find_one({
                "file_name": f_name,
                "file_path": {"$in": [parent_p, f"/{parent_p.lstrip('/')}"]},
                "file_type": "folder",
                "owner_id": user_id,
            })
            if not folder_doc:
                folder_doc = database.Files.find_one({
                    "file_name": f_name,
                    "file_type": "folder",
                })

    if folder_doc:
        f_name = folder_doc.get("file_name", "Folder")
        f_parent = folder_doc.get("file_path", "/")
        if f_parent in ["/", ""]:
            full_path = f"/{f_name}"
        else:
            full_path = f"{f_parent.rstrip('/')}/{f_name}"
        return folder_doc, f_name, full_path

    if folder_path_param:
        clean_p = folder_path_param.rstrip("/")
        f_name = clean_p.split("/")[-1] if "/" in clean_p else clean_p
        return None, f_name, clean_p

    return None, "Folder", "/Home"


@router.post("/create")
async def create_folder_route(request: CreateFolderRequest, user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        success = database.Files.create_folder(request.folderName, request.currentPath, user_id)
        if success:
            return {"message": f"Folder '{request.folderName}' created successfully"}
        else:
            raise HTTPException(status_code=400, detail="Folder already exists")
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-path")
async def create_folder_path_route(request: CreateFolderPathRequest, user: User = Depends(require_auth)):
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        success = database.Files.create_folder_path(request.fullPath, user_id)
        if success:
            return {"message": f"Folder path '{request.fullPath}' created successfully"}
        else:
            return {"message": f"Folder path '{request.fullPath}' already exists or was created"}
    except Exception as e:
        logger.error(f"Error creating folder path: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_folder_stats(
    id: Optional[str] = Query(None),
    path: Optional[str] = Query(None),
    user: User = Depends(require_auth)
):
    """Calculates recursive file count, subfolder count, and total size of a folder."""
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        _, folder_name, full_path = resolve_folder_info(id, path, user_id)

        escaped = re.escape(full_path)
        query = {
            "file_path": {"$regex": f"^{escaped}(/|$)"},
            "owner_id": user_id,
        }
        items = list(database.Files.find(query))

        total_files = 0
        total_subfolders = 0
        total_size = 0

        for item in items:
            if item.get("file_type") == "folder":
                total_subfolders += 1
            else:
                total_files += 1
                total_size += int(item.get("file_size") or 0)

        return {
            "folder_name": folder_name,
            "full_path": full_path,
            "total_files": total_files,
            "total_subfolders": total_subfolders,
            "total_size": total_size,
        }
    except Exception as e:
        logger.error(f"Error calculating folder stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-info")
async def get_folder_download_info(
    id: Optional[str] = Query(None),
    path: Optional[str] = Query(None),
    user: User = Depends(require_auth)
):
    """Returns folder zip packaging information and parts divided by 2GB threshold."""
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        folder_doc, folder_name, full_path = resolve_folder_info(id, path, user_id)

        escaped = re.escape(full_path)
        query = {
            "file_path": {"$regex": f"^{escaped}(/|$)"},
            "file_type": {"$ne": "folder"},
            "owner_id": user_id,
        }
        files = list(database.Files.find(query))
        files.sort(key=lambda x: (x.get("file_path", ""), x.get("file_name", "")))

        total_files = len(files)
        total_size = sum(int(f.get("file_size") or 0) for f in files)

        if not files:
            return {
                "folder_name": folder_name,
                "full_path": full_path,
                "total_files": 0,
                "total_size": 0,
                "total_parts": 0,
                "parts": [],
            }

        raw_parts = partition_files_for_zip(files, MAX_ZIP_PART_SIZE)
        num_parts = len(raw_parts)

        parts_result = []
        for idx, part_files in enumerate(raw_parts, 1):
            part_name = f"{folder_name}.zip" if num_parts == 1 else f"{folder_name}-part{idx}.zip"
            part_size = sum(int(f.get("file_size") or 0) for f in part_files)

            param = f"id={id}" if id else f"path={urllib.parse.quote(full_path)}"
            dl_url = f"/folders/download-zip?{param}&part={idx}"

            parts_result.append({
                "part_index": idx,
                "name": part_name,
                "size": part_size,
                "files_count": len(part_files),
                "download_url": dl_url,
            })

        return {
            "folder_name": folder_name,
            "full_path": full_path,
            "total_files": total_files,
            "total_size": total_size,
            "total_parts": num_parts,
            "parts": parts_result,
        }
    except Exception as e:
        logger.error(f"Error preparing folder download info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-zip")
async def download_folder_zip(
    request: Request,
    id: Optional[str] = Query(None),
    path: Optional[str] = Query(None),
    part: int = Query(1),
    token: Optional[str] = Query(None),
    user: User = Depends(require_auth)
):
    """Streams a requested zip part on-the-fly directly from Telegram."""
    try:
        user_id = str(user.telegram_user_id) if user.telegram_user_id else user.username
        folder_doc, folder_name, full_path = resolve_folder_info(id, path, user_id)

        escaped = re.escape(full_path)
        query = {
            "file_path": {"$regex": f"^{escaped}(/|$)"},
            "file_type": {"$ne": "folder"},
            "owner_id": user_id,
        }
        files = list(database.Files.find(query))
        files.sort(key=lambda x: (x.get("file_path", ""), x.get("file_name", "")))

        if not files:
            raise HTTPException(status_code=404, detail="Folder is empty or files not found")

        raw_parts = partition_files_for_zip(files, MAX_ZIP_PART_SIZE)
        if part < 1 or part > len(raw_parts):
            raise HTTPException(status_code=400, detail=f"Invalid part {part}. Total parts: {len(raw_parts)}")

        part_files = raw_parts[part - 1]
        zip_filename = f"{folder_name}.zip" if len(raw_parts) == 1 else f"{folder_name}-part{part}.zip"

        files_with_arcnames = []
        for f in part_files:
            f_dir = f.get("file_path", "")
            f_name = f.get("file_name", "unnamed_file")
            try:
                rel_dir = os.path.relpath(f_dir, full_path)
            except ValueError:
                rel_dir = "."

            if rel_dir == "." or not rel_dir:
                arcname = f"{folder_name}/{f_name}"
            else:
                arcname = f"{folder_name}/{rel_dir}/{f_name}"

            arcname = arcname.replace("\\", "/").replace("//", "/")
            files_with_arcnames.append({
                "arcname": arcname,
                "doc": f,
            })

        bot_manager = getattr(request.app.state, 'bot_manager', None)
        if not bot_manager:
            raise HTTPException(status_code=503, detail="Bot manager not available")

        client = bot_manager.get_least_busy_client() if hasattr(bot_manager, 'get_least_busy_client') else None
        if not client:
            raise HTTPException(status_code=503, detail="No available bot clients")

        active_clients = bot_manager.client_list if (hasattr(bot_manager, 'client_list') and bot_manager.client_list) else [client]
        byte_streamer = ByteStreamer(client)

        encoded_filename = urllib.parse.quote(zip_filename)
        ascii_fallback = re.sub(r'[^\x20-\x7E]', '_', zip_filename).replace('"', '_').replace('\\', '_')
        if not ascii_fallback.strip('_ '):
            ascii_fallback = "archive.zip"
        headers = {
            "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}',
            "Content-Type": "application/zip",
            "Cache-Control": "no-cache",
        }

        return StreamingResponse(
            generate_zip_stream(files_with_arcnames, byte_streamer, active_clients),
            media_type="application/zip",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in folder zip download: {e}")
        raise HTTPException(status_code=500, detail=str(e))