-- Add download_priority column to index_documents table
-- Run this as postgres user:
-- psql -h 127.0.0.1 -p 5432 -U postgres -d madison_county_index -f add_download_priority.sql

-- Add column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents' AND column_name='download_priority'
    ) THEN
        ALTER TABLE index_documents ADD COLUMN download_priority INTEGER DEFAULT 3;
        RAISE NOTICE 'Added download_priority column';
    ELSE
        RAISE NOTICE 'download_priority column already exists';
    END IF;
END $$;

-- Create index for performance (if not exists)
CREATE INDEX IF NOT EXISTS idx_download_priority
    ON index_documents(download_priority, download_status);

-- Set initial priorities based on document type
-- Priority 1: High priority documents (deeds, deeds of trust)
-- Priority 2: Medium priority documents (mortgages, liens)
-- Priority 3: Low priority documents (everything else)

-- Update priorities for high-priority document types
UPDATE index_documents
SET download_priority = 1
WHERE download_priority = 3  -- Only update defaults
  AND instrument_type_parsed IN (
    'DEED', 'WARRANTY DEED', 'QUIT CLAIM DEED', 'QUITCLAIM DEED',
    'DEED OF TRUST', 'TRUSTEE DEED', 'SPECIAL WARRANTY DEED'
  );

-- Update priorities for medium-priority document types
UPDATE index_documents
SET download_priority = 2
WHERE download_priority = 3  -- Only update defaults
  AND instrument_type_parsed IN (
    'MORTGAGE', 'DEED OF RELEASE', 'RELEASE', 'ASSIGNMENT',
    'LIEN', 'MECHANICS LIEN', 'JUDGMENT', 'UCC FINANCING STATEMENT'
  );

-- Verify
SELECT
    'Download priority column added' as status,
    COUNT(*) as total_records,
    COUNT(*) FILTER (WHERE download_priority = 1) as priority_1_high,
    COUNT(*) FILTER (WHERE download_priority = 2) as priority_2_medium,
    COUNT(*) FILTER (WHERE download_priority = 3) as priority_3_low
FROM index_documents;
