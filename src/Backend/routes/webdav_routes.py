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
from fastapi.responses import StreamingResponse, HTMLResponse
from pyrogram import Client
from bson import ObjectId

from src.Database import database
from src.Config import OWNER, LOGS, MOVIE, GROUP, FILTER_CHAT
import re
import asyncio
import glob
from ..security.credentials import verify_credentials
from ..modules.byte_streamer import ByteStreamer
from ..modules.streaming_utils import parse_range_header, resolve_mime_type
from ..modules.pipeline_uploader import upload_part_task
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
                    "trashed": {"$ne": True},
                    "is_vault": {"$ne": True}
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
                    "owner_id": owner_id,
                    "is_vault": {"$ne": True}
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


def format_size(size_bytes: Optional[int]) -> str:
    """Format bytes into human-readable size string."""
    if not size_bytes or size_bytes <= 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    size = float(size_bytes)
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024
        unit_idx += 1
    return f"{size:.1f} {units[unit_idx]}" if unit_idx > 0 else f"{int(size)} B"


def format_readable_date(dt_val: Optional[Any]) -> str:
    """Format datetime string or object into human-readable format."""
    if not dt_val:
        return "-"
    try:
        if isinstance(dt_val, datetime):
            return dt_val.strftime("%Y-%m-%d %H:%M")
        clean = str(dt_val).replace("Z", "").split(".")[0].replace("T", " ")
        return clean
    except Exception:
        return str(dt_val)


def get_icon(is_dir: bool, name: str) -> str:
    """Return appropriate emoji icon based on type."""
    if is_dir:
        return "📁"
    ext = os.path.splitext(name)[1].lower()
    if ext in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"]:
        return "🎬"
    elif ext in [".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac"]:
        return "🎵"
    elif ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"]:
        return "🖼️"
    elif ext in [".zip", ".rar", ".7z", ".tar", ".gz"]:
        return "📦"
    elif ext in [".pdf", ".doc", ".docx", ".txt", ".epub"]:
        return "📄"
    return "📎"


def get_directory_items(segments: List[str], owner_id: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Check if the target path is a directory/collection.
    Returns (is_directory, items_list).
    """
    # 1. Root /webdav/
    if len(segments) == 0:
        items = [
            {"name": "Home", "is_dir": True, "size": 0, "modified": None, "href": "/webdav/Home/"},
            {"name": "Telegram Inbox", "is_dir": True, "size": 0, "modified": None, "href": "/webdav/Telegram%20Inbox/"},
            {"name": "Starred", "is_dir": True, "size": 0, "modified": None, "href": "/webdav/Starred/"},
            {"name": "Trash", "is_dir": True, "size": 0, "modified": None, "href": "/webdav/Trash/"},
        ]
        return True, items

    # 2. Virtual top level
    if len(segments) == 1 and segments[0] in VIRTUAL_TOP_LEVEL:
        top_name = segments[0]
        items = []
        if top_name == "Home":
            folders = list(database.Files.find({
                "file_type": "folder",
                "file_path": {"$in": ["/Home", "/"]},
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            }))
            for fol in folders:
                fname = fol.get("file_name", "Folder")
                items.append({
                    "name": fname,
                    "is_dir": True,
                    "size": 0,
                    "modified": fol.get("modified_date"),
                    "href": f"/webdav/Home/{urllib.parse.quote(fname, safe='')}/"
                })

            files = list(database.Files.find({
                "file_type": {"$ne": "folder"},
                "file_path": {"$in": ["/Home", "/"]},
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            }))
            for f in files:
                fname = f.get("file_name", "File")
                items.append({
                    "name": fname,
                    "is_dir": False,
                    "size": f.get("file_size", 0),
                    "modified": f.get("modified_date"),
                    "href": f"/webdav/Home/{urllib.parse.quote(fname, safe='')}"
                })

        elif top_name == "Telegram Inbox":
            files = list(database.Files.find({
                "file_path": "/Telegram Inbox",
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            }))
            for f in files:
                fname = f.get("file_name", "File")
                items.append({
                    "name": fname,
                    "is_dir": False,
                    "size": f.get("file_size", 0),
                    "modified": f.get("modified_date"),
                    "href": f"/webdav/Telegram%20Inbox/{urllib.parse.quote(fname, safe='')}"
                })

        elif top_name == "Starred":
            items_cursor = list(database.Files.find({
                "starred": True,
                "owner_id": owner_id,
                "trashed": {"$ne": True},
                "is_vault": {"$ne": True}
            }))
            for it in items_cursor:
                fname = it.get("file_name", "Item")
                is_fol = it.get("file_type") == "folder"
                href = f"/webdav/Starred/{urllib.parse.quote(fname, safe='')}/" if is_fol else f"/webdav/Starred/{urllib.parse.quote(fname, safe='')}"
                items.append({
                    "name": fname,
                    "is_dir": is_fol,
                    "size": it.get("file_size", 0),
                    "modified": it.get("modified_date"),
                    "href": href
                })

        elif top_name == "Trash":
            items_cursor = list(database.Files.find({
                "trashed": True,
                "owner_id": owner_id,
                "is_vault": {"$ne": True}
            }))
            for it in items_cursor:
                fname = it.get("file_name", "Item")
                is_fol = it.get("file_type") == "folder"
                href = f"/webdav/Trash/{urllib.parse.quote(fname, safe='')}/" if is_fol else f"/webdav/Trash/{urllib.parse.quote(fname, safe='')}"
                items.append({
                    "name": fname,
                    "is_dir": is_fol,
                    "size": it.get("file_size", 0),
                    "modified": it.get("trashed_at") or it.get("modified_date"),
                    "href": href
                })

        return True, items

    # 3. Subfolder in Home
    if len(segments) >= 2 and segments[0] == "Home":
        target_subpath = "/" + "/".join(segments)
        parent_db_path = "/" + "/".join(segments[:-1])
        target_name = segments[-1]

        folder_doc = database.Files.find_one({
            "file_type": "folder",
            "file_name": target_name,
            "file_path": parent_db_path if parent_db_path != "/Home" else {"$in": ["/Home", "/"]},
            "owner_id": owner_id,
            "trashed": {"$ne": True}
        })

        if folder_doc:
            items = []
            base_url = "/webdav/" + "/".join(urllib.parse.quote(s, safe="") for s in segments)
            subfolders = list(database.Files.find({
                "file_type": "folder",
                "file_path": target_subpath,
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            }))
            for sf in subfolders:
                sf_name = sf.get("file_name", "Folder")
                items.append({
                    "name": sf_name,
                    "is_dir": True,
                    "size": 0,
                    "modified": sf.get("modified_date"),
                    "href": f"{base_url}/{urllib.parse.quote(sf_name, safe='')}/"
                })

            subfiles = list(database.Files.find({
                "file_type": {"$ne": "folder"},
                "file_path": target_subpath,
                "owner_id": owner_id,
                "trashed": {"$ne": True}
            }))
            for sf in subfiles:
                sf_name = sf.get("file_name", "File")
                items.append({
                    "name": sf_name,
                    "is_dir": False,
                    "size": sf.get("file_size", 0),
                    "modified": sf.get("modified_date"),
                    "href": f"{base_url}/{urllib.parse.quote(sf_name, safe='')}"
                })

            return True, items

    return False, []


def render_webdav_html(segments: List[str], items: List[Dict[str, Any]]) -> str:
    """Render a responsive HTML directory listing for browsers."""
    crumbs = ['<a href="/webdav/">webdav</a>']
    accum = []
    for s in segments:
        accum.append(s)
        sub_href = "/webdav/" + "/".join(urllib.parse.quote(seg, safe="") for seg in accum) + "/"
        crumbs.append(f'<a href="{sub_href}">{xml_escape(s)}</a>')
    breadcrumb_html = " / ".join(crumbs)

    parent_row = ""
    if len(segments) > 0:
        if len(segments) == 1:
            parent_href = "/webdav/"
        else:
            parent_href = "/webdav/" + "/".join(urllib.parse.quote(seg, safe="") for seg in segments[:-1]) + "/"
        parent_row = f'''
        <tr class="parent-row">
          <td colspan="4">
            <a href="{parent_href}" class="item-link parent-link">
              <span class="icon">📁</span>
              <span class="name">.. (Parent Directory)</span>
            </a>
          </td>
        </tr>
        '''

    sorted_items = sorted(items, key=lambda x: (not x.get("is_dir", False), x.get("name", "").lower()))

    rows_html = []
    for it in sorted_items:
        name = it.get("name", "")
        escaped_name = xml_escape(name)
        is_dir = it.get("is_dir", False)
        href = it.get("href", "#")
        size_str = format_size(it.get("size"))
        date_str = format_readable_date(it.get("modified"))
        icon = get_icon(is_dir, name)

        action_btn = ""
        if not is_dir:
            action_btn = f'<a href="{href}" download class="action-btn" title="Download">⬇️ Download</a>'
        else:
            action_btn = f'<a href="{href}" class="action-btn folder-btn" title="Open Folder">📂 Open</a>'

        rows_html.append(f'''
        <tr class="item-row" data-name="{escaped_name}">
          <td>
            <a href="{href}" class="item-link {'is-dir' if is_dir else 'is-file'}">
              <span class="icon">{icon}</span>
              <span class="name">{escaped_name}{'/' if is_dir else ''}</span>
            </a>
          </td>
          <td class="size-col">{size_str}</td>
          <td class="date-col">{date_str}</td>
          <td class="action-col">{action_btn}</td>
        </tr>
        ''')

    empty_state = ""
    if not rows_html:
        empty_state = '''
        <tr>
          <td colspan="4" class="empty-state">
            <div style="padding: 30px; text-align: center; color: #94a3b8;">
              <span style="font-size: 32px; display: block; margin-bottom: 8px;">📭</span>
              This directory is empty.
            </div>
          </td>
        </tr>
        '''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WebDAV - /{'/'.join(segments)}</title>
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: #0b0f19;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      padding: 24px;
    }}
    .container {{
      max-width: 1100px;
      width: 100%;
      margin: 0 auto;
      background: #131b2e;
      border: 1px solid #243049;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }}
    header {{
      padding: 20px 24px;
      background: #182238;
      border-bottom: 1px solid #243049;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }}
    .title-group {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .logo-badge {{
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      font-weight: bold;
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 13px;
      letter-spacing: 0.5px;
      border: 1px solid rgba(56, 189, 248, 0.25);
    }}
    .header-links {{
      display: flex;
      gap: 10px;
    }}
    .nav-btn {{
      background: #243049;
      color: #cbd5e1;
      text-decoration: none;
      padding: 7px 14px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      transition: all 0.2s;
    }}
    .nav-btn:hover {{
      background: #334155;
      color: #fff;
    }}
    .primary-btn {{
      background: #0284c7;
      color: #fff;
    }}
    .primary-btn:hover {{
      background: #0369a1;
    }}
    .breadcrumbs-bar {{
      padding: 14px 24px;
      background: #111827;
      border-bottom: 1px solid #243049;
      font-size: 14px;
      color: #94a3b8;
      overflow-x: auto;
      white-space: nowrap;
    }}
    .breadcrumbs-bar a {{
      color: #38bdf8;
      text-decoration: none;
      font-weight: 500;
    }}
    .breadcrumbs-bar a:hover {{
      text-decoration: underline;
    }}
    .toolbar {{
      padding: 14px 24px;
      border-bottom: 1px solid #243049;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }}
    .search-input {{
      background: #0b0f19;
      border: 1px solid #243049;
      color: #f1f5f9;
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      width: 100%;
      max-width: 320px;
      outline: none;
      transition: border-color 0.2s;
    }}
    .search-input:focus {{
      border-color: #38bdf8;
    }}
    .count-badge {{
      font-size: 12px;
      color: #94a3b8;
    }}
    .table-container {{
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }}
    th {{
      padding: 12px 20px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #94a3b8;
      border-bottom: 1px solid #243049;
      background: #111827;
    }}
    td {{
      padding: 12px 20px;
      font-size: 14px;
      border-bottom: 1px solid #1e293b;
      vertical-align: middle;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    tr:hover td {{
      background: rgba(36, 48, 73, 0.4);
    }}
    .item-link {{
      color: #e2e8f0;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 500;
      word-break: break-word;
    }}
    .item-link:hover {{
      color: #38bdf8;
    }}
    .is-dir .name {{
      color: #67e8f9;
      font-weight: 600;
    }}
    .parent-link {{
      color: #94a3b8;
    }}
    .icon {{
      font-size: 18px;
      flex-shrink: 0;
    }}
    .size-col {{
      color: #94a3b8;
      font-family: monospace;
      font-size: 13px;
      white-space: nowrap;
    }}
    .date-col {{
      color: #64748b;
      font-size: 13px;
      white-space: nowrap;
    }}
    .action-col {{
      text-align: right;
      white-space: nowrap;
    }}
    .action-btn {{
      display: inline-block;
      padding: 4px 10px;
      font-size: 12px;
      border-radius: 6px;
      background: #1e293b;
      color: #94a3b8;
      text-decoration: none;
      transition: all 0.15s;
    }}
    .action-btn:hover {{
      background: #0284c7;
      color: #fff;
    }}
    .folder-btn:hover {{
      background: #0d9488;
      color: #fff;
    }}
    footer {{
      padding: 16px 24px;
      background: #0f172a;
      border-top: 1px solid #243049;
      font-size: 12px;
      color: #64748b;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }}
    footer a {{
      color: #38bdf8;
      text-decoration: none;
    }}
    @media (max-width: 640px) {{
      body {{
        padding: 10px;
      }}
      th:nth-child(3), td:nth-child(3) {{
        display: none;
      }}
      .search-input {{
        max-width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="title-group">
        <span class="logo-badge">WEBDAV LIVE</span>
        <h2 style="font-size: 17px; font-weight: 700;">Telegram WebDAV Server</h2>
      </div>
      <div class="header-links">
        <a href="/" class="nav-btn primary-btn">Go to Main Web App ↗</a>
      </div>
    </header>

    <div class="breadcrumbs-bar">
      📍 Path: {breadcrumb_html}
    </div>

    <div class="toolbar">
      <input type="text" id="searchInput" class="search-input" placeholder="Search / filter files in this folder..." oninput="filterFiles()" />
      <span class="count-badge" id="itemCount">{len(items)} items</span>
    </div>

    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th style="width: 130px;">Size</th>
            <th style="width: 170px;">Last Modified</th>
            <th style="width: 110px; text-align: right;">Action</th>
          </tr>
        </thead>
        <tbody id="filesTableBody">
          {parent_row}
          {''.join(rows_html)}
          {empty_state}
        </tbody>
      </table>
    </div>

    <footer>
      <span>💡 <strong>Mount Info:</strong> Mount this URL in Windows using <strong>RaiDrive</strong> or in Android using <strong>MiXplorer</strong>.</span>
      <span>RFC 4918 WebDAV Server</span>
    </footer>
  </div>

  <script>
    function filterFiles() {{
      const q = document.getElementById('searchInput').value.toLowerCase();
      const rows = document.querySelectorAll('.item-row');
      let visible = 0;
      rows.forEach(r => {{
        const name = r.getAttribute('data-name').toLowerCase();
        if (name.includes(q)) {{
          r.style.display = '';
          visible++;
        }} else {{
          r.style.display = 'none';
        }}
      }});
      document.getElementById('itemCount').textContent = visible + ' items';
    }}
  </script>
</body>
</html>'''
    return html


async def handle_get_head(request: Request, segments: List[str], owner_id: str, is_head: bool = False) -> Response:
    """Handle WebDAV file download, Range-based media streaming, or HTML directory browsing."""
    is_dir, dir_items = get_directory_items(segments, owner_id)
    if is_dir:
        if is_head:
            return Response(status_code=200, media_type="text/html; charset=utf-8")
        return HTMLResponse(content=render_webdav_html(segments, dir_items), status_code=200)

    if len(segments) < 2:
        raise HTTPException(status_code=404, detail="File or directory not found")

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
    content_type = resolve_mime_type(target_name, explicit_mime=file_doc.get("mime_type"), is_watch=True)

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
    try:
        from_bytes, until_bytes = parse_range_header(range_header, file_size)
    except ValueError:
        return Response(
            status_code=416,
            headers={
                "Content-Range": f"bytes */{file_size}",
                "Accept-Ranges": "bytes",
            }
        )

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

    encoded_filename = urllib.parse.quote(target_name)
    ascii_fallback = re.sub(r'[^\x20-\x7E]', '_', target_name).replace('"', '_')
    headers = {
        "Content-Length": str(req_length),
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Last-Modified": format_dav_date(file_doc.get("modified_date")),
        "Content-Disposition": f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}',
        "X-Content-Type-Options": "nosniff",
        "Access-Control-Allow-Origin": "*",
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
    PART_MAX_SIZE = 1950 * 1024 * 1024  # 1950 MB Telegram Bot file limit
    upload_id = secrets.token_hex(8)
    part_index = 1
    current_part_file = os.path.join(tg_files_dir, f"dav_{upload_id}_part_{part_index}.tmp")
    current_part_written = 0
    total_written = 0
    upload_tasks: List[asyncio.Task] = []
    disk_semaphore = asyncio.Semaphore(2)  # Max 2 parts buffered on VM disk (~3.9 GB cap)
    await disk_semaphore.acquire()  # Acquire buffer slot for Part 1

    # Categorize file type upfront
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""
    file_type = "document"
    if ext in ["mp4", "mkv", "avi", "mov", "webm", "ts", "3gp"]:
        file_type = "video"
    elif ext in ["jpg", "jpeg", "png", "gif", "webp"]:
        file_type = "photo"
    elif ext in ["mp3", "wav", "ogg", "flac", "m4a"]:
        file_type = "audio"

    part_f = await aiofiles.open(current_part_file, "wb")
    try:
        async for chunk in request.stream():
            chunk_len = len(chunk)
            if current_part_written + chunk_len > PART_MAX_SIZE:
                split_point = PART_MAX_SIZE - current_part_written
                if split_point > 0:
                    await part_f.write(chunk[:split_point])
                    current_part_written += split_point
                    total_written += split_point

                await part_f.close()

                # Dispatch this part to Telegram in background (NON-BLOCKING!)
                # While Telegram uploads this part, the HTTP loop immediately starts receiving the next part!
                logger.info(
                    f"[WEBDAV_PUT] Part {part_index} reached {current_part_written} bytes. "
                    f"Dispatching to background Telegram uploader for '{file_name}'..."
                )
                p_task = asyncio.create_task(
                    upload_part_task(
                        part_file_path=current_part_file,
                        part_index=part_index,
                        file_name=file_name,
                        start_byte=total_written - current_part_written,
                        part_size=current_part_written,
                        chat_id=default_chat_id,
                        bot_manager=bot_manager,
                        fallback_client=client,
                        caption=f"{file_name} (Part {part_index})",
                        semaphore=disk_semaphore,
                        is_single_part=False,
                        file_type=file_type
                    )
                )
                upload_tasks.append(p_task)

                # Acquire buffer slot for next part (applies backpressure if 2 parts on disk)
                await disk_semaphore.acquire()

                # Immediately start receiving next part without waiting for Telegram upload!
                part_index += 1
                current_part_file = os.path.join(tg_files_dir, f"dav_{upload_id}_part_{part_index}.tmp")
                part_f = await aiofiles.open(current_part_file, "wb")
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

        if total_written == 0:
            disk_semaphore.release()
            if os.path.exists(current_part_file):
                os.remove(current_part_file)
            raise HTTPException(status_code=400, detail="Cannot upload empty files")

        # Case 1: Single-part file (<= 1950MB)
        if len(upload_tasks) == 0:
            logger.info(f"[WEBDAV_PUT] Uploading single part file '{file_name}' ({total_written} bytes)...")
            res = await upload_part_task(
                part_file_path=current_part_file,
                part_index=1,
                file_name=file_name,
                start_byte=0,
                part_size=total_written,
                chat_id=default_chat_id,
                bot_manager=bot_manager,
                fallback_client=client,
                caption=f"WebDAV upload: {file_name}",
                semaphore=disk_semaphore,
                is_single_part=True,
                file_type=file_type
            )

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
                        "message_id": res["message_id"],
                        "file_unique_id": res["file_unique_id"],
                        "file_size": total_written,
                        "thumbnail": res["thumbnail"],
                        "file_type": file_type,
                        "parts": None,
                        "modified_date": datetime.now(timezone.utc).isoformat()
                    }}
                )
            else:
                database.Files.add_file(
                    chat_id=default_chat_id,
                    message_id=res["message_id"],
                    thumbnail=res["thumbnail"],
                    file_type=file_type,
                    file_unique_id=res["file_unique_id"],
                    file_size=total_written,
                    file_name=file_name,
                    file_caption=f"WebDAV upload: {file_name}",
                    file_path=target_folder_path,
                    owner_id=owner_id
                )
        else:
            # Case 2: Multi-part file (> 1950MB)
            if current_part_written > 0:
                logger.info(f"[WEBDAV_PUT] Dispatching final part {part_index} ({current_part_written} bytes) for '{file_name}'...")
                final_task = asyncio.create_task(
                    upload_part_task(
                        part_file_path=current_part_file,
                        part_index=part_index,
                        file_name=file_name,
                        start_byte=total_written - current_part_written,
                        part_size=current_part_written,
                        chat_id=default_chat_id,
                        bot_manager=bot_manager,
                        fallback_client=client,
                        caption=f"{file_name} (Part {part_index}/{part_index})",
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

            # Wait for all background part uploads to complete
            logger.info(f"[WEBDAV_PUT] Awaiting completion of {len(upload_tasks)} background upload part(s) for '{file_name}'...")
            results = await asyncio.gather(*upload_tasks)
            results.sort(key=lambda x: x["part_index"])

            first_res = results[0]
            first_msg_id = first_res["message_id"]
            first_thumbnail = next((r["thumbnail"] for r in results if r.get("thumbnail")), None)
            first_media_unique_id = first_res["file_unique_id"]

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
                        "message_id": first_msg_id,
                        "file_unique_id": first_media_unique_id or f"dav_{first_msg_id}",
                        "file_size": total_written,
                        "thumbnail": first_thumbnail,
                        "file_type": file_type,
                        "parts": parts,
                        "modified_date": datetime.now(timezone.utc).isoformat()
                    }}
                )
            else:
                database.Files.insert_one({
                    "chat_id": default_chat_id,
                    "message_id": first_msg_id,
                    "thumbnail": first_thumbnail,
                    "file_type": file_type,
                    "file_unique_id": first_media_unique_id or f"dav_{first_msg_id}",
                    "file_size": total_written,
                    "file_name": file_name,
                    "file_caption": f"WebDAV upload: {file_name}",
                    "file_path": target_folder_path,
                    "owner_id": owner_id,
                    "parts": parts,
                    "modified_date": datetime.now(timezone.utc).isoformat(),
                    "starred": False,
                    "trashed": False
                })

        return Response(status_code=201)
    finally:
        if 'part_f' in locals() and not part_f.closed:
            await part_f.close()
        # Cancel any unfinished tasks if an exception aborted the request
        for t in upload_tasks:
            if not t.done():
                t.cancel()
        # Clean up any leftover temporary files for this upload session
        for tmp in glob.glob(os.path.join(tg_files_dir, f"dav_{upload_id}_part_*.tmp")):
            try:
                os.remove(tmp)
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
        # Permanently purge from database and delete Telegram messages
        item = database.Files.find_one({"file_name": target_name, "trashed": True, "owner_id": owner_id})
        if item:
            from collections import defaultdict
            messages_to_delete = defaultdict(set)
            
            def collect_file_messages(doc):
                c_id = doc.get("chat_id")
                m_id = doc.get("message_id")
                if c_id and m_id:
                    messages_to_delete[c_id].add(m_id)
                if doc.get("is_split"):
                    for part in doc.get("parts", []):
                        p_mid = part.get("message_id")
                        if p_mid and c_id:
                            messages_to_delete[c_id].add(p_mid)

            if item.get("file_type") == "folder":
                folder_name = item.get("file_name", "")
                orig_path = item.get("original_path") or item.get("file_path", "/")
                if orig_path in ["/", ""]:
                    f_full = f"/{folder_name}"
                else:
                    f_full = f"{orig_path.rstrip('/')}/{folder_name}"
                
                content_query = {
                    "$or": [
                        {"file_path": f_full},
                        {"file_path": {"$regex": f"^{re.escape(f_full)}/"}}
                    ],
                    "owner_id": owner_id
                }
                for child_doc in database.Files.find(content_query):
                    collect_file_messages(child_doc)
                database.Files.delete_many(content_query)
            else:
                collect_file_messages(item)
            
            database.Files.delete_one({"_id": item["_id"]})

            if messages_to_delete:
                try:
                    bot_manager = getattr(request.app.state, 'bot_manager', None)
                    client = bot_manager.get_least_busy_client() if (bot_manager and hasattr(bot_manager, 'get_least_busy_client')) else None
                    if not client and bot_manager and hasattr(bot_manager, 'client_list') and bot_manager.client_list:
                        client = bot_manager.client_list[0]
                    if client:
                        for c_id, m_ids in messages_to_delete.items():
                            m_list = list(m_ids)
                            for i in range(0, len(m_list), 100):
                                batch = m_list[i:i+100]
                                try:
                                    await client.delete_messages(chat_id=c_id, message_ids=batch)
                                except Exception:
                                    pass
                except Exception:
                    pass

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
