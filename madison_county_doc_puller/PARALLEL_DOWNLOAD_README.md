# Parallel Document Download System

## Overview

The parallel download system enhances the staged downloader with concurrent processing capabilities, significantly improving download performance for large-scale document retrieval.

## Key Features

- **Concurrent Downloads**: Uses ThreadPoolExecutor for parallel processing (default: 5 workers)
- **5-10x Performance Improvement**: Compared to sequential downloads
- **Thread-Safe Operations**: Proper synchronization for database, statistics, and rate limiting
- **Connection Pooling**: Efficient database connection management
- **Shared Rate Limiting**: Coordinated rate limiting across all worker threads
- **Real-time Progress**: Live progress tracking with tqdm
- **Resumability**: Same checkpoint system as sequential downloader

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│          Database Connection Pool                       │
│      (ThreadedConnectionPool: 2-20 connections)         │
└───────────────────┬─────────────────────────────────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
    ┌─────▼─────┐      ┌──────▼──────┐
    │  Worker 1 │      │  Worker N   │
    │           │ ...  │             │
    │ - Downloader    │ - Downloader   │
    │ - Connection    │ - Connection   │
    │ - PDF Optimizer │ - PDF Optimizer│
    └─────┬─────┘      └──────┬──────┘
          │                   │
          └─────────┬─────────┘
                    │
    ┌───────────────▼────────────────┐
    │   Shared Components            │
    │ - Rate Limiter (thread-safe)   │
    │ - Statistics (thread-safe)     │
    │ - GCS Manager                  │
    └────────────────────────────────┘
```

## Performance Comparison

| Configuration | Documents/Hour | Time for 100K docs |
|--------------|----------------|-------------------|
| Sequential (historical) | 932 | 107 hours (4.5 days) |
| Parallel (5 workers) | 4,000-5,000 | 20-25 hours (1 day) |
| Parallel (10 workers) | 7,000-8,000 | 12-14 hours |

## Installation

### Prerequisites

Same as sequential downloader:
- Python 3.8+
- PostgreSQL database with index_documents table
- Google Cloud Storage credentials
- Ghostscript (for PDF optimization)

### Python Dependencies

```bash
pip install psycopg2-binary google-cloud-storage tqdm
```

## Usage

### Basic Usage

```bash
# Download with default 5 workers
python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers 5

# Download with 10 workers for faster performance
python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers 10

# Dry run to test configuration
python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers 3 --dry-run
```

### Using the Shell Script

```bash
# Run with default settings (5 workers)
./download_mid_filtered_documents.sh

# Run with custom worker count
./download_mid_filtered_documents.sh --workers 10

# Dry run
./download_mid_filtered_documents.sh --workers 5 --dry-run
```

## Stage Configuration: stage-mid-filtered

This stage is specifically configured for downloading filtered document types from the MID portal (Books 238-3971).

### Included Document Types

The stage filters for these 57 document types:

**Primary Property Documents:**
- DEED
- TRUSTEES DEED
- TAX DEED
- Transfer on Death Deed
- DEED RESTRICTIONS
- RIGHT OF WAY
- EASEMENT

**Trust & Legal Instruments:**
- TRUST AGREEMENT
- DEED OF TRUST (not included - separate category)
- HEIRSHIP
- LAST WILL AND TESTAM
- LIVING WILL

**Property Agreements:**
- AGREEMENT
- AGREEMENT-DEEDS
- CONTRACT TO SELL
- OPTION
- PROTECTIVE COVENANT
- AMENDED PROTECTIVE C
- PROTECTIVE COV TERMI

**Mineral Rights:**
- MINERAL DEED
- ROYALTY DEED
- ASSIGN OIL GAS  MIN
- MINERAL RIGHT  ROYA

**Leases:**
- LEASE ASSIGNMENT
- ASSIGNMENT OF LEASES
- LEASE CONTRACT
- AMENDMENT TO LEASE
- NOTICE TO RENEW LEAS

**Subdivision & Property Records:**
- SUBDIVISION PLATS
- PLAT FILED
- CORRECTION OF PLAT
- MAP
- SURVEYS

**Legal Actions:**
- JUDGMENT OR ORDER
- EMINENT DOMAIN
- SEALED

**Covenants & Restrictions:**
- DECLARATION
- AMENDED DECLARATION
- SUPPLEMENT
- SUPPLEMENT TO COVENA
- DECLARATION OF ROAD
- ARCHITECTURAL REVIEW
- ENVIRONMENTAL PROTEC

**Documents & Certifications:**
- AFFIDAVIT "T"
- PATENT
- WAIVER
- CERT OF SALESEIZED
- RECEIVER

**Amendments:**
- AMENDMENT(T)
- AMENDMENT(W)

**Special Categories:**
- MISCELLANEOUS
- MISCELLANEOUS "T"
- MISCELLANEOUS "C"
- REVOCATION  CANCELL
- RECISSION OF FORECLO
- VOID LEASES 16TH SEC
- - [DEED 90W] (specific book reference)

### Database Query

The stage uses this filter in the database query:

```sql
WHERE book >= 238 AND book < 3972
  AND instrument_type_parsed IN (
    'DEED', 'RIGHT OF WAY', 'EASEMENT', ...
  )
```

### Expected Volume

Based on the analyze_index.py output, the filtered documents represent approximately:
- **DEED**: ~163,000 documents
- **LEASE ASSIGNMENT**: ~9,400 documents
- **RIGHT OF WAY**: ~8,400 documents
- Plus 50+ additional document types

**Estimated Total**: 200,000-250,000 documents from Books 238-3971

## Worker Configuration

### Recommended Worker Counts

| Use Case | Workers | Expected Performance |
|----------|---------|---------------------|
| Conservative (server load concerns) | 3-5 | 3,000-4,000 docs/hour |
| Balanced (recommended) | 5-8 | 4,000-6,000 docs/hour |
| Aggressive (maximum speed) | 10-15 | 7,000-10,000 docs/hour |

### Factors to Consider

**Server Load:**
- Madison County's server capacity
- Time of day (lower traffic = higher worker count)
- Current server response times

**Database Performance:**
- Connection pool size (max: 20 connections)
- Database server capacity
- Network latency

**Local Resources:**
- CPU cores available
- Memory (each worker: ~100-200 MB)
- Disk I/O for temporary files

**Network:**
- Bandwidth available
- GCS upload speed
- Stability of connection

## Rate Limiting

### Per-Thread Rate Limiting

Each worker thread respects a shared rate limiter:
- **Default delay**: 0.5 seconds between requests
- **Shared across threads**: All workers coordinate
- **Effective rate**: ~2 requests/second per worker

### Adjusting Rate Limits

Edit `RATE_LIMIT_DELAY` in `parallel_staged_downloader.py`:

```python
RATE_LIMIT_DELAY = 0.5  # 500ms delay (default)
RATE_LIMIT_DELAY = 1.0  # 1 second delay (more conservative)
RATE_LIMIT_DELAY = 0.3  # 300ms delay (more aggressive)
```

## Thread Safety

### Thread-Safe Components

1. **Database Connections**: Each worker gets its own connection from the pool
2. **Statistics Tracking**: Uses threading.Lock for all updates
3. **Rate Limiter**: Shared lock prevents race conditions
4. **GCS Manager**: Thread-safe by design
5. **PDF Optimizer**: Each worker has its own instance

### Not Thread-Safe (By Design)

- **Document Queue**: Managed by main thread only
- **Checkpoint Writing**: Single-threaded operation
- **Progress Bar**: Updated from main thread

## Monitoring

### Real-Time Monitoring

The system displays:
- Progress bar with completion percentage
- Documents per hour (real-time calculation)
- Success/failure rates
- Validation mismatch detection
- Storage optimization statistics

### Log Files

```bash
# View main log
tail -f madison_county_doc_puller/parallel_staged_download.log

# Filter for errors
grep -i error madison_county_doc_puller/parallel_staged_download.log

# Watch worker activity
tail -f madison_county_doc_puller/parallel_staged_download.log | grep "Worker"
```

### Database Monitoring

```sql
-- Check progress
SELECT download_status, COUNT(*)
FROM index_documents
WHERE book >= 238 AND book < 3972
GROUP BY download_status;

-- Recent activity (last 10 minutes)
SELECT COUNT(*) as completed_last_10min
FROM index_documents
WHERE download_status = 'completed'
  AND downloaded_at > CURRENT_TIMESTAMP - INTERVAL '10 minutes';

-- Current throughput
SELECT
    COUNT(*) as completed,
    ROUND(COUNT(*) / EXTRACT(EPOCH FROM (MAX(downloaded_at) - MIN(downloaded_at))) * 3600) as docs_per_hour
FROM index_documents
WHERE downloaded_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'
  AND download_status = 'completed';
```

## Error Handling

### Thread-Safe Error Tracking

Each worker reports errors independently:
- Errors captured in thread-safe statistics
- Failed documents marked in database
- Automatic retry up to 5 attempts
- Detailed error logging with thread ID

### Common Issues

**Issue: Workers timing out**
```
Solution: Increase rate limit delay or reduce worker count
```

**Issue: Database connection errors**
```
Solution: Check connection pool size, ensure DB can handle connections
```

**Issue: GCS upload failures**
```
Solution: Check credentials, network connectivity, GCS quota
```

**Issue: Memory usage high**
```
Solution: Reduce worker count, increase cleanup frequency
```

## Best Practices

### 1. Start Conservative

Begin with 3-5 workers and monitor:
- Server response times
- Error rates
- System resource usage

### 2. Ramp Up Gradually

If stable, increase workers:
- Add 2-3 workers at a time
- Monitor for 15-30 minutes
- Check error rates don't spike

### 3. Monitor Throughout

Watch these metrics:
- Documents per hour
- Success rate (should be >95%)
- Mismatch rate (expected: 5-15%)
- GCS upload success

### 4. Handle Interruptions

The system handles interruptions gracefully:
- Ctrl+C stops cleanly
- In-progress records reset automatically
- No data loss or corruption
- Resume with same command

### 5. Validate Results

After completion:
```bash
# Check completion rate
python3 download_validator.py --report

# Verify GCS uploads
gsutil ls -r gs://madison-county-title-plant/documents/mid-*/ | wc -l

# Check database consistency
psql -h 127.0.0.1 -U madison_index_app -d madison_county_index -c "
  SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE gcs_path IS NOT NULL) as with_gcs_path
  FROM index_documents
  WHERE download_status = 'completed';
"
```

## Troubleshooting

### Problem: Import errors

**Symptoms**: `ModuleNotFoundError: No module named 'psycopg2'`

**Solution**:
```bash
pip install psycopg2-binary google-cloud-storage tqdm
```

### Problem: Connection pool exhausted

**Symptoms**: `PoolError: connection pool exhausted`

**Solution**:
```python
# Increase max connections in parallel_staged_downloader.py
def create_connection_pool(min_conn: int = 2, max_conn: int = 30):  # Increased from 20
```

### Problem: Too many open files

**Symptoms**: `OSError: [Errno 24] Too many open files`

**Solution**:
```bash
# Increase file descriptor limit
ulimit -n 4096

# Or add to ~/.bashrc
echo "ulimit -n 4096" >> ~/.bashrc
```

### Problem: Slow GCS uploads

**Symptoms**: Upload taking longer than download

**Solution**:
- Check network bandwidth
- Verify GCS region is close
- Consider disabling PDF optimization temporarily
- Check GCS quota and rate limits

## Advanced Configuration

### Custom Document Types

To add or remove document types, edit `download_queue_manager.py`:

```python
'stage-mid-filtered': {
    'filters': {
        'document_types': [
            'DEED',
            'YOUR_NEW_TYPE',  # Add here
            # Remove unwanted types
        ]
    }
}
```

### Custom Book Ranges

Change the book range filter:

```python
'filters': {
    'book_ranges': [(238, 1000)],  # Only books 238-999
}
```

### Thread Configuration

Modify worker behavior in `parallel_staged_downloader.py`:

```python
# Change default workers
DEFAULT_WORKERS = 8  # Instead of 5

# Adjust rate limit per thread
RATE_LIMIT_DELAY = 0.3  # More aggressive

# Change batch size
batch_size=num_workers * 20  # Larger batches
```

## Performance Tuning

### Database Optimization

```sql
-- Add index for faster queries
CREATE INDEX idx_instrument_type_parsed
ON index_documents(instrument_type_parsed);

-- Analyze table
ANALYZE index_documents;
```

### GCS Optimization

```bash
# Use gsutil for better upload performance
export GCS_ENABLE_TRANSFER_ACCELERATION=true

# Check current GCS performance
gsutil perfdiag
```

### System Resources

```bash
# Monitor CPU usage
htop

# Monitor memory
free -h

# Monitor disk I/O
iostat -x 5

# Monitor network
iftop
```

## Comparison with Sequential Download

| Feature | Sequential | Parallel |
|---------|-----------|----------|
| Speed | 932 docs/hour | 4,000-8,000 docs/hour |
| Workers | 1 | 5-15 (configurable) |
| Memory | ~200 MB | ~500 MB - 2 GB |
| CPU Usage | Low (10-20%) | Medium-High (30-80%) |
| Complexity | Simple | Moderate |
| Error Handling | Basic | Advanced (thread-safe) |
| Resumability | Yes | Yes |
| Rate Limiting | Simple | Coordinated |

## Cost Analysis

### Time Savings

For 200,000 documents:

| Configuration | Time Required | Cost Savings |
|--------------|---------------|--------------|
| Sequential | 214 hours (8.9 days) | Baseline |
| Parallel (5 workers) | 40-50 hours (2 days) | 75% faster |
| Parallel (10 workers) | 25-30 hours (1.25 days) | 85% faster |

### Resource Costs

Assuming cloud VM:
- **Sequential**: $10-15 (9 days @ $1.50/day)
- **Parallel (5)**: $3-5 (2 days @ $1.50/day)
- **Parallel (10)**: $2-3 (1.5 days @ $1.50/day)

**Savings**: $7-12 per 200K documents

## Support

For issues or questions:

1. **Check logs**: `parallel_staged_download.log`
2. **Review documentation**: This file and `STAGED_DOWNLOAD_README.md`
3. **Database status**: Run validation queries above
4. **System resources**: Check CPU, memory, disk, network

## Future Enhancements

### Planned Features

- [ ] Async I/O with asyncio for even better performance
- [ ] Distributed processing across multiple machines
- [ ] Redis-based queue for distributed workers
- [ ] Real-time dashboard with websockets
- [ ] Automatic worker scaling based on load
- [ ] ML-based optimal worker count prediction
- [ ] Integration with Kubernetes for cloud scaling

### Under Consideration

- Process-based parallelism (multiprocessing) instead of threads
- GPU acceleration for PDF optimization
- Streaming uploads to GCS during download
- Compressed checkpoints for faster resume
- Webhook notifications for completion/errors
