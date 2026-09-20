import asyncio
import smtplib
import random
import logging
import os
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pymongo import MongoClient

from src.Config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, APP_NAME, DATABASE_URL

logger = logging.getLogger(__name__)

_mongo_client = None

def get_vault_db():
    """Retrieve shared PyMongo database instance for Vault."""
    global _mongo_client
    if _mongo_client is None:
        url = DATABASE_URL or os.getenv("DATABASE_URL", "mongodb://mongo:27017/telegramfileserver")
        _mongo_client = MongoClient(url)
    return _mongo_client["MyApp"]

def generate_otp() -> str:
    """Generate a secure 6-digit numeric OTP."""
    return f"{random.randint(100000, 999999)}"

def _send_smtp_email_sync(to_email: str, subject: str, html_content: str, text_content: str = "") -> bool:
    """Synchronous SMTP email dispatcher using STARTTLS."""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.error("SMTP credentials are not configured in environment!")
        raise ValueError("SMTP credentials are not configured")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{APP_NAME} Vault <{SMTP_USER}>"
    msg["To"] = to_email

    if text_content:
        msg.attach(MIMEText(text_content, "plain"))
    if html_content:
        msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Successfully sent email to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        raise e

async def send_email_async(to_email: str, subject: str, html_content: str, text_content: str = "") -> bool:
    """Non-blocking async email sender running in threadpool."""
    return await asyncio.to_thread(_send_smtp_email_sync, to_email, subject, html_content, text_content)

def get_otp_html_template(otp_code: str, purpose: str = "Private Vault Setup") -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background-color: #0f172a;
                margin: 0;
                padding: 40px 20px;
                color: #f8fafc;
            }}
            .card {{
                max-width: 480px;
                margin: 0 auto;
                background: #1e293b;
                border-radius: 16px;
                border: 1px solid #334155;
                padding: 36px 28px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
                text-align: center;
            }}
            .logo {{
                font-size: 32px;
                margin-bottom: 12px;
            }}
            h1 {{
                font-size: 22px;
                font-weight: 700;
                margin: 0 0 10px;
                color: #38bdf8;
            }}
            p {{
                font-size: 14px;
                color: #94a3b8;
                line-height: 1.6;
                margin: 0 0 24px;
            }}
            .otp-box {{
                background: #0f172a;
                border: 2px dashed #0284c7;
                border-radius: 12px;
                padding: 18px 24px;
                font-size: 36px;
                font-weight: 800;
                letter-spacing: 8px;
                color: #38bdf8;
                display: inline-block;
                margin-bottom: 24px;
            }}
            .footer {{
                font-size: 12px;
                color: #64748b;
                border-top: 1px solid #334155;
                padding-top: 18px;
                margin-top: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="logo">🔒</div>
            <h1>{purpose}</h1>
            <p>Your one-time security verification code is shown below. This code will expire in <strong>10 minutes</strong>.</p>
            <div class="otp-box">{otp_code}</div>
            <p style="font-size: 13px; color: #cbd5e1;">Never share this code with anyone. If you did not make this request, you can safely ignore this email.</p>
            <div class="footer">
                &copy; {datetime.now().year} {APP_NAME} &bull; End-to-End Encrypted Cloud
            </div>
        </div>
    </body>
    </html>
    """

async def create_and_send_vault_otp(email: str, user_id: str, purpose: str = "Private Vault Verification") -> dict:
    """
    Generates an OTP, stores it in MongoDB (MyApp.VaultOTP), enforces rate limits,
    and sends the email to the recipient.
    """
    otp_coll = get_vault_db()["VaultOTP"]
    now = datetime.now(timezone.utc)
    user_id_str = str(user_id)

    # Rate limiting: max 5 requests per 10 minutes for the same user/email
    ten_mins_ago = now - timedelta(minutes=10)
    recent_count = otp_coll.count_documents({
        "user_id": user_id_str,
        "created_at": {"$gte": ten_mins_ago}
    })

    if recent_count >= 5:
        raise ValueError("Too many OTP requests. Please wait a few minutes before trying again.")

    # Remove any existing pending OTPs for this user & purpose
    otp_coll.delete_many({"user_id": user_id_str, "purpose": purpose})

    otp_code = generate_otp()
    expires_at = now + timedelta(minutes=10)

    # Store in database
    otp_coll.insert_one({
        "user_id": user_id_str,
        "email": email.strip().lower(),
        "otp_code": otp_code,
        "purpose": purpose,
        "created_at": now,
        "expires_at": expires_at,
        "attempts": 0
    })

    # Dispatch email
    subject = f"Your {APP_NAME} Vault Code: {otp_code}"
    html = get_otp_html_template(otp_code, purpose)
    text = f"Your {APP_NAME} Vault Verification Code is: {otp_code}. Valid for 10 minutes."

    await send_email_async(email, subject, html, text)
    return {"success": True, "expires_at": expires_at.isoformat()}

async def verify_vault_otp(email: str, user_id: str, otp_code: str, purpose: str) -> bool:
    """
    Verifies the provided OTP against the database record.
    Increments attempts, and purges OTP upon successful verification or expiry.
    """
    otp_coll = get_vault_db()["VaultOTP"]
    now = datetime.now(timezone.utc)
    user_id_str = str(user_id)

    record = otp_coll.find_one({
        "user_id": user_id_str,
        "email": email.strip().lower(),
        "purpose": purpose,
        "expires_at": {"$gt": now}
    })

    if not record:
        return False

    if record.get("attempts", 0) >= 5:
        otp_coll.delete_one({"_id": record["_id"]})
        raise ValueError("Too many incorrect attempts. Please request a new OTP.")

    if record.get("otp_code") == otp_code.strip():
        # Successfully verified, consume the OTP
        otp_coll.delete_one({"_id": record["_id"]})
        return True
    else:
        # Increment failure attempts
        otp_coll.update_one(
            {"_id": record["_id"]},
            {"$inc": {"attempts": 1}}
        )
        return False
