# src/Config/_data.py

import os 
from dotenv import load_dotenv
from pyrogram.types import ChatPrivileges
load_dotenv()

APP_NAME = os.getenv("APP_NAME", "MyApp")
TIME_ZONE = os.getenv("TIME_ZONE", "+5:30")
WEB_APP = os.getenv("WEB_APP", None)
API_ID = int(os.getenv("API_ID", "0")) if os.getenv("API_ID") else None
API_HASH = str(os.getenv("API_HASH", ""))
LOGGER_BOT = os.getenv("LOGGER_BOT")
OWNER = int(os.getenv("OWNER")) if os.getenv("OWNER") else None
GROUP = int(os.getenv("GROUP")) if os.getenv("GROUP") else None
LOGS = int(os.getenv("LOGS")) if os.getenv("LOGS") else None
MOVIE = int(os.getenv("MOVIE")) if os.getenv("MOVIE") else None
MOVIE_GROUP = int(os.getenv("MOVIE_GRP")) if os.getenv("MOVIE_GRP") else None
FILTER_CHAT = int(os.getenv("FILTER_CHAT")) if os.getenv("FILTER_CHAT") else None
LEECH_SOURCE = int(os.getenv("LEECH_SOURCE")) if os.getenv("LEECH_SOURCE") else None
LEECH_CHAT = int(os.getenv("LEECH_CHAT")) if os.getenv("LEECH_CHAT") else None
DATABASE_URL = str(os.getenv("DATABASE_URL", None))

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Web Server Configuration
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
SESSION_SECRET_KEY = os.getenv(
    "SESSION_SECRET_KEY",
    "f6d2e3b9a0f43d9a2e6a56b2d3175cd9c05bbfe31d95ed2a7306b57cb1a8b6f0"
)

# Admin Credentials & Authorized Emails (Configurable via .env)
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "password")

_raw_admin_emails = os.getenv("AUTHORIZED_ADMIN_EMAILS", "")
AUTHORIZED_ADMIN_EMAILS = [e.strip() for e in _raw_admin_emails.split(",") if e.strip()]

# SMTP Email Configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

TOKENS = []
for i in range(20):
    if (t := os.getenv(f"TOKEN{i}")):
        TOKENS.append(t)


ADMIN=ChatPrivileges(
    can_manage_chat=True,
    can_delete_messages=True,
    can_manage_video_chats=True,
    can_restrict_members=True,
    can_promote_members=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
    )