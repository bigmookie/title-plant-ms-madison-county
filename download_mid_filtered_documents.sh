#!/bin/bash
# Download MID Portal Filtered Documents (Books 238-3971)
# Madison County Title Plant Project
#
# This script downloads only specific document types from the MID portal
# using parallel processing for improved performance.

set -e  # Exit on error

echo "=========================================="
echo "MID Portal Filtered Documents Download"
echo "=========================================="
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
  AND column_name IN ('actual_book', 'actual_page', 'book_page_mismatch', 'download_priority', 'instrument_type_parsed')
")

if [ "$SCHEMA_CHECK" -ne 5 ]; then
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
echo "=========================================="
echo "MID Portal Filtered Documents Statistics"
echo "=========================================="
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -c "
SELECT
    'MID Portal Filtered (Books 238-3971)' as scope,
    COUNT(*) as total_documents,
    MIN(book) as first_book,
    MAX(book) as last_book,
    COUNT(DISTINCT book) as unique_books,
    COUNT(DISTINCT instrument_type_parsed) as unique_doc_types,
    COUNT(*) FILTER (WHERE download_status = 'pending') as pending,
    COUNT(*) FILTER (WHERE download_status = 'completed') as completed,
    COUNT(*) FILTER (WHERE download_status = 'failed') as failed
FROM index_documents
WHERE book >= 238 AND book < 3972
  AND instrument_type_parsed IN (
    'DEED', 'RIGHT OF WAY', 'EASEMENT', 'TRUSTEES DEED', 'TRUST AGREEMENT',
    'SUBDIVISION PLATS', 'JUDGMENT OR ORDER', 'MISCELLANEOUS', 'MINERAL DEED',
    'AGREEMENT', 'PROTECTIVE COVENANT', 'HEIRSHIP', 'AGREEMENT-DEEDS',
    'ASSIGN OIL GAS  MIN', 'MINERAL RIGHT  ROYA', 'AMENDED PROTECTIVE C',
    'PATENT', 'AMENDMENT(T)', 'DEED RESTRICTIONS', 'REVOCATION  CANCELL',
    'AMENDMENT TO LEASE', 'SUPPLEMENT', 'AFFIDAVIT \"T\"', 'NOTICE TO RENEW LEAS',
    'TAX DEED', 'Transfer on Death Deed', 'OPTION', 'DECLARATION',
    'MISCELLANEOUS \"T\"', 'CONTRACT TO SELL', 'LAST WILL AND TESTAM',
    'EMINENT DOMAIN', 'WAIVER', 'AMENDED DECLARATION', 'SUPPLEMENT TO COVENA',
    'DECLARATION OF ROAD', 'SEALED', 'ROYALTY DEED', 'RECISSION OF FORECLO',
    'CORRECTION OF PLAT', 'PROTECTIVE COV TERMI', 'AMENDMENT(W)', 'LIVING WILL',
    'VOID LEASES 16TH SEC', 'MISCELLANEOUS \"C\"', 'RECEIVER', 'MAP',
    'ARCHITECTURAL REVIEW', 'SURVEYS', 'ENVIRONMENTAL PROTEC', 'CERT OF SALESEIZED',
    'LEASE ASSIGNMENT', 'ASSIGNMENT OF LEASES', 'LEASE CONTRACT', '- [DEED 90W]'
  );
"

# 7. Document type breakdown
echo ""
echo "=========================================="
echo "Document Type Breakdown (Top 20)"
echo "=========================================="
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -c "
SELECT
    instrument_type_parsed as document_type,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE download_status = 'pending') as pending,
    COUNT(*) FILTER (WHERE download_status = 'completed') as completed,
    ROUND(COUNT(*) FILTER (WHERE download_status = 'completed') * 100.0 / COUNT(*), 1) as pct_complete
FROM index_documents
WHERE book >= 238 AND book < 3972
  AND instrument_type_parsed IN (
    'DEED', 'RIGHT OF WAY', 'EASEMENT', 'TRUSTEES DEED', 'TRUST AGREEMENT',
    'SUBDIVISION PLATS', 'JUDGMENT OR ORDER', 'MISCELLANEOUS', 'MINERAL DEED',
    'AGREEMENT', 'PROTECTIVE COVENANT', 'HEIRSHIP', 'AGREEMENT-DEEDS',
    'ASSIGN OIL GAS  MIN', 'MINERAL RIGHT  ROYA', 'AMENDED PROTECTIVE C',
    'PATENT', 'AMENDMENT(T)', 'DEED RESTRICTIONS', 'REVOCATION  CANCELL',
    'AMENDMENT TO LEASE', 'SUPPLEMENT', 'AFFIDAVIT \"T\"', 'NOTICE TO RENEW LEAS',
    'TAX DEED', 'Transfer on Death Deed', 'OPTION', 'DECLARATION',
    'MISCELLANEOUS \"T\"', 'CONTRACT TO SELL', 'LAST WILL AND TESTAM',
    'EMINENT DOMAIN', 'WAIVER', 'AMENDED DECLARATION', 'SUPPLEMENT TO COVENA',
    'DECLARATION OF ROAD', 'SEALED', 'ROYALTY DEED', 'RECISSION OF FORECLO',
    'CORRECTION OF PLAT', 'PROTECTIVE COV TERMI', 'AMENDMENT(W)', 'LIVING WILL',
    'VOID LEASES 16TH SEC', 'MISCELLANEOUS \"C\"', 'RECEIVER', 'MAP',
    'ARCHITECTURAL REVIEW', 'SURVEYS', 'ENVIRONMENTAL PROTEC', 'CERT OF SALESEIZED',
    'LEASE ASSIGNMENT', 'ASSIGNMENT OF LEASES', 'LEASE CONTRACT', '- [DEED 90W]'
  )
GROUP BY instrument_type_parsed
ORDER BY total DESC
LIMIT 20;
"

echo ""
echo "=========================================="
echo "Ready to Start Parallel Download"
echo "=========================================="
echo ""
echo "This will:"
echo "  1. Download MID portal documents (Books 238-3971)"
echo "  2. Filter to specific document types only"
echo "  3. Use parallel processing (5 workers by default)"
echo "  4. Optimize each PDF (50-70% compression)"
echo "  5. Upload to GCS bucket: ${GCS_BUCKET_NAME:-madison-county-title-plant}"
echo "  6. Delete local files after upload"
echo "  7. Track progress in database"
echo ""
echo "Parallel Processing Benefits:"
echo "  - 5x faster than sequential downloads"
echo "  - Better resource utilization"
echo "  - Automatic retry and error handling"
echo ""
echo "You can adjust workers with: --workers N"
echo "Recommended: 5-10 workers for optimal performance"
echo ""

# Parse command line arguments
WORKERS=5
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--workers N] [--dry-run]"
            exit 1
            ;;
    esac
done

echo "Configuration:"
echo "  Workers: $WORKERS"
if [ -n "$DRY_RUN" ]; then
    echo "  Mode: DRY RUN (no actual downloads)"
fi
echo ""

read -p "Start download? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Download cancelled"
    exit 0
fi

# 8. Start download
echo ""
echo "=========================================="
echo "Starting Parallel Download"
echo "=========================================="
echo ""

cd madison_county_doc_puller

python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers $WORKERS $DRY_RUN

echo ""
echo "=========================================="
echo "Download Complete!"
echo "=========================================="
