#!/usr/bin/env python3
"""
Madison County Document Download - Validation & Monitoring Utilities

Provides validation and monitoring tools for download operations:
- Validate downloaded documents (file exists, PDF valid, size reasonable)
- Generate progress reports
- Monitor download health
- Identify issues and gaps

Usage:
    # Validate recent downloads
    python3 download_validator.py --validate --last-hours 24

    # Generate progress report
    python3 download_validator.py --report --stage stage-2-medium

    # Monitor download health
    python3 download_validator.py --monitor
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

# ============================================================================
# Configuration
# ============================================================================

LOG_FILE = Path(__file__).parent / 'validation.log'

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
# Validation Functions
# ============================================================================

def validate_pdf_file(file_path: str) -> bool:
    """
    Basic PDF validation.

    Args:
        file_path: Path to PDF file

    Returns:
        True if file appears to be a valid PDF
    """
    try:
        path = Path(file_path)

        if not path.exists():
            return False

        # Check file size (should be between 1KB and 50MB for typical documents)
        size = path.stat().st_size
        if size < 1000 or size > 50_000_000:
            logger.warning(f"Unusual file size: {size:,} bytes for {file_path}")
            return False

        # Check PDF header
        with open(path, 'rb') as f:
            header = f.read(5)
            if not header.startswith(b'%PDF-'):
                logger.warning(f"Invalid PDF header for {file_path}")
                return False

        return True

    except Exception as e:
        logger.error(f"Error validating {file_path}: {e}")
        return False

def validate_download_batch(conn, doc_ids: List[int]) -> Dict:
    """
    Validate a batch of downloaded documents.

    Args:
        conn: Database connection
        doc_ids: List of document IDs to validate

    Returns:
        Validation results dictionary
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    results = {
        'total_checked': len(doc_ids),
        'valid': 0,
        'invalid': 0,
        'issues': []
    }

    for doc_id in doc_ids:
        cursor.execute("""
            SELECT id, book, page, gcs_path, download_status
            FROM index_documents
            WHERE id = %s
        """, (doc_id,))

        doc = cursor.fetchone()

        if not doc:
            results['issues'].append({
                'doc_id': doc_id,
                'issue': 'Document not found in database'
            })
            results['invalid'] += 1
            continue

        # Check status
        if doc['download_status'] != 'completed':
            results['issues'].append({
                'doc_id': doc_id,
                'book': doc['book'],
                'page': doc['page'],
                'issue': f"Status is '{doc['download_status']}', expected 'completed'"
            })
            results['invalid'] += 1
            continue

        # Check GCS path exists
        if not doc['gcs_path']:
            results['issues'].append({
                'doc_id': doc_id,
                'book': doc['book'],
                'page': doc['page'],
                'issue': 'Missing GCS path'
            })
            results['invalid'] += 1
            continue

        results['valid'] += 1

    cursor.close()
    return results

# ============================================================================
# Monitoring Functions
# ============================================================================

def get_download_progress(conn) -> Dict:
    """Get overall download progress statistics."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Overall status counts
    cursor.execute("""
        SELECT
            download_status,
            COUNT(*) as count,
            COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as percentage
        FROM index_documents
        GROUP BY download_status
        ORDER BY count DESC
    """)
    status_breakdown = [dict(row) for row in cursor.fetchall()]

    # By priority
    cursor.execute("""
        SELECT
            download_priority,
            download_status,
            COUNT(*) as count
        FROM index_documents
        WHERE download_priority IS NOT NULL
        GROUP BY download_priority, download_status
        ORDER BY download_priority, download_status
    """)
    priority_breakdown = [dict(row) for row in cursor.fetchall()]

    # Recent activity (last 24 hours)
    cursor.execute("""
        SELECT
            DATE_TRUNC('hour', downloaded_at) as hour,
            COUNT(*) as count
        FROM index_documents
        WHERE download_status = 'completed'
          AND downloaded_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
        GROUP BY hour
        ORDER BY hour DESC
    """)
    hourly_activity = [dict(row) for row in cursor.fetchall()]

    # Error summary
    cursor.execute("""
        SELECT
            download_error,
            COUNT(*) as count
        FROM index_documents
        WHERE download_status = 'failed'
          AND download_error IS NOT NULL
        GROUP BY download_error
        ORDER BY count DESC
        LIMIT 20
    """)
    error_summary = [dict(row) for row in cursor.fetchall()]

    cursor.close()

    return {
        'status_breakdown': status_breakdown,
        'priority_breakdown': priority_breakdown,
        'hourly_activity': hourly_activity,
        'error_summary': error_summary
    }

def calculate_throughput(conn, hours: int = 24) -> Dict:
    """
    Calculate download throughput over time period.

    Args:
        conn: Database connection
        hours: Time period to analyze

    Returns:
        Throughput statistics
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
            COUNT(*) as completed,
            COUNT(*) / %s::float as per_hour,
            COUNT(*) / (%s::float * 60) as per_minute
        FROM index_documents
        WHERE download_status = 'completed'
          AND downloaded_at > CURRENT_TIMESTAMP - INTERVAL '%s hours'
    """, (hours, hours, hours))

    result = cursor.fetchone()
    cursor.close()

    return dict(result) if result else {}

def estimate_remaining_time(conn) -> Dict:
    """Estimate time to complete remaining downloads."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Get pending count
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM index_documents
        WHERE download_status = 'pending'
    """)
    pending = cursor.fetchone()['count']

    # Get recent throughput (last 6 hours for better estimate)
    throughput = calculate_throughput(conn, hours=6)

    if throughput.get('per_hour', 0) > 0:
        hours_remaining = pending / throughput['per_hour']
        days_remaining = hours_remaining / 24

        estimate = {
            'pending_documents': pending,
            'docs_per_hour': throughput['per_hour'],
            'estimated_hours': hours_remaining,
            'estimated_days': days_remaining,
            'estimated_completion': (datetime.now() + timedelta(hours=hours_remaining)).isoformat()
        }
    else:
        estimate = {
            'pending_documents': pending,
            'docs_per_hour': 0,
            'estimated_hours': None,
            'estimated_days': None,
            'estimated_completion': 'Unknown (no recent activity)'
        }

    cursor.close()
    return estimate

def identify_gaps(conn) -> List[Dict]:
    """
    Identify gaps in downloaded documents (missing book/page ranges).

    Returns:
        List of gap ranges
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        WITH book_coverage AS (
            SELECT DISTINCT book
            FROM index_documents
            WHERE download_status = 'completed'
            ORDER BY book
        ),
        book_gaps AS (
            SELECT
                book as gap_start,
                LEAD(book) OVER (ORDER BY book) as gap_end
            FROM book_coverage
        )
        SELECT
            gap_start,
            gap_end,
            gap_end - gap_start - 1 as missing_books
        FROM book_gaps
        WHERE gap_end - gap_start > 1
        ORDER BY missing_books DESC
        LIMIT 50
    """)

    gaps = [dict(row) for row in cursor.fetchall()]
    cursor.close()

    return gaps

# ============================================================================
# Reporting Functions
# ============================================================================

def print_progress_report(conn):
    """Print comprehensive progress report."""
    print("\n" + "="*80)
    print("DOWNLOAD PROGRESS REPORT")
    print("="*80)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Get statistics
    progress = get_download_progress(conn)

    # Status breakdown
    print("\nSTATUS BREAKDOWN:")
    for row in progress['status_breakdown']:
        status = row['download_status'] or 'NULL'
        print(f"  {status:15} {row['count']:>10,} ({row['percentage']:>5.1f}%)")

    # Priority breakdown
    print("\nPRIORITY BREAKDOWN:")
    current_priority = None
    for row in progress['priority_breakdown']:
        priority = row['download_priority']
        if priority != current_priority:
            priority_name = {1: 'Critical', 2: 'High', 3: 'Medium', 4: 'Low'}.get(priority, 'Unknown')
            print(f"\n  Priority {priority} ({priority_name}):")
            current_priority = priority
        print(f"    {row['download_status']:15} {row['count']:>8,}")

    # Throughput
    print("\nTHROUGHPUT:")
    throughput_24h = calculate_throughput(conn, hours=24)
    throughput_1h = calculate_throughput(conn, hours=1)

    if throughput_24h:
        print(f"  Last 24 hours:  {throughput_24h['completed']:>8,} docs ({throughput_24h['per_hour']:.1f}/hour)")
    if throughput_1h:
        print(f"  Last 1 hour:    {throughput_1h['completed']:>8,} docs ({throughput_1h['per_hour']:.1f}/hour)")

    # Time estimate
    print("\nESTIMATED COMPLETION:")
    estimate = estimate_remaining_time(conn)
    print(f"  Pending:        {estimate['pending_documents']:>8,} documents")
    if estimate['estimated_days']:
        print(f"  Est. time:      {estimate['estimated_days']:.1f} days ({estimate['estimated_hours']:.1f} hours)")
        print(f"  Est. complete:  {estimate['estimated_completion']}")
    else:
        print(f"  Est. complete:  {estimate['estimated_completion']}")

    # Recent errors
    if progress['error_summary']:
        print("\nTOP ERRORS (Last 20):")
        for row in progress['error_summary'][:10]:
            error = row['download_error'][:60]
            print(f"  {error:60} {row['count']:>5,}")

    # Gaps
    gaps = identify_gaps(conn)
    if gaps:
        print(f"\nGAPS IN COVERAGE ({len(gaps)} gaps found):")
        for gap in gaps[:10]:
            print(f"  Books {gap['gap_start']:>4} to {gap['gap_end']:>4} (missing {gap['missing_books']:>3} books)")

    print("\n" + "="*80)

def print_health_monitor(conn):
    """Print download health monitor."""
    print("\n" + "="*80)
    print("DOWNLOAD HEALTH MONITOR")
    print("="*80)

    # Check for stale in_progress records
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT COUNT(*) as count
        FROM index_documents
        WHERE download_status = 'in_progress'
          AND updated_at < CURRENT_TIMESTAMP - INTERVAL '30 minutes'
    """)
    stale_count = cursor.fetchone()['count']

    if stale_count > 0:
        print(f"\n⚠️  WARNING: {stale_count} stale 'in_progress' records (>30 min old)")
        print("   Run: python3 download_queue_manager.py --reset-stale")
    else:
        print("\n✓ No stale 'in_progress' records")

    # Check success rate (last 1000 documents)
    cursor.execute("""
        SELECT
            COUNT(*) FILTER (WHERE download_status = 'completed') * 100.0 / COUNT(*) as success_rate
        FROM (
            SELECT download_status
            FROM index_documents
            WHERE download_status IN ('completed', 'failed')
            ORDER BY updated_at DESC
            LIMIT 1000
        ) recent
    """)
    result = cursor.fetchone()
    success_rate = result['success_rate'] if result and result['success_rate'] else 0

    if success_rate >= 95:
        print(f"✓ Success rate: {success_rate:.1f}% (last 1000 docs)")
    elif success_rate >= 90:
        print(f"⚠️  Success rate: {success_rate:.1f}% (last 1000 docs) - Below target")
    else:
        print(f"❌ Success rate: {success_rate:.1f}% (last 1000 docs) - CRITICAL")

    # Check recent activity
    throughput = calculate_throughput(conn, hours=1)
    if throughput.get('completed', 0) > 0:
        print(f"✓ Recent activity: {throughput['completed']} docs in last hour")
    else:
        print("⚠️  No downloads in last hour")

    # Check for high error rates
    cursor.execute("""
        SELECT
            download_error,
            COUNT(*) as count
        FROM index_documents
        WHERE download_status = 'failed'
          AND updated_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'
        GROUP BY download_error
        ORDER BY count DESC
        LIMIT 5
    """)
    recent_errors = cursor.fetchall()

    if recent_errors:
        print("\n⚠️  Recent Errors (last hour):")
        for row in recent_errors:
            print(f"   {row['download_error'][:60]:60} {row['count']:>3}")

    cursor.close()
    print("\n" + "="*80)

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Validation and monitoring for document downloads',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--validate', action='store_true',
                       help='Validate downloaded documents')
    parser.add_argument('--report', action='store_true',
                       help='Generate progress report')
    parser.add_argument('--monitor', action='store_true',
                       help='Monitor download health')
    parser.add_argument('--last-hours', type=int, default=24,
                       help='Time window for validation/monitoring (default: 24)')

    args = parser.parse_args()

    if not any([args.validate, args.report, args.monitor]):
        parser.print_help()
        return 1

    # Connect to database
    try:
        conn = connect_db()
        logger.info("✓ Connected to database")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    try:
        if args.validate:
            # TODO: Implement validation logic
            print("Validation not yet implemented")

        if args.report:
            print_progress_report(conn)

        if args.monitor:
            print_health_monitor(conn)

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
    finally:
        conn.close()

    return 0

if __name__ == '__main__':
    sys.exit(main())
