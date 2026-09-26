# src/Backend/modules/google_drive_manager.py

import time
import logging
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple
import aiohttp
from datetime import datetime, timezone

from src.Config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from src.Database import database

logger = logging.getLogger("google_drive_manager")

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# In-memory access token cache: { account_id: { "token": str, "expires_at": float } }
_ACCESS_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}

def get_effective_client_credentials(custom_client_id: Optional[str] = None, custom_client_secret: Optional[str] = None) -> Tuple[str, str]:
    """Return custom client credentials if provided, otherwise fallback to system .env config."""
    cid = (custom_client_id or "").strip('"\' \t\r\n') or (GOOGLE_CLIENT_ID or "").strip('"\' \t\r\n')
    secret = (custom_client_secret or "").strip('"\' \t\r\n') or (GOOGLE_CLIENT_SECRET or "").strip('"\' \t\r\n')
    return cid, secret

class GoogleDriveManager:
    @staticmethod
    def generate_auth_url(redirect_uri: str, state: str, client_id: Optional[str] = None) -> str:
        """Generate Google OAuth 2.0 authorization URL with offline access to get refresh_token."""
        cid, _ = get_effective_client_credentials(client_id)
        if not cid:
            raise ValueError("Google Client ID is not configured in .env or passed as custom credential.")

        params = {
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # Ensures refresh_token is always returned
            "include_granted_scopes": "true",
            "state": state
        }
        return f"{OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def exchange_code(
        code: str,
        redirect_uri: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Exchange authorization code for access_token and refresh_token, and fetch user profile."""
        cid, secret = get_effective_client_credentials(client_id, client_secret)
        if not cid or not secret:
            raise ValueError("Google Client ID or Client Secret is missing.")

        payload = {
            "code": code,
            "client_id": cid,
            "client_secret": secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(OAUTH_TOKEN_URL, data=payload, timeout=15) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    logger.error(f"[GDRIVE] Token exchange failed ({resp.status}): {err_body}")
                    raise RuntimeError(f"Failed to exchange Google OAuth code: {err_body}")
                token_data = await resp.json()

            access_token = token_data.get("access_token")
            # Fetch user email and display name
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(USERINFO_URL, headers=headers, timeout=10) as u_resp:
                user_info = await u_resp.json() if u_resp.status == 200 else {}

        return {
            "tokens": token_data,
            "user_info": user_info,
            "client_id": cid,
            "client_secret": secret
        }

    @staticmethod
    async def get_valid_access_token(account_doc: Dict[str, Any]) -> str:
        """Return a cached or newly refreshed access token for the given account document."""
        account_id = str(account_doc.get("_id") or account_doc.get("id"))
        now = time.time()

        # Check in-memory cache
        if account_id in _ACCESS_TOKEN_CACHE:
            cached = _ACCESS_TOKEN_CACHE[account_id]
            if cached.get("expires_at", 0) > now + 60:
                return cached["token"]

        creds = account_doc.get("credentials", {})
        refresh_token = creds.get("refresh_token")
        if not refresh_token:
            raise ValueError(f"No refresh_token found for Google Drive account {account_id}")

        cid, secret = get_effective_client_credentials(creds.get("client_id"), creds.get("client_secret"))
        if not cid or not secret:
            raise ValueError("Missing Client ID or Secret to refresh Google Drive token.")

        payload = {
            "client_id": cid,
            "client_secret": secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(OAUTH_TOKEN_URL, data=payload, timeout=15) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    logger.error(f"[GDRIVE] Token refresh failed for account {account_id}: {err_text}")
                    raise RuntimeError(f"Google Drive token refresh failed: {err_text}")
                data = await resp.json()

        new_access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        _ACCESS_TOKEN_CACHE[account_id] = {
            "token": new_access_token,
            "expires_at": now + expires_in
        }

        return new_access_token

    @staticmethod
    async def list_folder(
        access_token: str,
        folder_id: str = "root",
        page_size: int = 50,
        page_token: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: Optional[str] = "folder,name",
        sort_order: Optional[str] = "asc"
    ) -> Dict[str, Any]:
        """List files and folders in a Google Drive directory."""
        clean_folder = folder_id.strip() if folder_id else "root"
        # Google Drive API query
        query_parts = [f"'{clean_folder}' in parents", "trashed = false"]
        if search_query and search_query.strip():
            escaped_q = search_query.replace("'", "\\'")
            query_parts.append(f"name contains '{escaped_q}'")

        q_str = " and ".join(query_parts)

        # Order by: folders first is customary
        order_by = "folder,name"
        if sort_by == "name":
            order_by = f"folder,name {sort_order or 'asc'}"
        elif sort_by in ("date", "modified", "modifiedTime"):
            order_by = f"folder,modifiedTime {sort_order or 'desc'}"
        elif sort_by in ("size", "quotaBytesUsed"):
            order_by = f"folder,quotaBytesUsed {sort_order or 'desc'}"

        params: Dict[str, Any] = {
            "q": q_str,
            "pageSize": min(200, max(1, page_size)),
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, iconLink, thumbnailLink, webViewLink, parents)",
            "orderBy": order_by,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true"
        }
        if page_token:
            params["pageToken"] = page_token

        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{DRIVE_API_BASE}/files"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=20) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    logger.error(f"[GDRIVE] list_folder failed: {err_txt}")
                    raise RuntimeError(f"Google Drive API error: {err_txt}")
                data = await resp.json()

        # Format items to standard FileItem schema
        raw_files = data.get("files", [])
        formatted_items = []
        for f in raw_files:
            mime = f.get("mimeType", "")
            is_folder = mime == "application/vnd.google-apps.folder"
            size = int(f.get("size", 0)) if not is_folder else 0

            # Infer type from mime / extension
            name = f.get("name", "Untitled")
            f_type = "folder" if is_folder else GoogleDriveManager._infer_file_type(name, mime)

            formatted_items.append({
                "id": f.get("id"),
                "name": name,
                "type": f_type,
                "mimeType": mime,
                "size": size,
                "modified": f.get("modifiedTime"),
                "thumbnailLink": f.get("thumbnailLink"),
                "webViewLink": f.get("webViewLink"),
                "is_folder": is_folder,
                "parents": f.get("parents", [])
            })

        return {
            "items": formatted_items,
            "nextPageToken": data.get("nextPageToken"),
            "folder_id": clean_folder
        }

    @staticmethod
    def _infer_file_type(name: str, mime: str) -> str:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if mime.startswith("video/") or ext in ("mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "m4v"):
            return "video"
        if mime.startswith("image/") or ext in ("jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"):
            return "photo"
        if mime.startswith("audio/") or ext in ("mp3", "m4a", "wav", "flac", "ogg", "aac", "opus"):
            return "audio"
        if ext in ("zip", "rar", "7z", "tar", "gz", "bz2", "xz"):
            return "archive"
        if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "epub"):
            return "document"
        return "file"

    @staticmethod
    async def get_file_info(access_token: str, file_id: str) -> Dict[str, Any]:
        """Fetch detailed metadata for a file or folder."""
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{DRIVE_API_BASE}/files/{file_id}"
        params = {
            "fields": "id, name, mimeType, size, modifiedTime, parents, md5Checksum, webViewLink, thumbnailLink",
            "supportsAllDrives": "true"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=15) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    raise RuntimeError(f"Failed to fetch file info: {err_txt}")
                return await resp.json()

    @staticmethod
    async def rename_file(access_token: str, file_id: str, new_name: str) -> Dict[str, Any]:
        """Rename a file or folder in Google Drive."""
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        url = f"{DRIVE_API_BASE}/files/{file_id}?supportsAllDrives=true"
        payload = {"name": new_name}
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload, timeout=15) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    raise RuntimeError(f"Failed to rename in Google Drive: {err_txt}")
                return await resp.json()

    @staticmethod
    async def delete_file(access_token: str, file_id: str, permanent: bool = False) -> bool:
        """Trash or permanently delete a file or folder in Google Drive."""
        headers = {"Authorization": f"Bearer {access_token}"}
        if permanent:
            url = f"{DRIVE_API_BASE}/files/{file_id}?supportsAllDrives=true"
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers, timeout=15) as resp:
                    return resp.status in (200, 204)
        else:
            url = f"{DRIVE_API_BASE}/files/{file_id}?supportsAllDrives=true"
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json={"trashed": True}, timeout=15) as resp:
                    return resp.status == 200

    @staticmethod
    async def create_folder(access_token: str, parent_id: str, folder_name: str) -> Dict[str, Any]:
        """Create a new folder in Google Drive."""
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        url = f"{DRIVE_API_BASE}/files?supportsAllDrives=true"
        payload = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id or "root"]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    raise RuntimeError(f"Failed to create folder in Google Drive: {err_txt}")
                return await resp.json()

    @staticmethod
    def get_download_url(file_id: str) -> str:
        """Return the REST download URL for streaming."""
        return f"{DRIVE_API_BASE}/files/{file_id}?alt=media&supportsAllDrives=true"
