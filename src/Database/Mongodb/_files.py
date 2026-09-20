# src/Database/Mongodb/_files.py

from typing import Any, Literal
from dataclasses import dataclass
from d4rk.Logs import setup_logger
from datetime import datetime

from pymongo.collection import Collection
from pymongo.results import InsertOneResult, UpdateResult

logger = setup_logger(__name__)


@dataclass
class FileData:
    id: int 
    chat_id: int
    message_id: int
    thumbnail: str = None
    file_type: Literal["document","video","photo","voice","audio","folder"] = None
    file_unique_id: str = None
    file_size: int = None
    file_name: str|None = None
    file_caption: str = None
    file_path: str = "/"  # Path where file is located, default is root
    owner_id: str = None  # Owner user ID for multi-user support
    modified_date: str = None  # ISO format date string for when file was last modified
    is_split: bool = False
    total_parts: int = 1
    part_size: int = None
    parts: list = None
    starred: bool = False
    trashed: bool = False
    trashed_at: str = None
    original_path: str = None
    is_vault: bool = False
    
class Files(Collection):
    def __init__(self,collection: Collection) -> None:
        super().__init__(
            collection.database,
            collection.name,
            create=False,
            codec_options=collection.codec_options,
            read_preference=collection.read_preference,
            write_concern=collection.write_concern,
            read_concern=collection.read_concern
        )

    def check_if_exists(self, chat_id: int, message_id: int, file_unique_id: int) -> bool:
        r = self.find_one({"chat_id": chat_id, "message_id": message_id, "file_unique_id": file_unique_id})
        return False if not r else True
    
    def add_file(self, chat_id: int, message_id: int, thumbnail: str, file_type: str, file_unique_id: str, file_size: int, file_name: str, file_caption: str, file_path: str = "/", owner_id: str = None, modified_date: str = None):
        saved = self.check_if_exists(chat_id, message_id, file_unique_id)
        if not saved:
            file_doc = {
                "chat_id": chat_id,
                "message_id": message_id,
                "thumbnail": thumbnail,
                "file_type": file_type,
                "file_unique_id": file_unique_id,
                "file_size": file_size,
                "file_name": file_name,
                "file_caption": file_caption,
                "file_path": file_path,  # Store file path
                "modified_date": modified_date or datetime.utcnow().isoformat()  # Set current time if not provided
            }
            
            # Add owner_id if provided
            if owner_id:
                file_doc["owner_id"] = owner_id
            
            self.insert_one(file_doc)
            return True
        return None

    def add_multipart_file(
        self,
        chat_id: int,
        thumbnail: str,
        file_type: str,
        file_unique_id: str,
        file_size: int,
        file_name: str,
        file_caption: str,
        parts: list,
        file_path: str = "/Home",
        owner_id: str = None,
        modified_date: str = None,
        part_size: int = None
    ):
        """Add a multi-part file entry to the database for files > 2GB"""
        if not file_path or file_path in ["/", "Home", "/Home"]:
            file_path = "/Home"
            
        file_doc = {
            "chat_id": chat_id,
            "message_id": parts[0]["message_id"] if parts else 0,
            "thumbnail": thumbnail,
            "file_type": file_type,
            "file_unique_id": file_unique_id,
            "file_size": file_size,
            "file_name": file_name,
            "file_caption": file_caption,
            "file_path": file_path,
            "owner_id": owner_id,
            "modified_date": modified_date or datetime.utcnow().isoformat(),
            "is_split": True,
            "total_parts": len(parts),
            "part_size": part_size or (parts[0]["part_size"] if parts else 0),
            "parts": parts
        }
        logger.info(f"Adding multi-part file '{file_name}' ({file_size} bytes, {len(parts)} parts) at path '{file_path}'")
        self.insert_one(file_doc)
        return True

    def add_folder(self, folder_name: str, folder_path: str = "/", owner_id: str = None):
        """Add a folder entry to the database"""
        # Normalize folder_path: root is "/Home"
        if not folder_path or folder_path in ["/", "Home", "/Home"]:
            folder_path = "/Home"
            path_query = {"$in": ["/Home", "/"]}
        else:
            path_query = folder_path

        # Log the parameters for debugging
        logger.info(f"add_folder called with folder_name='{folder_name}', folder_path='{folder_path}', owner_id='{owner_id}'")
            
        # Check if folder already exists
        query = {"file_name": folder_name, "file_path": path_query, "file_type": "folder"}
        # Include owner_id in query if provided
        if owner_id:
            query["owner_id"] = owner_id
        elif "owner_id" not in query:
            query["owner_id"] = {"$exists": False}
            
        existing = self.find_one(query)
        if existing:
            logger.info(f"Folder '{folder_name}' already exists at path '{folder_path}'")
            return False
            
        # Generate a unique ID for the folder
        import hashlib
        folder_unique_id = f"folder_{hashlib.md5(f'{folder_path}/{folder_name}'.encode()).hexdigest()}"
            
        # Insert folder entry
        folder_doc = {
            "chat_id": 0,  # System-created folder
            "message_id": 0,  # System-created folder
            "thumbnail": None,
            "file_type": "folder",
            "file_unique_id": folder_unique_id,
            "file_size": 0,
            "file_name": folder_name,
            "file_caption": folder_name,
            "file_path": folder_path,
            "modified_date": datetime.utcnow().isoformat()  # Set current time for folder creation
        }
        
        # Add owner_id if provided
        if owner_id:
            folder_doc["owner_id"] = owner_id
            
        if folder_path.startswith("/Vault") or folder_path == "Vault":
            folder_doc["is_vault"] = True
            
        logger.info(f"Inserting folder document: {folder_doc}")
        self.insert_one(folder_doc)
        return True

    def create_default_folders(self, owner_id: str = None):
        """Create default folders for a user when they log in"""
        default_folders = ["Images", "Documents", "Videos", "Audio", "Voice Messages"]
        created_folders = []
        
        for folder_name in default_folders:
            # Check if folder already exists
            query = {"file_name": folder_name, "file_path": "/Home", "file_type": "folder"}
            if owner_id:
                query["owner_id"] = owner_id
            existing_folder = self.find_one(query)
            
            if not existing_folder:
                # Create the default folder
                success = self.add_folder(folder_name, "/Home", owner_id)
                if success:
                    created_folders.append(folder_name)
        
        if created_folders:
            logger.info(f"Created default folders for user {owner_id}: {created_folders}")
        else:
            logger.info(f"Default folders already exist for user {owner_id}")
        
        return created_folders
    
    def create_folder_path(self, full_path: str, owner_id: str = None):
        """Recursively create folder structure for a given path"""
        # Log the parameters for debugging
        logger.info(f"create_folder_path called with full_path='{full_path}', owner_id='{owner_id}'")
        
        # Normalize the path
        full_path = full_path.rstrip('/')
        if not full_path or full_path == '/':
            logger.info("Empty or root path, returning True")
            return True
            
        # Split path into components
        path_parts = full_path.lstrip('/').split('/')
        logger.info(f"Path parts: {path_parts}")
        
        # Create each folder in the path
        current_path = "/"
        for i, folder_name in enumerate(path_parts):
            if folder_name:  # Skip empty parts
                logger.info(f"Creating folder '{folder_name}' at path '{current_path}'")
                # The folder's path should be the parent path, not the current path
                # For example, for "/qwes", we create folder "qwes" with path "/"
                success = self.add_folder(folder_name, current_path, owner_id)
                # Update current_path for next iteration
                if current_path == "/":
                    current_path = f"/{folder_name}"
                else:
                    current_path = f"{current_path}/{folder_name}"
                logger.info(f"Updated current_path to '{current_path}'")
                    
        return True

    def get_all_files(self, owner_id: str = None):
        # Filter by owner_id if provided (exclude trashed by default)
        query = {"trashed": {"$ne": True}}
        if owner_id:
            query["owner_id"] = owner_id
        
        files = self.find(query)
        return [FileData(
            id=file.get("_id"), 
            chat_id=file.get("chat_id"), 
            message_id=file.get("message_id"), 
            file_type=file.get("file_type"),
            thumbnail=file.get("thumbnail"), 
            file_unique_id=file.get("file_unique_id"), 
            file_size=file.get("file_size"), 
            file_name=file.get("file_name"), 
            file_caption=file.get("file_caption"),
            file_path=file.get("file_path", "/"),  # Default to root if not set
            owner_id=file.get("owner_id"),
            modified_date=file.get("modified_date"),
            is_split=file.get("is_split", False),
            total_parts=file.get("total_parts", 1),
            part_size=file.get("part_size"),
            parts=file.get("parts"),
            starred=bool(file.get("starred", False)),
            trashed=bool(file.get("trashed", False)),
            trashed_at=file.get("trashed_at"),
            original_path=file.get("original_path")
        ) for file in files]
    
    def get_files_by_path(self, path: str = "/", owner_id: str = None):
        """Get files and folders for a specific path"""
        # Build query with owner filter
        def build_query(base_query):
            if owner_id:
                base_query["owner_id"] = owner_id
            return base_query
        
        # Vault path (Root)
        if path in ["vault", "/vault", "/Vault", "Vault"]:
            query = build_query({"file_path": {"$in": ["/Vault", "Vault"]}, "is_vault": True, "trashed": {"$ne": True}})
            all_items = list(self.find(query))
        # Vault subfolders
        elif path.startswith("/Vault/") or path.startswith("Vault/"):
            query = build_query({"file_path": path, "is_vault": True, "trashed": {"$ne": True}})
            all_items = list(self.find(query))
        # Trash path
        elif path in ["trash", "/trash", "/Home/Trash", "Trash", "/Trash"]:
            query = build_query({"trashed": True, "is_vault": {"$ne": True}})
            all_items = list(self.find(query))
        # Starred path
        elif path in ["starred", "/starred", "/Home/Starred", "Starred", "/Starred"]:
            query = build_query({"starred": True, "trashed": {"$ne": True}, "is_vault": {"$ne": True}})
            all_items = list(self.find(query))
        # Telegram Inbox path
        elif path in ["inbox", "/inbox", "Telegram Inbox", "/Telegram Inbox", "/Home/Telegram Inbox", "inbox/"]:
            query = build_query({"file_path": "/Telegram Inbox", "trashed": {"$ne": True}, "is_vault": {"$ne": True}})
            all_items = list(self.find(query))
        # Special case: fetch all files (for virtual folders like Images, Documents, etc.)
        elif path == "all":
            # Get all files except folders
            files_query = build_query({"file_type": {"$ne": "folder"}, "trashed": {"$ne": True}, "is_vault": {"$ne": True}})
            all_items = list(self.find(files_query))
        # For root path, get files with path="/" and folders with path="/"
        elif path in ["/", "Home", "/Home"]:
            # Get root-level files and folders (support both /Home and /)
            files_query = build_query({"file_path": {"$in": ["/Home", "/"]}, "trashed": {"$ne": True}, "is_vault": {"$ne": True}})
            all_items = list(self.find(files_query))
        else:
            # Get files and folders in the specified folder
            base_query = {"file_path": path, "trashed": {"$ne": True}, "is_vault": {"$ne": True}}
            query = build_query(base_query)
            logger.info(f"Executing file query: {query}")
            all_items = list(self.find(query))
        
        return [FileData(
            id=file.get("_id"), 
            chat_id=file.get("chat_id"), 
            message_id=file.get("message_id"), 
            file_type=file.get("file_type"),
            thumbnail=file.get("thumbnail"), 
            file_unique_id=file.get("file_unique_id"), 
            file_size=file.get("file_size"), 
            file_name=file.get("file_name"), 
            file_caption=file.get("file_caption"),
            file_path=file.get("file_path", "/"),
            owner_id=file.get("owner_id"),
            modified_date=file.get("modified_date"),
            is_split=file.get("is_split", False),
            total_parts=file.get("total_parts", 1),
            part_size=file.get("part_size"),
            parts=file.get("parts"),
            starred=bool(file.get("starred", False)),
            trashed=bool(file.get("trashed", False)),
            trashed_at=file.get("trashed_at"),
            original_path=file.get("original_path"),
            is_vault=bool(file.get("is_vault", False))
        ) for file in all_items]
    
    def create_folder(self, folder_name: str, current_path: str = "/", owner_id: str = None):
        """Create a folder entry in the database"""
        if not current_path or current_path in ["/", "Home", "/Home"]:
            folder_path = "/Home"
        else:
            folder_path = current_path
        
        return self.add_folder(folder_name, folder_path, owner_id)

    def get_file_by_unique_id(self, file_unique_id: str, owner_id: str = None):
        """Get a file by its unique ID"""
        # Build query with owner filter
        query = {"file_unique_id": file_unique_id}
        if owner_id:
            query["owner_id"] = owner_id
            
        file_data = self.find_one(query)
        if not file_data:
            return None
        
        return FileData(
            id=file_data.get("_id"), 
            chat_id=file_data.get("chat_id"), 
            message_id=file_data.get("message_id"), 
            file_type=file_data.get("file_type"),
            thumbnail=file_data.get("thumbnail"), 
            file_unique_id=file_data.get("file_unique_id"), 
            file_size=file_data.get("file_size"), 
            file_name=file_data.get("file_name"), 
            file_caption=file_data.get("file_caption"),
            file_path=file_data.get("file_path", "/"),
            owner_id=file_data.get("owner_id"),
            modified_date=file_data.get("modified_date"),
            is_split=file_data.get("is_split", False),
            total_parts=file_data.get("total_parts", 1),
            part_size=file_data.get("part_size"),
            parts=file_data.get("parts")
        )

    def check_file_owner(self, file_id: str, owner_id: str) -> bool:
        """Check if a user owns a file or folder"""
        from bson import ObjectId
        
        # Build query with owner filter
        query = {"_id": ObjectId(file_id), "owner_id": owner_id}
        file_data = self.find_one(query)
        return file_data is not None
    
    def check_file_owner_by_unique_id(self, file_unique_id: str, owner_id: str) -> bool:
        """Check if a user owns a file or folder by its unique ID"""
        # Build query with owner filter
        query = {"file_unique_id": file_unique_id, "owner_id": owner_id}
        file_data = self.find_one(query)
        return file_data is not None
    
    def rename_file(self, file_id: str, new_name: str, owner_id: str = None) -> bool:
        """Rename a file or folder"""
        from bson import ObjectId
        
        # Build query with owner filter
        query = {"_id": ObjectId(file_id)}
        if owner_id:
            query["owner_id"] = owner_id
            
        # Find the file/folder by ID
        file_data = self.find_one(query)
        if not file_data:
            return False
            
        # Update the file/folder name and modified date
        result = self.update_one(
            query,
            {"$set": {"file_name": new_name, "modified_date": datetime.utcnow().isoformat()}}
        )
        
        # If this is a folder, we need to update the paths of all contained files
        if file_data.get("file_type") == "folder":
            old_path = file_data.get("file_path", "/")
            folder_name = file_data.get("file_name", "")
            
            # Construct the old full path and new full path
            # The folder's full path is its parent path + "/" + folder name
            if old_path == "/":
                old_full_path = f"/{folder_name}"
            else:
                old_full_path = f"{old_path}/{folder_name}"
                
            # For the new path, we keep the same parent path but change the folder name
            if old_path == "/":
                new_full_path = f"/{new_name}"
            else:
                new_full_path = f"{old_path}/{new_name}"
            
            # Update all files that are directly in this folder (with owner filter)
            folder_update_query = {"file_path": old_full_path}
            if owner_id:
                folder_update_query["owner_id"] = owner_id
                
            self.update_many(
                folder_update_query,
                {"$set": {"file_path": new_full_path, "modified_date": datetime.utcnow().isoformat()}}
            )
            
            # Update files in subfolders (paths that start with old_full_path + "/")
            import re
            regex_pattern = f"^{re.escape(old_full_path)}/"
            
            # Find all files with paths starting with old_full_path + "/" (with owner filter)
            subfolder_query = {"file_path": {"$regex": regex_pattern}}
            if owner_id:
                subfolder_query["owner_id"] = owner_id
                
            subfolder_files = self.find(subfolder_query)
            for file in subfolder_files:
                new_file_path = file["file_path"].replace(old_full_path, new_full_path, 1)
                self.update_one(
                    {"_id": file["_id"]},
                    {"$set": {"file_path": new_file_path, "modified_date": datetime.utcnow().isoformat()}}
                )
        
        return result.modified_count > 0

    def toggle_star(self, file_id: str, owner_id: str = None, starred: bool = None) -> bool:
        """Toggle or set starred status for a file or folder"""
        from bson import ObjectId
        query = {"_id": ObjectId(file_id)}
        if owner_id:
            query["owner_id"] = owner_id
        doc = self.find_one(query)
        if not doc:
            return False
        
        new_starred = starred if starred is not None else not doc.get("starred", False)
        self.update_one(query, {"$set": {"starred": new_starred}})
        return new_starred

    def move_to_trash(self, file_id: str, owner_id: str = None) -> bool:
        """Soft delete a file or folder into trash"""
        from bson import ObjectId
        query = {"_id": ObjectId(file_id)}
        if owner_id:
            query["owner_id"] = owner_id
        doc = self.find_one(query)
        if not doc:
            return False
        
        now = datetime.utcnow().isoformat()
        orig_path = doc.get("file_path", "/")
        self.update_one(query, {
            "$set": {
                "trashed": True,
                "trashed_at": now,
                "original_path": orig_path
            }
        })

        # If it's a folder, also trash all contents
        if doc.get("file_type") == "folder":
            folder_name = (doc.get("file_name") or "").strip()
            # Safety check: Never allow trashing root Home or system folders
            if folder_name.lower() in ["home", "root", "trash", "starred"] and orig_path in ["/", "/Home", "Home", ""]:
                return False
            
            if orig_path in ["/", ""]:
                f_full = f"/Home/{folder_name}"
            elif orig_path.startswith("/Home"):
                f_full = f"{orig_path.rstrip('/')}/{folder_name}"
            else:
                f_full = f"/Home/{orig_path.strip('/')}/{folder_name}"
            
            if f_full in ["/", "/Home", "Home", ""]:
                return False
            
            import re
            content_query = {
                "$or": [
                    {"file_path": f_full},
                    {"file_path": {"$regex": f"^{re.escape(f_full)}/"}}
                ]
            }
            if owner_id:
                content_query["owner_id"] = owner_id
            
            # Store original path and mark trashed
            self.update_many(content_query, {
                "$set": {
                    "trashed": True,
                    "trashed_at": now
                }
            })
        return True

    def restore_from_trash(self, file_id: str, owner_id: str = None) -> bool:
        """Restore a file or folder from trash back to active explorer"""
        from bson import ObjectId
        query = {"_id": ObjectId(file_id)}
        if owner_id:
            query["owner_id"] = owner_id
        doc = self.find_one(query)
        if not doc:
            return False
        
        self.update_one(query, {
            "$set": {"trashed": False},
            "$unset": {"trashed_at": ""}
        })

        # If folder, also restore sub-items
        if doc.get("file_type") == "folder":
            folder_name = doc.get("file_name", "")
            orig_path = doc.get("original_path") or doc.get("file_path", "/")
            if orig_path in ["/", "/Home", "Home"]:
                f_full = f"/Home/{folder_name}"
            else:
                f_full = f"{orig_path.rstrip('/')}/{folder_name}"
            
            import re
            content_query = {
                "$or": [
                    {"file_path": f_full},
                    {"file_path": {"$regex": f"^{re.escape(f_full)}/"}}
                ]
            }
            if owner_id:
                content_query["owner_id"] = owner_id
            
            self.update_many(content_query, {
                "$set": {"trashed": False},
                "$unset": {"trashed_at": ""}
            })
        return True

    def get_storage_analytics(self, owner_id: str = None) -> dict:
        """Calculates total storage used, breakdown by categories, total counts, and largest files"""
        query = {}
        if owner_id:
            query["owner_id"] = owner_id
        
        all_items = list(self.find(query))
        
        total_bytes = 0
        trash_bytes = 0
        trash_count = 0
        starred_count = 0
        total_files = 0
        total_folders = 0

        categories = {
            "video": {"count": 0, "bytes": 0},
            "audio": {"count": 0, "bytes": 0},
            "photo": {"count": 0, "bytes": 0},
            "document": {"count": 0, "bytes": 0},
            "archive": {"count": 0, "bytes": 0},
            "other": {"count": 0, "bytes": 0}
        }

        active_files = []

        archive_exts = {'zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'iso'}
        video_exts = {'mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv', 'm4v', '3gp', 'ts'}
        photo_exts = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'heic'}
        audio_exts = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'opus', 'wma'}
        doc_exts = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'xlsm', 'xlsb', 'ppt', 'pptx', 'txt', 'csv', 'tsv', 'ods', 'epub'}

        for item in all_items:
            is_trashed = bool(item.get("trashed", False))
            is_starred = bool(item.get("starred", False))
            f_type = item.get("file_type")
            f_size = int(item.get("file_size") or 0)
            f_name = item.get("file_name", "") or ""
            ext = f_name.split(".")[-1].lower() if "." in f_name else ""

            if is_starred and not is_trashed:
                starred_count += 1

            if is_trashed:
                trash_count += 1
                trash_bytes += f_size
                continue

            if f_type == "folder":
                total_folders += 1
                continue

            total_files += 1
            total_bytes += f_size
            active_files.append(item)

            if f_type == "video" or ext in video_exts:
                categories["video"]["count"] += 1
                categories["video"]["bytes"] += f_size
            elif f_type in ["audio", "voice"] or ext in audio_exts:
                categories["audio"]["count"] += 1
                categories["audio"]["bytes"] += f_size
            elif f_type == "photo" or ext in photo_exts:
                categories["photo"]["count"] += 1
                categories["photo"]["bytes"] += f_size
            elif ext in archive_exts:
                categories["archive"]["count"] += 1
                categories["archive"]["bytes"] += f_size
            elif f_type == "document" or ext in doc_exts:
                categories["document"]["count"] += 1
                categories["document"]["bytes"] += f_size
            else:
                categories["other"]["count"] += 1
                categories["other"]["bytes"] += f_size

        # Top 10 largest files
        active_files.sort(key=lambda x: int(x.get("file_size") or 0), reverse=True)
        largest_files = [
            {
                "id": str(f.get("_id")),
                "file_unique_id": f.get("file_unique_id"),
                "file_name": f.get("file_name"),
                "file_size": int(f.get("file_size") or 0),
                "file_type": f.get("file_type"),
                "file_path": f.get("file_path"),
                "thumbnail": f.get("thumbnail"),
                "modified_date": f.get("modified_date")
            }
            for f in active_files[:10]
        ]

        return {
            "total_bytes": total_bytes,
            "total_files": total_files,
            "total_folders": total_folders,
            "trash_bytes": trash_bytes,
            "trash_count": trash_count,
            "starred_count": starred_count,
            "by_category": categories,
            "largest_files": largest_files
        }
