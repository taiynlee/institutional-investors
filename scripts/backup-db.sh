#!/usr/bin/env bash
# PostgreSQL daily backup — pg_dump inside db container → local .sql.gz
# Keeps last 7 backups. Run via systemd timer (daily 02:00).

set -euo pipefail

BACKUP_DIR="/home/tommy0322/institutional-investors/backups"
CONTAINER="institutional-investors-db-1"
DB_USER="stock"
DB_NAME="stock_force"
KEEP=7

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/stock_force_${TIMESTAMP}.sql.gz"

docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup OK: $FILE ($(du -sh "$FILE" | cut -f1))"

# Remove old backups, keep last $KEEP files
ls -t "$BACKUP_DIR"/stock_force_*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup done (kept last $KEEP backups)"
