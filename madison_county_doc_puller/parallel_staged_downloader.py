#!/usr/bin/env python3
"""
Madison County Document Download - Parallel Staged Downloader

Enhanced version of staged_downloader.py with parallel processing support.
Uses ThreadPoolExecutor for concurrent downloads to significantly speed up
the download process while respecting rate limits.

Key Features:
- Concurrent downloads using ThreadPoolExecutor (default: 5 workers)
- Thread-safe statistics tracking
- Per-thread database connections
- Shared rate limiting across threads
- Progress monitoring with tqdm

Usage:
    python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers 5
"""

import sys
import os
import argparse
import logging
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

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

LOG_FILE = Path(__file__).parent / 'parallel_staged_download.log'
CHECKPOINT_DIR = Path(__file__).parent / 'checkpoints'
CHECKPOINT_DIR.mkdir(exist_ok=True)

# GCS Configuration
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'madison-county-title-plant')
GCS_CREDENTIALS_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# Parallel Configuration
DEFAULT_WORKERS = 5  # Number of concurrent download threads
RATE_LIMIT_DELAY = 0.5  # Delay between requests (seconds) per thread

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# Database Connection Pool
# ============================================================================

def create_connection_pool(min_conn: int = 2, max_conn: int = 20):
    """Create a threaded connection pool for database connections."""
    return ThreadedConnectionPool(
        minconn=min_conn,
        maxconn=max_conn,
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=os.getenv('DB_PORT', 5432),
        database=os.getenv('DB_NAME', 'madison_county_index'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )

# ============================================================================
# Thread-Safe Rate Limiter
# ============================================================================

class RateLimiter:
    """Thread-safe rate limiter for controlling request frequency."""

    def __init__(self, delay: float = 0.5):
        """
        Initialize rate limiter.

        Args:
            delay: Minimum delay between requests (seconds)
        """
        self.delay = delay
        self.lock = threading.Lock()
        self.last_request = 0

    def wait(self):
        """Wait if necessary to respect rate limit."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self.last_request = time.time()

# ============================================================================
# Thread-Safe Statistics
# ============================================================================

class ThreadSafeStatistics:
    """Thread-safe download statistics tracker."""

    def __init__(self):
        self.lock = threading.Lock()
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
        """Record successful download (thread-safe)."""
        with self.lock:
            self.total_attempted += 1
            self.total_completed += 1
            self.portal_stats[portal] = self.portal_stats.get(portal, 0) + 1
            if book_page_mismatch:
                self.total_mismatches += 1
            self.total_bytes_original += original_size
            self.total_bytes_optimized += optimized_size

    def record_failure(self, error: str, portal: str):
        """Record failed download (thread-safe)."""
        with self.lock:
            self.total_attempted += 1
            self.total_failed += 1
            self.errors_by_type[error] = self.errors_by_type.get(error, 0) + 1
            self.portal_stats[portal] = self.portal_stats.get(portal, 0) + 1

    def record_skip(self, reason: str):
        """Record skipped download (thread-safe)."""
        with self.lock:
            self.total_skipped += 1
            self.errors_by_type[reason] = self.errors_by_type.get(reason, 0) + 1

    def get_success_rate(self) -> float:
        """Calculate success rate (thread-safe)."""
        with self.lock:
            if self.total_attempted == 0:
                return 0.0
            return self.total_completed / self.total_attempted

    def get_docs_per_hour(self) -> float:
        """Calculate documents per hour (thread-safe)."""
        with self.lock:
            elapsed = (datetime.now() - self.start_time).total_seconds() / 3600
            if elapsed == 0:
                return 0.0
            return self.total_completed / elapsed

    def to_dict(self) -> Dict:
        """Export statistics as dictionary (thread-safe)."""
        with self.lock:
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
                'errors_by_type': dict(self.errors_by_type),
                'portal_stats': dict(self.portal_stats)
            }

    def print_summary(self):
        """Print statistics summary (thread-safe)."""
        data = self.to_dict()
        print("\n" + "="*80)
        print("DOWNLOAD STATISTICS")
        print("="*80)
        print(f"Duration:          {data['duration_hours']:.2f} hours")
        print(f"Total attempted:   {data['total_attempted']:,}")
        print(f"Completed:         {data['total_completed']:,}")
        print(f"Failed:            {data['total_failed']:,}")
        print(f"Skipped:           {data['total_skipped']:,}")
        print(f"Success rate:      {data['success_rate']:.1%}")
        print(f"Docs/hour:         {data['docs_per_hour']:.1f}")

        if data['total_completed'] > 0:
            print(f"\nValidation:")
            print(f"  Mismatches:      {data['total_mismatches']:,} ({data['mismatch_rate']:.1f}%)")

        if data['bytes_original'] > 0:
            print(f"\nStorage Optimization:")
            print(f"  Original size:   {data['bytes_original'] / 1024 / 1024:.1f} MB")
            print(f"  Optimized size:  {data['bytes_optimized'] / 1024 / 1024:.1f} MB")
            print(f"  Saved:           {data['bytes_saved'] / 1024 / 1024:.1f} MB ({data['optimization_rate']:.1f}%)")

        if data['portal_stats']:
            print("\nBy Portal:")
            for portal, count in data['portal_stats'].items():
                if count > 0:
                    print(f"  {portal:15} {count:>8,}")

        if data['errors_by_type']:
            print("\nTop Errors:")
            sorted_errors = sorted(data['errors_by_type'].items(), key=lambda x: x[1], reverse=True)[:10]
            for error, count in sorted_errors:
                error_short = error[:60] + '...' if len(error) > 60 else error
                print(f"  {error_short:60} {count:>5,}")

        print("="*80)

# ============================================================================
# Parallel Download Worker
# ============================================================================

class DownloadWorker:
    """Worker class for processing documents in parallel."""

    def __init__(self, worker_id: int, conn_pool: ThreadedConnectionPool,
                 stage: str, rate_limiter: RateLimiter,
                 gcs_manager: GCSManager, pdf_optimizer: Optional[PDFOptimizer],
                 dry_run: bool = False):
        """
        Initialize download worker.

        Args:
            worker_id: Unique worker identifier
            conn_pool: Database connection pool
            stage: Stage identifier
            rate_limiter: Shared rate limiter
            gcs_manager: GCS manager instance
            pdf_optimizer: PDF optimizer instance
            dry_run: If True, don't actually download
        """
        self.worker_id = worker_id
        self.conn_pool = conn_pool
        self.stage = stage
        self.rate_limiter = rate_limiter
        self.gcs_manager = gcs_manager
        self.pdf_optimizer = pdf_optimizer
        self.dry_run = dry_run

        # Each worker gets its own downloader and database connection
        self.downloader = MadisonCountyDownloader(
            download_dir=Path(__file__).parent / 'temp_downloads' / f'worker_{worker_id}'
        )
        self.conn = None

    def get_connection(self):
        """Get database connection from pool."""
        if not self.conn:
            self.conn = self.conn_pool.getconn()
        return self.conn

    def return_connection(self):
        """Return database connection to pool."""
        if self.conn:
            self.conn_pool.putconn(self.conn)
            self.conn = None

    def process_document(self, doc: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Process a single document: download, optimize, upload.

        Args:
            doc: Document record

        Returns:
            Tuple of (success, error_message, validation_data)
        """
        doc_id = doc['id']
        portal = determine_portal(doc['book'])
        book = doc['book']
        page = doc['page']
        instrument_number = doc.get('instrument_number')

        try:
            # Get database connection
            conn = self.get_connection()
            queue = DownloadQueueManager(conn, self.stage)

            # Mark as in progress
            queue.mark_in_progress(doc_id)

            # Rate limit before download
            self.rate_limiter.wait()

            if self.dry_run:
                logger.info(f"[Worker {self.worker_id}] [DRY RUN] Would download: Instrument {instrument_number}, Book {book}, Page {page}")
                time.sleep(0.1)
                validation_data = {
                    'actual_book': book,
                    'actual_page': page,
                    'book_page_mismatch': False
                }
                gcs_url = f"gs://fake/{book}-{page}.pdf"
                original_size = 30000
                optimized_size = 15000
            else:
                # Download with validation
                if instrument_number:
                    result = self.downloader.download_by_instrument(
                        instrument_number=instrument_number,
                        expected_book=book,
                        expected_page=page
                    )
                else:
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
                    logger.warning(f"[Worker {self.worker_id}] Book/page mismatch! "
                                 f"Expected: {result.expected_book}/{result.expected_page}, "
                                 f"Actual: {result.actual_book}/{result.actual_page}")

                # Optimize and upload to GCS
                gcs_url, original_size, optimized_size = self._upload_to_gcs(result.local_path, doc)

                # Cleanup local file
                if Path(result.local_path).exists():
                    Path(result.local_path).unlink()

            # Mark as completed
            queue.mark_completed(
                doc_id=doc_id,
                gcs_path=gcs_url,
                actual_book=validation_data.get('actual_book'),
                actual_page=validation_data.get('actual_page'),
                book_page_mismatch=validation_data.get('book_page_mismatch', False)
            )

            return (True, None, {
                'validation_data': validation_data,
                'original_size': original_size,
                'optimized_size': optimized_size,
                'portal': portal
            })

        except Exception as e:
            error_msg = str(e)[:500]
            try:
                conn = self.get_connection()
                queue = DownloadQueueManager(conn, self.stage)
                queue.mark_failed(doc_id, error_msg, retry=True)
            except Exception as db_error:
                logger.error(f"[Worker {self.worker_id}] Failed to mark doc {doc_id} as failed: {db_error}")

            return (False, error_msg, {'portal': portal})

    def _upload_to_gcs(self, local_path: str, doc: Dict) -> Tuple[str, int, int]:
        """
        Optimize and upload document to GCS.

        Args:
            local_path: Local file path
            doc: Document record

        Returns:
            Tuple of (gcs_url, original_size, optimized_size)
        """
        local_file = Path(local_path)
        original_size = local_file.stat().st_size

        # Optimize PDF if optimizer available
        optimized_size = original_size
        if self.pdf_optimizer:
            try:
                original_size, optimized_size = self.pdf_optimizer.optimize_in_place(local_file)
                logger.info(f"[Worker {self.worker_id}] Optimized: {original_size:,} → {optimized_size:,} bytes")
            except Exception as e:
                logger.warning(f"[Worker {self.worker_id}] PDF optimization failed: {e}")

        # Determine GCS path
        doc_type = (doc.get('document_type') or 'unknown').lower().replace('_', '-')
        book = doc['book']
        page = doc['page']
        instrument_number = doc.get('instrument_number') or 0

        if book < 238:
            folder_prefix = 'historical'
        elif book < 1000:
            folder_prefix = 'mid-early'
        else:
            folder_prefix = 'mid-recent'

        gcs_path = f"documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf"

        # Metadata
        metadata = {
            'book': str(book),
            'page': str(page),
            'instrument_number': str(instrument_number),
            'document_type': doc_type,
            'instrument_type': doc.get('instrument_type_parsed') or '',
            'original_size': str(original_size),
            'optimized_size': str(optimized_size)
        }

        # Upload
        gcs_url, checksum = self.gcs_manager.upload_file(
            local_path=local_file,
            gcs_path=gcs_path,
            metadata=metadata
        )

        return (gcs_url, original_size, optimized_size)

# ============================================================================
# Parallel Download Manager
# ============================================================================

class ParallelDownloadManager:
    """Manager for parallel document downloads."""

    def __init__(self, conn_pool: ThreadedConnectionPool, stage: str,
                 num_workers: int = 5, dry_run: bool = False):
        """
        Initialize parallel download manager.

        Args:
            conn_pool: Database connection pool
            stage: Stage identifier
            num_workers: Number of worker threads
            dry_run: If True, don't actually download
        """
        self.conn_pool = conn_pool
        self.stage = stage
        self.num_workers = num_workers
        self.dry_run = dry_run

        # Get main connection for queue management
        self.main_conn = conn_pool.getconn()
        self.queue = DownloadQueueManager(self.main_conn, stage, batch_size=num_workers * 10)

        # Shared components
        self.rate_limiter = RateLimiter(delay=RATE_LIMIT_DELAY)
        self.stats = ThreadSafeStatistics()

        # Initialize GCS and PDF optimizer
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
                raise

            try:
                self.pdf_optimizer = PDFOptimizer(quality='ebook')
                logger.info("✓ PDF optimizer initialized")
            except Exception as e:
                logger.warning(f"PDF optimizer not available: {e}")

        logger.info(f"Initialized {STAGE_CONFIGS[stage]['name']} with {num_workers} workers")
        if dry_run:
            logger.info("DRY RUN MODE - No actual downloads")

    def run(self):
        """Execute parallel download process."""
        print("\n" + "="*80)
        print(f"PARALLEL STAGED DOWNLOAD - {STAGE_CONFIGS[self.stage]['name']}")
        print("="*80)
        print(f"Stage: {self.stage}")
        print(f"Workers: {self.num_workers}")
        print(f"Description: {STAGE_CONFIGS[self.stage]['description']}")
        if self.dry_run:
            print("Mode: DRY RUN")
        print("="*80 + "\n")

        # Reset stale in_progress records
        reset_count = self.queue.reset_in_progress_records()
        if reset_count > 0:
            logger.info(f"Reset {reset_count} stale records")

        # Get statistics
        queue_stats = self.queue.get_queue_statistics()
        pending_count = queue_stats['by_status'].get('pending', 0)

        print(f"Pending documents: {pending_count:,}\n")

        if pending_count == 0:
            print("No documents to download. Exiting.")
            return

        # Confirm start
        if not self.dry_run:
            response = input("Start download? (y/n): ")
            if response.lower() != 'y':
                print("Download cancelled.")
                return

        # Create workers
        workers = [
            DownloadWorker(
                worker_id=i,
                conn_pool=self.conn_pool,
                stage=self.stage,
                rate_limiter=self.rate_limiter,
                gcs_manager=self.gcs_manager,
                pdf_optimizer=self.pdf_optimizer,
                dry_run=self.dry_run
            )
            for i in range(self.num_workers)
        ]

        # Process documents with ThreadPoolExecutor
        document_count = 0
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            with tqdm(total=pending_count, desc="Downloading") as pbar:
                while True:
                    # Fetch next batch
                    batch = self.queue.fetch_next_batch(limit=self.num_workers * 10)

                    if not batch:
                        logger.info("No more documents in queue")
                        break

                    # Submit batch to workers
                    futures = {}
                    for doc in batch:
                        worker = workers[document_count % self.num_workers]
                        future = executor.submit(worker.process_document, doc)
                        futures[future] = doc

                    # Process completed futures
                    for future in as_completed(futures):
                        doc = futures[future]
                        success, error, result_data = future.result()

                        if success:
                            self.stats.record_success(
                                portal=result_data['portal'],
                                book_page_mismatch=result_data['validation_data'].get('book_page_mismatch', False),
                                original_size=result_data.get('original_size', 0),
                                optimized_size=result_data.get('optimized_size', 0)
                            )
                        else:
                            self.stats.record_failure(error, result_data['portal'])

                        document_count += 1
                        pbar.update(1)

                        # Check stage limit
                        if STAGE_CONFIGS[self.stage]['limit']:
                            if document_count >= STAGE_CONFIGS[self.stage]['limit']:
                                logger.info(f"Stage limit reached: {document_count}")
                                executor.shutdown(wait=True)
                                break

        # Cleanup workers
        for worker in workers:
            worker.return_connection()

        # Return main connection
        self.conn_pool.putconn(self.main_conn)

        # Print final statistics
        self.stats.print_summary()
        logger.info(f"Download complete. Log file: {LOG_FILE}")

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Parallel staged document downloader for Madison County Title Plant',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download MID filtered documents with 5 workers
  python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers 5

  # Dry run with 10 workers
  python3 parallel_staged_downloader.py --stage stage-mid-filtered --workers 10 --dry-run

  # Test with 3 workers
  python3 parallel_staged_downloader.py --stage stage-0-test --workers 3
        """
    )

    parser.add_argument('--stage', required=True, choices=list(STAGE_CONFIGS.keys()),
                       help='Download stage')
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS,
                       help=f'Number of concurrent workers (default: {DEFAULT_WORKERS})')
    parser.add_argument('--dry-run', action='store_true',
                       help='Simulate downloads without actually downloading')

    args = parser.parse_args()

    # Validate workers
    if args.workers < 1 or args.workers > 20:
        logger.error("Workers must be between 1 and 20")
        return 1

    # Create connection pool
    try:
        conn_pool = create_connection_pool(min_conn=2, max_conn=args.workers + 5)
        logger.info("✓ Created database connection pool")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Make sure you've run: source index_database/.db_credentials")
        return 1

    # Create and run download manager
    try:
        manager = ParallelDownloadManager(conn_pool, args.stage, args.workers, args.dry_run)
        manager.run()
    except KeyboardInterrupt:
        logger.info("\n\nDownload interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Download failed: {e}", exc_info=True)
        return 1
    finally:
        conn_pool.closeall()

    return 0

if __name__ == '__main__':
    sys.exit(main())
