# Storage Architecture Specification

## Overview
This specification defines the storage architecture for the Madison County Title Plant, utilizing Google Cloud Storage (GCS) as the primary repository with local staging and intelligent caching. The system emphasizes cost optimization, efficient retrieval, and scalability.

## Authentication Strategy

### Recommended Approach: API Key Authentication
Based on the project requirements and Google's authentication documentation, we recommend using **API keys** for GCS operations where supported, with ADC as a fallback for operations requiring more complex permissions.

#### Rationale
1. **Simplicity**: No service account JSON files to manage
2. **Security**: API keys can be restricted to specific APIs and operations
3. **Portability**: Easier to configure across different environments
4. **Express Mode Compatible**: Works with Google Cloud express mode

#### Implementation
```python
from google.cloud import storage

# For operations that support API keys
storage_client = storage.Client(
    client_options={"api_key": os.environ.get("GCS_API_KEY")}
)

# Fallback to ADC for operations requiring it
# Set up via: gcloud auth application-default login
fallback_client = storage.Client()
```

## Storage Hierarchy

### Bucket Structure
```
madison-county-title-plant/
├── optimized-documents/     # Compressed PDFs only (no raw storage)
│   ├── construction_liens/
│   │   └── {book}-{page}.pdf
│   ├── deed/
│   │   └── {book}-{page}.pdf
│   ├── deed_of_trust/
│   │   └── {book}-{page}.pdf
│   ├── federal_tax_liens/
│   │   └── {book}-{page}.pdf
│   ├── lis_pendens/
│   │   └── {book}-{page}.pdf
│   ├── plats/
│   │   └── {book}-{page}.pdf
│   ├── tax_sale/
│   │   └── {book}-{page}.pdf
│   └── uccs/
│       └── {book}-{page}.pdf
├── ocr-output/              # Raw OCR extraction results
│   ├── construction_liens/
│   │   └── {book}-{page}.json
│   ├── deed/
│   │   └── {book}-{page}.json
│   ├── deed_of_trust/
│   │   └── {book}-{page}.json
│   ├── federal_tax_liens/
│   │   └── {book}-{page}.json
│   ├── lis_pendens/
│   │   └── {book}-{page}.json
│   ├── plats/
│   │   └── {book}-{page}.json
│   ├── tax_sale/
│   │   └── {book}-{page}.json
│   └── uccs/
│       └── {book}-{page}.json
├── human-approved-ocr/      # Human-reviewed and corrected OCR
│   ├── construction_liens/
│   │   └── {book}-{page}.json
│   ├── deed/
│   │   └── {book}-{page}.json
│   ├── deed_of_trust/
│   │   └── {book}-{page}.json
│   ├── federal_tax_liens/
│   │   └── {book}-{page}.json
│   ├── lis_pendens/
│   │   └── {book}-{page}.json
│   ├── plats/
│   │   └── {book}-{page}.json
│   ├── tax_sale/
│   │   └── {book}-{page}.json
│   └── uccs/
│       └── {book}-{page}.json
├── indexes/                 # Search indexes and manifests
│   └── {date}_index.xlsx
└── analytics/              # Derived data and reports
```

### Naming Conventions
```python
def generate_gcs_path(book_type: str, book: int, page: int, 
                     storage_type: str, suffix: str) -> str:
    """
    Generate standardized GCS object path
    Pattern: {storage_type}/{book_type_folder}/{book}-{page}.{suffix}
    
    Args:
        book_type: Document type (e.g., "DEED OF TRUST")
        book: Book number
        page: Page number
        storage_type: "optimized-documents", "ocr-output", or "human-approved-ocr"
        suffix: File extension (pdf, json)
    """
    # Map book type to folder name (matches document-download-spec.md)
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
    
    folder = BOOK_TYPE_MAPPING.get(book_type.upper(), 'miscellaneous')
    return f"{storage_type}/{folder}/{book}-{page}.{suffix}"
```

## Storage Classes & Lifecycle

### Storage Class Strategy (Based on Access Patterns)
```python
class StorageClassPolicy:
    """
    Storage classes aligned with document lifecycle and access patterns.
    Based on GCS best practices for cost optimization.
    """
    # Initial upload and active processing phase
    OPTIMIZED_DOCUMENTS_NEW = "STANDARD"     # First 30 days - frequent access
    OCR_OUTPUT_ACTIVE = "STANDARD"          # Active OCR processing
    HUMAN_APPROVED_NEW = "STANDARD"         # Recently reviewed documents
    
    # Aging document tiers (automated via lifecycle policies)
    DOCUMENTS_MONTHLY = "NEARLINE"          # 30-90 days - monthly access
    DOCUMENTS_QUARTERLY = "COLDLINE"        # 90-365 days - quarterly access  
    DOCUMENTS_ARCHIVE = "ARCHIVE"           # 365+ days - yearly or less
```

### Lifecycle Rules (Cascading Tiering Strategy)
```json
{
    "lifecycle": {
        "rules": [
            {
                "comment": "Move optimized PDFs to Nearline after 30 days",
                "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
                "condition": {
                    "age": 30,
                    "matchesPrefix": ["optimized-documents/"],
                    "matchesStorageClass": ["STANDARD"]
                }
            },
            {
                "comment": "Move optimized PDFs to Coldline after 90 days",
                "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
                "condition": {
                    "age": 90,
                    "matchesPrefix": ["optimized-documents/"],
                    "matchesStorageClass": ["NEARLINE"]
                }
            },
            {
                "comment": "Archive optimized PDFs after 365 days",
                "action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"},
                "condition": {
                    "age": 365,
                    "matchesPrefix": ["optimized-documents/"],
                    "matchesStorageClass": ["COLDLINE"]
                }
            },
            {
                "comment": "Move OCR output to Nearline after 60 days",
                "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
                "condition": {
                    "age": 60,
                    "matchesPrefix": ["ocr-output/", "human-approved-ocr/"],
                    "matchesStorageClass": ["STANDARD"]
                }
            },
            {
                "comment": "Archive OCR data after 180 days",
                "action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"},
                "condition": {
                    "age": 180,
                    "matchesPrefix": ["ocr-output/", "human-approved-ocr/"],
                    "matchesStorageClass": ["NEARLINE"]
                }
            },
            {
                "comment": "Clean up incomplete multipart uploads after 7 days",
                "action": {"type": "AbortIncompleteMultipartUpload"},
                "condition": {"age": 7}
            }
        ]
    }
}
```

### Cost Optimization Considerations
```python
class CostModelingFactors:
    """
    Comprehensive cost factors per GCS research recommendations.
    All costs are examples and subject to change.
    """
    # Storage costs (per GB/month) - Multi-region North America
    STORAGE_COSTS = {
        "STANDARD": 0.026,
        "NEARLINE": 0.010,  # 62% savings vs Standard
        "COLDLINE": 0.007,  # 73% savings vs Standard
        "ARCHIVE": 0.004    # 85% savings vs Standard
    }
    
    # Retrieval fees (per GB) - Critical for cold tiers
    RETRIEVAL_FEES = {
        "STANDARD": 0.00,
        "NEARLINE": 0.01,   # Adds cost for access
        "COLDLINE": 0.02,   # Higher retrieval cost
        "ARCHIVE": 0.05     # Highest retrieval cost
    }
    
    # Minimum storage durations (days) - Early deletion penalties apply
    MIN_STORAGE_DURATION = {
        "STANDARD": 0,
        "NEARLINE": 30,
        "COLDLINE": 90,
        "ARCHIVE": 365
    }
    
    # Operation costs increase for colder tiers
    CLASS_A_OPS_PER_1000 = {
        "STANDARD": 0.005,
        "NEARLINE": 0.010,
        "COLDLINE": 0.020,
        "ARCHIVE": 0.050   # 10x more expensive than Standard
    }
```

## Upload Pipeline

### Local Staging
```python
class LocalToGCSPipeline:
    def __init__(self):
        self.staging_dir = Path("/staging/uploads")
        self.batch_size = 100  # Files per batch
        self.chunk_size = 8 * 1024 * 1024  # 8MB chunks
        
    def upload_with_retry(self, local_path: Path, gcs_path: str):
        """Upload with resumable transfers and retry logic"""
        blob = bucket.blob(gcs_path)
        blob.chunk_size = self.chunk_size
        
        with exponential_backoff() as retry:
            blob.upload_from_filename(
                local_path,
                content_type='application/pdf',
                checksum='crc32c'
            )
```

### Batch Upload Process
1. **Accumulate files locally** until batch_size reached
2. **Validate PDFs** before upload
3. **Compress if beneficial** (>20% size reduction)
4. **Upload in parallel** with thread pool
5. **Verify checksums** post-upload
6. **Clean up local files** after confirmation

### Compression Strategy
```python
def should_compress(pdf_path: Path) -> bool:
    """Determine if PDF compression would be beneficial"""
    original_size = pdf_path.stat().st_size
    
    # Skip if already small
    if original_size < 100_000:  # 100KB
        return False
    
    # Test compression ratio
    test_compressed = compress_pdf_sample(pdf_path)
    compression_ratio = test_compressed.size / original_size
    
    return compression_ratio < 0.8  # 20% reduction threshold
```

## PDF Optimization

### Optimization Techniques
1. **Image Downsampling**
   ```python
   gs_command = [
       'gs', '-sDEVICE=pdfwrite',
       '-dCompatibilityLevel=1.4',
       '-dPDFSETTINGS=/ebook',  # 150 dpi
       '-dNOPAUSE', '-dBATCH',
       '-sOutputFile=output.pdf',
       'input.pdf'
   ]
   ```

2. **Remove Redundant Data**
   - Strip JavaScript
   - Remove form fields
   - Clean metadata
   - Eliminate duplicate images

3. **Selective Compression**
   - Maintain text quality
   - Compress images based on type
   - Preserve vector graphics

### Quality Thresholds
```python
class QualityMetrics:
    MIN_DPI = 150              # Minimum resolution for OCR
    MAX_COMPRESSION = 0.3      # Maximum 70% size reduction
    TEXT_CLARITY_SCORE = 0.8   # Minimum OCR confidence
```

## Data Organization

### Custom Metadata Strategy
Based on GCS limitations (no native metadata search), we implement a dual approach:
1. **GCS Custom Metadata**: Stored with objects for context
2. **External Search Index**: Cloud Firestore/BigQuery for searchable metadata

```python
class DocumentMetadata:
    """
    Custom metadata attached to each GCS object.
    Note: Keys must be prefixed with 'x-goog-meta-' when set via API.
    """
    # Standard metadata
    CONTENT_TYPE = "application/pdf"
    CONTENT_DISPOSITION = 'attachment; filename="{book}-{page}.pdf"'
    
    # Custom metadata fields (searchable via external index)
    CUSTOM_METADATA = {
        "x-goog-meta-book": "{book}",
        "x-goog-meta-page": "{page}",
        "x-goog-meta-book-type": "{book_type}",  # e.g., "DEED OF TRUST"
        "x-goog-meta-document-id": "{book}-{page}",
        "x-goog-meta-recording-date": "{recording_date}",
        "x-goog-meta-grantor": "{grantor}",
        "x-goog-meta-grantee": "{grantee}",
        "x-goog-meta-legal-description": "{legal_desc_hash}",  # Hash for quick lookup
        "x-goog-meta-ocr-status": "{status}",  # pending, completed, approved
        "x-goog-meta-ocr-confidence": "{confidence}",
        "x-goog-meta-processing-date": "{date}",
        "x-goog-meta-checksum": "{crc32c}"
    }
```

### External Search Index Structure
```json
{
    "document_id": "3456-789",
    "gcs_paths": {
        "optimized": "gs://madison-county-title-plant/optimized-documents/deed_of_trust/3456-789.pdf",
        "ocr": "gs://madison-county-title-plant/ocr-output/deed_of_trust/3456-789.json",
        "approved": "gs://madison-county-title-plant/human-approved-ocr/deed_of_trust/3456-789.json"
    },
    "metadata": {
        "book": 3456,
        "page": 789,
        "book_type": "DEED OF TRUST",
        "document_type_folder": "deed_of_trust",
        "recording_date": "2024-01-15",
        "parties": {
            "grantor": ["John Smith", "Jane Smith"],
            "grantee": ["ABC Bank Corporation"]
        },
        "legal_description": "Lot 5, Block 3, Madison Heights Subdivision",
        "file_sizes": {
            "optimized_pdf": 876543,
            "ocr_json": 12345
        },
        "checksums": {
            "optimized": "crc32c:abc123...",
            "ocr": "crc32c:def456..."
        },
        "ocr_metrics": {
            "confidence": 0.95,
            "status": "approved",
            "approved_date": "2024-01-20",
            "reviewer": "user@example.com"
        },
        "upload_timestamp": "2024-01-15T10:30:00Z",
        "last_accessed": "2024-02-01T14:22:00Z"
    }
}
```

### Index Structure
```python
# Primary index for fast lookups
primary_index = {
    "book_1_page_1": "0001_0001_DEED",
    "book_1_page_2": "0001_0002_DEED_OF_TRUST",
    # ...
}

# Secondary indexes for search
type_index = {
    "DEED": ["0001_0001_DEED", "0001_0003_DEED"],
    "DEED_OF_TRUST": ["0001_0002_DEED_OF_TRUST"],
    # ...
}
```

## Caching Strategy

### Local Cache
```python
class LocalCache:
    def __init__(self, max_size_gb=50):
        self.cache_dir = Path("/cache/documents")
        self.max_size = max_size_gb * 1024**3
        self.lru_index = OrderedDict()
        
    def get_or_fetch(self, document_id: str) -> Path:
        if document_id in self.lru_index:
            # Move to end (most recently used)
            self.lru_index.move_to_end(document_id)
            return self.cache_dir / f"{document_id}.pdf"
        
        # Fetch from GCS
        path = self.fetch_from_gcs(document_id)
        self.add_to_cache(document_id, path)
        return path
```

### CDN Configuration (Future)
- Cloud CDN for frequently accessed documents
- Regional edge caches
- Custom cache keys based on document ID

## Access Control & Document Retrieval

### Bucket Configuration
```python
class BucketConfiguration:
    """
    GCS bucket setup following security best practices from research.
    """
    BUCKET_NAME = "madison-county-title-plant"
    LOCATION = "us-central1"  # Regional for cost optimization
    
    # Security settings
    UNIFORM_ACCESS = True  # Disable ACLs, use IAM only
    PUBLIC_ACCESS_PREVENTION = "enforced"  # Prevent public access
    VERSIONING = True  # Enable for data protection
    
    # Encryption
    DEFAULT_KMS_KEY = None  # Use Google-managed encryption
    
    # CORS configuration for web access
    CORS_CONFIG = [{
        "origin": ["https://madison-title-plant.com"],
        "method": ["GET", "HEAD"],
        "responseHeader": ["Content-Type"],
        "maxAgeSeconds": 3600
    }]
```

### IAM Permissions (Principle of Least Privilege)
```python
# Service account roles
SERVICE_ROLES = {
    "uploader": {
        "title": "Document Uploader",
        "role": "roles/storage.objectCreator",  # Can only create, not delete
        "bucket": "madison-county-title-plant",
        "prefix": "optimized-documents/*"
    },
    "ocr_processor": {
        "title": "OCR Processor",
        "role": "roles/storage.objectViewer",  # Read-only access
        "bucket": "madison-county-title-plant",
        "prefix": "optimized-documents/*"
    },
    "ocr_writer": {
        "title": "OCR Writer",
        "role": "roles/storage.objectCreator",
        "bucket": "madison-county-title-plant",
        "prefix": "ocr-output/*"
    },
    "api_service": {
        "title": "API Service Account",
        "role": "roles/storage.objectViewer",
        "bucket": "madison-county-title-plant",
        "description": "Generates signed URLs for user downloads"
    }
}
```

### Signed URLs for Secure Document Access
```python
from google.cloud import storage
from datetime import timedelta

class SecureDocumentAccess:
    """
    Implements signed URL pattern for secure, time-limited document access.
    Based on GCS best practices for serving documents to end users.
    """
    
    def __init__(self):
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket("madison-county-title-plant")
        
    def generate_signed_url(self, 
                          book: int, 
                          page: int,
                          book_type: str,
                          expiration_minutes: int = 5) -> str:
        """
        Generate a signed URL for secure document download.
        
        This is the architecturally superior pattern for end-user downloads:
        1. User requests document through API
        2. API validates user permissions
        3. API generates short-lived signed URL
        4. User downloads directly from GCS (bypassing API server)
        
        Benefits:
        - Offloads bandwidth from application servers
        - Leverages Google's global CDN
        - Provides time-limited access without permanent permissions
        """
        # Map book type to folder
        folder = self.get_folder_name(book_type)
        blob_name = f"optimized-documents/{folder}/{book}-{page}.pdf"
        
        blob = self.bucket.blob(blob_name)
        
        # Generate signed URL with short expiration
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
            response_disposition=f'attachment; filename="{book}-{page}.pdf"',
            response_type="application/pdf"
        )
        
        return url
    
    def generate_batch_urls(self, documents: list, expiration_minutes: int = 15) -> dict:
        """
        Generate signed URLs for multiple documents (e.g., title chain).
        Longer expiration for batch downloads.
        """
        urls = {}
        for doc in documents:
            key = f"{doc['book']}-{doc['page']}"
            urls[key] = self.generate_signed_url(
                book=doc['book'],
                page=doc['page'],
                book_type=doc['book_type'],
                expiration_minutes=expiration_minutes
            )
        return urls
```

### API Key Configuration (Limited Use)
```python
# API keys only for operations that support them
# Most GCS operations require OAuth2/Service Account auth
api_key_config = {
    "description": "Limited to public bucket operations only",
    "restrictions": {
        "api_targets": [
            {
                "service": "storage.googleapis.com",
                "methods": ["storage.objects.list"]  # Very limited scope
            }
        ],
        "ip_restrictions": ["35.235.240.0/20"]  # Restrict to GCP IPs
    }
}
```

## Cost Optimization

### Storage Costs (Monthly Estimates)
```python
def calculate_storage_costs():
    # Assumptions
    total_documents = 500_000
    avg_size_mb = 2
    compression_ratio = 0.4
    
    # Raw storage (STANDARD -> NEARLINE -> COLDLINE)
    raw_size_gb = (total_documents * avg_size_mb) / 1024
    raw_cost_month_1 = raw_size_gb * 0.020  # STANDARD
    raw_cost_month_2_3 = raw_size_gb * 0.010  # NEARLINE
    raw_cost_after = raw_size_gb * 0.004  # COLDLINE
    
    # Optimized storage (NEARLINE)
    opt_size_gb = raw_size_gb * compression_ratio
    opt_cost = opt_size_gb * 0.010
    
    return {
        "month_1": raw_cost_month_1 + opt_cost,
        "month_2_3": raw_cost_month_2_3 + opt_cost,
        "ongoing": raw_cost_after + opt_cost
    }
```

### Optimization Strategies
1. **Aggressive Compression** for documents > 6 months old
2. **Delete Temporary Files** after 30 days
3. **Archive Rarely Accessed** documents (>1 year)
4. **Batch Operations** to minimize API calls
5. **Regional Storage** in us-central1 (lowest cost)

## Event-Driven Processing with Cloud Functions

### Serverless PDF Processing Pipeline
```python
import functions_framework
from google.cloud import storage, firestore
import PyPDF2

@functions_framework.cloud_event
def process_uploaded_pdf(cloud_event):
    """
    Cloud Function triggered by document upload to GCS.
    Implements event-driven architecture for automatic processing.
    
    Trigger: google.storage.object.finalize
    """
    # Extract event data
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]
    
    # Parse file path to extract metadata
    # Example: optimized-documents/deed_of_trust/3456-789.pdf
    parts = file_name.split('/')
    if len(parts) != 3:
        return
    
    storage_type = parts[0]
    book_type_folder = parts[1]
    file_base = parts[2].replace('.pdf', '')
    book, page = file_base.split('-')
    
    if storage_type == "optimized-documents":
        # Trigger OCR processing
        trigger_ocr_processing(bucket_name, file_name, book, page, book_type_folder)
    
    # Update search index
    update_search_index(bucket_name, file_name, book, page, book_type_folder)

def update_search_index(bucket_name: str, file_name: str, 
                        book: str, page: str, book_type: str):
    """
    Update external search index in Firestore.
    This addresses GCS's lack of native metadata search.
    """
    db = firestore.Client()
    storage_client = storage.Client()
    
    # Get object metadata
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    blob.reload()  # Fetch metadata
    
    # Build index document
    doc_ref = db.collection('document_index').document(f"{book}-{page}")
    doc_ref.set({
        'book': int(book),
        'page': int(page),
        'book_type': book_type,
        'gcs_path': f"gs://{bucket_name}/{file_name}",
        'file_size': blob.size,
        'content_type': blob.content_type,
        'created': blob.time_created,
        'updated': blob.updated,
        'custom_metadata': blob.metadata or {},
        'checksum': blob.crc32c,
        'indexed_at': firestore.SERVER_TIMESTAMP
    })
```

### Cloud Function Deployment
```yaml
# function-config.yaml
name: process-uploaded-pdf
entry_point: process_uploaded_pdf
runtime: python311
trigger:
  event_type: google.storage.object.finalize
  resource: madison-county-title-plant
  retry: true
env_vars:
  - FIRESTORE_PROJECT: madison-county-title-plant
max_instances: 100
timeout: 540s
memory: 512M
```

## Monitoring & Metrics

### Key Metrics (Based on GCS Best Practices)
```python
class StorageMetrics:
    """
    Comprehensive metrics for cost and performance monitoring.
    """
    # Cost metrics
    COST_METRICS = [
        "storage_cost_by_class",     # Track costs per storage tier
        "retrieval_fees_monthly",    # Monitor cold tier access costs
        "operation_costs_daily",     # Class A/B operation costs
        "early_deletion_penalties",  # Track lifecycle misalignment
        "network_egress_costs"       # Data transfer costs
    ]
    
    # Performance metrics
    PERFORMANCE_METRICS = [
        "upload_throughput_mbps",
        "download_latency_p99",
        "signed_url_generation_time",
        "compression_ratio_avg",
        "cache_hit_ratio"
    ]
    
    # Operational metrics
    OPERATIONAL_METRICS = [
        "total_objects_by_type",
        "storage_gb_by_class",
        "lifecycle_transitions_daily",
        "failed_uploads_hourly",
        "ocr_queue_depth"
    ]
```

### Alert Conditions
```python
ALERT_THRESHOLDS = {
    # Cost alerts
    "monthly_storage_budget": 1000,  # USD
    "retrieval_cost_spike": 100,     # USD per day
    
    # Performance alerts
    "upload_failure_rate": 0.05,     # 5% threshold
    "signed_url_generation": 1.0,    # seconds
    
    # Capacity alerts
    "storage_usage_percent": 80,     # of quota
    "object_count": 10_000_000       # scalability limit
}
```

## Disaster Recovery

### Backup Strategy
1. **Cross-Region Replication** for critical data
2. **Versioning** enabled on all buckets
3. **Soft Delete** with 7-day retention
4. **Regular Exports** to Archive storage

### Recovery Procedures
```python
def restore_from_backup(date: datetime):
    """Restore documents to specific point in time"""
    # List versions before date
    # Copy versions to restore bucket
    # Validate integrity
    # Switch traffic to restore bucket
```

## Migration Path

### Phase 1: Local Storage
- Download to local disk
- Organize in standard structure
- Build upload queue

### Phase 2: GCS Migration
- Batch upload to GCS
- Maintain local cache
- Update references

### Phase 3: Full Cloud
- Direct download to GCS
- Serverless processing
- Global CDN distribution

## Testing Requirements

### Unit Tests
- Path generation logic
- Compression algorithms
- Cache eviction policies

### Integration Tests
- GCS upload/download
- API key authentication
- Lifecycle rule application

### Performance Tests
- Upload throughput
- Compression ratios
- Cache efficiency

## Security Considerations

### Data Protection
- Encryption at rest (AES-256)
- Encryption in transit (TLS 1.2+)
- Signed URLs for temporary access
- Audit logging enabled

### Access Patterns
- No public bucket access
- Service-specific API keys
- Principle of least privilege
- Regular permission audits