# Madison County Title Plant Project

## Project Overview
This project aims to create a comprehensive digital title plant for Madison County, Mississippi by systematically downloading, processing, and indexing all available historical land records. The system will enable programmatic title searches and automated title report generation.

## Claude Code Integration Guidelines

### Project Context
This CLAUDE.md file provides situational awareness for Claude Code when working in this repository. It captures essential workflows, commands, and project-specific instructions for efficient development.

### Key Commands & Tools
- **Testing**: `python -m pytest tests/` - Run the test suite
- **Linting**: `python -m black .` and `python -m flake8` - Code formatting and linting
- **Document Processing**: `python madison_county_doc_puller/doc_puller.py` - Run document downloader
- **OCR Processing**: `python doc_reader/document_reader.py` - Extract text from PDFs

### Development Workflow
1. **Test-Driven Development**: Generate failing tests first, then implement features
2. **Validation Steps**: Use independent verification for critical data extraction
   - Deploy sub-agents for validating legal description parsing
   - Independent verification of entity resolution across documents
   - Cross-check title chain construction algorithms
3. **Iterative Refinement**: Review and refine code through multiple passes
4. **Documentation**: Update technical specs and API documentation as code evolves

### Enhanced Reasoning for Complex Tasks
When tackling complex challenges, use these keywords to activate deeper reasoning:
- **"think hard"** - For complex data extraction algorithms
- **"ultrathink"** - For multi-step legal document analysis workflows
- Specifically apply to:
  - Legal description parsing from OCR text
  - Entity resolution across multiple documents
  - Title chain construction and gap analysis
  - Fuzzy matching for document type classification

## Key Components

### Data Sources
1. **Historical Deeds & Deeds of Trust** - Available through three portals:
   - Historical Books portal (Books < 238, includes Book 237)
   - MID portal (Books 238-3971)
   - DuProcess/NEW portal (Books 3972+, excluded from Phase 1)

2. **Will Records**:
   - Historical wills from drupal-search-historical-books
   - Will indexes (1892-1992 and 1992-2009)

3. **Chancery Court Records**:
   - Chancery causes (1871-1982)
   - Chancery cases (1982-1992)
   - Case file inquiries (1992-2009)

### Existing Infrastructure
- TBD

### Project Phases

#### Phase 1: Data Collection & Storage
- Download all available historical and MID documents (excluding "NEW" set)
  - Priority 1: Will Records (historical wills, indexes)
  - Priority 2: Historical Deeds (Books < 238)
  - Priority 3: MID portal documents (Books 238-3971)
- Optimize PDFs for storage efficiency
- Implement logical file organization in Google Cloud Storage
- Process existing index spreadsheets to generate download queues
  - Extract document types from InstrumentType field using regex pattern before " -"
  - Implement fuzzy matching for truncated document types
  - Map to standardized document type codes

#### Phase 2: Text Extraction & Indexing
- Extract raw text from all documents using Google Document AI (first step)
- Apply AI processing only for error correction and data structuring (second step)
- Parse and structure extracted data according to legal document models
- Create searchable indexes for property descriptions, parties, dates, and document types

#### Phase 3: Title Plant Implementation
- Build search algorithms for property title chains
- Implement automated title examination workflows
- Create API endpoints for programmatic title searches
- Develop title report generation system

## Technical Stack
- **Language**: Python
- **Web Scraping**: Selenium WebDriver (with retry mechanisms for failures)
- **OCR**: Google Document AI (primary text extraction)
- **AI Services**: Optional post-processing for error correction
- **Storage**: Google Cloud Storage (with local-to-GCS upload pipeline)
- **Data Models**: Python dataclasses with enum-based classification system

## Success Criteria
The completed system should enable programmatic base title determination for any property in Madison County, Mississippi, providing comprehensive historical ownership chains and encumbrance information.

## References
- Deep Research - High Accuracy, Low Cost Land Record Data Extraction
- Relational Database Best Practices
- Title Plant Design
- Title Search Process in Mississippi
- Deep Research - Claude Code - Best Practices

## Prompt Templates & Workflows

### Enhanced Reasoning
- Use "think hard" or "ultrathink" keywords when tackling complex data extraction challenges
- Request structured planning before implementation for multi-step workflows

### Visual Validation
- When reviewing extracted data, request side-by-side comparisons with source PDFs
- Use screenshot tools to verify UI components match design specifications

### Code Review Process
1. Generate implementation plan with detailed steps
2. Review and approve approach
3. Implement with test coverage
4. Validate output with independent verification

## MCP Integration Opportunities
- Consider MCP servers for specialized document processing tasks
- Potential integration with external title search APIs
- Database query optimization through dedicated MCP servers