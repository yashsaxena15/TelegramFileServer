#!/bin/bash
set -euo pipefail

# ==============================================================================
# TelegramFileServer - MongoDB Database Restore Script
# Source: /mnt/gdrive2/Telegram database backup /
# Restores compressed .archive.gz directly to Docker MongoDB
# ==============================================================================

CONTAINER_NAME="telegramfileserver-mongo-1"
BACKUP_BASE="/mnt/gdrive2"

if [ -d "$BACKUP_BASE/Telegram database backup " ]; then
    BACKUP_DIR="$BACKUP_BASE/Telegram database backup "
elif [ -d "$BACKUP_BASE/Telegram database backup" ]; then
    BACKUP_DIR="$BACKUP_BASE/Telegram database backup"
else
    echo "ERROR: Backup directory not found on $BACKUP_BASE" >&2
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
    echo "ERROR: MongoDB container '$CONTAINER_NAME' is not running!" >&2
    exit 1
fi

echo "========================================================================"
echo "Available MongoDB Backups in Google Drive:"
echo "========================================================================"

mapfile -t BACKUPS < <(find "$BACKUP_DIR" -maxdepth 1 -name "mongo_backup_*.archive.gz" -type f 2>/dev/null | sort -r || true)

if [ ${#BACKUPS[@]} -eq 0 ]; then
    echo "No backup archives found in $BACKUP_DIR"
    exit 1
fi

i=1
for b in "${BACKUPS[@]}"; do
    size=$(du -h "$b" | cut -f1)
    echo "  [$i] $(basename "$b")  (Size: $size)"
    ((i++))
done
echo "========================================================================"

TARGET_BACKUP=""
if [ -n "${1:-}" ]; then
    if [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le ${#BACKUPS[@]} ]; then
        TARGET_BACKUP="${BACKUPS[$(( $1 - 1 ))]}"
    elif [ -f "$1" ]; then
        TARGET_BACKUP="$1"
    else
        echo "ERROR: Invalid selection '$1'" >&2
        exit 1
    fi
else
    read -r -p "Select backup number to restore [1-${#BACKUPS[@]}] (default 1 = latest, 'q' to quit): " choice
    choice=${choice:-1}
    if [ "$choice" = "q" ] || [ "$choice" = "Q" ]; then
        echo "Restore cancelled by user."
        exit 0
    fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#BACKUPS[@]} ]; then
        TARGET_BACKUP="${BACKUPS[$(( choice - 1 ))]}"
    else
        echo "ERROR: Invalid choice '$choice'" >&2
        exit 1
    fi
fi

echo ""
echo "Selected Backup: $(basename "$TARGET_BACKUP")"
read -r -p "WARNING: This will overwrite/restore MongoDB collections. Proceed? (y/N): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restoring database from $(basename "$TARGET_BACKUP") to $CONTAINER_NAME..."
if docker exec -i "$CONTAINER_NAME" mongorestore --archive --gzip --drop < "$TARGET_BACKUP"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: MongoDB database restored successfully!"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: mongorestore failed!" >&2
    exit 1
fi
