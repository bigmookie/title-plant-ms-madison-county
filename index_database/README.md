# Madison County Title Plant - Index Database

## Overview

This directory contains the **Index Database** - a separate PostgreSQL database that stores pre-existing index data from DuProcess and Historic Deeds sources. This database serves two primary purposes:

1. **Download Queue Management**: Tracks which documents need to be downloaded, their status, and retry information
2. **Production Database Validation**: Provides ground truth data to validate OCR/AI-processed documents in the production database

## Architecture

```
┌─────────────────────────────────────────┐
│         Index Database                  │
│     (Pre-existing Index Data)           │
│                                         │
│  ┌────────────────────────────────┐   │
│  │   index_documents table        │   │
│  │   - DuProcess indexes          │   │
│  │   - Historic Deeds checklist   │   │
│  │   - Download queue status      │   │
│  └────────────────────────────────┘   │
│                                         │
│  Purpose:                               │
│  • Feed document downloader             │
│  • Validate production DB               │
│  • Track download progress              │
└─────────────────────────────────────────┘
             │
             ├──> Document Downloader
             │    (uses index as queue)
             │
             └──> Production DB Validator
                  (compares OCR vs index)

┌─────────────────────────────────────────┐
│      Production Database                │
│   (OCR/AI-Processed Documents)          │
│                                         │
│  Built from scratch via:                │
│  • Document AI OCR                      │
│  • Data extraction                      │
│  • Entity resolution                    │
└─────────────────────────────────────────┘
```

## Data Sources

### 1. DuProcess Indexes (1985-2025)
- **Location**: `madison_docs/DuProcess Indexes/`
- **Format**: ~1000 Excel files, one per date range
- **Fields**: 54 columns including:
  - Document identification (book, page, instrument type)
  - Parties (grantor, grantee)
  - Legal descriptions (lot, block, section-township-range)
  - Recording dates and metadata
  - Quarter section breakdowns
  - Modern identifiers (parcel numbers, addresses)

### 2. Historic Deeds Checklist
- **Location**: `madison_docs/Deeds - Historic - Typewritten Only.xlsx`
- **Format**: Simple book/page list
- **Purpose**: Download checklist for historical documents
- **Fields**: book, page only (all other fields NULL)

## Database Schema

### Main Table: `index_documents`

```sql
CREATE TABLE index_documents (
    id BIGSERIAL PRIMARY KEY,

    -- Source tracking
    source VARCHAR(50) NOT NULL,  -- 'DuProcess' or 'Historical'
    source_file VARCHAR(500),
    import_date TIMESTAMP,

    -- Document identification
    book INTEGER NOT NULL,
    page INTEGER NOT NULL,
    instrument_type_parsed VARCHAR(100),
    document_type VARCHAR(100),  -- Mapped enum value

    -- Download queue management
    download_status VARCHAR(50) DEFAULT 'pending',
    download_attempts INTEGER DEFAULT 0,
    downloaded_at TIMESTAMP,
    gcs_path TEXT,

    -- ... 54 total columns from DuProcess spec
);
```

See [`schema/index_database_schema.sql`](schema/index_database_schema.sql) for complete schema.

## Setup Instructions

### Prerequisites

1. **GCP Project**: `madison-county-title-plant`
2. **Cloud SQL Instance**: Already running in `us-south1`
3. **gcloud CLI**: Installed and authenticated
4. **Python 3.8+**: For import scripts
5. **WSL (Windows)**: For running proxy and scripts

### Step 1: Install Python Dependencies

```bash
cd database
pip install -r requirements.txt
```

### Step 2: Download Cloud SQL Auth Proxy

```bash
cd database
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.19.0/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy
```

### Step 3: Authenticate with Google Cloud

```bash
# User authentication
gcloud auth login

# Application Default Credentials (recommended)
gcloud auth application-default login

# Set project
gcloud config set project madison-county-title-plant
```

### Step 4: Create Database and Apply Schema

```bash
cd database
./setup_index_database.sh
```

This script will:
- Create the `madison_county_index` database
- Apply the schema from `schema/index_database_schema.sql`
- Create an application user with credentials
- Grant appropriate permissions
- Display connection information

**Important**: The script will save credentials to `index_database/.db_credentials`. Keep this file secure!

### Step 5: Start Cloud SQL Auth Proxy

In a **separate terminal** (keep it running):

```bash
cd database
./start_proxy.sh
```

This starts the proxy on `127.0.0.1:5432`, allowing local connections to Cloud SQL.

### Step 6: Import Index Data

In your **main terminal**:

```bash
cd database

# Load credentials
source .db_credentials

# Run import
python3 import_index_data.py
```

This will:
- Load all ~1000 DuProcess Excel files
- Load Historic Deeds checklist
- Parse instrument types using DUPROCESS_TYPE_MAPPING
- Insert ~1 million+ records into the database
- Display progress bars and summary statistics

**Expected Runtime**: 30-60 minutes depending on system performance.

## Usage

### Connecting to the Database

#### Via psql (Command Line)

```bash
# Start proxy first (in separate terminal)
./start_proxy.sh

# Connect with psql
psql -h 127.0.0.1 -p 5432 -U madison_index_app -d madison_county_index
```

#### Via Python (Application Code)

```python
import psycopg2
import os

conn = psycopg2.connect(
    host='127.0.0.1',
    port=5432,
    database='madison_county_index',
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)

cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM index_documents")
count = cursor.fetchone()[0]
print(f"Total records: {count:,}")
```

#### Via gcloud CLI (Direct Connection)

```bash
gcloud sql connect madison-county-title-plant \
    --user=postgres \
    --database=madison_county_index
```

### Querying the Database

#### Get Download Queue Status

```sql
SELECT * FROM download_queue_summary;
```

#### Find Documents to Download

```sql
SELECT book, page, instrument_type_parsed
FROM index_documents
WHERE download_status = 'pending'
ORDER BY book, page
LIMIT 100;
```

#### Search by Document Type

```sql
SELECT COUNT(*), document_type
FROM index_documents
WHERE document_type IS NOT NULL
GROUP BY document_type
ORDER BY COUNT(*) DESC;
```

#### Find Documents by Party Name

```sql
SELECT book, page, grantor_party, grantee_party, file_date
FROM index_documents
WHERE grantor_party ILIKE '%SMITH%'
   OR grantee_party ILIKE '%SMITH%'
ORDER BY file_date DESC
LIMIT 20;
```

#### Check Import Progress

```sql
SELECT
    source,
    COUNT(*) as total_records,
    MIN(book) as min_book,
    MAX(book) as max_book
FROM index_documents
GROUP BY source;
```

#### Query Related Items (Cross-References)

```sql
-- Find documents with related items
SELECT book, page, related_items
FROM index_documents
WHERE related_items IS NOT NULL
  AND jsonb_array_length(related_items) > 0
LIMIT 10;

-- Count related items per document
SELECT
    jsonb_array_length(related_items) as num_references,
    COUNT(*) as document_count
FROM index_documents
WHERE related_items IS NOT NULL
GROUP BY num_references
ORDER BY num_references;

-- Find documents referenced by a specific document
SELECT
    ref->>'instrument_number' as ref_instrument,
    ref->>'book' as ref_book,
    ref->>'page' as ref_page,
    ref->>'exists_in_db' as found,
    ref->>'target_id' as target_doc_id
FROM index_documents,
     jsonb_array_elements(related_items) as ref
WHERE book = 3948 AND page = 776;

-- Find all documents that reference a specific book/page
SELECT
    d.id,
    d.book as source_book,
    d.page as source_page,
    d.instrument_type_parsed,
    ref->>'instrument_number' as ref_instrument
FROM index_documents d,
     jsonb_array_elements(d.related_items) as ref
WHERE ref->>'book' = '4002'
  AND ref->>'page' = '839';
```

### Updating Download Status

```python
# Mark document as downloaded
cursor.execute("""
    UPDATE index_documents
    SET download_status = 'completed',
        downloaded_at = CURRENT_TIMESTAMP,
        gcs_path = %s
    WHERE book = %s AND page = %s
""", (gcs_path, book, page))
conn.commit()
```

## File Structure

```
index_database/
├── README.md                          # This file
├── requirements.txt                   # Python dependencies
│
├── schema/
│   └── index_database_schema.sql     # Complete database schema
│
├── setup_index_database.sh           # Database setup script
├── start_proxy.sh                    # Cloud SQL Auth Proxy helper
├── import_index_data.py              # Initial data import script (all files)
├── update_index_data.py              # Incremental update script (new files only)
│
├── .db_credentials                   # Database credentials (DO NOT COMMIT)
├── .last_import_time                 # Tracking file for auto-updates (generated)
├── .proxy.pid                        # Proxy process ID (generated)
├── cloud-sql-proxy                   # Proxy binary (download separately)
├── cloud-sql-proxy.log              # Proxy logs
├── index_import.log                 # Import script logs
└── index_update.log                 # Update script logs
```

## Maintenance

### Updating with New Data

When new DuProcess Excel files are added, use the update script for incremental imports:

```bash
cd index_database
source .db_credentials

# Import specific file
python3 update_index_data.py --file "madison_docs/DuProcess Indexes/2025-04-01.xlsx"

# Import files matching pattern
python3 update_index_data.py --pattern "2025-04-*.xlsx"

# Auto-import all files modified since last import
python3 update_index_data.py --auto

# Dry run to preview changes
python3 update_index_data.py --auto --dry-run
```

**Features:**
- **Conflict Handling**: Automatically updates existing records if source file is newer
- **Tracking**: Maintains `.last_import_time` file for `--auto` mode
- **Statistics**: Shows before/after comparison of database state
- **Logging**: All operations logged to `index_update.log`

### Re-importing All Data

If you need to re-import (e.g., after schema changes):

```bash
# Drop and recreate database
gcloud sql databases delete madison_county_index --instance=madison-county-title-plant
./setup_index_database.sh

# Re-import data
source .db_credentials
python3 import_index_data.py
```

### Backup and Restore

```bash
# Export to SQL file
gcloud sql export sql madison-county-title-plant \
    gs://madison-county-title-plant/backups/index_db_$(date +%Y%m%d).sql \
    --database=madison_county_index

# Import from SQL file
gcloud sql import sql madison-county-title-plant \
    gs://madison-county-title-plant/backups/index_db_YYYYMMDD.sql \
    --database=madison_county_index
```

### Monitoring

```bash
# Check database size
gcloud sql instances describe madison-county-title-plant \
    --format="value(settings.dataDiskSizeGb)"

# View recent connections
gcloud sql operations list --instance=madison-county-title-plant \
    --limit=10

# Check proxy logs
tail -f cloud-sql-proxy.log
```

## Troubleshooting

### "Database connection failed"

**Issue**: Cannot connect to database via proxy.

**Solutions**:
1. Verify proxy is running: `ps aux | grep cloud-sql-proxy`
2. Check proxy logs: `cat cloud-sql-proxy.log`
3. Verify authentication: `gcloud auth list`
4. Test connection: `gcloud sql connect madison-county-title-plant --user=postgres`

### "Permission denied" errors

**Issue**: Database user lacks permissions.

**Solution**:
```bash
# Re-run grants
gcloud sql connect madison-county-title-plant --user=postgres --database=madison_county_index
# Then run:
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO madison_index_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO madison_index_app;
```

### "Excel file not found" during import

**Issue**: Import script cannot find Excel files.

**Solution**:
- Verify file paths in `import_index_data.py`:
  - `DUPROCESS_DIR = BASE_DIR / 'madison_docs' / 'DuProcess Indexes'`
  - `HISTORIC_DEEDS_FILE = BASE_DIR / 'madison_docs' / 'Deeds - Historic - Typewritten Only.xlsx'`
- Ensure files exist in correct locations
- Check file permissions

### Import script crashes or hangs

**Issue**: Import fails partway through.

**Solutions**:
1. Check logs: `tail -f index_import.log`
2. Verify database has enough storage
3. Check for corrupted Excel files
4. Re-run import (script uses `ON CONFLICT` to handle duplicates)

### "Too many connections" error

**Issue**: Cloud SQL connection limit reached.

**Solution**:
```bash
# Close unused connections
gcloud sql instances patch madison-county-title-plant \
    --database-flags max_connections=200

# Kill idle connections in database
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'madison_county_index'
AND state = 'idle'
AND state_change < NOW() - INTERVAL '1 hour';
```

## Security Notes

1. **Credentials**: Never commit `.db_credentials` to version control
2. **Proxy**: Always use Cloud SQL Auth Proxy for connections
3. **Permissions**: Follow principle of least privilege for database users
4. **Backups**: Enable automated backups (already configured)
5. **Logs**: Review `cloud-sql-proxy.log` and `index_import.log` regularly

## Next Steps

After setting up the index database:

1. **Document Downloader Integration**
   - Query `index_documents` for pending downloads
   - Update `download_status` as documents are processed
   - Track `download_attempts` for retry logic

2. **Production Database Validation**
   - Compare OCR-extracted data against index data
   - Flag discrepancies for manual review
   - Calculate match confidence scores

3. **Analytics and Reporting**
   - Use materialized views for performance
   - Generate download progress reports
   - Track document type distributions

## Support

For issues or questions:
1. Check this README and troubleshooting section
2. Review logs (`index_import.log`, `cloud-sql-proxy.log`)
3. Consult the specs:
   - [`specs/master-spec.md`](../specs/master-spec.md)
   - [`specs/storage-spec.md`](../specs/storage-spec.md)
   - [`specs/data-models-spec.md`](../specs/data-models-spec.md)
