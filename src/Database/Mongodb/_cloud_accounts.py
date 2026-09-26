# src/Database/Mongodb/_cloud_accounts.py

from typing import Any, Optional, List, Dict, Union
from datetime import datetime, timezone
from bson import ObjectId

from d4rk.Logs import setup_logger
from pymongo.collection import Collection

logger = setup_logger(__name__)

class CloudAccounts(Collection):
    def __init__(self, collection: Collection) -> None:
        super().__init__(
            collection.database,
            collection.name,
            create=False,
            codec_options=collection.codec_options,
            read_preference=collection.read_preference,
            write_concern=collection.write_concern,
            read_concern=collection.read_concern
        )

    def get_user_accounts(self, user_id: Union[str, List[str]], provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all connected cloud accounts for a given user, optionally filtered by provider."""
        try:
            if isinstance(user_id, (list, tuple, set)):
                query: Dict[str, Any] = {"user_id": {"$in": [str(u) for u in user_id]}}
            else:
                query = {"user_id": str(user_id)}
            if provider:
                query["provider"] = provider
            cursor = self.find(query).sort("created_at", -1)
            accounts = []
            for doc in cursor:
                doc["id"] = str(doc.pop("_id"))
                if isinstance(doc.get("created_at"), datetime):
                    doc["created_at"] = doc["created_at"].isoformat()
                if isinstance(doc.get("last_synced"), datetime):
                    doc["last_synced"] = doc["last_synced"].isoformat()
                # Mask sensitive refresh_token and client_secret for safety
                if "credentials" in doc:
                    creds = doc["credentials"]
                    doc["has_credentials"] = bool(creds.get("refresh_token"))
                    # Do not leak the raw secret / token to frontend
                    doc["credentials"] = {
                        "client_id": creds.get("client_id", ""),
                        "has_refresh_token": bool(creds.get("refresh_token")),
                        "is_custom": bool(creds.get("client_id") and creds.get("client_secret"))
                    }
                accounts.append(doc)
            return accounts
        except Exception as e:
            logger.error(f"[CLOUD_ACCOUNTS] Error fetching accounts for user {user_id}: {e}")
            return []

    def get_account_raw(self, account_id: str, user_id: Optional[Union[str, List[str]]] = None) -> Optional[Dict[str, Any]]:
        """Fetch internal raw account document including credentials."""
        try:
            query: Dict[str, Any] = {"_id": ObjectId(account_id)}
            if user_id:
                if isinstance(user_id, (list, tuple, set)):
                    query["user_id"] = {"$in": [str(u) for u in user_id]}
                else:
                    query["user_id"] = str(user_id)
            doc = self.find_one(query)
            if doc:
                doc["id"] = str(doc["_id"])
            return doc
        except Exception as e:
            logger.error(f"[CLOUD_ACCOUNTS] Error fetching raw account {account_id}: {e}")
            return None

    def save_account(
        self,
        user_id: str,
        provider: str,
        account_name: str,
        account_email: str,
        credentials: Dict[str, Any],
        root_folder_id: str = "root"
    ) -> Optional[str]:
        """Insert or update a cloud account document."""
        try:
            now = datetime.now(timezone.utc)
            # Check if this email + provider is already connected for this user
            existing = self.find_one({
                "user_id": str(user_id),
                "provider": provider,
                "account_email": account_email
            })

            data = {
                "user_id": str(user_id),
                "provider": provider,
                "account_name": account_name,
                "account_email": account_email,
                "credentials": credentials,
                "root_folder_id": root_folder_id,
                "last_synced": now
            }

            if existing:
                self.update_one({"_id": existing["_id"]}, {"$set": data})
                logger.info(f"[CLOUD_ACCOUNTS] Updated existing account {existing['_id']} for {account_email}")
                return str(existing["_id"])
            else:
                data["created_at"] = now
                res = self.insert_one(data)
                logger.info(f"[CLOUD_ACCOUNTS] Inserted new account {res.inserted_id} for {account_email}")
                return str(res.inserted_id)
        except Exception as e:
            logger.error(f"[CLOUD_ACCOUNTS] Error saving cloud account: {e}")
            return None

    def update_account_tokens(self, account_id: str, new_credentials: Dict[str, Any]) -> bool:
        """Update credentials (e.g. refreshed access_token, expiry)."""
        try:
            self.update_one(
                {"_id": ObjectId(account_id)},
                {
                    "$set": {
                        "credentials": new_credentials,
                        "last_synced": datetime.now(timezone.utc)
                    }
                }
            )
            return True
        except Exception as e:
            logger.error(f"[CLOUD_ACCOUNTS] Error updating tokens for {account_id}: {e}")
            return False

    def delete_account(self, account_id: str, user_id: Union[str, List[str]]) -> bool:
        """Remove a cloud account connection."""
        try:
            if isinstance(user_id, (list, tuple, set)):
                query: Dict[str, Any] = {"_id": ObjectId(account_id), "user_id": {"$in": [str(u) for u in user_id]}}
            else:
                query = {"_id": ObjectId(account_id), "user_id": str(user_id)}
            res = self.delete_one(query)
            return res.deleted_count > 0
        except Exception as e:
            logger.error(f"[CLOUD_ACCOUNTS] Error deleting account {account_id}: {e}")
            return False
