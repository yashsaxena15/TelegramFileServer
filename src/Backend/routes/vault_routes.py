import os
import time
import re
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..security.credentials import require_auth, User
from ..modules.email_service import create_and_send_vault_otp, verify_vault_otp, get_vault_db
from src.Config import SESSION_SECRET_KEY
from src.Database import database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["Vault"])

# 15 minutes of inactivity before vault auto-locks
VAULT_INACTIVITY_TIMEOUT = 900 


# Pydantic Request Models
class RequestEmailOtpModel(BaseModel):
    email: str

class VerifyAndCreateModel(BaseModel):
    email: str
    otp_code: str
    pin: str

class UnlockVaultModel(BaseModel):
    pin: str

class ForgotPinResetModel(BaseModel):
    otp_code: str
    new_pin: str

class ChangePinModel(BaseModel):
    current_pin: str
    new_pin: str

class MoveVaultItemModel(BaseModel):
    file_id: str
    target_path: Optional[str] = None

class CreateVaultFolderModel(BaseModel):
    folder_name: str
    current_path: Optional[str] = "/Vault"


# Cryptographic Helpers
def _derive_pin_key(pin: str, salt: bytes) -> bytes:
    """Derive a 256-bit encryption key from 4-digit PIN using PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100000, 32)

def _get_recovery_master_key(user_id: str) -> bytes:
    """Derive a server-side recovery key tied to this user and system secret."""
    return hashlib.pbkdf2_hmac("sha256", SESSION_SECRET_KEY.encode("utf-8"), user_id.encode("utf-8"), 50000, 32)

def _mask_email(email: str) -> str:
    """Mask email for privacy, e.g. ya***28@gmail.com."""
    try:
        parts = email.split("@")
        if len(parts) != 2:
            return email
        name, domain = parts
        if len(name) <= 3:
            masked_name = name[0] + "***"
        else:
            masked_name = name[:2] + "***" + name[-2:]
        return f"{masked_name}@{domain}"
    except Exception:
        return email

def is_vault_unlocked(request: Request) -> bool:
    """Check if vault is unlocked and within the inactivity window."""
    unlocked = request.session.get("vault_unlocked", False)
    if not unlocked:
        return False
    unlocked_at = request.session.get("vault_unlocked_at", 0)
    if time.time() - unlocked_at > VAULT_INACTIVITY_TIMEOUT:
        request.session["vault_unlocked"] = False
        return False
    # Touch activity timestamp
    request.session["vault_unlocked_at"] = time.time()
    return True


@router.get("/status")
async def get_vault_status(request: Request, user: User = Depends(require_auth)):
    """Check whether the user has set up a Vault, and if it's currently unlocked."""
    user_id = str(user.telegram_user_id or user.username or "admin")
    vault_coll = get_vault_db()["VaultConfig"]
    config = vault_coll.find_one({"user_id": user_id})

    if not config:
        return {
            "is_setup": False,
            "is_unlocked": False,
            "email": None,
            "remaining_seconds": 0
        }

    unlocked = is_vault_unlocked(request)
    remaining_seconds = 0
    if unlocked:
        unlocked_at = request.session.get("vault_unlocked_at", 0)
        remaining_seconds = max(0, int(VAULT_INACTIVITY_TIMEOUT - (time.time() - unlocked_at)))

    return {
        "is_setup": True,
        "is_unlocked": unlocked,
        "email": _mask_email(config.get("email", "")),
        "remaining_seconds": remaining_seconds
    }


@router.post("/setup/request-otp")
async def request_setup_otp(body: RequestEmailOtpModel, user: User = Depends(require_auth)):
    """Step 1 of Setup: Send verification OTP to the user's provided email."""
    email = body.email.strip().lower()
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    try:
        await create_and_send_vault_otp(email, user_id, purpose="Private Vault Setup")
        return {"success": True, "message": f"Verification code sent to {email}"}
    except ValueError as ve:
        raise HTTPException(status_code=429, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to send setup OTP: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch verification email. Please try again.")


@router.post("/setup/verify-and-create")
async def verify_and_create_vault(request: Request, body: VerifyAndCreateModel, user: User = Depends(require_auth)):
    """Step 2 of Setup: Verify OTP and create Vault with chosen 4-digit PIN."""
    pin = body.pin.strip()
    if not re.match(r"^\d{4}$", pin):
        raise HTTPException(status_code=400, detail="Vault PIN must be exactly 4 numeric digits.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    email = body.email.strip().lower()

    # 1. Verify OTP
    try:
        valid = await verify_vault_otp(email, user_id, body.otp_code.strip(), purpose="Private Vault Setup")
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # 2. Generate cryptographically strong random VaultKey (256-bit)
    vault_key = os.urandom(32)

    # 3. Create Envelope 1 (PIN Encrypted)
    pin_salt = os.urandom(16)
    pin_derived_key = _derive_pin_key(pin, pin_salt)
    pin_hash = hashlib.sha256(pin_derived_key).hexdigest()

    aes_pin = AESGCM(pin_derived_key)
    iv_pin = os.urandom(12)
    encrypted_vault_key = aes_pin.encrypt(iv_pin, vault_key, None)

    # 4. Create Envelope 2 (Server-assisted Recovery Encrypted)
    rec_key = _get_recovery_master_key(user_id)
    aes_rec = AESGCM(rec_key)
    iv_rec = os.urandom(12)
    recovery_envelope = aes_rec.encrypt(iv_rec, vault_key, None)

    # 5. Persist in VaultConfig
    vault_coll = get_vault_db()["VaultConfig"]
    now = datetime.now(timezone.utc)

    vault_coll.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "email": email,
                "pin_salt": pin_salt.hex(),
                "pin_hash": pin_hash,
                "encrypted_vault_key": encrypted_vault_key.hex(),
                "vault_key_iv": iv_pin.hex(),
                "recovery_envelope": recovery_envelope.hex(),
                "recovery_iv": iv_rec.hex(),
                "created_at": now,
                "updated_at": now
            }
        },
        upsert=True
    )

    # 6. Unlock session immediately
    request.session["vault_unlocked"] = True
    request.session["vault_unlocked_at"] = time.time()

    return {"success": True, "message": "Private Vault successfully initialized and unlocked!"}


@router.post("/unlock")
async def unlock_vault(request: Request, body: UnlockVaultModel, user: User = Depends(require_auth)):
    """Unlock Vault using 4-digit PIN."""
    pin = body.pin.strip()
    if not re.match(r"^\d{4}$", pin):
        raise HTTPException(status_code=400, detail="Please enter a valid 4-digit PIN.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    vault_coll = get_vault_db()["VaultConfig"]
    config = vault_coll.find_one({"user_id": user_id})

    if not config:
        raise HTTPException(status_code=404, detail="Vault is not setup yet.")

    pin_salt = bytes.fromhex(config["pin_salt"])
    pin_derived_key = _derive_pin_key(pin, pin_salt)
    calculated_hash = hashlib.sha256(pin_derived_key).hexdigest()

    if calculated_hash != config["pin_hash"]:
        raise HTTPException(status_code=401, detail="Incorrect 4-digit PIN.")

    # Successful unlock
    request.session["vault_unlocked"] = True
    request.session["vault_unlocked_at"] = time.time()

    return {"success": True, "message": "Vault successfully unlocked."}


@router.post("/lock")
async def lock_vault(request: Request, user: User = Depends(require_auth)):
    """Immediately lock the vault."""
    request.session["vault_unlocked"] = False
    request.session["vault_unlocked_at"] = 0
    return {"success": True, "message": "Vault locked."}


@router.post("/forgot-pin/request-otp")
async def forgot_pin_request_otp(user: User = Depends(require_auth)):
    """Request a 6-digit OTP to the registered recovery email for PIN reset."""
    user_id = str(user.telegram_user_id or user.username or "admin")
    vault_coll = get_vault_db()["VaultConfig"]
    config = vault_coll.find_one({"user_id": user_id})

    if not config or not config.get("email"):
        raise HTTPException(status_code=404, detail="No registered recovery email found for this Vault.")

    email = config["email"]
    try:
        await create_and_send_vault_otp(email, user_id, purpose="Vault PIN Reset")
        return {
            "success": True,
            "message": f"Verification code sent to {_mask_email(email)}",
            "masked_email": _mask_email(email)
        }
    except ValueError as ve:
        raise HTTPException(status_code=429, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to send reset OTP: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch verification email.")


@router.post("/forgot-pin/reset")
async def forgot_pin_reset(request: Request, body: ForgotPinResetModel, user: User = Depends(require_auth)):
    """Verify OTP and set a new 4-digit PIN without losing files."""
    new_pin = body.new_pin.strip()
    if not re.match(r"^\d{4}$", new_pin):
        raise HTTPException(status_code=400, detail="New PIN must be exactly 4 numeric digits.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    vault_coll = get_vault_db()["VaultConfig"]
    config = vault_coll.find_one({"user_id": user_id})

    if not config:
        raise HTTPException(status_code=404, detail="Vault not found.")

    email = config["email"]

    # 1. Verify OTP
    try:
        valid = await verify_vault_otp(email, user_id, body.otp_code.strip(), purpose="Vault PIN Reset")
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # 2. Recover Master VaultKey from Recovery Envelope
    try:
        rec_key = _get_recovery_master_key(user_id)
        aes_rec = AESGCM(rec_key)
        recovery_envelope = bytes.fromhex(config["recovery_envelope"])
        recovery_iv = bytes.fromhex(config["recovery_iv"])
        vault_key = aes_rec.decrypt(recovery_iv, recovery_envelope, None)
    except Exception as e:
        logger.error(f"Recovery decryption failed: {e}")
        raise HTTPException(status_code=500, detail="Decryption error during key recovery.")

    # 3. Re-encrypt VaultKey into Envelope 1 with the new PIN
    new_salt = os.urandom(16)
    new_pin_derived_key = _derive_pin_key(new_pin, new_salt)
    new_pin_hash = hashlib.sha256(new_pin_derived_key).hexdigest()

    aes_pin = AESGCM(new_pin_derived_key)
    new_iv_pin = os.urandom(12)
    new_encrypted_vault_key = aes_pin.encrypt(new_iv_pin, vault_key, None)

    now = datetime.now(timezone.utc)
    vault_coll.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "pin_salt": new_salt.hex(),
                "pin_hash": new_pin_hash,
                "encrypted_vault_key": new_encrypted_vault_key.hex(),
                "vault_key_iv": new_iv_pin.hex(),
                "updated_at": now
            }
        }
    )

    # 4. Automatically unlock session
    request.session["vault_unlocked"] = True
    request.session["vault_unlocked_at"] = time.time()

    return {"success": True, "message": "PIN successfully reset and Vault unlocked!"}


@router.post("/change-pin")
async def change_pin(request: Request, body: ChangePinModel, user: User = Depends(require_auth)):
    """Change PIN when current PIN is known."""
    current_pin = body.current_pin.strip()
    new_pin = body.new_pin.strip()

    if not re.match(r"^\d{4}$", new_pin):
        raise HTTPException(status_code=400, detail="New PIN must be exactly 4 numeric digits.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    vault_coll = get_vault_db()["VaultConfig"]
    config = vault_coll.find_one({"user_id": user_id})

    if not config:
        raise HTTPException(status_code=404, detail="Vault not found.")

    # Verify current PIN
    current_salt = bytes.fromhex(config["pin_salt"])
    current_derived_key = _derive_pin_key(current_pin, current_salt)
    if hashlib.sha256(current_derived_key).hexdigest() != config["pin_hash"]:
        raise HTTPException(status_code=401, detail="Current PIN is incorrect.")

    # Decrypt VaultKey using current PIN
    try:
        aes_cur = AESGCM(current_derived_key)
        vault_key = aes_cur.decrypt(bytes.fromhex(config["vault_key_iv"]), bytes.fromhex(config["encrypted_vault_key"]), None)
    except Exception:
        raise HTTPException(status_code=500, detail="Decryption failed with current PIN.")

    # Re-encrypt with new PIN
    new_salt = os.urandom(16)
    new_derived_key = _derive_pin_key(new_pin, new_salt)
    new_pin_hash = hashlib.sha256(new_derived_key).hexdigest()

    aes_new = AESGCM(new_derived_key)
    new_iv = os.urandom(12)
    new_encrypted_key = aes_new.encrypt(new_iv, vault_key, None)

    now = datetime.now(timezone.utc)
    vault_coll.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "pin_salt": new_salt.hex(),
                "pin_hash": new_pin_hash,
                "encrypted_vault_key": new_encrypted_key.hex(),
                "vault_key_iv": new_iv.hex(),
                "updated_at": now
            }
        }
    )

    request.session["vault_unlocked"] = True
    request.session["vault_unlocked_at"] = time.time()
    return {"success": True, "message": "PIN changed successfully."}


@router.post("/move-in")
async def move_into_vault(request: Request, body: MoveVaultItemModel, user: User = Depends(require_auth)):
    """Move a file or folder into the Private Vault."""
    if not is_vault_unlocked(request):
        raise HTTPException(status_code=403, detail="Vault is locked. Please unlock Vault first.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    target_path = body.target_path or "/Vault"
    if not target_path.startswith("/Vault"):
        target_path = "/Vault"

    try:
        obj_id = ObjectId(body.file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file ID.")

    # Update item and any sub-items if folder
    item = database.Files.find_one({"_id": obj_id})
    if not item:
        raise HTTPException(status_code=404, detail="File or folder not found.")

    database.Files.update_one(
        {"_id": obj_id},
        {"$set": {"is_vault": True, "file_path": target_path}}
    )

    # If it was a folder, move its nested children into vault too
    if item.get("file_type") == "folder":
        old_full_path = f"{item.get('file_path', '').rstrip('/')}/{item.get('file_name', '')}"
        new_full_path = f"{target_path.rstrip('/')}/{item.get('file_name', '')}"
        database.Files.update_many(
            {"file_path": {"$regex": f"^{re.escape(old_full_path)}(/.*)?$"}},
            {"$set": {"is_vault": True}}
        )

    return {"success": True, "message": f"Moved to Vault ({target_path})"}


@router.post("/move-out")
async def move_out_of_vault(request: Request, body: MoveVaultItemModel, user: User = Depends(require_auth)):
    """Move a file or folder out of Private Vault back into Home."""
    if not is_vault_unlocked(request):
        raise HTTPException(status_code=403, detail="Vault is locked. Please unlock Vault first.")

    target_path = body.target_path or "/Home"
    try:
        obj_id = ObjectId(body.file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file ID.")

    item = database.Files.find_one({"_id": obj_id})
    if not item:
        raise HTTPException(status_code=404, detail="File or folder not found.")

    database.Files.update_one(
        {"_id": obj_id},
        {"$set": {"is_vault": False, "file_path": target_path}}
    )

    if item.get("file_type") == "folder":
        old_full_path = f"{item.get('file_path', '').rstrip('/')}/{item.get('file_name', '')}"
        database.Files.update_many(
            {"file_path": {"$regex": f"^{re.escape(old_full_path)}(/.*)?$"}},
            {"$set": {"is_vault": False}}
        )

    return {"success": True, "message": f"Moved to {target_path}"}


@router.post("/create-folder")
async def create_vault_folder(request: Request, body: CreateVaultFolderModel, user: User = Depends(require_auth)):
    """Create a folder inside Private Vault."""
    if not is_vault_unlocked(request):
        raise HTTPException(status_code=403, detail="Vault is locked. Please unlock Vault first.")

    user_id = str(user.telegram_user_id or user.username or "admin")
    name = body.folder_name.strip()
    if not name or len(name) > 60:
        raise HTTPException(status_code=400, detail="Invalid folder name.")

    current_path = body.current_path or "/Vault"
    if not current_path.startswith("/Vault"):
        current_path = "/Vault"

    success = database.Files.add_folder(name, current_path, user_id)
    if not success:
        raise HTTPException(status_code=400, detail="A folder with this name already exists in this location.")

    return {"success": True, "message": f"Folder '{name}' created inside Vault."}
