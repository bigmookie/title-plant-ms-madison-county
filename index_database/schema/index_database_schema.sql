-- Madison County Title Plant - Index Database Schema
-- Purpose: Store pre-existing index data for validation and download queue management
-- Separate from production database that will be populated from OCR/AI processing

-- Create database (run separately via gcloud)
-- CREATE DATABASE madison_county_index;

-- ============================================================================
-- Main Index Documents Table
-- ============================================================================
-- This table combines data from:
-- 1. DuProcess Indexes (1985-2025, ~1000+ Excel files)
-- 2. Historic Deeds checklist (book/page only)
-- ============================================================================

CREATE TABLE IF NOT EXISTS index_documents (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- Source tracking
    source VARCHAR(50) NOT NULL CHECK (source IN ('DuProcess', 'Historical')),
    source_file VARCHAR(500),  -- Original Excel filename
    import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- DuProcess core fields
    gin BIGINT,  -- DuProcess unique identifier (null for Historical)
    instrument_number BIGINT,
    book_volume VARCHAR(100),  -- Book/Volume field from DuProcess
    book INTEGER,  -- Parsed book number (required for both sources)
    page INTEGER,  -- Page number (required for both sources)

    -- Document identification
    instrument_type_raw TEXT,  -- Raw InstrumentType string from DuProcess
    instrument_type_parsed VARCHAR(100),  -- Parsed type (before " -")
    document_type VARCHAR(100),  -- Mapped to DocumentType enum from data-models-spec.md

    -- Recording information
    file_date TIMESTAMP,  -- FileDate from DuProcess
    num_pages INTEGER,

    -- Party information
    party_type VARCHAR(50),
    party_seq INTEGER,
    searched_name TEXT,
    cross_party_name TEXT,
    grantor_party TEXT,
    grantee_party TEXT,

    -- Legal description fields
    description TEXT,
    location VARCHAR(200),
    direction VARCHAR(50),
    legals TEXT,
    sub_div VARCHAR(200),
    block VARCHAR(50),
    lot VARCHAR(100),
    sec INTEGER,  -- Section
    town VARCHAR(50),  -- Township
    rng VARCHAR(50),  -- Range
    square VARCHAR(50),
    remarks TEXT,

    -- Quarter section breakdown (for Section-Township-Range legal descriptions)
    ne_of_ne BOOLEAN,
    nw_of_ne BOOLEAN,
    sw_of_ne BOOLEAN,
    se_of_ne BOOLEAN,
    ne_of_nw BOOLEAN,
    nw_of_nw BOOLEAN,
    sw_of_nw BOOLEAN,
    se_of_nw BOOLEAN,
    ne_of_sw BOOLEAN,
    nw_of_sw BOOLEAN,
    sw_of_sw BOOLEAN,
    se_of_sw BOOLEAN,
    ne_of_se BOOLEAN,
    nw_of_se BOOLEAN,
    sw_of_se BOOLEAN,
    se_of_se BOOLEAN,

    -- Modern property identifiers
    address TEXT,
    street_name VARCHAR(200),
    city VARCHAR(100),
    zip VARCHAR(20),
    parcel_num VARCHAR(100),
    parcel_id VARCHAR(100),
    ppin VARCHAR(100),
    patent_num VARCHAR(100),

    -- Workflow tracking from DuProcess
    workflow_status VARCHAR(100),
    verified_status VARCHAR(100),
    doc_status VARCHAR(100),
    related_items_raw TEXT,      -- Raw text from DuProcess (e.g., "945431 bk:4140/753")
    related_items JSONB,          -- Parsed and cross-referenced JSON array

    -- Download queue management
    download_status VARCHAR(50) DEFAULT 'pending' CHECK (
        download_status IN ('pending', 'in_progress', 'completed', 'failed', 'skipped')
    ),
    download_priority INTEGER DEFAULT 3,  -- Priority: 1 (high), 2 (medium), 3 (low)
    download_attempts INTEGER DEFAULT 0,
    downloaded_at TIMESTAMP,
    download_error TEXT,  -- Store error message if failed

    -- Google Cloud Storage path
    gcs_path TEXT,  -- Path to uploaded document in GCS

    -- Validation fields (actual book/page from downloaded document)
    actual_book INTEGER,           -- Actual book from document response
    actual_page INTEGER,           -- Actual page from document response
    book_page_mismatch BOOLEAN DEFAULT FALSE,  -- Flag if index differs from actual

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT unique_book_page_source UNIQUE (book, page, source),
    CONSTRAINT book_page_positive CHECK (book > 0 AND page > 0)
);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Primary lookup indexes
CREATE INDEX idx_book_page ON index_documents(book, page);
CREATE INDEX idx_gin ON index_documents(gin) WHERE gin IS NOT NULL;
CREATE INDEX idx_instrument_number ON index_documents(instrument_number) WHERE instrument_number IS NOT NULL;

-- Download queue indexes
CREATE INDEX idx_download_status ON index_documents(download_status);
CREATE INDEX idx_download_status_pending ON index_documents(download_status, book, page)
    WHERE download_status = 'pending';
CREATE INDEX idx_download_failed ON index_documents(download_status, download_attempts)
    WHERE download_status = 'failed';

-- Document type classification
CREATE INDEX idx_document_type ON index_documents(document_type) WHERE document_type IS NOT NULL;
CREATE INDEX idx_instrument_type_parsed ON index_documents(instrument_type_parsed) WHERE instrument_type_parsed IS NOT NULL;

-- Date-based queries
CREATE INDEX idx_file_date ON index_documents(file_date) WHERE file_date IS NOT NULL;

-- Party name searches (for validation)
CREATE INDEX idx_grantor ON index_documents USING gin(to_tsvector('english', grantor_party))
    WHERE grantor_party IS NOT NULL;
CREATE INDEX idx_grantee ON index_documents USING gin(to_tsvector('english', grantee_party))
    WHERE grantee_party IS NOT NULL;

-- Legal description searches
CREATE INDEX idx_subdivision ON index_documents(sub_div) WHERE sub_div IS NOT NULL;
CREATE INDEX idx_section_township_range ON index_documents(sec, town, rng)
    WHERE sec IS NOT NULL;
CREATE INDEX idx_parcel_num ON index_documents(parcel_num) WHERE parcel_num IS NOT NULL;

-- Source tracking
CREATE INDEX idx_source ON index_documents(source);
CREATE INDEX idx_source_file ON index_documents(source_file);

-- ============================================================================
-- Trigger for updated_at timestamp
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_index_documents_updated_at
    BEFORE UPDATE ON index_documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Useful Views for Reporting
-- ============================================================================

-- Download queue summary
CREATE VIEW download_queue_summary AS
SELECT
    download_status,
    COUNT(*) as count,
    MIN(book) as min_book,
    MAX(book) as max_book
FROM index_documents
GROUP BY download_status
ORDER BY
    CASE download_status
        WHEN 'pending' THEN 1
        WHEN 'in_progress' THEN 2
        WHEN 'failed' THEN 3
        WHEN 'completed' THEN 4
        WHEN 'skipped' THEN 5
    END;

-- Document type distribution
CREATE VIEW document_type_distribution AS
SELECT
    source,
    instrument_type_parsed,
    document_type,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY source), 2) as percentage
FROM index_documents
WHERE instrument_type_parsed IS NOT NULL
GROUP BY source, instrument_type_parsed, document_type
ORDER BY source, count DESC;

-- Books coverage summary
CREATE VIEW books_coverage AS
SELECT
    book,
    source,
    COUNT(*) as page_count,
    MIN(page) as first_page,
    MAX(page) as last_page,
    COUNT(DISTINCT instrument_type_parsed) as unique_doc_types
FROM index_documents
GROUP BY book, source
ORDER BY book, source;

-- Failed downloads for retry
CREATE VIEW failed_downloads AS
SELECT
    id,
    book,
    page,
    instrument_type_parsed,
    download_attempts,
    download_error,
    downloaded_at
FROM index_documents
WHERE download_status = 'failed'
ORDER BY download_attempts ASC, book ASC, page ASC;

-- ============================================================================
-- Grant permissions (adjust user as needed)
-- ============================================================================

-- Example: GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO your_user;
-- Example: GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO your_user;

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE index_documents IS
'Pre-existing index data from DuProcess and Historic Deeds sources. Used for validation of production database and to feed document download queue.';

COMMENT ON COLUMN index_documents.source IS
'Data source: DuProcess (detailed indexes 1985-2025) or Historical (book/page checklist only)';

COMMENT ON COLUMN index_documents.gin IS
'DuProcess Global Index Number - unique identifier in DuProcess system';

COMMENT ON COLUMN index_documents.instrument_type_raw IS
'Raw InstrumentType string from DuProcess, e.g., "DEED OF TRUST - [DOT 3972]"';

COMMENT ON COLUMN index_documents.instrument_type_parsed IS
'Parsed instrument type (text before " -"), used for document type classification';

COMMENT ON COLUMN index_documents.document_type IS
'Mapped to standardized DocumentType enum using DUPROCESS_TYPE_MAPPING from data-models-spec.md';

COMMENT ON COLUMN index_documents.download_status IS
'Download queue status: pending (not started), in_progress (downloading), completed (done), failed (error), skipped (intentionally not downloaded)';
