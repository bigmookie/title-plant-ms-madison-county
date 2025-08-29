# Madison County Title Plant - Phase 1 Document Download System

## Overview
Phase 1 of the Madison County Title Plant project implements a robust document download, optimization, and storage pipeline. This system processes index spreadsheets to systematically download historical land records, optimize them for storage, and upload them to Google Cloud Storage.

## Features
- ✅ Processes Excel index files to build download queue
- ✅ Downloads from multiple portals (Historical, MID)
- ✅ Implements retry logic with exponential backoff
- ✅ Optimizes PDFs for storage efficiency (30-70% size reduction)
- ✅ Uploads to Google Cloud Storage with metadata
- ✅ Supports parallel processing for faster downloads
- ✅ Resumable processing with checkpoint system
- ✅ Comprehensive logging and error tracking

## Quick Start

### 1. Prerequisites
- Python 3.8+
- Google Cloud account with Storage API enabled
- Service account credentials for GCS access
- Ghostscript (optional, for better PDF optimization)

### 2. Installation

```bash
# Clone the repository
git clone <repository-url>
cd title-plant-ms-madison-county

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Ghostscript (optional but recommended)
# Ubuntu/Debian: sudo apt-get install ghostscript
# macOS: brew install ghostscript
# Windows: Download from https://www.ghostscript.com/download/gsdnld.html
```

### 3. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your configuration
# Required: Set GOOGLE_APPLICATION_CREDENTIALS path
# Required: Set GCS_BUCKET_NAME
```

### 4. Prepare Index Files
Place your Excel index files in `madison_docs/DuProcess Indexes/`

### 5. Run the System

```bash
# Build queue and start processing
python main.py process

# Process with parallel downloads (faster)
python main.py process --parallel --workers 5

# Process limited number for testing
python main.py process --limit 10
```

## Command Reference

### Build Queue
```bash
# Build download queue from index files
python main.py build-queue

# Force rebuild even if queue exists
python main.py build-queue --force
```

### Process Documents
```bash
# Sequential processing (safer, slower)
python main.py process

# Parallel processing (faster)
python main.py process --parallel --workers 5

# Process with limit
python main.py process --limit 100

# Rebuild queue before processing
python main.py process --rebuild-queue
```

### View Statistics
```bash
# Show queue and processing statistics
python main.py stats
```

### Test Single Document
```bash
# Test download of a specific document
python main.py test --book 237 --page 1

# Specify portal explicitly
python main.py test --book 500 --page 10 --portal mid
```

### Generate Report
```bash
# Generate processing report
python main.py report

# Save report to file
python main.py report --output report.json
```

## System Architecture

### Document Flow
1. **Index Processing** → Read Excel files, extract metadata
2. **Queue Building** → Create prioritized download queue
3. **Document Download** → Fetch from appropriate portal
4. **PDF Optimization** → Compress and standardize
5. **GCS Upload** → Store with metadata
6. **Cleanup** → Remove temporary files

### Portal Routing
- **Historical Portal**: Books < 238 (includes letters)
- **MID Portal**: Books 238-3971
- **DuProcess Portal**: Books 3972+ (Phase 2)

### Priority System
1. Priority 1: Will documents
2. Priority 2: Historical deeds
3. Priority 3: MID deeds
4. Priority 5: All other documents

## Google Cloud Storage Structure
```
madison-county-title-plant/
├── documents/
│   ├── optimized-pdfs/
│   │   ├── deeds/
│   │   │   └── book-{num}/
│   │   │       └── {book}-{page}.pdf
│   │   ├── deeds-of-trust/
│   │   ├── wills/
│   │   └── chancery/
│   └── extracted-text/  (Phase 2)
└── indexes/
```

## Monitoring & Troubleshooting

### Check Progress
```bash
# View real-time progress
tail -f logs/madison_title_plant.log

# Check checkpoint files
ls checkpoints/
```

### Resume After Failure
The system automatically saves progress. Simply re-run the same command:
```bash
python main.py process
```

### Common Issues

**Issue**: "No module named 'google.cloud'"
```bash
pip install google-cloud-storage
```

**Issue**: Ghostscript not found
- System will use fallback optimization (less efficient)
- Install Ghostscript for better compression

**Issue**: Authentication failed
- Verify GOOGLE_APPLICATION_CREDENTIALS path
- Ensure service account has Storage Object Admin role

**Issue**: Rate limiting errors
- Reduce workers: `--workers 2`
- Increase RATE_LIMIT_DELAY in .env

## Performance Tuning

### Parallel Processing
- Start with 3-5 workers
- Monitor for rate limiting
- Adjust based on network speed

### PDF Optimization
- Quality 85 provides good balance
- DPI 150 suitable for most documents
- Higher values for documents with small text

### Storage Costs
- Documents automatically transition to Nearline (30 days)
- Then to Coldline (90 days) for cost savings

## Development

### Running Tests
```bash
pytest tests/
```

### Code Formatting
```bash
black madison_title_plant/
flake8 madison_title_plant/
```

## Phase 2 Preview
Next phase will add:
- OCR text extraction using Google Document AI
- AI-powered error correction
- Structured data extraction
- Searchable indexes
- API endpoints

## Support
For issues or questions, refer to:
- `CLAUDE.md` - Project documentation
- `spec.md` - Technical specifications
- `.claude/commands/` - Workflow templates