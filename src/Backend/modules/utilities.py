# src/Backend/modules/utilities.py

from typing import Dict
from datetime import datetime
from src.Database import database
from d4rk.Logs import setup_logger

logger = setup_logger("web_server_utilities")

work_loads = {}
_auth_tokens: Dict[str, Dict] = {}

def load_persistent_tokens(app):
    """Load persistent auth tokens from database on startup"""
    try:
        database.Users.cleanup_expired_tokens()
        tokens_cursor = database.Users.database.AuthTokens.find({
            'expires_at': {'$gte': datetime.now()}
        })
        
        loaded_count = 0
        for token_data in tokens_cursor:
            auth_token = token_data['auth_token']
            _auth_tokens[auth_token] = {
                "authenticated": True,
                "username": token_data['username'],
                "auth_method": token_data['auth_method'],
                "created_at": token_data['created_at'].isoformat() if hasattr(token_data['created_at'], 'isoformat') else str(token_data['created_at'])
            }
            loaded_count += 1
        
    except Exception as e:
        logger.error(f"Failed to load persistent auth tokens: {e}")

def cleanup_stale_upload_files(max_age_seconds: int = 3600):
    """
    Purges any temporary upload directories (chunk_*) or files (dav_*, *.tmp)
    in tg_files/ that are older than max_age_seconds or abandoned.
    """
    import os
    import time
    import shutil

    tg_files_dir = os.path.join(os.getcwd(), "tg_files")
    if not os.path.exists(tg_files_dir):
        return

    now = time.time()
    try:
        for entry in os.listdir(tg_files_dir):
            entry_path = os.path.join(tg_files_dir, entry)
            try:
                mtime = os.path.getmtime(entry_path)
                if now - mtime >= max_age_seconds:
                    if os.path.isdir(entry_path):
                        shutil.rmtree(entry_path, ignore_errors=True)
                        logger.info(f"[JANITOR] Cleaned up stale upload directory: {entry}")
                    else:
                        os.remove(entry_path)
                        logger.info(f"[JANITOR] Cleaned up stale upload file: {entry}")
            except Exception as e:
                logger.warning(f"[JANITOR] Failed to clean {entry_path}: {e}")
    except Exception as e:
        logger.error(f"[JANITOR] Error during tg_files cleanup: {e}")

__all__ = ['work_loads', '_auth_tokens', 'load_persistent_tokens', 'cleanup_stale_upload_files']