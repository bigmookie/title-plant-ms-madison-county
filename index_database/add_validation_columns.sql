-- Add columns to track book/page validation from downloads
-- Run this after migrating related_items schema

-- Add columns if they don't exist
DO $$
BEGIN
    -- Actual book/page from downloaded document
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents' AND column_name='actual_book'
    ) THEN
        ALTER TABLE index_documents ADD COLUMN actual_book INTEGER;
        RAISE NOTICE 'Added actual_book column';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents' AND column_name='actual_page'
    ) THEN
        ALTER TABLE index_documents ADD COLUMN actual_page INTEGER;
        RAISE NOTICE 'Added actual_page column';
    END IF;

    -- Flag for book/page mismatch
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents' AND column_name='book_page_mismatch'
    ) THEN
        ALTER TABLE index_documents ADD COLUMN book_page_mismatch BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added book_page_mismatch column';
    END IF;
END $$;

-- Verify
SELECT
    'Validation columns added' as status,
    COUNT(*) as total_records,
    COUNT(actual_book) as with_actual_book,
    COUNT(actual_page) as with_actual_page,
    COUNT(*) FILTER (WHERE book_page_mismatch = TRUE) as with_mismatches
FROM index_documents;
