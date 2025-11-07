#!/usr/bin/env python3
"""
Madison County Document Download - Staged Downloader

Main orchestration script for staged document downloads. Integrates with:
- Index database for queue management
- simple_doc_downloader for fast downloads (requests-based)
- GCS for storage
- Checkpointing for resumability

Stages:
- Stage 0: Test (20 documents)
- Stage 1: Small (2,000 documents)
- Stage 2: Medium (50,000 documents)
- Stage 3: Large (900,000 documents)
- Stage 4: Retry failed downloads

Usage:
    python3 staged_downloader.py --stage stage-1-small [--dry-run] [--resume]
"""

import sys
import os
import argparse
import logging
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from tqdm import tqdm

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2

# Import existing components
from madison_county_doc_puller.simple_doc_downloader import MadisonCountyDownloader
from madison_county_doc_puller.download_queue_manager import (
    DownloadQueueManager,
    determine_portal,
    STAGE_CONFIGS
)
from madison_county_doc_puller.pdf_optimizer import PDFOptimizer
from madison_county_doc_puller.gcs_manager import GCSManager

# ============================================================================
# Configuration
# ============================================================================

LOG_FILE = Path(__file__).parent / 'staged_download.log'
CHECKPOINT_DIR = Path(__file__).parent / 'checkpoints'
CHECKPOINT_DIR.mkdir(exist_ok=True)

# GCS Configuration
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'madison-county-title-plant')
GCS_CREDENTIALS_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

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
# Checkpoint Management
# ============================================================================

class CheckpointManager:
    """Manage download checkpoints for resumability."""

    def __init__(self, checkpoint_dir: Path, stage: str):
        self.checkpoint_dir = checkpoint_dir
        self.stage = stage
        self.checkpoint_interval = 100  # Save every 100 documents

    def save_checkpoint(self, queue_checkpoint: Dict, stats: Dict):
        """Save progress checkpoint."""
        checkpoint = {
            'stage': self.stage,
            'timestamp': datetime.now().isoformat(),
            'queue_state': queue_checkpoint,
            'statistics': stats
        }

        filename = f'checkpoint_{self.stage}_{int(time.time())}.json'
        path = self.checkpoint_dir / filename

        with open(path, 'w') as f:
            json.dump(checkpoint, f, indent=2)

        logger.info(f"Checkpoint saved: {filename}")
        return checkpoint

    def load_last_checkpoint(self) -> Optional[Dict]:
        """Load most recent checkpoint for this stage."""
        checkpoints = sorted(
            self.checkpoint_dir.glob(f'checkpoint_{self.stage}_*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if checkpoints:
            with open(checkpoints[0]) as f:
                checkpoint = json.load(f)
                logger.info(f"Loaded checkpoint from {checkpoints[0].name}")
                return checkpoint

        return None

    def cleanup_old_checkpoints(self, keep_last: int = 5):
        """Keep only the last N checkpoints."""
        checkpoints = sorted(
            self.checkpoint_dir.glob(f'checkpoint_{self.stage}_*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for checkpoint in checkpoints[keep_last:]:
            checkpoint.unlink()
            logger.debug(f"Deleted old checkpoint: {checkpoint.name}")

# ============================================================================
# Download Statistics
# ============================================================================

class DownloadStatistics:
    """Track download statistics and progress."""

    def __init__(self):
        self.start_time = datetime.now()
        self.total_attempted = 0
        self.total_completed = 0
        self.total_failed = 0
        self.total_skipped = 0
        self.total_mismatches = 0
        self.total_bytes_original = 0
        self.total_bytes_optimized = 0
        self.errors_by_type = {}
        self.portal_stats = {'historical': 0, 'mid': 0, 'new': 0}

    def record_success(self, portal: str, book_page_mismatch: bool = False,
                      original_size: int = 0, optimized_size: int = 0):
        """Record successful download."""
        self.total_attempted += 1
        self.total_completed += 1
        self.portal_stats[portal] = self.portal_stats.get(portal, 0) + 1
        if book_page_mismatch:
            self.total_mismatches += 1
        self.total_bytes_original += original_size
        self.total_bytes_optimized += optimized_size

    def record_failure(self, error: str, portal: str):
        """Record failed download."""
        self.total_attempted += 1
        self.total_failed += 1
        self.errors_by_type[error] = self.errors_by_type.get(error, 0) + 1
        self.portal_stats[portal] = self.portal_stats.get(portal, 0) + 1

    def record_skip(self, reason: str):
        """Record skipped download."""
        self.total_skipped += 1
        self.errors_by_type[reason] = self.errors_by_type.get(reason, 0) + 1

    def get_success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_attempted == 0:
            return 0.0
        return self.total_completed / self.total_attempted

    def get_docs_per_hour(self) -> float:
        """Calculate documents per hour."""
        elapsed = (datetime.now() - self.start_time).total_seconds() / 3600
        if elapsed == 0:
            return 0.0
        return self.total_completed / elapsed

    def to_dict(self) -> Dict:
        """Export statistics as dictionary."""
        savings = self.total_bytes_original - self.total_bytes_optimized
        savings_pct = (savings / self.total_bytes_original * 100) if self.total_bytes_original > 0 else 0

        return {
            'start_time': self.start_time.isoformat(),
            'duration_hours': (datetime.now() - self.start_time).total_seconds() / 3600,
            'total_attempted': self.total_attempted,
            'total_completed': self.total_completed,
            'total_failed': self.total_failed,
            'total_skipped': self.total_skipped,
            'total_mismatches': self.total_mismatches,
            'mismatch_rate': (self.total_mismatches / self.total_completed * 100) if self.total_completed > 0 else 0,
            'success_rate': self.get_success_rate(),
            'docs_per_hour': self.get_docs_per_hour(),
            'bytes_original': self.total_bytes_original,
            'bytes_optimized': self.total_bytes_optimized,
            'bytes_saved': savings,
            'optimization_rate': savings_pct,
            'errors_by_type': self.errors_by_type,
            'portal_stats': self.portal_stats
        }

    def print_summary(self):
        """Print statistics summary."""
        print("\n" + "="*80)
        print("DOWNLOAD STATISTICS")
        print("="*80)
        print(f"Duration:          {(datetime.now() - self.start_time).total_seconds() / 3600:.2f} hours")
        print(f"Total attempted:   {self.total_attempted:,}")
        print(f"Completed:         {self.total_completed:,}")
        print(f"Failed:            {self.total_failed:,}")
        print(f"Skipped:           {self.total_skipped:,}")
        print(f"Success rate:      {self.get_success_rate():.1%}")
        print(f"Docs/hour:         {self.get_docs_per_hour():.1f}")

        if self.total_completed > 0:
            mismatch_rate = (self.total_mismatches / self.total_completed * 100)
            print(f"\nValidation:")
            print(f"  Mismatches:      {self.total_mismatches:,} ({mismatch_rate:.1f}%)")

        if self.total_bytes_original > 0:
            savings = self.total_bytes_original - self.total_bytes_optimized
            savings_pct = (savings / self.total_bytes_original * 100)
            print(f"\nStorage Optimization:")
            print(f"  Original size:   {self.total_bytes_original / 1024 / 1024:.1f} MB")
            print(f"  Optimized size:  {self.total_bytes_optimized / 1024 / 1024:.1f} MB")
            print(f"  Saved:           {savings / 1024 / 1024:.1f} MB ({savings_pct:.1f}%)")

        if self.portal_stats:
            print("\nBy Portal:")
            for portal, count in self.portal_stats.items():
                if count > 0:
                    print(f"  {portal:15} {count:>8,}")

        if self.errors_by_type:
            print("\nTop Errors:")
            sorted_errors = sorted(self.errors_by_type.items(), key=lambda x: x[1], reverse=True)[:10]
            for error, count in sorted_errors:
                error_short = error[:60] + '...' if len(error) > 60 else error
                print(f"  {error_short:60} {count:>5,}")

        print("="*80)

# ============================================================================
# Staged Download Manager
# ============================================================================

class StagedDownloadManager:
    """
    Main orchestration class for staged document downloads.
    """

    def __init__(self, db_conn, stage: str, dry_run: bool = False):
        """
        Initialize download manager.

        Args:
            db_conn: Database connection
            stage: Stage identifier (e.g., 'stage-1-small')
            dry_run: If True, don't actually download
        """
        self.conn = db_conn
        self.stage = stage
        self.dry_run = dry_run

        # Initialize components
        self.queue = DownloadQueueManager(db_conn, stage, batch_size=100)
        self.checkpoint_manager = CheckpointManager(CHECKPOINT_DIR, stage)
        self.stats = DownloadStatistics()

        # Initialize downloader (will be created per document type)
        self.downloader = None

        # Initialize GCS manager and PDF optimizer (unless dry run)
        self.gcs_manager = None
        self.pdf_optimizer = None
        if not dry_run:
            try:
                self.gcs_manager = GCSManager(
                    bucket_name=GCS_BUCKET_NAME,
                    credentials_path=GCS_CREDENTIALS_PATH
                )
                logger.info(f"✓ Connected to GCS bucket: {GCS_BUCKET_NAME}")
            except Exception as e:
                logger.error(f"Failed to initialize GCS: {e}")
                logger.error("Set GOOGLE_APPLICATION_CREDENTIALS environment variable")
                raise

            try:
                self.pdf_optimizer = PDFOptimizer(quality='ebook')
                logger.info("✓ PDF optimizer initialized")
            except Exception as e:
                logger.warning(f"PDF optimizer not available: {e}")
                logger.warning("Install ghostscript: sudo apt-get install ghostscript")

        logger.info(f"Initialized {STAGE_CONFIGS[stage]['name']}")
        if dry_run:
            logger.info("DRY RUN MODE - No actual downloads will be performed")

    def setup_downloader(self, portal: str):
        """
        Setup document downloader for specific portal.

        Args:
            portal: Portal identifier ('historical', 'mid', or 'new')
        """
        # Use new requests-based downloader
        if not self.downloader:
            self.downloader = MadisonCountyDownloader(
                download_dir=Path(__file__).parent / 'temp_downloads'
            )
            logger.info(f"Initialized downloader (requests-based, 10-20x faster)")

    def download_document(self, doc: Dict) -> tuple[Optional[str], Optional[dict]]:
        """
        Download a single document using instrument number.

        Args:
            doc: Document record from database

        Returns:
            Tuple of (local_path, validation_data) where validation_data contains
            actual_book, actual_page, and book_page_mismatch
        """
        portal = determine_portal(doc['book'])
        book = doc['book']
        page = doc['page']
        instrument_number = doc.get('instrument_number')

        try:
            # Setup downloader if needed
            self.setup_downloader(portal)

            if self.dry_run:
                logger.info(f"[DRY RUN] Would download: Instrument {instrument_number}, Book {book}, Page {page} ({portal})")
                time.sleep(0.1)  # Simulate delay
                return (f"/fake/path/{book}-{page}.pdf", {
                    'actual_book': book,
                    'actual_page': page,
                    'book_page_mismatch': False
                })

            # Download by instrument number (if available) with validation
            if instrument_number:
                result = self.downloader.download_by_instrument(
                    instrument_number=instrument_number,
                    expected_book=book,
                    expected_page=page
                )
            else:
                # Fallback to book/page for documents without instrument numbers
                logger.warning(f"No instrument number for Book {book}, Page {page}, using book/page method")
                result = self.downloader.download_by_book_page(book=book, page=page)

            if not result.success:
                raise Exception(result.error or "Download failed")

            # Extract validation data
            validation_data = {
                'actual_book': result.actual_book,
                'actual_page': result.actual_page,
                'book_page_mismatch': result.book_page_mismatch
            }

            if result.book_page_mismatch:
                logger.warning(f"Book/page mismatch detected! "
                             f"Expected: {result.expected_book}/{result.expected_page}, "
                             f"Actual: {result.actual_book}/{result.actual_page}")

            return (result.local_path, validation_data)

        except Exception as e:
            logger.error(f"Download failed for Instrument {instrument_number} (Book {book}, Page {page}): {e}")
            raise

    def upload_to_gcs(self, local_path: str, doc: Dict) -> Tuple[str, int, int]:
        """
        Optimize and upload document to Google Cloud Storage.

        Args:
            local_path: Local file path
            doc: Document record

        Returns:
            Tuple of (gcs_url, original_size, optimized_size)
        """
        if self.dry_run:
            mock_gcs = f"gs://madison-county-title-plant/optimized-documents/deed/{doc['book']:04d}-{doc['page']:04d}.pdf"
            return (mock_gcs, 30000, 15000)  # Mock sizes

        local_file = Path(local_path)

        # Get original size
        original_size = local_file.stat().st_size

        # Optimize PDF if optimizer available
        optimized_size = original_size
        if self.pdf_optimizer:
            try:
                _, original_size, optimized_size = self.pdf_optimizer.optimize_in_place(local_file)
                logger.info(f"Optimized PDF: {original_size:,} → {optimized_size:,} bytes")
            except Exception as e:
                logger.warning(f"PDF optimization failed, uploading original: {e}")

        # Determine GCS path based on document type and book number
        doc_type = doc.get('document_type', 'unknown').lower().replace('_', '-')
        book = doc['book']
        page = doc['page']
        instrument_number = doc.get('instrument_number', 0)

        # Organize by book ranges for better structure
        if book < 238:
            folder_prefix = 'historical'
        elif book < 1000:
            folder_prefix = 'mid-early'
        else:
            folder_prefix = 'mid-recent'

        gcs_path = f"documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf"

        # Metadata for GCS
        metadata = {
            'book': str(book),
            'page': str(page),
            'instrument_number': str(instrument_number),
            'document_type': doc_type,
            'instrument_type': doc.get('instrument_type_parsed', ''),
            'original_size': str(original_size),
            'optimized_size': str(optimized_size)
        }

        # Upload to GCS
        try:
            gcs_url, checksum = self.gcs_manager.upload_file(
                local_path=local_file,
                gcs_path=gcs_path,
                metadata=metadata
            )
            logger.info(f"Uploaded to GCS: {gcs_url}")
            return (gcs_url, original_size, optimized_size)

        except Exception as e:
            logger.error(f"GCS upload failed: {e}")
            raise

    def process_document(self, doc: Dict):
        """
        Process a single document: download, optimize, upload, update database.

        Args:
            doc: Document record
        """
        doc_id = doc['id']
        portal = determine_portal(doc['book'])

        try:
            # Mark as in progress
            self.queue.mark_in_progress(doc_id)

            # Download with validation
            local_path, validation_data = self.download_document(doc)

            if not local_path:
                raise Exception("Download returned None")

            # Optimize and upload to GCS
            gcs_url, original_size, optimized_size = self.upload_to_gcs(local_path, doc)

            # Mark as completed with validation data
            self.queue.mark_completed(
                doc_id=doc_id,
                gcs_path=gcs_url,
                actual_book=validation_data.get('actual_book'),
                actual_page=validation_data.get('actual_page'),
                book_page_mismatch=validation_data.get('book_page_mismatch', False)
            )

            # Update statistics with file sizes
            self.stats.record_success(
                portal=portal,
                book_page_mismatch=validation_data.get('book_page_mismatch', False),
                original_size=original_size,
                optimized_size=optimized_size
            )

            # Cleanup local file after successful upload
            if not self.dry_run and Path(local_path).exists():
                Path(local_path).unlink()
                logger.debug(f"Cleaned up local file: {local_path}")

        except Exception as e:
            error_msg = str(e)[:500]
            self.queue.mark_failed(doc_id, error_msg, retry=True)
            self.stats.record_failure(error_msg, portal)
            logger.error(f"Failed to process doc {doc_id}: {error_msg}")

    def run(self, resume: bool = False):
        """
        Execute staged download process.

        Args:
            resume: If True, resume from last checkpoint
        """
        print("\n" + "="*80)
        print(f"STAGED DOWNLOAD - {STAGE_CONFIGS[self.stage]['name']}")
        print("="*80)
        print(f"Stage: {self.stage}")
        print(f"Description: {STAGE_CONFIGS[self.stage]['description']}")
        if self.dry_run:
            print("Mode: DRY RUN")
        print("="*80 + "\n")

        # Resume from checkpoint if requested
        if resume:
            checkpoint = self.checkpoint_manager.load_last_checkpoint()
            if checkpoint:
                self.queue.load_checkpoint(checkpoint['queue_state'])
                logger.info("Resumed from checkpoint")

        # Reset any stale in_progress records
        reset_count = self.queue.reset_in_progress_records()
        if reset_count > 0:
            logger.info(f"Reset {reset_count} stale records")

        # Get initial statistics
        queue_stats = self.queue.get_queue_statistics()
        pending_count = queue_stats['by_status'].get('pending', 0)

        print(f"Pending documents: {pending_count:,}\n")

        if pending_count == 0:
            print("No documents to download. Exiting.")
            return

        # Confirm start (unless dry run)
        if not self.dry_run and not resume:
            response = input("Start download? (y/n): ")
            if response.lower() != 'y':
                print("Download cancelled.")
                return

        # Process queue
        document_count = 0
        checkpoint_interval = 100

        with tqdm(total=pending_count, desc="Downloading") as pbar:
            while True:
                # Fetch next batch
                batch = self.queue.fetch_next_batch()

                if not batch:
                    logger.info("No more documents in queue")
                    break

                # Process each document
                for doc in batch:
                    self.process_document(doc)
                    document_count += 1
                    pbar.update(1)

                    # Checkpoint periodically
                    if document_count % checkpoint_interval == 0:
                        checkpoint = self.queue.save_checkpoint()
                        self.checkpoint_manager.save_checkpoint(
                            checkpoint,
                            self.stats.to_dict()
                        )

                    # Rate limiting (2 seconds between requests)
                    if not self.dry_run:
                        time.sleep(2)

                # Check stage limit
                if STAGE_CONFIGS[self.stage]['limit']:
                    if document_count >= STAGE_CONFIGS[self.stage]['limit']:
                        logger.info(f"Stage limit reached: {document_count}")
                        break

        # Final checkpoint
        checkpoint = self.queue.save_checkpoint()
        self.checkpoint_manager.save_checkpoint(checkpoint, self.stats.to_dict())

        # Print final statistics
        self.stats.print_summary()

        # Cleanup old checkpoints
        self.checkpoint_manager.cleanup_old_checkpoints()

        logger.info(f"Download complete. Log file: {LOG_FILE}")

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Staged document downloader for Madison County Title Plant',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Stages:
  stage-0-test            Test run (20 documents)
  stage-historical-all    All historical books 1-237
  stage-1-small           Small scale (2,000 documents)
  stage-2-medium          Medium scale (50,000 documents)
  stage-3-large           Large scale (900,000+ documents)
  stage-4-retry           Retry failed downloads

Examples:
  # Test run
  python3 staged_downloader.py --stage stage-0-test --dry-run

  # Download all historical records
  python3 staged_downloader.py --stage stage-historical-all

  # Small scale download
  python3 staged_downloader.py --stage stage-1-small

  # Resume interrupted download
  python3 staged_downloader.py --stage stage-2-medium --resume
        """
    )

    parser.add_argument('--stage', required=True, choices=list(STAGE_CONFIGS.keys()),
                       help='Download stage')
    parser.add_argument('--dry-run', action='store_true',
                       help='Simulate downloads without actually downloading')
    parser.add_argument('--resume', action='store_true',
                       help='Resume from last checkpoint')

    args = parser.parse_args()

    # Connect to database
    try:
        conn = connect_db()
        logger.info("✓ Connected to database")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Make sure you've run: source index_database/.db_credentials")
        return 1

    # Create and run download manager
    try:
        manager = StagedDownloadManager(conn, args.stage, args.dry_run)
        manager.run(resume=args.resume)
    except KeyboardInterrupt:
        logger.info("\n\nDownload interrupted by user")
        logger.info("Run with --resume to continue from last checkpoint")
        return 130
    except Exception as e:
        logger.error(f"Download failed: {e}", exc_info=True)
        return 1
    finally:
        conn.close()

    return 0

if __name__ == '__main__':
    sys.exit(main())
