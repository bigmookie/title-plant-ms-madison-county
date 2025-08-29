# Madison County Title Plant - Technical Specification

## Development Methodology

### Test-Driven Development Approach
Following Claude Code best practices, all components will be developed using TDD:
1. Write failing tests for each new feature
2. Commit tests to version control
3. Implement code to satisfy test requirements
4. Validate implementation with independent verification
5. Refactor and optimize with test coverage intact

### Iterative Development Workflow
- **Planning Phase**: Use enhanced reasoning ("think hard") for complex algorithms
- **Implementation Phase**: Incremental development with frequent validation
- **Review Phase**: Independent sub-agent verification of critical components
- **Documentation Phase**: Update specs and API docs with each iteration

## System Architecture

### Phase 1: Data Collection & Storage

#### 1.1 Document Download System

**Primary Tool**: `madison_county_doc_puller/doc_puller.py`
- Selenium-based web scraper supporting three portals:
  - **Historical Portal**: Books < 238 via dropdown interface (includes Book 237)
  - **MID Portal**: Books 238-3971 via direct URL construction  
  - **DuProcess Portal**: Books 3972+ (excluded from Phase 1)
- **Error Recovery**: Implement retry mechanism with exponential backoff for failed downloads
- **Storage Pipeline**:
  1. Download PDF to temporary local directory
  2. Optimize PDF (compress, standardize resolution)
  3. Upload optimized PDF to GCS at `documents/optimized-pdfs/{doc_type}/book-{book}/{book}-{page}.pdf`
  4. Delete temporary local files
  5. Log successful upload with checksum

**Index Processing**:
- Process all Excel files in `madison_docs/DuProcess Indexes/` (1985-2014+)
- Extract Book/Page combinations for systematic downloading
- Parse InstrumentType field using regex to extract document type before " -"
- Implement fuzzy matching for truncated document types:
  - "ASSIGNMENT OF DEED O" → "ASSIGNMENT OF DEED OF TRUST"
  - "AMENDED PROTECTIVE C" → "AMENDED PROTECTIVE COVENANT"
  - Use Levenshtein distance or similar algorithm
- Map document types to standardized codes from doc_type_lookup dictionary
- Generate consolidated download queue with portal routing and document type

**New Web Scrapers Required** (Priority Order):

1. **Historical Wills Scraper** (PRIORITY 1)
   - Target: `https://tools.madison-co.net/elected-offices/chancery-clerk/drupal-search-historical-books/`
   - Pattern: `?file=MAD-WILL-A-0001.pdf&method=browse&type=will`
   - Extract will book/page combinations from `madison_docs/Wills - Historic.xlsx`
   - Implement retry mechanism for download failures

2. **Will Index Scraper (1992-2009)**
   - Target: `https://www.madison-co.com/search-will-index-1992-present`
   - Extract structured will index data

3. **Will Index Scraper (1892-1992)**
   - Target: `https://www.madison-co.com/search-will-index-1892-1992`
   - Download PDF indexes for processing

4. **Chancery Cases Scraper (1871-1982)**
   - Target: `https://www.madison-co.com/search-index-chancery-cases-book-1-1871-1982`
   - Extract chancery cause documents

5. **Chancery Cases Scraper (1982-1992)**
   - Target: `https://www.madison-co.com/search-index-chancery-cases-book-2-1982-1992`
   - Continue chancery case extraction

6. **Chancery Court Case Inquiry (1992-2009)**
   - Target: `https://www.madison-co.com/chancery-court-case-file-inquiry`
   - Extract modern chancery case files

#### 1.2 Storage Architecture

**Google Cloud Storage Structure**:
```
madison-county-title-plant/
├── documents/
│   ├── optimized-pdfs/
│   │   ├── deeds/
│   │   │   ├── book-001/
│   │   │   │   ├── 001-0001.pdf
│   │   │   │   └── 001-0002.pdf
│   │   │   └── book-xxx/
│   │   ├── deeds-of-trust/
│   │   │   └── book-xxx/
│   │   ├── wills/
│   │   │   └── book-xxx/
│   │   └── chancery/
│   │       └── case-xxx/
│   └── extracted-text/
│       ├── deeds/
│       │   ├── book-001/
│       │   │   ├── 001-0001.json
│       │   │   └── 001-0002.json
│       │   └── book-xxx/
│       ├── deeds-of-trust/
│       │   └── book-xxx/
│       ├── wills/
│       │   └── book-xxx/
│       └── chancery/
│           └── case-xxx/
└── indexes/
    ├── master-index/
    └── search-indexes/
```

**PDF Optimization Pipeline**:
- Download document to temporary local storage
- Optimize PDF (compress images, standardize resolution)
- Upload optimized version to GCS
- Delete local temporary files (both raw and optimized)
- Generate and store checksums for data validation
- Maintain consistent naming: `{book}-{page}.pdf` and `{book}-{page}.json`

### Phase 2: Text Extraction & Processing

#### 2.1 OCR Pipeline

**Google Document AI Integration**:
- Utilize existing `doc_reader/document_reader.py` framework
- **Phase 1**: Extract raw text using Google Document AI only
- **Phase 2**: Apply AI services (OpenAI/Gemini/Claude) for OCR error correction if needed
- Batch process documents by type for optimal API usage
- Implement retry logic for failed extractions
- **Storage Format**: Save extracted text as JSON with metadata:
  - Store at `documents/extracted-text/{doc_type}/book-{book}/{book}-{page}.json`
  - Match PDF filename structure for easy correlation
  - Include OCR confidence scores and processing metadata
- Prioritize raw text extraction over AI processing for cost efficiency

**Text Processing Pipeline**:
1. **Document Classification**
   - Identify document type using `records_models.py` enums
   - Classify by DocumentCategory (CONVEYANCE, SECURITY, SERVITUDES, etc.)
   - Determine SubjectMatter (SURFACE, MINERAL, TIMBER, ROYALTY)

2. **Data Extraction**
   - Party identification (grantors/grantees)
   - Property descriptions (legal descriptions, addresses)
   - Recording information (book, page, date)
   - Financial details (consideration, loan amounts)
   - Special provisions (reservations, easements, restrictions)

3. **Entity Resolution**
   - Normalize party names across documents
   - Standardize property descriptions
   - Link related documents (assignments, releases, modifications)

#### 2.2 Data Models Implementation

**Core Models** (from `records_models.py`):
```python
@dataclass
class RecordedDocument:
    document_id: str
    doc_type: DocumentType
    categories: Set[DocumentCategory]
    subject_matters: Set[SubjectMatter]
    instrument_number: Optional[str]
    recording_date: date
    short_description: Optional[str]
    notes: Optional[str]
```

**Extended Models for Title Plant**:
- PropertyDescription
- Party (with name variations)
- DocumentRelationship
- TitleChain
- Encumbrance

### Phase 3: Title Plant Implementation

#### 3.1 Database Design

**Relational Structure**:
- Documents table (core document metadata)
- Parties table (normalized party names)
- Properties table (standardized legal descriptions)
- Document_Parties junction (grantor/grantee relationships)
- Document_Properties junction (property involvement)
- Title_Chains table (computed ownership sequences)

**Indexing Strategy**:
- B-tree indexes on recording dates, book/page
- Full-text search indexes on property descriptions
- Composite indexes for common query patterns
- Spatial indexes for property boundaries (future enhancement)

#### 3.2 Search & Analysis Algorithms

**Title Chain Construction**:
1. **Backward Chain Analysis**
   - Start from current owner/deed
   - Follow grantor→grantee relationships backward
   - Identify chain breaks and resolve conflicts
   - Flag potential title defects

2. **Encumbrance Discovery**
   - Cross-reference all recorded instruments affecting property
   - Classify by type (liens, easements, restrictions)
   - Determine active vs. released encumbrances
   - Calculate priority ordering

3. **Gap Analysis**
   - Identify missing links in ownership chain
   - Flag potential adverse possession claims
   - Highlight areas requiring additional research

#### 3.3 API Design

**RESTful Endpoints**:
```
GET /api/title-search/{property-id}
POST /api/title-report/generate
GET /api/documents/search
GET /api/property/{legal-description}
```

**Response Format**:
- JSON structure with embedded document references
- Include confidence scores for automated findings
- Provide manual review flags for complex cases
- Support both summary and detailed report formats

### Quality Assurance & Validation

#### Data Quality Checks
- Document count validation against known indexes
- OCR accuracy sampling and validation
- Cross-reference checks between related documents
- Automated detection of data anomalies

#### Performance Requirements
- Sub-second response for simple title searches
- Batch processing capability for large document sets
- Scalable cloud architecture supporting concurrent users
- 99.9% uptime for production API endpoints

### Security & Compliance

#### Data Protection
- Encrypt sensitive document data at rest and in transit
- Implement role-based access controls
- Maintain audit logs for all system access
- Comply with applicable privacy regulations

#### Backup & Recovery
- Daily incremental backups of all processed data
- Weekly full backups with long-term retention
- Disaster recovery procedures with RTO < 4 hours
- Cross-region data replication for business continuity

### Deployment Strategy

#### Development Environment
- Local development with Docker containers
- Automated testing pipeline with CI/CD integration
- Staging environment mirroring production architecture
- Claude Code integration for development assistance

#### Environment Configuration
- Use `.env` file for all API keys and sensitive configuration
- Never commit API keys to version control
- Environment variables structure:
```bash
# API Keys
OPENAI_API_KEY=your-key-here
GEMINI_API_KEY=your-key-here
CLAUDE_API_KEY=your-key-here

# Google Cloud Configuration
GOOGLE_CLOUD_PROJECT=madison-county-title
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
GCS_BUCKET_NAME=madison-county-title-plant
DOCUMENT_AI_PROCESSOR_ID=2a9f06e7330cbb0a
DOCUMENT_AI_LOCATION=us

# Database Configuration
DATABASE_URL=postgresql://user:pass@host:port/dbname
```

#### Production Deployment
- Google Cloud Platform infrastructure
- Kubernetes orchestration for scalability
- Cloud Storage for document repository
- Cloud SQL for relational data
- Monitoring and alerting with Stackdriver

### MCP Integration Architecture

#### Potential MCP Server Implementations
1. **Document Processing Server**
   - Specialized OCR and text extraction
   - Document classification and routing
   - Batch processing optimization

2. **Title Search Server**
   - Complex query optimization
   - Chain-of-title construction
   - Encumbrance analysis

3. **External API Gateway**
   - County clerk system integration
   - Third-party title data services
   - Real-time property tax lookups

#### MCP Configuration
```json
{
  "mcpServers": {
    "document-processor": {
      "command": "python",
      "args": ["mcp_servers/document_processor.py"],
      "env": {
        "GOOGLE_CLOUD_PROJECT": "madison-county-title"
      }
    },
    "title-search": {
      "command": "python",
      "args": ["mcp_servers/title_search.py"],
      "env": {
        "DATABASE_URL": "${DATABASE_URL}"
      }
    }
  }
}
```

### Claude Code Integration Points

#### Automated Workflows
1. **Data Validation Pipeline**
   - Claude validates extracted data against known patterns
   - Flags anomalies for human review
   - Suggests corrections based on context

2. **Code Generation Templates**
   - Scraper templates for new document sources
   - Data model extensions for new document types
   - API endpoint scaffolding

3. **Testing Automation**
   - Generate comprehensive test cases
   - Mock data creation for edge cases
   - Performance testing scenarios

### Success Metrics

#### Phase 1 Success Criteria
- Successfully download 100% of available historical documents
- Achieve <5% download failure rate with robust retry logic
- Implement efficient PDF optimization reducing storage by 30%+

#### Phase 2 Success Criteria  
- Achieve 95%+ OCR accuracy on clear documents
- Successfully classify 90%+ of documents by type
- Extract key data points (parties, dates, property) from 85%+ of documents

#### Phase 3 Success Criteria
- Generate complete title chains for 80%+ of properties
- Identify all recorded encumbrances with 95%+ accuracy
- Support programmatic title searches with <2 second response time