#!/bin/bash
# Madison County Title Plant - Database Restore Script
#
# Restores a PostgreSQL backup from local file or GCS.
#
# Usage:
#   ./scripts/restore_database.sh backups/madison_county_backup_20260125.sql
#   ./scripts/restore_database.sh gs://madison-county-title-plant/backups/madison_county_backup_final_20260125.sql

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load database credentials
if [ -f "$PROJECT_DIR/index_database/.db_credentials" ]; then
    source "$PROJECT_DIR/index_database/.db_credentials"
else
    echo "Error: Credentials file not found"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file_or_gcs_path>"
    echo ""
    echo "Examples:"
    echo "  $0 backups/madison_county_backup_20260125.sql"
    echo "  $0 gs://madison-county-title-plant/backups/madison_county_backup_final_20260125.sql"
    exit 1
fi

BACKUP_SOURCE="$1"
TEMP_FILE=""

echo "============================================"
echo "Madison County Database Restore"
echo "============================================"
echo "Source: $BACKUP_SOURCE"
echo "Database: $DB_NAME"
echo ""

# Download from GCS if needed
if [[ "$BACKUP_SOURCE" == gs://* ]]; then
    echo "Downloading from GCS..."
    TEMP_FILE="/tmp/madison_restore_$(date +%s).sql"
    gcloud storage cp "$BACKUP_SOURCE" "$TEMP_FILE"
    BACKUP_FILE="$TEMP_FILE"
else
    BACKUP_FILE="$BACKUP_SOURCE"
fi

# Check if file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Confirm before restore
echo "WARNING: This will overwrite the existing database!"
read -p "Continue? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    [ -n "$TEMP_FILE" ] && rm -f "$TEMP_FILE"
    exit 0
fi

# Determine file format and restore
echo ""
echo "Restoring database..."

# Check if it's a custom format (pg_dump -Fc) or plain SQL
FILE_TYPE=$(file "$BACKUP_FILE" | grep -o "PostgreSQL custom database dump" || echo "")

if [ -n "$FILE_TYPE" ]; then
    # Custom format - use pg_restore
    PGPASSWORD="$DB_PASSWORD" pg_restore \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --clean \
        --if-exists \
        "$BACKUP_FILE" 2>&1 || true
else
    # Plain SQL format - use psql
    PGPASSWORD="$DB_PASSWORD" psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -f "$BACKUP_FILE"
fi

# Cleanup temp file
[ -n "$TEMP_FILE" ] && rm -f "$TEMP_FILE"

# Verify
echo ""
echo "Verifying restore..."
RECORD_COUNT=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM index_documents;")
echo "Records in database: $RECORD_COUNT"

echo ""
echo "============================================"
echo "Restore complete!"
echo "============================================"
