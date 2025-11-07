# Quick Start: Historical Documents Download

## Setup Checklist

### 1. Install Ghostscript
```bash
sudo apt-get update
sudo apt-get install ghostscript
gs --version  # Verify
```

### 2. Set Up GCS Credentials
```bash
# Set environment variables (add to ~/.bashrc for persistence)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/gcs-credentials.json"
export GCS_BUCKET_NAME="madison-county-title-plant"

# Reload
source ~/.bashrc
```

### 3. Verify Database
```bash
cd index_database
source .db_credentials

# Run migrations (if not done already)
psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f add_validation_columns.sql
psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f add_download_priority.sql
```

## Start Downloading Historical Documents

### Option 1: Test First (Recommended)
```bash
cd madison_county_doc_puller
source ../index_database/.db_credentials

# Dry run (no actual download)
python3 staged_downloader.py --stage stage-0-test --dry-run

# Real test (20 documents)
python3 staged_downloader.py --stage stage-0-test
```

### Option 2: Download All Historical Books (Books 1-237)
```bash
cd madison_county_doc_puller
source ../index_database/.db_credentials

# This will download ALL historical records
python3 staged_downloader.py --stage stage-historical-all
```

**Note**: This may take 12-24 hours for ~50,000 documents. You can resume if interrupted:
```bash
python3 staged_downloader.py --stage stage-historical-all --resume
```

### Option 3: Download Single Book (for testing)

Query to find a specific book:
```bash
source ../index_database/.db_credentials
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -c "
SELECT book, COUNT(*) as pages
FROM index_documents
WHERE book >= 1 AND book < 238
  AND download_status = 'pending'
GROUP BY book
ORDER BY book
LIMIT 10;
"
```

Then download that specific book (requires code modification - see below).

## What Happens During Download

1. **Download**: PDF from Madison County portal (~0.5-1 second)
2. **Validate**: Book/page numbers from HTML response
3. **Optimize**: Ghostscript compression (50-70% reduction)
4. **Upload**: To GCS bucket with metadata
5. **Update**: Database with gcs_path and validation data
6. **Cleanup**: Delete local file

## Monitor Progress

### Real-time Progress
Watch the terminal output:
```
Downloading: 45%|████████▌         | 450/1000 [15:00<18:20, 1.5s/doc]
```

### Check Database
```bash
source index_database/.db_credentials
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$DB_USER" -d madison_county_index -c "
SELECT
    download_status,
    COUNT(*) as count,
    COUNT(*) FILTER (WHERE book < 238) as historical,
    COUNT(*) FILTER (WHERE gcs_path IS NOT NULL) as uploaded
FROM index_documents
GROUP BY download_status;
"
```

### Check GCS Bucket
```bash
# List uploaded files
gsutil ls gs://madison-county-title-plant/documents/historical/ | head -20

# Count files
gsutil ls -r gs://madison-county-title-plant/documents/historical/ | wc -l

# Check storage size
gsutil du -sh gs://madison-county-title-plant
```

## Expected Performance

### Stage 0 Test (20 docs)
- Duration: 1-2 minutes
- Storage: ~0.5-1 MB
- Mismatch rate: 0-15%

### Historical Books Complete (~50,000 docs)
- Duration: 12-24 hours
- Original size: ~10-15 GB
- Optimized size: ~3-5 GB
- Storage savings: ~7-10 GB

## Troubleshooting

### "Ghostscript not found"
```bash
sudo apt-get install ghostscript
```

### "Failed to initialize GCS"
```bash
# Check environment
echo $GOOGLE_APPLICATION_CREDENTIALS
cat $GOOGLE_APPLICATION_CREDENTIALS | head -5

# Verify bucket
gsutil ls gs://madison-county-title-plant
```

### "column does not exist"
```bash
# Run migrations as postgres user
psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f index_database/add_validation_columns.sql
psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f index_database/add_download_priority.sql
```

### Resume Interrupted Download
```bash
python3 staged_downloader.py --stage stage-historical-all --resume
```

## Complete Workflow Example

```bash
# 1. Set up environment
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/gcs-credentials.json"
export GCS_BUCKET_NAME="madison-county-title-plant"

# 2. Navigate to directory
cd /mnt/c/Users/gardn/Documents/Projects/title-plant-ms-madison-county/madison_county_doc_puller

# 3. Load database credentials
source ../index_database/.db_credentials

# 4. Test with dry run
python3 staged_downloader.py --stage stage-0-test --dry-run

# 5. Run actual test
python3 staged_downloader.py --stage stage-0-test

# 6. Verify uploads
gsutil ls gs://madison-county-title-plant/documents/historical/

# 7. Start full historical download
python3 staged_downloader.py --stage stage-historical-all
```

## Final Output

When complete, you'll see:
```
================================================================================
DOWNLOAD STATISTICS
================================================================================
Duration:          14.5 hours
Total attempted:   50,000
Completed:         49,850
Failed:            150
Success rate:      99.7%
Docs/hour:         3,441.4

Validation:
  Mismatches:      5,234 (10.5%)

Storage Optimization:
  Original size:   12,450.5 MB
  Optimized size:  3,735.2 MB
  Saved:           8,715.3 MB (70.0%)

By Portal:
  historical      49,850
================================================================================
```

All files will be in GCS at:
```
gs://madison-county-title-plant/documents/historical/deed/
gs://madison-county-title-plant/documents/historical/deed-of-trust/
gs://madison-county-title-plant/documents/historical/mortgage/
...
```

Ready to start! 🚀
