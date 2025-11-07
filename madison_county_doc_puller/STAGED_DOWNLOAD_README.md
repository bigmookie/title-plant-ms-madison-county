# Staged Document Download System

## Overview

This staged download system provides a systematic, controlled approach to downloading approximately 1 million land records from Madison County's portals. The system emphasizes data quality, incremental validation, cost management, and resumability.

## Architecture

```
┌─────────────────────────────────────────┐
│        Index Database                   │
│   (Download Queue Management)           │
│                                         │
│  - Pending documents (~1M)              │
│  - Download priorities (1-4)            │
│  - Status tracking                      │
│  - Portal routing logic                 │
└──────────────┬──────────────────────────┘
               │
               ├──> Data Cleaning (clean_index_data.py)
               │    - Remove invalid records
               │    - Deduplicate
               │    - Assign priorities
               │
               ├──> Queue Manager (download_queue_manager.py)
               │    - Fetch documents by stage
               │    - Track status (pending → in_progress → completed/failed)
               │    - Save checkpoints
               │
               ├──> Staged Downloader (staged_downloader.py)
               │    - Orchestrate downloads
               │    - Handle retries
               │    - Upload to GCS
               │
               └──> Validator (download_validator.py)
                    - Monitor progress
                    - Validate downloads
                    - Generate reports
```

## Portal Architecture

### Three Portals, Different Download Strategies

1. **Historical Books Portal** (Books < 238)
   - Direct PDF download links
   - Simpler HTML structure
   - ~30K-40K documents (Priority 2)

2. **MID Portal** (Books 238-3971)
   - HTML response with embedded PDF links
   - Requires document type code
   - ~850K-900K documents (Priority 3)

3. **NEW Portal / DuProcess** (Books >= 3972)
   - Modern interface
   - **EXCLUDED from Phase 1**
   - Will be handled in future phase

## Staged Approach

### Stage 0: Test Run
**Purpose**: Validate infrastructure with minimal data

**Scope**:
- 10 documents from Historical portal
- 10 documents from MID portal
- Total: 20 documents

**Command**:
```bash
python3 staged_downloader.py --stage stage-0-test --dry-run
python3 staged_downloader.py --stage stage-0-test
```

**Success Criteria**:
- All 20 documents downloaded successfully
- Correct portal routing
- GCS upload working
- Database tracking accurate
- Error handling functional

**Duration**: 1 day
**Cost**: ~$0

### Stage 1: Small Scale
**Purpose**: Validate at small scale, test all workflows

**Scope**:
- 1,000 Historical documents (Books 1-50, Priority 1-2)
- 1,000 MID documents (Books 238-300, Priority 1-2)
- Total: 2,000 documents

**Command**:
```bash
python3 staged_downloader.py --stage stage-1-small
```

**Success Criteria**:
- Success rate > 95%
- All document types represented
- GCS folder structure correct
- Database tracking accurate

**Duration**: 2-3 days
**Cost**: ~$5

### Stage 2: Medium Scale
**Purpose**: Validate scaling, test monitoring

**Scope**:
- All Priority 1 documents (Wills) - ~5K-10K
- All Priority 2 documents (Historical < 238) - ~30K-40K
- Sample of Priority 3 (MID portal) - ~10K
- Total: ~50,000 documents

**Command**:
```bash
python3 staged_downloader.py --stage stage-2-medium
```

**Success Criteria**:
- 50K documents downloaded
- Success rate > 95%
- Average download speed: 100-200 docs/hour
- Storage costs match projections

**Duration**: 1-2 weeks
**Cost**: ~$10

### Stage 3: Large Scale
**Purpose**: Complete MID portal downloads

**Scope**:
- All remaining Priority 3 (MID portal)
- Books 238-3971
- Total: ~850K-900K documents

**Command**:
```bash
python3 staged_downloader.py --stage stage-3-large
```

**Success Criteria**:
- 900K+ documents downloaded
- Overall success rate > 95%
- Storage costs within 20% of projections

**Duration**: 2-4 weeks
**Cost**: ~$65-75/month

### Stage 4: Retry Failed
**Purpose**: Retry failed downloads

**Scope**:
- All documents marked as 'failed'
- Up to 5 retry attempts

**Command**:
```bash
python3 staged_downloader.py --stage stage-4-retry
```

**Duration**: 1 week
**Cost**: ~$5

## Setup Instructions

### Prerequisites

1. **Index Database Setup**
   ```bash
   cd index_database
   source .db_credentials
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Cloud SQL Auth Proxy Running**
   ```bash
   cd index_database
   ./start_proxy.sh
   ```

### Step 1: Clean Index Data

First, clean and prepare the index database:

```bash
cd index_database

# Dry run to see what would be cleaned
python3 clean_index_data.py --dry-run

# Generate report only (no changes)
python3 clean_index_data.py --report-only

# Perform cleaning
python3 clean_index_data.py
```

**This will**:
- Mark invalid records (NULL book/page, invalid ranges)
- Exclude NEW portal books (>= 3972)
- Deduplicate records
- Assign download priorities (1=Critical, 2=High, 3=Medium, 4=Low)
- Generate statistics and recommendations

### Step 2: Run Stage 0 Test

Test the download infrastructure:

```bash
cd ../madison_county_doc_puller

# Dry run first
python3 staged_downloader.py --stage stage-0-test --dry-run

# Actual test
python3 staged_downloader.py --stage stage-0-test
```

**Monitor**:
```bash
# In another terminal
python3 download_validator.py --monitor
```

### Step 3: Validate Stage 0 Results

```bash
python3 download_validator.py --report
python3 download_validator.py --monitor
```

**Check for**:
- All 20 documents completed
- No critical errors
- GCS paths populated
- Portal routing correct

### Step 4: Proceed to Stage 1

Once Stage 0 validates:

```bash
python3 staged_downloader.py --stage stage-1-small
```

**Monitor progress**:
```bash
# Progress report
python3 download_validator.py --report

# Health check
python3 download_validator.py --monitor

# View logs
tail -f staged_download.log
```

### Step 5: Continue Staged Progression

After each stage validates:

```bash
# Stage 2
python3 staged_downloader.py --stage stage-2-medium

# Stage 3
python3 staged_downloader.py --stage stage-3-large

# Stage 4 (retry)
python3 staged_downloader.py --stage stage-4-retry
```

## Resumability

### Automatic Checkpoints

The system saves checkpoints every 100 documents:
- Queue state (last fetched ID)
- Download statistics
- Timestamp

### Resume After Interruption

```bash
python3 staged_downloader.py --stage stage-2-medium --resume
```

This will:
1. Load the last checkpoint
2. Resume from last processed document
3. Reset any stale 'in_progress' records

### Checkpoint Location

```
madison_county_doc_puller/checkpoints/
├── checkpoint_stage-1-small_1699382400.json
├── checkpoint_stage-2-medium_1699468800.json
└── ...
```

## Monitoring and Validation

### Progress Reports

```bash
# Generate progress report
python3 download_validator.py --report
```

**Shows**:
- Status breakdown (completed, pending, failed)
- Priority breakdown
- Throughput (docs/hour)
- Estimated completion time
- Top errors
- Coverage gaps

### Health Monitoring

```bash
# Check download health
python3 download_validator.py --monitor
```

**Checks**:
- Stale 'in_progress' records (>30 min old)
- Success rate (last 1000 docs)
- Recent activity (last hour)
- Recent error patterns

### Real-time Monitoring

```bash
# Watch log file
tail -f staged_download.log

# Watch validation log
tail -f validation.log

# Watch database connection
watch -n 10 'psql -h 127.0.0.1 -U madison_index_app -d madison_county_index -c "SELECT download_status, COUNT(*) FROM index_documents GROUP BY download_status"'
```

## Database Status Tracking

### Download Status Values

- **pending**: Ready to download
- **in_progress**: Currently being downloaded
- **completed**: Successfully downloaded and uploaded to GCS
- **failed**: Download failed (will retry up to 5 times)
- **skipped**: Intentionally skipped (invalid data, excluded, etc.)

### Priority Levels

- **1 (Critical)**: Wills and critical document types
- **2 (High)**: Historical books (< 238)
- **3 (Medium)**: MID portal books (238-3971)
- **4 (Low)**: Other documents

### Key Database Queries

```sql
-- Overall progress
SELECT download_status, COUNT(*) as count
FROM index_documents
GROUP BY download_status;

-- By priority
SELECT download_priority, download_status, COUNT(*)
FROM index_documents
GROUP BY download_priority, download_status
ORDER BY download_priority;

-- Recent completions
SELECT COUNT(*) as completed_today
FROM index_documents
WHERE download_status = 'completed'
  AND downloaded_at > CURRENT_TIMESTAMP - INTERVAL '24 hours';

-- Success rate
SELECT
    COUNT(*) FILTER (WHERE download_status = 'completed') * 100.0 / COUNT(*) as success_rate
FROM index_documents
WHERE download_status IN ('completed', 'failed');

-- Top errors
SELECT download_error, COUNT(*) as count
FROM index_documents
WHERE download_status = 'failed'
GROUP BY download_error
ORDER BY count DESC
LIMIT 10;
```

## Error Handling

### Automatic Retries

- Failed downloads automatically retry up to 5 times
- Exponential backoff between retries (2, 4, 8, 16, 32 seconds)
- After 5 failures, status changes to 'failed' (permanent)

### Common Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| 404 Not Found | Document doesn't exist in portal | Mark as permanent failure |
| Timeout | Portal slow or network issue | Retry (automatic) |
| Connection Error | Network interruption | Retry (automatic) |
| Invalid PDF | Corrupted download | Retry (automatic) |
| Rate Limiting | Too many requests | Increase delay between requests |

### Manual Error Recovery

```bash
# Reset stale in_progress records
python3 download_queue_manager.py --reset-stale

# Retry all failed downloads
python3 staged_downloader.py --stage stage-4-retry
```

## Cost Projections

### Storage Costs

**Assumptions**:
- 1M documents
- Average size: 2MB per document
- Total: ~2TB

**Monthly Costs**:
- **STANDARD** (first 30 days): $52/month
- **NEARLINE** (30-90 days): $20/month
- **COLDLINE** (90-365 days): $14/month
- **ARCHIVE** (365+ days): $8/month

### Total Phase 1 Cost

- Storage (first month): ~$50
- Operations: ~$5-10
- Bandwidth: ~$10-20
- **Total**: ~$70-85 for first month

After lifecycle transitions: ~$20-30/month

## File Structure

```
madison_county_doc_puller/
├── staged_downloader.py          # Main orchestration script
├── download_queue_manager.py     # Queue management from database
├── download_validator.py         # Validation and monitoring
├── doc_puller.py                 # Existing downloader (reused)
│
├── checkpoints/                  # Resumability checkpoints
│   └── checkpoint_*.json
│
├── temp_downloads/               # Temporary local storage
│   └── [cleaned after upload]
│
├── staged_download.log           # Main download log
├── validation.log                # Validation log
└── STAGED_DOWNLOAD_README.md     # This file
```

## Troubleshooting

### Problem: Downloads not starting

**Check**:
1. Database connection: `source index_database/.db_credentials`
2. Proxy running: `ps aux | grep cloud-sql-proxy`
3. Pending documents exist: `python3 download_validator.py --report`

### Problem: Low success rate (<95%)

**Actions**:
1. Check error summary: `python3 download_validator.py --report`
2. Review logs: `tail -100 staged_download.log`
3. Check portal availability: Test manual download
4. Increase delay between requests (rate limiting)

### Problem: Process crashed

**Recovery**:
```bash
# Resume from checkpoint
python3 staged_downloader.py --stage [your-stage] --resume
```

### Problem: Stale in_progress records

**Fix**:
```bash
# Automatically reset when running with --resume
python3 staged_downloader.py --stage [your-stage] --resume

# Or manually check
python3 download_validator.py --monitor
```

## Best Practices

1. **Always run dry-run first** on new stages
2. **Monitor health regularly** during long downloads
3. **Save checkpoints frequently** (automatic every 100 docs)
4. **Validate each stage** before proceeding to next
5. **Keep logs** for troubleshooting and auditing
6. **Set billing alerts** in GCP console
7. **Test resumability** before large stages

## Next Steps After Downloads

Once downloads are complete:

1. **Validate final statistics**
   ```bash
   python3 download_validator.py --report
   ```

2. **Export manifest**
   - Document all completed downloads
   - Save to download-metadata/ folder
   - Include checksums and metadata

3. **Begin Phase 2: OCR Processing**
   - Use Google Document AI
   - Extract text from all PDFs
   - Structure data according to document types

4. **Build production database**
   - Parse OCR text
   - Extract entities and legal descriptions
   - Validate against index database

## Support

For issues or questions:
1. Check logs: `staged_download.log`, `validation.log`
2. Run health check: `python3 download_validator.py --monitor`
3. Review progress: `python3 download_validator.py --report`
4. Consult specs: `specs/master-spec.md`, `specs/document-download-spec.md`
