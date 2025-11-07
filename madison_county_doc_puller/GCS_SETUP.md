# GCS Upload & PDF Optimization Setup Guide

## Overview

The staged downloader now includes:
- **GCS Upload**: Automatic upload to Google Cloud Storage
- **PDF Optimization**: Ghostscript compression (50-70% file size reduction)
- **Automatic Cleanup**: Local files deleted after upload

## Prerequisites

### 1. Install Ghostscript

Ghostscript is required for PDF optimization:

```bash
# Ubuntu/Debian/WSL
sudo apt-get update
sudo apt-get install ghostscript

# Verify installation
gs --version
```

**Expected output**: `GPL Ghostscript 9.x.x`

### 2. Set Up Google Cloud Storage

#### A. Create GCS Bucket (if not exists)

```bash
# Install gcloud CLI if needed
# https://cloud.google.com/sdk/docs/install

# Create bucket
gsutil mb -l US gs://madison-county-title-plant

# Verify
gsutil ls gs://madison-county-title-plant
```

#### B. Create Service Account & Download Credentials

1. Go to Google Cloud Console
2. Navigate to **IAM & Admin > Service Accounts**
3. Click **Create Service Account**
   - Name: `madison-county-downloader`
   - Description: `Service account for document downloads`
4. Grant role: **Storage Object Admin**
5. Click **Create Key** → JSON format
6. Save as `gcs-credentials.json` in a secure location

#### C. Set Environment Variable

```bash
# Add to your ~/.bashrc or ~/.zshrc
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/gcs-credentials.json"
export GCS_BUCKET_NAME="madison-county-title-plant"

# For current session
source ~/.bashrc

# Verify
echo $GOOGLE_APPLICATION_CREDENTIALS
```

**For WSL/Ubuntu**, add to `~/.bashrc`:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/mnt/c/Users/YOUR_USERNAME/gcs-credentials.json"
export GCS_BUCKET_NAME="madison-county-title-plant"
```

### 3. Test GCS Connection

```bash
cd madison_county_doc_puller

# Test GCS connection
python3 -c "
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd().parent / 'madison_title_plant'))
from storage.gcs_manager import GCSManager

manager = GCSManager('madison-county-title-plant')
print('✓ GCS connection successful!')
print(f'Bucket: {manager.bucket.name}')
"
```

### 4. Test PDF Optimizer

```bash
# Test with existing downloaded PDF
python3 pdf_optimizer.py downloads/0285-0055.pdf

# Expected output:
# ✓ Success!
#   Input:     downloads/0285-0055.pdf
#   Output:    downloads/0285-0055_optimized.pdf
#   Original:  30,720 bytes
#   Optimized: 15,360 bytes
#   Savings:   50.0%
```

## Usage

### Dry Run (Test Without Upload)

```bash
cd madison_county_doc_puller

# Load database credentials
source ../index_database/.db_credentials

# Test run (no actual download/upload)
python3 staged_downloader.py --stage stage-0-test --dry-run
```

**Expected Output:**
```
✓ Connected to database
✓ Connected to GCS bucket: madison-county-title-plant
✓ PDF optimizer initialized
DRY RUN MODE - No actual downloads will be performed
```

### Production Run

```bash
# Run Stage 0 test (20 documents with real upload)
python3 staged_downloader.py --stage stage-0-test

# Download all historical records (Books 1-237)
python3 staged_downloader.py --stage stage-historical-all
```

## File Organization in GCS

Documents are organized by book range and document type:

```
gs://madison-county-title-plant/
├── documents/
│   ├── historical/           # Books 1-237
│   │   ├── deed/
│   │   │   ├── 0001-0001.pdf
│   │   │   ├── 0001-0002.pdf
│   │   │   └── ...
│   │   ├── deed-of-trust/
│   │   └── mortgage/
│   ├── mid-early/            # Books 238-999
│   │   └── deed/
│   └── mid-recent/           # Books 1000+
│       └── deed/
```

## Optimization Settings

The PDF optimizer uses **'ebook' quality** by default:
- **Resolution**: 150 DPI
- **Compression**: Optimized for web viewing
- **File Size**: Typically 50-70% reduction
- **Quality**: Excellent for legal documents

### Quality Options

If needed, adjust in `staged_downloader.py` line 311:

```python
self.pdf_optimizer = PDFOptimizer(quality='ebook')  # Current
# Options: 'screen' (72dpi), 'ebook' (150dpi), 'printer' (300dpi), 'prepress' (300dpi)
```

## Expected Performance

### Stage 0 Test (20 documents)
- **Download time**: 30-60 seconds
- **Optimization time**: 10-20 seconds
- **Upload time**: 5-10 seconds
- **Total time**: ~2 minutes
- **Storage saved**: ~50-70%

### Historical Books Complete (Books 1-237)
Assuming ~50,000 documents:
- **Duration**: 12-24 hours (with rate limiting)
- **Original size**: ~10-15 GB
- **Optimized size**: ~3-5 GB
- **Storage savings**: ~7-10 GB

## Troubleshooting

### Issue: "Ghostscript not found"
```bash
sudo apt-get install ghostscript
gs --version  # Verify
```

### Issue: "Failed to initialize GCS"
```bash
# Check environment variable
echo $GOOGLE_APPLICATION_CREDENTIALS

# Verify credentials file exists
cat $GOOGLE_APPLICATION_CREDENTIALS | head -5

# Test authentication
gcloud auth application-default login
```

### Issue: "Permission denied" (GCS)
- Verify service account has **Storage Object Admin** role
- Check bucket name is correct
- Ensure credentials JSON is valid

### Issue: PDF optimization fails
- Check ghostscript is installed: `gs --version`
- Check PDF is valid: `gs -dNOPAUSE -dBATCH -sDEVICE=nullpage input.pdf`
- If optimization fails, original PDF will be uploaded

### Issue: Slow uploads
- **Check network**: `gsutil perfdiag -n 5 -t wthru -s 1M`
- **Adjust rate limiting**: Edit `time.sleep(2)` in `staged_downloader.py` line 499
- **Use parallel uploads**: (future enhancement)

## Cost Optimization

### GCS Storage Classes
The bucket is configured with lifecycle rules:
- **Standard**: 0-30 days (frequent access)
- **Nearline**: 31-90 days (monthly access)
- **Coldline**: 90+ days (quarterly access)

### Estimated Costs (assuming 1M documents, 5GB total)

**Storage**:
- Standard (first 30 days): $0.023/GB/month = ~$0.12/month
- Nearline (after 30 days): $0.013/GB/month = ~$0.07/month
- Coldline (after 90 days): $0.007/GB/month = ~$0.04/month

**Operations** (1M documents):
- Upload (Class A): $0.05/10k ops = ~$5 one-time
- Download (Class B): $0.004/10k ops = ~$0.40 for initial processing

**Total First Year**: ~$6-10 (mostly one-time upload costs)

### Cost Reduction Tips
1. **Enable compression**: Already done (50-70% savings)
2. **Lifecycle policies**: Already configured
3. **Batch processing**: Download/process in stages
4. **Regional storage**: Use single region (US)

## Monitoring

### Check Upload Progress

```bash
# View GCS bucket contents
gsutil ls -r gs://madison-county-title-plant/documents/ | head -20

# Count uploaded files
gsutil ls -r gs://madison-county-title-plant/documents/ | wc -l

# Check storage size
gsutil du -sh gs://madison-county-title-plant
```

### Database Query

```sql
-- Check upload status
SELECT
    download_status,
    COUNT(*) as count,
    COUNT(*) FILTER (WHERE gcs_path IS NOT NULL) as uploaded
FROM index_documents
GROUP BY download_status;

-- Check storage savings
SELECT
    'Storage Optimization' as metric,
    COUNT(*) as total_docs,
    SUM(CAST(split_part(split_part(gcs_path, 'original_size:', 2), ',', 1) AS BIGINT)) as original_bytes,
    -- Note: This is a simplified query; actual metadata extraction may differ
FROM index_documents
WHERE gcs_path IS NOT NULL;
```

## Next Steps

1. **Test dry-run**: `python3 staged_downloader.py --stage stage-0-test --dry-run`
2. **Run test upload**: `python3 staged_downloader.py --stage stage-0-test`
3. **Verify GCS**: `gsutil ls gs://madison-county-title-plant/documents/historical/`
4. **Start historical download**: `python3 staged_downloader.py --stage stage-historical-all`

## Security Notes

- **Never commit** `gcs-credentials.json` to version control
- Add to `.gitignore`:
  ```
  gcs-credentials.json
  *-credentials.json
  ```
- Store credentials securely
- Use service accounts with minimal required permissions
- Rotate credentials periodically

## Summary

✅ **Ghostscript**: Install with `apt-get install ghostscript`
✅ **GCS Setup**: Create bucket & service account
✅ **Environment**: Set `GOOGLE_APPLICATION_CREDENTIALS`
✅ **Test**: Run dry-run mode first
✅ **Monitor**: Check GCS bucket and database
✅ **Optimize**: 50-70% storage savings automatically

The system is now ready for production downloads with automatic optimization and cloud storage!
