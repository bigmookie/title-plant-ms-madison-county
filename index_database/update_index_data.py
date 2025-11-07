#!/usr/bin/env python3
"""
Madison County Title Plant - Index Data Update Script

This script handles incremental updates to the index database when new
DuProcess Excel files are added. It can:
- Import specific files by path or pattern
- Auto-detect new files since last import
- Show statistics and dry-run mode for safety

Usage:
    # Import specific file
    python3 update_index_data.py --file "madison_docs/DuProcess Indexes/2025-04-01.xlsx"

    # Import multiple files matching pattern
    python3 update_index_data.py --pattern "2025-*.xlsx"

    # Import all new files (based on modification time)
    python3 update_index_data.py --auto

    # Dry run to see what would be imported
    python3 update_index_data.py --auto --dry-run
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
import argparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import pandas as pd
from tqdm import tqdm

# Import from existing import script
from index_database.import_index_data import (
    DUPROCESS_TYPE_MAPPING,
    parse_instrument_type,
    connect_db,
    load_duprocess_file,
    DatabaseManager
)

# ============================================================================
# Configuration
# ============================================================================

BASE_DIR = Path(__file__).parent.parent
DUPROCESS_DIR = BASE_DIR / 'madison_docs' / 'DuProcess Indexes'
LOG_FILE = Path(__file__).parent / 'index_update.log'
TRACKING_FILE = Path(__file__).parent / '.last_import_time'

# ============================================================================
# Logging Setup
# ============================================================================

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
# Tracking Functions
# ============================================================================

def get_last_import_time() -> Optional[datetime]:
    """Get timestamp of last import from tracking file."""
    if TRACKING_FILE.exists():
        try:
            with open(TRACKING_FILE, 'r') as f:
                timestamp_str = f.read().strip()
                return datetime.fromisoformat(timestamp_str)
        except Exception as e:
            logger.warning(f"Could not read last import time: {e}")
    return None

def save_import_time(timestamp: datetime):
    """Save import timestamp to tracking file."""
    try:
        with open(TRACKING_FILE, 'w') as f:
            f.write(timestamp.isoformat())
    except Exception as e:
        logger.error(f"Could not save import time: {e}")

def find_new_files(since: Optional[datetime] = None) -> List[Path]:
    """Find DuProcess Excel files modified after the given timestamp."""
    if since is None:
        since = get_last_import_time()

    if since is None:
        logger.warning("No previous import time found. Use --pattern or --file instead.")
        return []

    new_files = []
    for file_path in DUPROCESS_DIR.glob('*.xlsx'):
        # Skip temp files
        if file_path.name.startswith('~$'):
            continue

        # Check modification time
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        if mtime > since:
            new_files.append(file_path)

    return sorted(new_files)

def find_files_by_pattern(pattern: str) -> List[Path]:
    """Find DuProcess Excel files matching the given pattern."""
    files = []
    for file_path in DUPROCESS_DIR.glob(pattern):
        if file_path.is_file() and not file_path.name.startswith('~$'):
            files.append(file_path)
    return sorted(files)


# ============================================================================
# Statistics
# ============================================================================

def get_database_stats(conn) -> dict:
    """Get current database statistics."""
    cursor = conn.cursor()

    stats = {}

    # Total records
    cursor.execute("SELECT COUNT(*) FROM index_documents")
    stats['total_records'] = cursor.fetchone()[0]

    # By source
    cursor.execute("""
        SELECT source, COUNT(*)
        FROM index_documents
        GROUP BY source
    """)
    stats['by_source'] = dict(cursor.fetchall())

    # Download status
    cursor.execute("""
        SELECT download_status, COUNT(*)
        FROM index_documents
        GROUP BY download_status
    """)
    stats['by_status'] = dict(cursor.fetchall())

    # Recent imports
    cursor.execute("""
        SELECT COUNT(*)
        FROM index_documents
        WHERE import_date > NOW() - INTERVAL '24 hours'
    """)
    stats['imported_today'] = cursor.fetchone()[0]

    cursor.close()
    return stats

def print_stats(before: dict, after: dict):
    """Print before/after statistics."""
    print("\n" + "="*70)
    print("DATABASE STATISTICS")
    print("="*70)

    print(f"\nTotal Records:")
    print(f"  Before: {before['total_records']:,}")
    print(f"  After:  {after['total_records']:,}")
    print(f"  Change: +{after['total_records'] - before['total_records']:,}")

    print(f"\nBy Source:")
    for source in set(list(before['by_source'].keys()) + list(after['by_source'].keys())):
        before_count = before['by_source'].get(source, 0)
        after_count = after['by_source'].get(source, 0)
        print(f"  {source:12} {before_count:8,} → {after_count:8,} (+{after_count - before_count:,})")

    print(f"\nDownload Status:")
    for status in sorted(set(list(before['by_status'].keys()) + list(after['by_status'].keys()))):
        before_count = before['by_status'].get(status, 0)
        after_count = after['by_status'].get(status, 0)
        print(f"  {status:12} {before_count:8,} → {after_count:8,}")

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Update Madison County Index Database with new DuProcess files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import specific file
  %(prog)s --file "madison_docs/DuProcess Indexes/2025-04-01.xlsx"

  # Import files matching pattern
  %(prog)s --pattern "2025-04-*.xlsx"

  # Auto-import all new files
  %(prog)s --auto

  # Dry run (show what would be imported)
  %(prog)s --auto --dry-run
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--file', help='Import specific file')
    group.add_argument('--pattern', help='Import files matching pattern (e.g., "2025-*.xlsx")')
    group.add_argument('--auto', action='store_true', help='Auto-detect new files since last import')

    parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without making changes')
    parser.add_argument('--force', action='store_true', help='Force import even if files were previously imported')

    args = parser.parse_args()

    print("\n" + "="*70)
    print("Madison County Title Plant - Index Data Update")
    print("="*70 + "\n")

    # Determine files to import
    files_to_import = []

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = BASE_DIR / file_path
        if file_path.exists():
            files_to_import = [file_path]
        else:
            logger.error(f"File not found: {file_path}")
            return 1

    elif args.pattern:
        files_to_import = find_files_by_pattern(args.pattern)
        if not files_to_import:
            logger.warning(f"No files found matching pattern: {args.pattern}")
            return 1

    elif args.auto:
        last_import = get_last_import_time()
        if last_import:
            print(f"Last import: {last_import.strftime('%Y-%m-%d %H:%M:%S')}")
            files_to_import = find_new_files(last_import)
        else:
            logger.error("No previous import found. Use --pattern or --file for first import.")
            return 1

    if not files_to_import:
        print("No new files to import.")
        return 0

    # Show files to be imported
    print(f"\nFiles to import ({len(files_to_import)}):")
    for f in files_to_import:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        print(f"  - {f.name} (modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')})")

    if args.dry_run:
        print("\n[DRY RUN] Analyzing files without making database changes...")

    # Confirm unless forced or dry-run
    if not args.dry_run and not args.force and not args.auto:
        response = input("\nProceed with import? (y/n): ")
        if response.lower() != 'y':
            print("Import cancelled.")
            return 0

    # Connect to database
    try:
        db = DatabaseManager()
        logger.info("Connected to database")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    # Get before statistics
    print("\nGathering database statistics...")
    before_stats = get_database_stats(db.conn)

    # Handle dry run
    if args.dry_run:
        total_records = 0
        for file_path in tqdm(files_to_import, desc="Analyzing files"):
            records = load_duprocess_file(file_path)
            total_records += len(records)

        print(f"\n[DRY RUN] Would import {total_records:,} records from {len(files_to_import)} files")
        db.close()
        return 0

    # Process files
    print(f"\nProcessing {len(files_to_import)} files...")

    total_records = 0

    for file_path in tqdm(files_to_import, desc="Importing files"):
        records = load_duprocess_file(file_path)
        if records:
            db.insert_batch(records)
            total_records += len(records)
            logger.info(f"Imported {file_path.name}: {len(records)} records")

    # Get after statistics
    after_stats = get_database_stats(db.conn)

    # Update tracking file
    if not args.dry_run:
        save_import_time(datetime.now())

    # Print results
    print("\n" + "="*70)
    print("IMPORT COMPLETE")
    print("="*70)
    print(f"\nFiles processed:     {len(files_to_import)}")
    print(f"Records processed:   {total_records:,}")

    print_stats(before_stats, after_stats)

    print(f"\nLog file: {LOG_FILE}")
    print("\nNote: Existing records were updated based on book/page/source conflicts.")

    db.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
