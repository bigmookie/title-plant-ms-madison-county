#!/bin/bash
# Download All Historical Documents (Books 1-237)
# Madison County Title Plant Project

set -e  # Exit on error

echo "=================================="
echo "Historical Documents Download"
echo "=================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# 1. Check Ghostscript
if ! command -v gs &> /dev/null; then
    echo "❌ Ghostscript not found"
    echo "Install with: sudo apt-get install ghostscript"
    exit 1
fi
echo "✓ Ghostscript installed: $(gs --version 2>&1 | head -1)"

# 2. Check GCS credentials
if [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "❌ GOOGLE_APPLICATION_CREDENTIALS not set"
    echo "Set with: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json"
    exit 1
fi

if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "❌ GCS credentials file not found: $GOOGLE_APPLICATION_CREDENTIALS"
    exit 1
fi
echo "✓ GCS credentials: $GOOGLE_APPLICATION_CREDENTIALS"

# 3. Check database credentials
if [ ! -f "index_database/.db_credentials" ]; then
    echo "❌ Database credentials not found: index_database/.db_credentials"
    exit 1
fi
echo "✓ Database credentials found"

# Load database credentials
source index_database/.db_credentials

# 4. Test database connection
echo "✓ Testing database connection..."
if ! PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -c "\q" 2>/dev/null; then
    echo "❌ Database connection failed"
    exit 1
fi
echo "✓ Database connection successful"

# 5. Check required columns exist
echo "✓ Checking database schema..."
SCHEMA_CHECK=$(PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -t -c "
SELECT COUNT(*)
FROM information_schema.columns
WHERE table_name='index_documents'
  AND column_name IN ('actual_book', 'actual_page', 'book_page_mismatch', 'download_priority')
")

if [ "$SCHEMA_CHECK" -ne 4 ]; then
    echo "⚠️  Missing database columns. Running migrations..."

    # Run migrations as postgres user (will prompt for password)
    echo "Please enter postgres password when prompted:"
    psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f index_database/add_validation_columns.sql
    psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f index_database/add_download_priority.sql

    echo "✓ Migrations completed"
fi
echo "✓ Database schema ready"

# 6. Show statistics
echo ""
echo "=================================="
echo "Historical Documents Statistics"
echo "=================================="
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -c "
SELECT
    'Historical Books (1-237)' as scope,
    COUNT(*) as total_documents,
    MIN(book) as first_book,
    MAX(book) as last_book,
    COUNT(DISTINCT book) as unique_books,
    COUNT(*) FILTER (WHERE download_status = 'pending') as pending,
    COUNT(*) FILTER (WHERE download_status = 'completed') as completed,
    COUNT(*) FILTER (WHERE download_status = 'failed') as failed
FROM index_documents
WHERE book >= 1 AND book < 238;
"

echo ""
echo "=================================="
echo "Ready to Start Download"
echo "=================================="
echo ""
echo "This will:"
echo "  1. Download all historical documents (Books 1-237)"
echo "  2. Optimize each PDF (50-70% compression)"
echo "  3. Upload to GCS bucket: ${GCS_BUCKET_NAME:-madison-county-title-plant}"
echo "  4. Delete local files after upload"
echo "  5. Track progress in database"
echo ""
echo "Estimated time: 12-24 hours"
echo "You can resume if interrupted with: --resume flag"
echo ""

read -p "Start download? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Download cancelled"
    exit 0
fi

# 7. Start download
echo ""
echo "=================================="
echo "Starting Download"
echo "=================================="
echo ""

cd madison_county_doc_puller

python3 staged_downloader.py --stage stage-historical-all

echo ""
echo "=================================="
echo "Download Complete!"
echo "=================================="
