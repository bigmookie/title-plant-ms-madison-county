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
3. **Iterative Refinement**: Review and refine code through multiple passes
4. **Documentation**: Update technical specs and API documentation as code evolves

## Key Components

### Data Sources
1. **Historical Deeds & Deeds of Trust** - Available through three portals:
   - Historical Books portal (pre-1985)
   - MID portal (Books 237-3971)
   - DuProcess/NEW portal (Books 3972+, excluded from Phase 1)

2. **Will Records**:
   - Historical wills from drupal-search-historical-books
   - Will indexes (1892-1992 and 1992-2009)

3. **Chancery Court Records**:
   - Chancery causes (1871-1982)
   - Chancery cases (1982-1992)
   - Case file inquiries (1992-2009)

### Existing Infrastructure
- **Document Puller**: `madison_county_doc_puller/doc_puller.py` - Selenium-based web scraper for automated PDF downloads
- **Document Reader**: `doc_reader/` - Google Document AI integration for OCR text extraction
- **Data Models**: `records_models.py` - Structured data models for legal documents with support for surface/mineral/timber interests
- **Index Files**: `madison_docs/` - Extensive collection of spreadsheet indexes containing book/page references

### Project Phases

#### Phase 1: Data Collection & Storage
- Download all available historical documents (excluding "NEW" set)
- Optimize PDFs for storage efficiency
- Implement logical file organization in Google Cloud Storage
- Process existing index spreadsheets to generate download queues

#### Phase 2: Text Extraction & Indexing
- Extract text from all documents using Google Document AI
- Parse and structure extracted data according to legal document models
- Create searchable indexes for property descriptions, parties, dates, and document types

#### Phase 3: Title Plant Implementation
- Build search algorithms for property title chains
- Implement automated title examination workflows
- Create API endpoints for programmatic title searches
- Develop title report generation system

## Technical Stack
- **Language**: Python
- **Web Scraping**: Selenium WebDriver
- **OCR**: Google Document AI
- **Storage**: Google Cloud Storage
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