# Document Download Specification

## Overview
This specification defines the document download system for extracting historical land records from Madison County's three document portals. The system prioritizes reliability, resumability, and comprehensive tracking of download progress.

## Portal Architecture

### 1. Historical Books Portal (Books < 238)
- **URL Pattern**: `https://tools.madison-co.net/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php`
- **Coverage**: All books numbered below 238, including Book 237
- **Document Types**: Deeds, Deeds of Trust, Wills, and other historical instruments
- **Authentication**: None required (public access)
- **Technology**: Direct PDF download via GET request
- **Response Type**: PDF file directly

### 2. MID Portal (Books 238-3971)
- **URL Pattern**: `https://tools.madison-co.net/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php`
- **Coverage**: Books 238 through 3971
- **Document Types**: Standard real estate instruments with document type codes
- **Authentication**: None required (public access)
- **Technology**: HTML response with multiple PDF download links
- **Response Type**: HTML page containing "Download Image" links that must be parsed and PDFs concatenated

### 3. DuProcess/NEW Portal (Books 3972+)
- **URL Pattern**: TBD
- **Coverage**: Books 3972 onwards
- **Status**: EXCLUDED from Phase 1
- **Reason**: Focus on historical completeness first

## Download Queue Management

### Priority System
```python
class DownloadPriority(Enum):
    CRITICAL = 1  # Will records and indexes
    HIGH = 2      # Historical deeds (< Book 238)
    MEDIUM = 3    # MID portal documents (Books 238-3971)
    LOW = 4       # Supplementary documents
```

### Queue Generation
1. **Index Processing**
   - Parse DuProcess index spreadsheets (e.g., `2014-08-31.xlsx`)
   - Extract Book Type field from spreadsheet
   - Map book type to appropriate folder using `BOOK_TYPE_MAPPING`
   - Generate download URLs based on book/page references

2. **Book Type Processing**
   ```python
   def process_index_file(index_path: str):
       """Process DuProcess index spreadsheet"""
       df = pd.read_excel(index_path)
       
       for _, row in df.iterrows():
           book = row['Book']
           page = row['Page']
           book_type = row['BookType']  # e.g., "DEED OF TRUST", "UCC"
           
           # Determine target folder
           folder = get_document_folder(book_type)
           
           # Add to download queue with proper classification
           queue_item = {
               'book': book,
               'page': page,
               'book_type': book_type,
               'target_folder': folder,
               'filename': f"{book}-{page}.pdf"
           }
   ```

3. **Deduplication**
   - Track downloaded documents by unique identifier: `{book}-{page}`
   - Skip previously downloaded items
   - Maintain download manifest in JSON format with book type classification

## Technical Implementation

### Core Components

#### 1. Portal-Specific Download Logic
```python
class DocumentDownloader:
    def __init__(self):
        self.base_url = "https://tools.madison-co.net/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
        self.session = requests.Session()
        
    def download_historical(self, book: int, page: int) -> tuple:
        """Books < 238: Direct PDF download"""
        params = {
            "book": str(book),
            "bpage": str(page),
            "do_search": "Submit Query"
        }
        response = self.session.get(self.base_url, params=params, timeout=10)
        
        if response.content.startswith(b'%PDF-'):
            return response.content, None
        return None, "Not a PDF response"
    
    def download_mid(self, book: int, page: int, doc_type: str = "01") -> tuple:
        """Books 238-3971: Parse HTML and concatenate multiple PDFs"""
        params = {
            "doc_type": doc_type,  # Use document type code
            "book": str(book),
            "bpage": str(page),
            "do_search": "Submit Query"
        }
        response = self.session.get(self.base_url, params=params, timeout=10)
        
        # Parse HTML for download links
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', string=re.compile(r'Download Image \d+'))
        
        if links:
            pdfs = []
            for link in links:
                pdf_response = self.session.get(
                    f"https://tools.madison-co.net{link['href']}"
                )
                pdfs.append(pdf_response.content)
            
            # Concatenate PDFs
            return self.merge_pdfs(pdfs), None
        return None, "No download links found"
```

#### 2. Retry Mechanism
```python
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((TimeoutException, WebDriverException))
)
def download_document(self, book: int, page: int, doc_type: str):
    # Implementation with timeout handling
    pass
```

#### 3. Session Management
- Implement connection pooling
- Handle stale element references
- Automatic session refresh after N downloads
- Cookie persistence for maintaining state

### Error Handling

#### Failure Categories
1. **Transient Failures** (Retry)
   - Network timeouts
   - Temporary server errors (5xx)
   - Rate limiting (429)

2. **Permanent Failures** (Skip & Log)
   - Document not found (404)
   - Invalid parameters (400)
   - Access denied (403)

3. **Critical Failures** (Alert & Pause)
   - Authentication failures
   - Portal structure changes
   - Disk space exhaustion

#### Logging Strategy
```python
logging.config.dictConfig({
    'version': 1,
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'downloads.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5
        },
        'error_file': {
            'class': 'logging.FileHandler',
            'filename': 'download_errors.log',
            'level': 'ERROR'
        }
    }
})
```

## Progress Tracking

### Metadata Storage
```json
{
    "download_id": "uuid",
    "book": 123,
    "page": 456,
    "document_type": "DEED",
    "portal": "historical",
    "download_timestamp": "2024-01-01T00:00:00Z",
    "file_size": 1234567,
    "checksum": "sha256_hash",
    "status": "completed",
    "retry_count": 0,
    "error_message": null
}
```

### Resume Capability
1. **Checkpoint System**
   - Save progress every 100 downloads
   - Store last successful download position
   - Enable restart from checkpoint

2. **Partial Download Recovery**
   - Detect incomplete downloads
   - Resume or restart based on file integrity
   - Validate downloaded PDFs using PyPDF2

## Performance Optimization

### Concurrent Downloads
```python
from concurrent.futures import ThreadPoolExecutor

class ParallelDownloader:
    def __init__(self, max_workers=3):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        # Separate thread pool per portal to avoid rate limiting
```

### Rate Limiting
- Implement adaptive rate limiting based on response times
- Default: 2-second delay between requests
- Backoff multiplier: 1.5x on rate limit detection

### Resource Management
- Maximum memory usage: 2GB
- Disk space monitoring with 5GB minimum threshold
- Automatic cleanup of temporary files

## File Organization

### Naming Convention
```
/downloads/
├── construction_liens/
│   ├── {book}-{page}.pdf  # e.g., 3456-123.pdf
│   └── metadata.json
├── deed/
│   ├── {book}-{page}.pdf  # 33.10% of all documents
│   └── metadata.json
├── deed_of_trust/
│   ├── {book}-{page}.pdf  # 55.93% of all documents
│   └── metadata.json       # Includes Condominium Liens
├── federal_tax_liens/
│   ├── {book}-{page}.pdf
│   └── metadata.json
├── lis_pendens/
│   ├── {book}-{page}.pdf
│   └── metadata.json
├── plats/
│   ├── {book}-{page}.pdf  # Includes both PLATS and SUBDIVISION PLATS
│   └── metadata.json
├── tax_sale/
│   ├── {book}-{page}.pdf  # Includes TAX SALE and TAX SALE 2
│   └── metadata.json
├── uccs/
│   ├── {book}-{page}.pdf  # 6.62% of all documents
│   └── metadata.json
└── indexes/
    └── {date}_index.xlsx  # e.g., 2014-08-31.xlsx
```

### Book Type Classification & Mapping
Based on analysis of Madison County records (995,743 total documents):

| Folder Name | Included Book Types | Percentage | Count |
|------------|-------------------|------------|--------|
| `deed_of_trust/` | DEED OF TRUST, CONDOMINIUM LIEN | 55.93% | 556,885 |
| `deed/` | DEED | 33.10% | 329,586 |
| `uccs/` | UCC | 6.62% | 65,898 |
| `tax_sale/` | TAX SALE, TAX SALE 2 | 2.27% | 22,608 |
| `federal_tax_liens/` | FEDERAL TAX LIENS | 1.16% | 11,552 |
| `construction_liens/` | CONSTRUCTION LIENS | 0.44% | 4,338 |
| `plats/` | PLATS, SUBDIVISION PLATS | 0.36% | 3,538 |
| `lis_pendens/` | LIS PENDENS | 0.13% | 1,338 |

### Document Type Mapping Logic
```python
BOOK_TYPE_MAPPING = {
    'DEED OF TRUST': 'deed_of_trust',
    'CONDOMINIUM LIEN': 'deed_of_trust',
    'DEED': 'deed',
    'UCC': 'uccs',
    'TAX SALE': 'tax_sale',
    'TAX SALE 2': 'tax_sale',
    'FEDERAL TAX LIENS': 'federal_tax_liens',
    'CONSTRUCTION LIENS': 'construction_liens',
    'PLATS': 'plats',
    'SUBDIVISION PLATS': 'plats',
    'LIS PENDENS': 'lis_pendens'
}

def get_document_folder(book_type: str) -> str:
    """Map book type from index to appropriate folder"""
    return BOOK_TYPE_MAPPING.get(book_type.upper(), 'miscellaneous')
```

### Validation Rules
1. PDF must be valid and openable
2. File size > 1KB (avoid empty downloads)
3. First page must be readable
4. Checksum verification for integrity

## Integration Points

### Input Sources
- Excel/CSV index files
- Manual book/page lists
- API endpoints (if available)

### Output Destinations
- Local file system (Phase 1)
- Google Cloud Storage upload queue (Phase 1.5)
- Download manifest database

## Testing Strategy

### Unit Tests
```python
def test_document_type_parsing():
    assert parse_instrument_type("DEED - REGULAR") == "DEED"
    assert parse_instrument_type("DEED OF TR") == "DEED OF TRUST"
```

### Integration Tests
- Mock portal responses
- Test retry logic with simulated failures
- Validate checkpoint/resume functionality

### End-to-End Tests
- Download sample set from each portal
- Verify file integrity
- Confirm metadata accuracy

## Monitoring & Alerts

### Key Metrics
- Downloads per hour
- Success/failure rates by portal
- Average download time
- Queue depth

### Alert Conditions
- Success rate < 80% over 1 hour
- No downloads in 30 minutes
- Disk space < 5GB
- Memory usage > 80%

## Security Considerations

### Data Protection
- No credentials stored in code
- Secure temporary file handling
- Audit log of all downloads

### Rate Limit Compliance
- Respect robots.txt
- User-Agent identification
- Graceful backoff on 429 responses

## Future Enhancements

### Phase 2 Considerations
- Incremental download detection
- Delta synchronization
- API integration if Madison County provides one
- Machine learning for document classification

### Scalability Path
- Distributed downloading across multiple machines
- Message queue integration (Redis/RabbitMQ)
- Cloud-native architecture migration