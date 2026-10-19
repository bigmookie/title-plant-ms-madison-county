# Madison County Document Puller

A Python script to download land record documents from Madison County, MS with Google Cloud Storage (GCS) integration. The script first checks if documents exist in your GCS bucket before falling back to the web portal.

## Features

- **GCS-First Download**: Checks GCS bucket for existing documents before querying the web portal
- **Batch Processing**: Process multiple documents from Excel or text files
- **Parallel Downloads**: Multi-threaded downloading for faster batch processing
- **Auto-Upload**: Optionally upload newly downloaded documents to GCS
- **Progress Reports**: Generates detailed download reports

## Installation

### Prerequisites

- Python 3.8+
- Google Cloud service account credentials (for GCS features)

### Install Dependencies

```bash
pip install requests beautifulsoup4 openpyxl python-dotenv google-cloud-storage
```

### Environment Setup

Create a `.env` file in the project root (or use the existing one):

```bash
# GCS Configuration
GCS_BUCKET_NAME=madison-county-title-plant
GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
```

## GCS Bucket Structure

Documents are organized in the GCS bucket using this path format:

```
documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf
```

### Folder Prefixes

| Book Range | Folder Prefix |
|------------|---------------|
| < 238      | `historical`  |
| 238-999    | `mid-early`   |
| >= 1000    | `mid-recent`  |

### Examples

| Book | Page | Doc Type | GCS Path |
|------|------|----------|----------|
| 50   | 100  | deed     | `documents/historical/deed/0050-0100.pdf` |
| 500  | 200  | deed-of-trust | `documents/mid-early/deed-of-trust/0500-0200.pdf` |
| 1500 | 50   | right-of-way | `documents/mid-recent/right-of-way/1500-0050.pdf` |

## Usage

### Single Document Download

```bash
# Download with GCS check (default)
python madison_doc_puller.py --book 500 --page 100

# Skip GCS, download from web portal only
python madison_doc_puller.py --book 500 --page 100 --skip-gcs

# View document info without downloading
python madison_doc_puller.py --book 500 --page 100 --info-only
```

### Batch Processing

```bash
# Process Excel file
python madison_doc_puller.py --excel documents.xlsx

# Process text file
python madison_doc_puller.py --txt documents.txt

# With parallel workers
python madison_doc_puller.py --excel documents.xlsx --workers 4

# Upload new downloads to GCS
python madison_doc_puller.py --excel documents.xlsx --upload-to-gcs
```

### Interactive Mode

```bash
# Opens file dialog to select input file
python madison_doc_puller.py
```

## Input File Formats

### Excel Format

**Option 1**: Separate columns
| Column A (Book) | Column B (Page) |
|-----------------|-----------------|
| 500             | 100             |
| 501             | 50              |

**Option 2**: Combined format in Column A
| Column A        |
|-----------------|
| 500/100         |
| 501-50          |

### Text File Format

```
# One document per line: book/page [optional doc_type]
500/100 deed
501-50 deed-of-trust
DT 502/308
CCC/165
238/15
100/50
```

- Default doc type is "deed"
- `DT` (or `DOT`) before the reference marks a deed of trust book. Deed of trust books are numbered separately from deed books, so `DT 151/206` is never filled with Deed Book 151, Page 206; deeds of trust are saved locally as `DT-0502-0308.pdf`
- Lettered books (A-ZZZ) are supported, e.g. `CCC/165` -> `CCC-0165.pdf`
- Books < 238 and lettered books are treated as "deed" unless marked `DT`

## Command Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--excel` | `-e` | Path to Excel file for batch processing |
| `--txt` | `-t` | Path to text file for batch processing |
| `--book` | `-b` | Book number (single document mode) |
| `--page` | `-p` | Page number (single document mode) |
| `--output-dir` | `-o` | Output directory for downloads |
| `--info-only` | | Show document info without downloading |
| `--skip-gcs` | | Skip GCS check, download from web only |
| `--upload-to-gcs` | | Upload new downloads to GCS |
| `--bucket` | | GCS bucket name (overrides .env) |
| `--workers` | `-w` | Number of parallel workers |
| `--delay` | | Delay between web requests (seconds) |

## Output

### Downloaded Files

Files are saved to a `docs/` subdirectory in the same location as the input file (or current directory for single downloads).

Filename format: `{book:04d}-{page:04d}.pdf` (e.g., `0500-0100.pdf`)

### Download Report

A summary report is generated after batch processing:

```
======================================================================
MADISON COUNTY DOCUMENT PULLER - SUMMARY REPORT
======================================================================

Report Generated: 2026-01-16 10:30:00
Source File:      documents.xlsx
Output Directory: /path/to/docs
Time Elapsed:     45.2 seconds

----------------------------------------------------------------------
DOWNLOAD STATISTICS
----------------------------------------------------------------------
Total Documents Requested:  50
Successfully Downloaded:    45
  - From GCS:               30
  - From Web Portal:        15
Already Existed (Skipped):  3
Failed:                     2
```

## Download Priority

1. **Local file** - If the file already exists locally, skip download
2. **GCS bucket** - Check if document exists in GCS (unless `--skip-gcs`)
3. **Web portal** - Download from Madison County web portal as fallback

## Error Handling

- Failed downloads are logged in the summary report
- Retry logic for transient network errors
- Graceful handling of missing documents (returns "No document found")

## Examples

### Download all documents from a list, prioritizing GCS

```bash
python madison_doc_puller.py --excel my_documents.xlsx --workers 4
```

### Download and upload to GCS for future use

```bash
python madison_doc_puller.py --txt documents.txt --upload-to-gcs
```

### Quick single document check

```bash
python madison_doc_puller.py -b 285 -p 55 --info-only
```

## Troubleshooting

### GCS Authentication Errors

Ensure your service account credentials are properly configured:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
```

Or set it in your `.env` file.

### Missing Dependencies

```bash
pip install --upgrade google-cloud-storage python-dotenv
```

### Rate Limiting

If you encounter rate limiting from the web portal, increase the delay:

```bash
python madison_doc_puller.py --excel docs.xlsx --delay 2.0
```

## Related Files

- `madison_county_doc_puller/gcs_manager.py` - Core GCS management class
- `madison_county_doc_puller/parallel_staged_downloader.py` - Database-integrated downloader
- `.env` - Environment configuration
