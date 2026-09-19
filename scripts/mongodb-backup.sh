#!/bin/bash
set -euo pipefail

# ==============================================================================
# TelegramFileServer - Automated MongoDB Backup Script
# Destination: /mnt/gdrive2/Telegram database backup /
# Retention: Strictly keep the latest 5 backups (auto-delete oldest)
# ==============================================================================

DATE=$(date +"%Y-%m-%d_%H-%M-%S")
CONTAINER_NAME="telegramfileserver-mongo-1"
BACKUP_BASE="/mnt/gdrive2"

# Detect directory (handling potential trailing space in rclone Google Drive mount)
if [ -d "$BACKUP_BASE/Telegram database backup " ]; then
    BACKUP_DIR="$BACKUP_BASE/Telegram database backup "
elif [ -d "$BACKUP_BASE/Telegram database backup" ]; then
    BACKUP_DIR="$BACKUP_BASE/Telegram database backup"
else
    BACKUP_DIR="$BACKUP_BASE/Telegram database backup"
    mkdir -p "$BACKUP_DIR" 2>/dev/null || true
fi

BACKUP_NAME="mongo_backup_${DATE}.archive.gz"
TEMP_FILE="/tmp/${BACKUP_NAME}"
TARGET_FILE="${BACKUP_DIR}/${BACKUP_NAME}"
MAX_BACKUPS=5

echo "========================================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting MongoDB Backup..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Target Destination: $TARGET_FILE"

# 1. Verify Google Drive mount is active
if ! grep -qs "$BACKUP_BASE" /proc/mounts; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Mount point $BACKUP_BASE is not mounted!" >&2
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Directory $BACKUP_DIR does not exist!" >&2
    exit 1
fi

# 2. Verify MongoDB container is running
if ! docker ps --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: MongoDB container '$CONTAINER_NAME' is not running!" >&2
    exit 1
fi

# 3. Perform live compressed dump (point-in-time snapshot, zero downtime)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dumping database from container $CONTAINER_NAME..."
if docker exec "$CONTAINER_NAME" mongodump --archive --gzip > "$TEMP_FILE"; then
    # Verify dumped file is not empty
    if [ -s "$TEMP_FILE" ]; then
        FILE_SIZE=$(du -h "$TEMP_FILE" | cut -f1)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dump created successfully ($FILE_SIZE). Transferring to Google Drive..."
        
        # Copy to Google Drive backup directory
        cp "$TEMP_FILE" "$TARGET_FILE"
        rm -f "$TEMP_FILE"
        
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup successfully written to: $TARGET_FILE"
        
        # 4. Retention Policy: Strictly keep latest 5 backups
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking retention policy (max $MAX_BACKUPS backups)..."
        
        # Sort files by filename in descending order (newest timestamp first)
        # Using find + sort -r ensures consistency regardless of filesystem mtime updates
        ALL_BACKUPS=$(find "$BACKUP_DIR" -maxdepth 1 -name "mongo_backup_*.archive.gz" -type f 2>/dev/null | sort -r || true)
        
        # tail -n +6 grabs the 6th and older backups for deletion
        OLD_BACKUPS=$(echo "$ALL_BACKUPS" | sed '/^$/d' | tail -n +$((MAX_BACKUPS + 1)) || true)
        
        if [ -n "$OLD_BACKUPS" ]; then
            echo "$OLD_BACKUPS" | while IFS= read -r old_file; do
                if [ -n "$old_file" ] && [ -f "$old_file" ]; then
                    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pruning old backup: $(basename "$old_file")"
                    rm -f "$old_file"
                fi
            done
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup count is within limit ($MAX_BACKUPS). No pruning required."
        fi
        
        CURRENT_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -name "mongo_backup_*.archive.gz" -type f 2>/dev/null | wc -l)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Total active backups in Google Drive: $CURRENT_COUNT"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] MongoDB Backup completed successfully!"
        echo "========================================================================"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Dumped file is empty!" >&2
        rm -f "$TEMP_FILE"
        exit 1
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: mongodump execution failed!" >&2
    rm -f "$TEMP_FILE"
    exit 1
fi
