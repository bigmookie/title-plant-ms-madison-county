-- Migration script for existing databases with old related_items schema
-- This converts the old TEXT column to the new dual-column structure

-- Step 1: Check if migration is needed
DO $$
BEGIN
    -- Check if related_items_raw already exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents'
        AND column_name='related_items_raw'
    ) THEN
        RAISE NOTICE 'Starting migration: Adding related_items_raw column...';

        -- Add new column
        ALTER TABLE index_documents ADD COLUMN related_items_raw TEXT;

        -- Copy existing data from related_items to related_items_raw
        UPDATE index_documents
        SET related_items_raw = related_items
        WHERE related_items IS NOT NULL;

        RAISE NOTICE 'Migration Step 1 complete: related_items_raw populated with % rows',
            (SELECT COUNT(*) FROM index_documents WHERE related_items_raw IS NOT NULL);
    ELSE
        RAISE NOTICE 'Migration Step 1 skipped: related_items_raw already exists';
    END IF;
END $$;

-- Step 2: Convert related_items from TEXT to JSONB
DO $$
BEGIN
    -- Check current type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents'
        AND column_name='related_items'
        AND data_type='text'
    ) THEN
        RAISE NOTICE 'Starting migration: Converting related_items to JSONB...';

        -- Rename old column
        ALTER TABLE index_documents
        RENAME COLUMN related_items TO related_items_old;

        -- Add new JSONB column
        ALTER TABLE index_documents
        ADD COLUMN related_items JSONB;

        RAISE NOTICE 'Migration Step 2 complete: related_items converted to JSONB';
        RAISE NOTICE 'Old data preserved in related_items_old (can be dropped after verification)';
        RAISE NOTICE 'Run parse_related_items.py to populate the new related_items column';
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='index_documents'
        AND column_name='related_items'
        AND data_type='jsonb'
    ) THEN
        RAISE NOTICE 'Migration Step 2 skipped: related_items already JSONB';
    ELSE
        RAISE NOTICE 'Migration Step 2 skipped: related_items column configuration unknown';
    END IF;
END $$;

-- Step 3: Verify migration
SELECT
    'Migration verification' as status,
    COUNT(*) as total_records,
    COUNT(related_items_raw) as with_related_items_raw,
    COUNT(related_items) as with_related_items_parsed,
    (SELECT data_type FROM information_schema.columns
     WHERE table_name='index_documents' AND column_name='related_items') as related_items_type
FROM index_documents;

-- Instructions for cleanup after verification
SELECT '
Next steps:
1. Run parse_related_items.py to populate the related_items (JSONB) column
2. After verification, optionally drop the old column:
   ALTER TABLE index_documents DROP COLUMN related_items_old;
' as instructions;
