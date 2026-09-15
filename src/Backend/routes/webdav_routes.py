# src/Backend/routes/webdav_routes.py

import os
import base64
import urllib.parse
import secrets
import mimetypes
import aiofiles
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape
from typing import Optional, Tuple, Dict, Any, List

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from pyrogram import Client
from bson import ObjectId

from src.Database import database
from src.Config import OWNER, LOGS, MOVIE, GROUP, FILTER_CHAT
from ..security.credentials import verify_credentials
from ..modules.byte_streamer import ByteStreamer
from ..modules.streaming_utils import parse_range_header
from d4rk.Logs import setup_logger

logger = setup_logger("webdav_routes")

router = APIRouter(prefix="/webdav", tags=["WebDAV"])

VIRTUAL_TOP_LEVEL = ["Home", "Telegram Inbox", "Starred", "Trash"]


def format_dav_date(dt: Optional[Any] = None) -> str:
    """Format datetime into standard RFC 1123 format for WebDAV."""
    if not dt:
        dt = datetime.now(timezone.utc)
    elif isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt, usegmt=True)


def parse_webdav_path(raw_path: str) -> List[str]:
    """Clean and decompose WebDAV URI path into logical segments."""
    unquoted = urllib.parse.unquote(raw_path or "")
    # Remove prefix if present
    if unquoted.startswith("/webdav"):
        unquoted = unquoted[len("/webdav"):]
    segments = [s for s in unquoted.strip("/").split("/") if s]
    return segments


def authenticate_webdav(request: Request) -> Tuple[Dict[str, Any], str, Optional[int]]:
    """
    Authenticate WebDAV request via HTTP Basic Auth.
    Returns (user_data, owner_id, chat_id).
    """
    auth_header = request.headers.get("Authorization", "")
    token_query = request.query_params.get("token")

    username = None
    password = None

    if auth_header.startswith("Basic "):
        try:
            encoded = auth_header[6:].strip()
            decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
            if ":" in decoded:
                username, password = decoded.split(":", 1)
        except Exception as e:
            logger.warning(f"[WEBDAV] Failed to decode Basic Auth: {e}")

    # Fallback to query token if provided
    if not username and token_query:
        # Check token in database
        token_doc = database.Users.get_auth_token(token_query) if hasattr(database, "Users") else None
        if token_doc:
            username = token_doc.get("username")
            user_data = database.Users.getUser(username) if hasattr(database, "Users") else None
            if user_data:
                owner_id = str(user_data.get("telegram_user_id") or user_data.get("username") or OWNER)
                chat_id = user_data.get("index_chat_id")
                return user_data, owner_id, chat_id

    if not username or not password or not verify_credentials(username, password):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="TelegramFileServer WebDAV"'}
        )

    # Resolve user metadata
    user_data = database.Users.getUser(username) if hasattr(database, "Users") else None
    if not user_data:
        user_data = {"username": username, "telegram_user_id": OWNER}

    owner_id = str(user_data.get("telegram_user_id") or user_data.get("username") or OWNER)
    chat_id = user_data.get("index_chat_id")
    if not chat_id:
        chat_id = [c for c in [LOGS, MOVIE, GROUP, FILTER_CHAT] if c is not None][0] if [c for c in [LOGS, MOVIE, GROUP, FILTER_CHAT] if c is not None] else None

    return user_data, owner_id, chat_id


def build_response_xml(href: str, display_name: str, is_collection: bool, size: int = 0, mime_type: str = "application/octet-stream", modified: Optional[str] = None) -> str:
    """Build a single <D:response> block for WebDAV 207 Multi-Status."""
    encoded_href = urllib.parse.quote(href, safe="/")
    escaped_name = xml_escape(display_name or "")
    date_str = format_dav_date(modified)

    if is_collection:
        prop_block = f"""        <D:displayname>{escaped_name}</D:displayname>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:getlastmodified>{date_str}</D:getlastmodified>"""
    else:
        prop_block = f"""        <D:displayname>{escaped_name}</D:displayname>
        <D:resourcetype/>
        <D:getcontentlength>{size}</D:getcontentlength>
        <D:getcontenttype>{mime_type}</D:getcontenttype>
        <D:getlastmodified>{date_str}</D:getlastmodified>"""

    return f"""  <D:response>
    <D:href>{encoded_href}</D:href>
    <D:propstat>
      <D:prop>
{prop_block}
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""


@router.api_route("", methods=["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "DELETE", "MKCOL", "MOVE", "COPY", "LOCK", "UNLOCK", "PROPPATCH"])
@router.api_route("/", methods=["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "DELETE", "MKCOL", "MOVE", "COPY", "LOCK", "UNLOCK", "PROPPATCH"])
@router.api_route("/{path:path}", methods=["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "DELETE", "MKCOL", "MOVE", "COPY", "LOCK", "UNLOCK", "PROPPATCH"])
async def webdav_dispatcher(request: Request, path: str = ""):
    method = request.method.upper()

    # 1. OPTIONS: Handshake & capabilities (Clients like RaiDrive/Windows test this upfront)
    if method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "DAV": "1, 2",
                "MS-Author-Via": "DAV",
                "Allow": "OPTIONS, GET, HEAD, POST, PUT, DELETE, TRACE, PROPFIND, PROPPATCH, MKCOL, COPY, MOVE, LOCK, UNLOCK",
                "Accept-Ranges": "bytes",
            }
        )

    # 2. Authenticate all operational WebDAV requests
    user_data, owner_id, default_chat_id = authenticate_webdav(request)
    segments = parse_webdav_path(path)

    # 3. Handle specific methods
    if method == "PROPFIND":
        return await handle_propfind(request, segments, owner_id)
    elif method in ("GET", "HEAD"):
        return await handle_get_head(request, segments, owner_id, is_head=(method == "HEAD"))
    elif method == "PUT":
        return await handle_put(request, segments, owner_id, default_chat_id)
    elif method == "MKCOL":
        return await handle_mkcol(request, segments, owner_id)
    elif method == "DELETE":
        return await handle_delete(request, segments, owner_id)
    elif method == "MOVE":
        return await handle_move(request, segments, owner_id)
    elif method == "COPY":
        return await handle_copy(request, segments, owner_id)
    elif method == "LOCK":
        return handle_lock(request)
    elif method == "UNLOCK":
        return Response(status_code=204)
    elif method == "PROPPATCH":
        return handle_proppatch(request)
    else:
        raise HTTPException(status_code=405, detail="Method Not Allowed")


# --- Handler Implementations ---

async def handle_propfind(request: Request, segments: List[str], owner_id: str) -> Response:
    """Handle WebDAV PROPFIND directory and file enumeration."""
    depth = request.headers.get("Depth", "1")
    responses_xml = []

    # Case A: Root (/webdav/)
    if len(segments) == 0:
        responses_xml.append(build_response_xml("/webdav/", "WebDAV Root", is_collection=True))
        if depth == "1":
            for top in VIRTUAL_TOP_LEVEL:
                responses_xml.append(build_response_xml(f"/webdav/{top}/", top, is_collection=True))

    # Case B: Top-level Virtual Folders (/webdav/Home, /webdav/Telegram Inbox, etc.)
    elif len(segments) == 1 and segments[0] in VIRTUAL_TOP_LEVEL:
        top_name = segments[0]
        responses_xml.append(build_response_xml(f"/webdav/{top_name}/", top_name, is_collection=True))

        if depth == "1":
            if top_name == "Home":
                # User-created folders in Home root
                folders = list(database.Files.find({
                    "file_type": "folder",
                    "file_path": {"$in": ["/Home", "/"]},
                    "owner_id": owner_id,
                    "trashed": {"$ne": True}
                }))
                for fol in folders:
                    fol_name = fol.get("file_name", "Folder")
                    responses_xml.append(build_response_xml(
                        f"/webdav/Home/{fol_name}/",
                        fol_name,
                        is_collection=True,
                        modified=fol.get("modified_date")
                    ))

                # Files in Home root
                files = list(database.Files.find({
                    "file_type": {"$ne": "folder"},
                    "file_path": {"$in": ["/Home", "/"]},
                    "owner_id": owner_id,
                    "trashed": {"$ne": True}
                }))
                for f in files:
                    fname = f.get("file_name", "File")
                    mimetype, _ = mimetypes.guess_type(fname)
                    responses_xml.append(build_response_xml(
                        f"/webdav/Home/{fname}",
                        fname,
                        is_collection=False,
                        size=f.get("file_size", 0),
                        mime_type=mimetype or "application/octet-stream",
                        modified=f.get("modified_date")
                    ))

            elif top_name == "Telegram Inbox":
                files = list(database.Files.find({
                    "file_path": "/Telegram Inbox",
                    "owner_id": owner_id,
                    "trashed": {"$ne": True}
                }))
                for f in files:
                    fname = f.get("file_name", "File")
                    mimetype, _ = mimetypes.guess_type(fname)
                    responses_xml.append(build_response_xml(
                        f"/webdav/Telegram Inbox/{fname}",
                        fname,
                        is_collection=False,
                        size=f.get("file_size", 0),
                        mime_type=mimetype or "application/octet-stream",
                        modified=f.get("modified_date")
                    ))

            elif top_name == "Starred":
                items = list(database.Files.find({
                    "starred": True,
                    "owner_id": owner_id,
                    "trashed": {"$ne": True}
                }))
                for item in items:
                    iname = item.get("file_name", "Item")
                    is_fol = item.get("file_type") == "folder"
                    mimetype, _ = mimetypes.guess_type(iname)
                    responses_xml.append(build_response_xml(
                        f"/webdav/Starred/{iname}/" if is_fol else f"/webdav/Starred/{iname}",
                        iname,
                        is_collection=is_fol,
                        size=item.get("file_size", 0),
                        mime_type=mimetype or "application/octet-stream",
                        modified=item.get("modified_date")
                    ))

            elif top_name == "Trash":
                items = list(database.Files.find({
                    "trashed": True,
                    "owner_id": owner_id
                }))
                for item in items:
                    iname = item.get("file_name", "Item")
                    is_fol = item.get("file_type") == "folder"
                    mimetype, _ = mimetypes.guess_type(iname)
                    responses_xml.append(build_response_xml(
                        f"/webdav/Trash/{iname}/" if is_fol else f"/webdav/Trash/{iname}",
                        iname,
                        is_collection=is_fol,
                        size=item.get("file_size", 0),
                        mime_type=mimetype or "application/octet-stream",
                        modified=item.get("trashed_at") or item.get("modified_date")
                    ))

    # Case C: Subfolders and Files inside Home or other sections
    else:
        top_name = segments[0]
        if top_name == "Home":
            # Determine path in database
            target_subpath = "/" + "/".join(segments)
            parent_db_path = "/" + "/".join(segments[:-1])
            target_name = segments[-1]

            # 1. Check if target is a folder
            folder_doc = database.Files.find_one({
                "file_type": "folder",
                "file_name": target_name,
                "file_path": parent_db_path if parent_db_path != "/Home" else {"$in": ["/Home", "/"]},
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            })

            if folder_doc:
                # Target is a folder
                responses_xml.append(build_response_xml(
                    f"/webdav/{'/'.join(segments)}/",
                    target_name,
                    is_collection=True,
                    modified=folder_doc.get("modified_date")
                ))

                if depth == "1":
                    # List subfolders inside this folder
                    subfolders = list(database.Files.find({
                        "file_type": "folder",
                        "file_path": target_subpath,
                        "owner_id": owner_id,
                        "trashed": {"$ne": True}
                    }))
                    for sf in subfolders:
                        sf_name = sf.get("file_name", "Folder")
                        responses_xml.append(build_response_xml(
                            f"/webdav/{'/'.join(segments)}/{sf_name}/",
                            sf_name,
                            is_collection=True,
                            modified=sf.get("modified_date")
                        ))

                    # List files inside this folder
                    subfiles = list(database.Files.find({
                        "file_type": {"$ne": "folder"},
                        "file_path": target_subpath,
                        "owner_id": owner_id,
                        "trashed": {"$ne": True}
                    }))
                    for sf in subfiles:
                        sf_name = sf.get("file_name", "File")
                        mimetype, _ = mimetypes.guess_type(sf_name)
                        responses_xml.append(build_response_xml(
                            f"/webdav/{'/'.join(segments)}/{sf_name}",
                            sf_name,
                            is_collection=False,
                            size=sf.get("file_size", 0),
                            mime_type=mimetype or "application/octet-stream",
                            modified=sf.get("modified_date")
                        ))
            else:
                # 2. Check if target is a file
                file_doc = database.Files.find_one({
                    "file_type": {"$ne": "folder"},
                    "file_name": target_name,
                    "file_path": parent_db_path if parent_db_path != "/Home" else {"$in": ["/Home", "/"]},
                    "owner_id": owner_id,
                    "trashed": {"$ne": True}
                })
                if not file_doc:
                    raise HTTPException(status_code=404, detail="Item not found")

                mimetype, _ = mimetypes.guess_type(target_name)
                responses_xml.append(build_response_xml(
                    f"/webdav/{'/'.join(segments)}",
                    target_name,
                    is_collection=False,
                    size=file_doc.get("file_size", 0),
                    mime_type=mimetype or "application/octet-stream",
                    modified=file_doc.get("modified_date")
                ))

        elif top_name == "Telegram Inbox":
            fname = segments[-1]
            file_doc = database.Files.find_one({
                "file_path": "/Telegram Inbox",
                "file_name": fname,
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            })
            if not file_doc:
                raise HTTPException(status_code=404, detail="File not found")
            mimetype, _ = mimetypes.guess_type(fname)
            responses_xml.append(build_response_xml(
                f"/webdav/Telegram Inbox/{fname}",
                fname,
                is_collection=False,
                size=file_doc.get("file_size", 0),
                mime_type=mimetype or "application/octet-stream",
                modified=file_doc.get("modified_date")
            ))
        else:
            raise HTTPException(status_code=404, detail="Path not found")

    full_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
{chr(10).join(responses_xml)}
</D:multistatus>"""

    return Response(
        content=full_xml,
        status_code=207,
        media_type="application/xml; charset=utf-8"
    )


async def handle_get_head(request: Request, segments: List[str], owner_id: str, is_head: bool = False) -> Response:
    """Handle WebDAV file download and Range-based media streaming."""
    if len(segments) < 2:
        raise HTTPException(status_code=400, detail="Cannot download a directory")

    top_name = segments[0]
    target_name = segments[-1]

    file_doc = None
    if top_name == "Home":
        parent_db_path = "/" + "/".join(segments[:-1])
        file_doc = database.Files.find_one({
            "file_type": {"$ne": "folder"},
            "file_name": target_name,
            "file_path": parent_db_path if parent_db_path != "/Home" else {"$in": ["/Home", "/"]},
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })
    elif top_name == "Telegram Inbox":
        file_doc = database.Files.find_one({
            "file_path": "/Telegram Inbox",
            "file_name": target_name,
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })
    elif top_name == "Starred":
        file_doc = database.Files.find_one({
            "file_name": target_name,
            "starred": True,
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })
    elif top_name == "Trash":
        file_doc = database.Files.find_one({
            "file_name": target_name,
            "trashed": True,
            "owner_id": owner_id
        })

    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")

    file_size = file_doc.get("file_size", 0)
    chat_id = file_doc.get("chat_id")
    message_id = file_doc.get("message_id")
    parts = file_doc.get("parts")
    mimetype, _ = mimetypes.guess_type(target_name)
    content_type = mimetype or "application/octet-stream"

    if is_head:
        return Response(
            status_code=200,
            headers={
                "Content-Length": str(file_size),
                "Content-Type": content_type,
                "Accept-Ranges": "bytes",
                "Last-Modified": format_dav_date(file_doc.get("modified_date")),
            }
        )

    # GET stream
    bot_manager = getattr(request.app.state, "bot_manager", None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot worker pool not ready")

    client = bot_manager.get_least_busy_client()
    if not client:
        raise HTTPException(status_code=503, detail="No active bot client")

    range_header = request.headers.get("Range", "")
    from_bytes, until_bytes = parse_range_header(range_header, file_size)
    req_length = until_bytes - from_bytes + 1

    # Prepare streaming parts
    if not parts:
        parts_list = [{
            "part_index": 1,
            "chat_id": chat_id,
            "message_id": message_id,
            "start_byte": 0,
            "end_byte": file_size - 1,
            "part_size": file_size,
        }]
    else:
        parts_list = parts

    parts_to_stream = []
    for p in parts_list:
        p_start = p.get("start_byte", 0)
        p_end = p.get("end_byte", p_start + p.get("part_size", 0) - 1)
        if p_end < from_bytes or p_start > until_bytes:
            continue

        overlap_start = max(from_bytes, p_start)
        overlap_end = min(until_bytes, p_end)

        parts_to_stream.append({
            "chat_id": p.get("chat_id", chat_id),
            "message_id": p.get("message_id", message_id),
            "part_from_byte": overlap_start - p_start,
            "part_until_byte": overlap_end - p_start,
            "part_index": p.get("part_index", 1),
        })

    tg_connect = ByteStreamer(client)
    active_clients = [c for c in getattr(bot_manager, "client_list", []) if getattr(c, "is_connected", False)] or [client]

    body = tg_connect.yield_parts(
        parts_to_stream=parts_to_stream,
        chunk_size=1024 * 1024,
        client_list=active_clients,
    )

    headers = {
        "Content-Length": str(req_length),
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Last-Modified": format_dav_date(file_doc.get("modified_date")),
    }
    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

    return StreamingResponse(
        body,
        status_code=206 if range_header else 200,
        headers=headers
    )


async def handle_put(request: Request, segments: List[str], owner_id: str, default_chat_id: Optional[int]) -> Response:
    """Handle WebDAV file upload via HTTP PUT."""
    if len(segments) < 2:
        raise HTTPException(status_code=400, detail="Cannot upload to root directly")

    top_name = segments[0]
    file_name = segments[-1]

    if top_name == "Home":
        target_folder_path = "/" + "/".join(segments[:-1])
    elif top_name == "Telegram Inbox":
        target_folder_path = "/Telegram Inbox"
    else:
        raise HTTPException(status_code=403, detail=f"Cannot upload directly to {top_name}")

    bot_manager = getattr(request.app.state, "bot_manager", None)
    if not bot_manager:
        raise HTTPException(status_code=503, detail="Bot worker pool not ready")

    client = bot_manager.get_least_busy_client()
    if not client:
        raise HTTPException(status_code=503, detail="No active bot client")

    if not default_chat_id:
        raise HTTPException(status_code=400, detail="No valid storage channel configured for uploads")

    tg_files_dir = os.path.join(os.getcwd(), "tg_files")
    os.makedirs(tg_files_dir, exist_ok=True)
    upload_id = secrets.token_hex(8)
    tmp_file = os.path.join(tg_files_dir, f"dav_{upload_id}.tmp")

    try:
        # Stream request body to temp file
        async with aiofiles.open(tmp_file, "wb") as f:
            async for chunk in request.stream():
                await f.write(chunk)

        total_size = os.path.getsize(tmp_file)
        logger.info(f"[WEBDAV_PUT] Received file '{file_name}' ({total_size} bytes) for '{target_folder_path}'")

        # Telegram bot upload
        msg = await client.send_document(
            chat_id=default_chat_id,
            document=tmp_file,
            file_name=file_name,
            caption=f"WebDAV upload: {file_name}"
        )

        media = msg.document or msg.video or msg.audio or msg.photo
        file_unique_id = getattr(media, "file_unique_id", f"dav_{msg.id}")
        thumbnail = media.thumbs[0].file_id if (hasattr(media, "thumbs") and media.thumbs) else None

        # Categorize file type
        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        file_type = "document"
        if ext in ["mp4", "mkv", "avi", "mov", "webm"]:
            file_type = "video"
        elif ext in ["jpg", "jpeg", "png", "gif", "webp"]:
            file_type = "photo"
        elif ext in ["mp3", "wav", "ogg", "flac", "m4a"]:
            file_type = "audio"

        # Check if already exists; if so, replace
        existing = database.Files.find_one({
            "file_name": file_name,
            "file_path": target_folder_path,
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })
        if existing:
            database.Files.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "chat_id": default_chat_id,
                    "message_id": msg.id,
                    "file_unique_id": file_unique_id,
                    "file_size": total_size,
                    "thumbnail": thumbnail,
                    "file_type": file_type,
                    "modified_date": datetime.utcnow().isoformat()
                }}
            )
        else:
            database.Files.add_file(
                chat_id=default_chat_id,
                message_id=msg.id,
                thumbnail=thumbnail,
                file_type=file_type,
                file_unique_id=file_unique_id,
                file_size=total_size,
                file_name=file_name,
                file_caption="",
                file_path=target_folder_path,
                owner_id=owner_id
            )

        return Response(status_code=201)
    finally:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


async def handle_mkcol(request: Request, segments: List[str], owner_id: str) -> Response:
    """Handle WebDAV directory creation via MKCOL."""
    if len(segments) < 2:
        raise HTTPException(status_code=403, detail="Cannot create folders in root")

    if segments[0] != "Home":
        raise HTTPException(status_code=403, detail="Folders can only be created inside Home")

    new_folder_name = segments[-1]
    parent_folder_path = "/" + "/".join(segments[:-1])

    success = database.Files.add_folder(
        folder_name=new_folder_name,
        folder_path=parent_folder_path,
        owner_id=owner_id
    )
    if not success:
        return Response(status_code=200)  # Folder already exists

    return Response(status_code=201)


async def handle_delete(request: Request, segments: List[str], owner_id: str) -> Response:
    """Handle WebDAV item deletion via DELETE."""
    if len(segments) < 2:
        raise HTTPException(status_code=403, detail="Cannot delete top-level folders")

    top_name = segments[0]
    target_name = segments[-1]

    if top_name == "Trash":
        # Permanently purge from database
        item = database.Files.find_one({"file_name": target_name, "trashed": True, "owner_id": owner_id})
        if item:
            database.Files.delete_one({"_id": item["_id"]})
        return Response(status_code=204)

    # For Home or Telegram Inbox: Move to Trash
    parent_path = "/" + "/".join(segments[:-1])
    item = database.Files.find_one({
        "file_name": target_name,
        "file_path": parent_path if parent_path != "/Home" else {"$in": ["/Home", "/"]},
        "owner_id": owner_id,
        "trashed": {"$ne": True}
    })
    if not item and top_name == "Telegram Inbox":
        item = database.Files.find_one({
            "file_name": target_name,
            "file_path": "/Telegram Inbox",
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })

    if item:
        database.Files.move_to_trash(str(item["_id"]), owner_id)
        return Response(status_code=204)

    raise HTTPException(status_code=404, detail="Item not found")


async def handle_move(request: Request, segments: List[str], owner_id: str) -> Response:
    """Handle WebDAV file/folder renaming and movement via MOVE."""
    dest_header = request.headers.get("Destination", "")
    if not dest_header:
        raise HTTPException(status_code=400, detail="Missing Destination header")

    dest_url = urllib.parse.urlparse(dest_header)
    dest_segments = parse_webdav_path(dest_url.path)

    if len(segments) < 2 or len(dest_segments) < 2:
        raise HTTPException(status_code=403, detail="Cannot move top-level virtual directories")

    source_top = segments[0]
    source_name = segments[-1]
    dest_top = dest_segments[0]
    dest_name = dest_segments[-1]

    # Resolve source document
    source_parent = "/" + "/".join(segments[:-1])
    source_doc = database.Files.find_one({
        "file_name": source_name,
        "file_path": source_parent if source_parent != "/Home" else {"$in": ["/Home", "/"]},
        "owner_id": owner_id,
        "trashed": {"$ne": True}
    })
    if not source_doc and source_top == "Telegram Inbox":
        source_doc = database.Files.find_one({
            "file_name": source_name,
            "file_path": "/Telegram Inbox",
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })

    if not source_doc:
        raise HTTPException(status_code=404, detail="Source item not found")

    dest_parent_path = "/" + "/".join(dest_segments[:-1])
    if dest_top == "Telegram Inbox":
        dest_parent_path = "/Telegram Inbox"

    # If it's a folder rename/move:
    if source_doc.get("file_type") == "folder":
        old_folder_path = "/" + "/".join(segments)
        new_folder_path = "/" + "/".join(dest_segments)

        database.Files.update_one(
            {"_id": source_doc["_id"]},
            {"$set": {
                "file_name": dest_name,
                "file_path": dest_parent_path,
                "modified_date": datetime.utcnow().isoformat()
            }}
        )

        # Recursively update all child files and subfolders
        database.Files.update_many(
            {"file_path": old_folder_path, "owner_id": owner_id},
            {"$set": {"file_path": new_folder_path}}
        )
        database.Files.update_many(
            {"file_path": {"$regex": f"^{old_folder_path}/"}, "owner_id": owner_id},
            [{"$set": {"file_path": {"$replaceOne": {"input": "$file_path", "find": old_folder_path, "replacement": new_folder_path}}}}]
        )
    else:
        # File move or rename
        database.Files.update_one(
            {"_id": source_doc["_id"]},
            {"$set": {
                "file_name": dest_name,
                "file_path": dest_parent_path,
                "modified_date": datetime.utcnow().isoformat()
            }}
        )

    logger.info(f"[WEBDAV_MOVE] Moved '{source_name}' to '{dest_parent_path}/{dest_name}'")
    return Response(status_code=201)


async def handle_copy(request: Request, segments: List[str], owner_id: str) -> Response:
    """Handle WebDAV file copy via COPY."""
    dest_header = request.headers.get("Destination", "")
    if not dest_header:
        raise HTTPException(status_code=400, detail="Missing Destination header")

    dest_url = urllib.parse.urlparse(dest_header)
    dest_segments = parse_webdav_path(dest_url.path)
    if len(dest_segments) < 2:
        raise HTTPException(status_code=403, detail="Invalid destination path")

    source_name = segments[-1]
    source_parent = "/" + "/".join(segments[:-1])
    dest_name = dest_segments[-1]
    dest_parent = "/" + "/".join(dest_segments[:-1])

    source_doc = database.Files.find_one({
        "file_name": source_name,
        "file_path": source_parent if source_parent != "/Home" else {"$in": ["/Home", "/"]},
        "owner_id": owner_id,
        "trashed": {"$ne": True}
    })
    if not source_doc:
        raise HTTPException(status_code=404, detail="Source file not found")

    new_doc = dict(source_doc)
    new_doc.pop("_id", None)
    new_doc["file_name"] = dest_name
    new_doc["file_path"] = dest_parent
    new_doc["modified_date"] = datetime.utcnow().isoformat()

    database.Files.insert_one(new_doc)
    return Response(status_code=201)


def handle_lock(request: Request) -> Response:
    """Satisfy WebDAV LOCK requests from RaiDrive, Windows Explorer, and Microsoft Office."""
    lock_token = f"urn:uuid:{secrets.token_hex(16)}"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<D:prop xmlns:D="DAV:">
  <D:lockdiscovery>
    <D:activelock>
      <D:locktype><D:write/></D:locktype>
      <D:lockscope><D:exclusive/></D:lockscope>
      <D:depth>0</D:depth>
      <D:timeout>Second-3600</D:timeout>
      <D:locktoken>
        <D:href>{lock_token}</D:href>
      </D:locktoken>
      <D:lockroot>
        <D:href>{request.url.path}</D:href>
      </D:lockroot>
    </D:activelock>
  </D:lockdiscovery>
</D:prop>"""
    return Response(
        content=xml,
        status_code=200,
        media_type="application/xml; charset=utf-8",
        headers={"Lock-Token": f"<{lock_token}>"}
    )


def handle_proppatch(request: Request) -> Response:
    """Acknowledge PROPPATCH attributes."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>{request.url.path}</D:href>
    <D:propstat>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"""
    return Response(
        content=xml,
        status_code=207,
        media_type="application/xml; charset=utf-8"
    )
