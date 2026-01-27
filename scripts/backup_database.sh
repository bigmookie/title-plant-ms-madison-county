#!/bin/bash
# Madison County Title Plant - Database Backup Script
#
# Creates a local PostgreSQL backup and optionally uploads to GCS.
#
# Usage:
#   ./scripts/backup_database.sh              # Local backup only
#   ./scripts/backup_database.sh --upload     # Local backup + upload to GCS

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="madison_county_backup_${TIMESTAMP}.sql"
GCS_BUCKET="gs://madison-county-title-plant/backups"

# Load database credentials
if [ -f "$PROJECT_DIR/index_database/.db_credentials" ]; then
    source "$PROJECT_DIR/index_database/.db_credentials"
else
    echo "Error: Credentials file not found at $PROJECT_DIR/index_database/.db_credentials"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "============================================"
echo "Madison County Database Backup"
echo "============================================"
echo "Timestamp: $TIMESTAMP"
echo "Database: $DB_NAME"
echo ""

# Create backup
echo "Creating backup..."
PGPASSWORD="$DB_PASSWORD" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -F c \
    -f "$BACKUP_DIR/$BACKUP_FILE"

# Get file size
BACKUP_SIZE=$(ls -lh "$BACKUP_DIR/$BACKUP_FILE" | awk '{print $5}')
echo "Backup created: $BACKUP_DIR/$BACKUP_FILE ($BACKUP_SIZE)"

# Upload to GCS if requested
if [ "$1" == "--upload" ]; then
    echo ""
    echo "Uploading to GCS..."
    gcloud storage cp "$BACKUP_DIR/$BACKUP_FILE" "$GCS_BUCKET/$BACKUP_FILE"
    echo "Uploaded to: $GCS_BUCKET/$BACKUP_FILE"
fi

# Clean up old local backups (keep last 5)
echo ""
echo "Cleaning up old backups (keeping last 5)..."
ls -t "$BACKUP_DIR"/madison_county_backup_*.sql 2>/dev/null | tail -n +6 | xargs -r rm -v

echo ""
echo "============================================"
echo "Backup complete!"
echo "============================================"
