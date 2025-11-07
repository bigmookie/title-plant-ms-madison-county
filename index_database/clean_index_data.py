#!/usr/bin/env python3
"""
Madison County Title Plant - Index Data Cleaning Script

This script performs data quality checks and cleaning operations on the
index database before starting document downloads.

Operations:
1. Identify and mark invalid records (NULL book/page, invalid ranges)
2. Deduplicate records (same book/page/source)
3. Exclude NEW portal books (>= 3972) from Phase 1
4. Assign download priorities
5. Validate portal routing
6. Generate statistics and reports

Usage:
    python3 clean_index_data.py [--dry-run] [--report-only]
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import argparse
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor

# ============================================================================
# Configuration
# ============================================================================

LOG_FILE = Path(__file__).parent / 'index_cleaning.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
# Cleaning Operations
# ============================================================================

def add_priority_column_if_needed(conn):
    """Add download_priority column if it doesn't exist."""
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='index_documents'
              AND column_name='download_priority'
        """)

        if not cursor.fetchone():
            logger.info("Adding download_priority column...")
            cursor.execute("""
                ALTER TABLE index_documents
                ADD COLUMN download_priority INTEGER
            """)
            conn.commit()
            logger.info("✓ download_priority column added")
        else:
            logger.info("✓ download_priority column already exists")

    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Error adding priority column: {e}")
        raise
    finally:
        cursor.close()

def get_current_statistics(conn) -> Dict:
    """Get current database statistics before cleaning."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    stats = {}

    # Total records
    cursor.execute("SELECT COUNT(*) as total FROM index_documents")
    stats['total_records'] = cursor.fetchone()['total']

    # By source
    cursor.execute("""
        SELECT source, COUNT(*) as count
        FROM index_documents
        GROUP BY source
    """)
    stats['by_source'] = {row['source']: row['count'] for row in cursor.fetchall()}

    # By download status
    cursor.execute("""
        SELECT download_status, COUNT(*) as count
        FROM index_documents
        GROUP BY download_status
    """)
    stats['by_status'] = {row['download_status']: row['count'] for row in cursor.fetchall()}

    # Book ranges
    cursor.execute("""
        SELECT
            MIN(book) as min_book,
            MAX(book) as max_book,
            COUNT(DISTINCT book) as unique_books
        FROM index_documents
        WHERE book IS NOT NULL
    """)
    book_stats = cursor.fetchone()
    stats['book_range'] = {
        'min': book_stats['min_book'],
        'max': book_stats['max_book'],
        'unique_count': book_stats['unique_books']
    }

    cursor.close()
    return stats

def mark_invalid_records(conn, dry_run: bool = False) -> int:
    """Mark records with invalid book/page data as skipped."""
    cursor = conn.cursor()

    query = """
        UPDATE index_documents
        SET download_status = 'skipped',
            download_error = 'Invalid book/page data',
            updated_at = CURRENT_TIMESTAMP
        WHERE download_status = 'pending'
          AND (book IS NULL OR page IS NULL OR book <= 0 OR page <= 0)
    """

    if dry_run:
        # Count only
        count_query = query.replace("UPDATE index_documents SET", "SELECT COUNT(*) FROM index_documents WHERE").split("WHERE", 1)[0] + " WHERE " + query.split("WHERE", 2)[2]
        cursor.execute(count_query.replace("SET download_status", "WHERE download_status"))
        count = cursor.fetchone()[0]
        logger.info(f"[DRY RUN] Would mark {count} invalid records as skipped")
        return count

    cursor.execute(query)
    count = cursor.rowcount
    conn.commit()
    logger.info(f"✓ Marked {count} invalid records as skipped")

    cursor.close()
    return count

def exclude_new_portal_books(conn, dry_run: bool = False) -> int:
    """Exclude books >= 3972 (NEW portal) from Phase 1."""
    cursor = conn.cursor()

    query = """
        UPDATE index_documents
        SET download_status = 'skipped',
            download_error = 'NEW portal excluded from Phase 1 (book >= 3972)',
            updated_at = CURRENT_TIMESTAMP
        WHERE download_status = 'pending'
          AND book >= 3972
    """

    if dry_run:
        cursor.execute("""
            SELECT COUNT(*) FROM index_documents
            WHERE download_status = 'pending' AND book >= 3972
        """)
        count = cursor.fetchone()[0]
        logger.info(f"[DRY RUN] Would exclude {count} NEW portal records (books >= 3972)")
        return count

    cursor.execute(query)
    count = cursor.rowcount
    conn.commit()
    logger.info(f"✓ Excluded {count} NEW portal records from Phase 1")

    cursor.close()
    return count

def deduplicate_records(conn, dry_run: bool = False) -> int:
    """
    Deduplicate records with same book/page/source.
    Keep the earliest record by file_date, then import_date.
    """
    cursor = conn.cursor()

    # First, find duplicates
    cursor.execute("""
        SELECT book, page, source, COUNT(*) as dup_count
        FROM index_documents
        WHERE download_status = 'pending'
        GROUP BY book, page, source
        HAVING COUNT(*) > 1
    """)

    duplicates = cursor.fetchall()
    logger.info(f"Found {len(duplicates)} sets of duplicate book/page/source combinations")

    if dry_run:
        total_to_skip = sum(dup[3] - 1 for dup in duplicates)  # dup_count - 1 per group
        logger.info(f"[DRY RUN] Would mark {total_to_skip} duplicate records as skipped")
        return total_to_skip

    # Mark duplicates (keep earliest)
    query = """
        WITH ranked_duplicates AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY book, page, source
                       ORDER BY file_date NULLS LAST, import_date
                   ) as rn
            FROM index_documents
            WHERE download_status = 'pending'
        )
        UPDATE index_documents
        SET download_status = 'skipped',
            download_error = 'Duplicate book/page (older record)',
            updated_at = CURRENT_TIMESTAMP
        WHERE id IN (
            SELECT id FROM ranked_duplicates WHERE rn > 1
        )
    """

    cursor.execute(query)
    count = cursor.rowcount
    conn.commit()
    logger.info(f"✓ Marked {count} duplicate records as skipped")

    cursor.close()
    return count

def assign_download_priorities(conn, dry_run: bool = False) -> Dict[int, int]:
    """
    Assign download priorities:
    1 = Critical (Wills, critical document types)
    2 = High (Historical books < 238)
    3 = Medium (MID portal books 238-3971)
    4 = Low (Other)
    """
    cursor = conn.cursor()

    priority_queries = {
        1: """
            UPDATE index_documents
            SET download_priority = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE download_status = 'pending'
              AND (instrument_type_parsed ILIKE '%WILL%'
                   OR instrument_type_parsed ILIKE '%TESTAMENT%'
                   OR document_type = 'LAST_WILL_AND_TESTAMENT')
        """,
        2: """
            UPDATE index_documents
            SET download_priority = 2,
                updated_at = CURRENT_TIMESTAMP
            WHERE download_status = 'pending'
              AND download_priority IS NULL
              AND book < 238
        """,
        3: """
            UPDATE index_documents
            SET download_priority = 3,
                updated_at = CURRENT_TIMESTAMP
            WHERE download_status = 'pending'
              AND download_priority IS NULL
              AND book >= 238 AND book < 3972
        """,
        4: """
            UPDATE index_documents
            SET download_priority = 4,
                updated_at = CURRENT_TIMESTAMP
            WHERE download_status = 'pending'
              AND download_priority IS NULL
        """
    }

    counts = {}

    for priority, query in priority_queries.items():
        if dry_run:
            count_query = query.replace("UPDATE index_documents SET download_priority =", "SELECT COUNT(*) FROM index_documents WHERE download_status = 'pending' AND (").replace("WHERE download_status", "AND (").replace("updated_at = CURRENT_TIMESTAMP", "1=1)")
            cursor.execute(query.replace("UPDATE index_documents SET", "SELECT COUNT(*) FROM index_documents WHERE").split("WHERE")[1])
            # Simplified for dry run
            counts[priority] = 0
            logger.info(f"[DRY RUN] Would assign priority {priority} to records")
        else:
            cursor.execute(query)
            counts[priority] = cursor.rowcount
            logger.info(f"✓ Assigned priority {priority} to {counts[priority]} records")

    if not dry_run:
        conn.commit()

    cursor.close()
    return counts

def validate_portal_routing(conn) -> Dict:
    """Validate and report portal routing distribution."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
            CASE
                WHEN book < 238 THEN 'Historical'
                WHEN book >= 238 AND book < 3972 THEN 'MID'
                WHEN book >= 3972 THEN 'NEW (Excluded)'
                ELSE 'Unknown'
            END as portal,
            download_priority,
            COUNT(*) as count,
            COUNT(DISTINCT book) as unique_books,
            MIN(book) as min_book,
            MAX(book) as max_book
        FROM index_documents
        WHERE download_status = 'pending'
        GROUP BY portal, download_priority
        ORDER BY portal, download_priority
    """)

    results = cursor.fetchall()

    logger.info("\n" + "="*80)
    logger.info("PORTAL ROUTING VALIDATION")
    logger.info("="*80)

    for row in results:
        logger.info(
            f"Portal: {row['portal']:15} | "
            f"Priority: {row['download_priority']} | "
            f"Documents: {row['count']:>8,} | "
            f"Books: {row['unique_books']:>5} | "
            f"Range: {row['min_book']}-{row['max_book']}"
        )

    cursor.close()
    return [dict(row) for row in results]

def generate_stage_recommendations(conn) -> Dict:
    """Generate recommendations for staged downloads."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Stage 0: Test (10 from each portal)
    cursor.execute("""
        SELECT 'Stage 0 - Test' as stage,
               'Historical' as portal,
               10 as recommended_count,
               (SELECT COUNT(*) FROM index_documents
                WHERE download_status = 'pending' AND book < 238) as available
        UNION ALL
        SELECT 'Stage 0 - Test' as stage,
               'MID' as portal,
               10 as recommended_count,
               (SELECT COUNT(*) FROM index_documents
                WHERE download_status = 'pending' AND book >= 238 AND book < 3972) as available
    """)

    stage_0 = cursor.fetchall()

    # Stage 1: Small scale
    cursor.execute("""
        SELECT
            download_priority,
            CASE
                WHEN book < 238 THEN 'Historical'
                ELSE 'MID'
            END as portal,
            COUNT(*) as available,
            CASE
                WHEN download_priority <= 2 THEN LEAST(COUNT(*), 1000)
                ELSE 0
            END as recommended
        FROM index_documents
        WHERE download_status = 'pending'
          AND download_priority <= 2
        GROUP BY download_priority, portal
        ORDER BY download_priority, portal
    """)

    stage_1 = cursor.fetchall()

    logger.info("\n" + "="*80)
    logger.info("STAGED DOWNLOAD RECOMMENDATIONS")
    logger.info("="*80)

    logger.info("\nStage 0 - Test Run:")
    for row in stage_0:
        logger.info(f"  {row['portal']:15} - Recommended: {row['recommended_count']:>5}, Available: {row['available']:>8,}")

    logger.info("\nStage 1 - Small Scale (Priority 1 & 2):")
    total_stage_1 = 0
    for row in stage_1:
        logger.info(f"  Priority {row['download_priority']} ({row['portal']:15}) - Recommended: {row['recommended']:>5,}, Available: {row['available']:>8,}")
        total_stage_1 += row['recommended']
    logger.info(f"  Total Stage 1: {total_stage_1:,} documents")

    cursor.close()

    return {
        'stage_0': [dict(row) for row in stage_0],
        'stage_1': [dict(row) for row in stage_1]
    }

def print_summary_report(before_stats: Dict, after_stats: Dict, cleaning_results: Dict):
    """Print comprehensive summary report."""
    print("\n" + "="*80)
    print("INDEX DATABASE CLEANING SUMMARY")
    print("="*80)

    print("\nBEFORE CLEANING:")
    print(f"  Total records:         {before_stats['total_records']:>10,}")
    print(f"  Pending downloads:     {before_stats['by_status'].get('pending', 0):>10,}")
    print(f"  Book range:            {before_stats['book_range']['min']:>10,} - {before_stats['book_range']['max']:,}")
    print(f"  Unique books:          {before_stats['book_range']['unique_count']:>10,}")

    print("\nCLEANING OPERATIONS:")
    print(f"  Invalid records marked:       {cleaning_results.get('invalid', 0):>10,}")
    print(f"  NEW portal excluded:          {cleaning_results.get('excluded', 0):>10,}")
    print(f"  Duplicates removed:           {cleaning_results.get('duplicates', 0):>10,}")
    print(f"  Priorities assigned:")
    for priority, count in cleaning_results.get('priorities', {}).items():
        priority_name = {1: 'Critical', 2: 'High', 3: 'Medium', 4: 'Low'}.get(priority, 'Unknown')
        print(f"    Priority {priority} ({priority_name:8}):  {count:>10,}")

    print("\nAFTER CLEANING:")
    print(f"  Total records:         {after_stats['total_records']:>10,}")
    print(f"  Pending downloads:     {after_stats['by_status'].get('pending', 0):>10,}")
    print(f"  Skipped records:       {after_stats['by_status'].get('skipped', 0):>10,}")
    print(f"  Ready for download:    {after_stats['by_status'].get('pending', 0):>10,}")

    print("\nSTATUS BREAKDOWN:")
    for status, count in after_stats['by_status'].items():
        print(f"  {status:20} {count:>10,}")

    print("\n" + "="*80)

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Clean and prepare index database for document downloads',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--report-only', action='store_true',
                       help='Generate statistics report only, no cleaning')

    args = parser.parse_args()

    print("\n" + "="*80)
    print("MADISON COUNTY INDEX DATABASE - DATA CLEANING")
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

    # Get initial statistics
    logger.info("\nGathering initial statistics...")
    before_stats = get_current_statistics(conn)

    if args.report_only:
        print_summary_report(before_stats, before_stats, {})
        validate_portal_routing(conn)
        generate_stage_recommendations(conn)
        conn.close()
        return 0

    # Add priority column if needed
    add_priority_column_if_needed(conn)

    # Perform cleaning operations
    cleaning_results = {}

    logger.info("\n" + "="*80)
    logger.info("CLEANING OPERATIONS")
    logger.info("="*80 + "\n")

    logger.info("1. Marking invalid records...")
    cleaning_results['invalid'] = mark_invalid_records(conn, args.dry_run)

    logger.info("\n2. Excluding NEW portal books (>= 3972)...")
    cleaning_results['excluded'] = exclude_new_portal_books(conn, args.dry_run)

    logger.info("\n3. Deduplicating records...")
    cleaning_results['duplicates'] = deduplicate_records(conn, args.dry_run)

    logger.info("\n4. Assigning download priorities...")
    cleaning_results['priorities'] = assign_download_priorities(conn, args.dry_run)

    # Get final statistics
    logger.info("\nGathering final statistics...")
    after_stats = get_current_statistics(conn)

    # Print summary
    print_summary_report(before_stats, after_stats, cleaning_results)

    # Validation and recommendations
    validate_portal_routing(conn)
    generate_stage_recommendations(conn)

    logger.info(f"\nLog file: {LOG_FILE}")

    if args.dry_run:
        logger.info("\n⚠️  DRY RUN COMPLETE - No changes were made")
    else:
        logger.info("\n✓ CLEANING COMPLETE - Database ready for staged downloads")

    conn.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
