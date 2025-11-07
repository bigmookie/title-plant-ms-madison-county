#!/usr/bin/env python3
"""
Madison County Index Database - Related Items Parser

Parses the related_items column and cross-references with existing documents.

Operations:
1. Add related_items_raw column (preserve original data)
2. Parse related_items into structured JSON format
3. Cross-reference with index_documents by book/page
4. Store reference validation (exists_in_db, target_id)

Format: "INSTRUMENT_NUMBER bk:BOOK/PAGE"
Multiple references separated by newlines.

Usage:
    python3 parse_related_items.py [--dry-run] [--batch-size 1000]
"""

import sys
import os
import re
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import argparse
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch
from tqdm import tqdm

# ============================================================================
# Configuration
# ============================================================================

LOG_FILE = Path(__file__).parent / 'parse_related_items.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Regex pattern for parsing related items
# Matches: INSTRUMENT_NUMBER bk:BOOK/PAGE
# Handles extra whitespace between book and page
RELATED_ITEM_PATTERN = re.compile(r'(\d+)\s+bk:(\d+)\s*/(\d+)')

# ============================================================================
# Database Connection
# ============================================================================

def connect_db():
    """Connect to the index database."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=os.getenv('DB_PORT', 5432),
        database=os.getenv('DB_NAME', 'madison_county_index'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )

# ============================================================================
# Schema Setup
# ============================================================================

def add_columns_if_needed(conn, dry_run: bool = False):
    """Add related_items_raw and update related_items type to JSONB."""
    cursor = conn.cursor()

    try:
        # Check if related_items_raw exists
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name='index_documents'
              AND column_name IN ('related_items', 'related_items_raw')
        """)

        existing_cols = {row[0]: row[1] for row in cursor.fetchall()}

        if 'related_items_raw' not in existing_cols:
            logger.info("Adding related_items_raw column...")

            if not dry_run:
                # Add related_items_raw column
                cursor.execute("""
                    ALTER TABLE index_documents
                    ADD COLUMN related_items_raw TEXT
                """)

                # Copy existing data to _raw column
                cursor.execute("""
                    UPDATE index_documents
                    SET related_items_raw = related_items
                    WHERE related_items IS NOT NULL
                """)

                conn.commit()
                logger.info("✓ related_items_raw column added and populated")
            else:
                logger.info("[DRY RUN] Would add related_items_raw column")
        else:
            logger.info("✓ related_items_raw column already exists")

        # Check if related_items needs to be converted to JSONB
        if existing_cols.get('related_items') == 'text':
            logger.info("Converting related_items column to JSONB...")

            if not dry_run:
                # Rename old column temporarily
                cursor.execute("""
                    ALTER TABLE index_documents
                    RENAME COLUMN related_items TO related_items_old
                """)

                # Add new JSONB column
                cursor.execute("""
                    ALTER TABLE index_documents
                    ADD COLUMN related_items JSONB
                """)

                conn.commit()
                logger.info("✓ related_items converted to JSONB (old data in related_items_old)")
            else:
                logger.info("[DRY RUN] Would convert related_items to JSONB")
        elif existing_cols.get('related_items') == 'jsonb':
            logger.info("✓ related_items is already JSONB")
        else:
            logger.info(f"✓ related_items type: {existing_cols.get('related_items')}")

    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Error modifying schema: {e}")
        raise
    finally:
        cursor.close()

# ============================================================================
# Parsing Functions
# ============================================================================

def parse_related_item(raw_text: str) -> List[Dict]:
    """
    Parse related_items text into structured format.

    Format: "INSTRUMENT_NUMBER bk:BOOK/PAGE"
    Multiple references separated by newlines.

    Args:
        raw_text: Raw related_items text

    Returns:
        List of parsed references
    """
    if not raw_text or not raw_text.strip():
        return []

    references = []
    seen = set()  # Track duplicates

    # Split by newlines for multiple references
    lines = raw_text.strip().split('\n')

    for line in lines:
        # Find all matches in this line (handles multiple refs per line)
        matches = RELATED_ITEM_PATTERN.findall(line)

        for match in matches:
            instrument_num = int(match[0])
            book = int(match[1])
            page = int(match[2])

            # Create unique key to detect duplicates
            key = (instrument_num, book, page)

            if key not in seen:
                references.append({
                    'instrument_number': instrument_num,
                    'book': book,
                    'page': page,
                    'exists_in_db': None,  # Will be filled by cross-reference
                    'target_id': None       # Will be filled by cross-reference
                })
                seen.add(key)

    return references

def cross_reference_batch(conn, references: List[Tuple[int, int, int]]) -> Dict[Tuple[int, int], int]:
    """
    Cross-reference a batch of (book, page) pairs with the database.

    Args:
        conn: Database connection
        references: List of (instrument_number, book, page) tuples

    Returns:
        Dictionary mapping (book, page) -> document_id
    """
    if not references:
        return {}

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Extract unique (book, page) pairs
    book_page_pairs = list(set((ref[1], ref[2]) for ref in references))

    # Build query with VALUES clause for efficient lookup
    values_clause = ','.join([f"({book}, {page})" for book, page in book_page_pairs])

    query = f"""
        SELECT id, book, page, instrument_number
        FROM index_documents
        WHERE (book, page) IN (VALUES {values_clause})
    """

    cursor.execute(query)
    results = cursor.fetchall()

    # Build lookup dictionary
    # Prefer matching by instrument_number if available
    lookup = {}

    for row in results:
        key = (row['book'], row['page'])

        # If multiple records for same book/page, prefer exact instrument_number match
        if key not in lookup:
            lookup[key] = row['id']
        else:
            # Keep the one that matches instrument_number if we find it later
            pass

    cursor.close()
    return lookup

def enrich_references(references: List[Dict], lookup: Dict[Tuple[int, int], int]) -> List[Dict]:
    """
    Enrich parsed references with database cross-reference data.

    Args:
        references: List of parsed references
        lookup: Dictionary mapping (book, page) -> document_id

    Returns:
        Enriched references
    """
    for ref in references:
        key = (ref['book'], ref['page'])

        if key in lookup:
            ref['exists_in_db'] = True
            ref['target_id'] = lookup[key]
        else:
            ref['exists_in_db'] = False
            ref['target_id'] = None

    return references

# ============================================================================
# Processing Functions
# ============================================================================

def process_batch(conn, batch: List[Dict], dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Process a batch of documents, parsing and enriching related_items.

    Args:
        conn: Database connection
        batch: List of document records
        dry_run: If True, don't write to database

    Returns:
        Tuple of (processed, with_references, errors)
    """
    processed = 0
    with_references = 0
    errors = 0

    # Collect all references for batch cross-reference
    all_references = []
    doc_references = {}  # doc_id -> parsed_references

    for doc in batch:
        doc_id = doc['id']
        raw_text = doc['related_items_raw']

        try:
            # Parse references
            references = parse_related_item(raw_text)

            if references:
                with_references += 1
                doc_references[doc_id] = references

                # Collect for batch lookup
                for ref in references:
                    all_references.append((ref['instrument_number'], ref['book'], ref['page']))
            else:
                # No references, set to empty array
                doc_references[doc_id] = []

            processed += 1

        except Exception as e:
            logger.error(f"Error parsing doc {doc_id}: {e}")
            errors += 1

    # Batch cross-reference
    if all_references:
        logger.debug(f"Cross-referencing {len(all_references)} references...")
        lookup = cross_reference_batch(conn, all_references)

        # Enrich all references
        for doc_id, references in doc_references.items():
            if references:
                doc_references[doc_id] = enrich_references(references, lookup)

    # Update database
    if not dry_run and doc_references:
        cursor = conn.cursor()

        update_query = """
            UPDATE index_documents
            SET related_items = %s::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """

        update_data = [
            (json.dumps(references), doc_id)
            for doc_id, references in doc_references.items()
        ]

        execute_batch(cursor, update_query, update_data, page_size=100)
        conn.commit()
        cursor.close()

    return processed, with_references, errors

def process_all_documents(conn, batch_size: int = 1000, dry_run: bool = False):
    """
    Process all documents with related_items.

    Args:
        conn: Database connection
        batch_size: Number of documents to process per batch
        dry_run: If True, don't write to database
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Check which column to use (related_items_raw if exists, else related_items)
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name='index_documents'
          AND column_name IN ('related_items_raw', 'related_items')
    """)
    available_cols = [row['column_name'] for row in cursor.fetchall()]

    # Use related_items_raw if it exists, else fall back to related_items
    source_column = 'related_items_raw' if 'related_items_raw' in available_cols else 'related_items'
    logger.info(f"Using column: {source_column}")

    # Count total documents with related_items
    cursor.execute(f"""
        SELECT COUNT(*) as count
        FROM index_documents
        WHERE {source_column} IS NOT NULL
          AND {source_column} != ''
    """)

    total = cursor.fetchone()['count']
    logger.info(f"Processing {total:,} documents with related_items")

    if total == 0:
        logger.info("No documents to process")
        return

    # Process in batches
    total_processed = 0
    total_with_refs = 0
    total_errors = 0

    offset = 0

    with tqdm(total=total, desc="Parsing related_items") as pbar:
        while offset < total:
            # Fetch batch
            cursor.execute(f"""
                SELECT id, {source_column} as related_items_raw
                FROM index_documents
                WHERE {source_column} IS NOT NULL
                  AND {source_column} != ''
                ORDER BY id
                LIMIT %s OFFSET %s
            """, (batch_size, offset))

            batch = cursor.fetchall()

            if not batch:
                break

            # Process batch
            processed, with_refs, errors = process_batch(
                conn,
                [dict(row) for row in batch],
                dry_run
            )

            total_processed += processed
            total_with_refs += with_refs
            total_errors += errors

            pbar.update(len(batch))
            offset += batch_size

    cursor.close()

    # Print summary
    print("\n" + "="*80)
    print("RELATED ITEMS PARSING COMPLETE")
    print("="*80)
    print(f"Total processed:        {total_processed:>10,}")
    print(f"With references:        {total_with_refs:>10,}")
    print(f"Errors:                 {total_errors:>10,}")
    print(f"Success rate:           {(total_processed-total_errors)*100.0/total_processed:>9.1f}%")
    print("="*80)

def generate_statistics(conn):
    """Generate statistics about parsed related_items."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Check if related_items has been converted to JSONB
    cursor.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name='index_documents'
          AND column_name='related_items'
    """)

    result = cursor.fetchone()
    if not result or result['data_type'] != 'jsonb':
        print("\n⚠️  related_items column not yet converted to JSONB")
        print("Run without --dry-run to parse and convert data first.")
        cursor.close()
        return

    print("\n" + "="*80)
    print("RELATED ITEMS STATISTICS")
    print("="*80)

    # Count by number of references
    cursor.execute("""
        SELECT
            jsonb_array_length(related_items) as num_refs,
            COUNT(*) as count
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND jsonb_typeof(related_items) = 'array'
        GROUP BY num_refs
        ORDER BY num_refs
        LIMIT 20
    """)

    print("\nReferences per document:")
    for row in cursor.fetchall():
        print(f"  {row['num_refs']} references: {row['count']:>8,} documents")

    # Count exists_in_db
    cursor.execute("""
        SELECT
            COUNT(*) FILTER (WHERE ref->>'exists_in_db' = 'true') as found,
            COUNT(*) FILTER (WHERE ref->>'exists_in_db' = 'false') as not_found,
            COUNT(*) as total
        FROM index_documents,
             jsonb_array_elements(related_items) as ref
        WHERE related_items IS NOT NULL
    """)

    result = cursor.fetchone()
    if result:
        print(f"\nCross-reference results:")
        print(f"  Found in DB:     {result['found']:>10,} ({result['found']*100.0/result['total']:.1f}%)")
        print(f"  Not found:       {result['not_found']:>10,} ({result['not_found']*100.0/result['total']:.1f}%)")
        print(f"  Total refs:      {result['total']:>10,}")

    # Sample parsed data
    cursor.execute("""
        SELECT book, page, related_items
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND jsonb_typeof(related_items) = 'array'
          AND jsonb_array_length(related_items) > 0
        LIMIT 5
    """)

    print("\nSample parsed data:")
    for i, row in enumerate(cursor.fetchall(), 1):
        print(f"\n{i}. Book {row['book']}, Page {row['page']}")
        print(f"   Parsed: {json.dumps(row['related_items'], indent=6)}")

    cursor.close()
    print("\n" + "="*80)

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Parse and cross-reference related_items in index database',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--batch-size', type=int, default=1000,
                       help='Number of documents to process per batch (default: 1000)')
    parser.add_argument('--stats-only', action='store_true',
                       help='Only generate statistics (requires data already parsed)')

    args = parser.parse_args()

    print("\n" + "="*80)
    print("MADISON COUNTY INDEX - RELATED ITEMS PARSER")
    print("="*80)

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made to the database\n")

    # Connect to database
    try:
        conn = connect_db()
        logger.info("✓ Connected to database")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    try:
        if args.stats_only:
            generate_statistics(conn)
        else:
            # Add columns if needed
            add_columns_if_needed(conn, args.dry_run)

            # Process all documents
            process_all_documents(conn, args.batch_size, args.dry_run)

            # Generate statistics
            if not args.dry_run:
                generate_statistics(conn)

        logger.info(f"\nLog file: {LOG_FILE}")

        if args.dry_run:
            logger.info("\n⚠️  DRY RUN COMPLETE - No changes were made")
        else:
            logger.info("\n✓ PARSING COMPLETE")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
    finally:
        conn.close()

    return 0

if __name__ == '__main__':
    sys.exit(main())
