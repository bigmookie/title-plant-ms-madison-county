"""Main orchestrator for document download pipeline."""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .config.settings import Settings, get_settings
from .processors.index_processor import IndexProcessor, DownloadQueueItem
from .processors.pdf_optimizer import PDFOptimizer
from .scrapers.scraper_factory import ScraperFactory
from .storage.gcs_manager import GCSManager

logger = logging.getLogger(__name__)

class DocumentPipelineOrchestrator:
    """Orchestrate the complete document download, optimization, and upload pipeline."""
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize orchestrator.
        
        Args:
            settings: Application settings (uses default if None)
        """
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        
        # Initialize components
        self.index_processor = IndexProcessor(
            self.settings.index_dir,
            self.settings.checkpoint_dir / 'index_checkpoint.json'
        )
        self.scraper_factory = ScraperFactory(self.settings)
        self.pdf_optimizer = PDFOptimizer(
            self.settings.pdf_compression_quality,
            self.settings.pdf_dpi
        )
        self.gcs_manager = GCSManager(
            self.settings.gcs_bucket_name,
            self.settings.gcp_credentials_path
        )
        
        # Queue and state management
        self.queue: List[DownloadQueueItem] = []
        self.queue_file = self.settings.checkpoint_dir / 'download_queue.json'
        self.progress_file = self.settings.checkpoint_dir / 'progress.json'
        self.progress = {
            'total': 0,
            'completed': 0,
            'failed': 0,
            'skipped': 0,
            'start_time': None,
            'last_update': None
        }
        
        # Thread safety
        self.progress_lock = threading.Lock()
    
    def initialize_queue(self, force_rebuild: bool = False) -> int:
        """
        Initialize or load the download queue.
        
        Args:
            force_rebuild: Force rebuilding queue from indexes
            
        Returns:
            Number of items in queue
        """
        if not force_rebuild and self.queue_file.exists():
            logger.info("Loading existing queue")
            self.index_processor.load_queue(self.queue_file)
            self.queue = self.index_processor.queue
        else:
            logger.info("Building queue from index files")
            self.queue = self.index_processor.process_all_indexes()
            self.index_processor.save_queue(self.queue_file)
        
        # Filter out completed items if resuming
        pending_queue = [item for item in self.queue if item.status != 'completed']
        
        logger.info(f"Queue initialized with {len(pending_queue)} pending items "
                   f"(total: {len(self.queue)})")
        
        # Update progress
        self.progress['total'] = len(self.queue)
        self.progress['completed'] = len(self.queue) - len(pending_queue)
        
        return len(pending_queue)
    
    def process_single_document(self, item: DownloadQueueItem) -> bool:
        """
        Process a single document through the complete pipeline.
        
        Args:
            item: Download queue item
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Processing: Book {item.book}, Page {item.page} ({item.document_type})")
        
        try:
            # Step 1: Download document
            scraper = self.scraper_factory.get_scraper(item.portal)
            local_path, checksum, error = scraper.download_with_retry(
                item.book,
                item.page,
                item.document_code
            )
            
            if error:
                item.status = 'failed'
                item.error_message = error
                item.attempts += 1
                logger.error(f"Download failed: {error}")
                return False
            
            item.checksum = checksum
            
            # Step 2: Optimize PDF
            logger.debug("Optimizing PDF")
            optimized_path, orig_size, opt_size = self.pdf_optimizer.optimize(local_path)
            logger.debug(f"Optimization: {orig_size:,} -> {opt_size:,} bytes")
            
            # Step 3: Upload to GCS
            gcs_path = item.get_gcs_path()
            metadata = {
                'book': item.book,
                'page': item.page,
                'document_type': item.document_type,
                'document_code': item.document_code,
                'portal': item.portal,
                'instrument_number': item.instrument_number,
                'file_date': item.file_date,
                'original_size': str(orig_size),
                'optimized_size': str(opt_size)
            }
            
            gcs_url, _ = self.gcs_manager.upload_file(
                optimized_path,
                gcs_path,
                metadata=metadata
            )
            
            item.gcs_path = gcs_url
            item.status = 'completed'
            
            # Step 4: Clean up local files
            scraper.cleanup_temp_file(local_path)
            if optimized_path != local_path:
                scraper.cleanup_temp_file(optimized_path)
            
            logger.info(f"Successfully processed: {gcs_url}")
            return True
            
        except Exception as e:
            logger.error(f"Pipeline error for Book {item.book}, Page {item.page}: {e}")
            item.status = 'failed'
            item.error_message = str(e)
            item.attempts += 1
            return False
    
    def process_queue_sequential(self, max_items: Optional[int] = None):
        """
        Process queue sequentially (single-threaded).
        
        Args:
            max_items: Maximum number of items to process
        """
        pending_items = [item for item in self.queue if item.status != 'completed']
        
        if max_items:
            pending_items = pending_items[:max_items]
        
        logger.info(f"Processing {len(pending_items)} documents sequentially")
        
        self.progress['start_time'] = datetime.now().isoformat()
        
        for idx, item in enumerate(pending_items, 1):
            logger.info(f"Progress: {idx}/{len(pending_items)}")
            
            success = self.process_single_document(item)
            
            with self.progress_lock:
                if success:
                    self.progress['completed'] += 1
                else:
                    self.progress['failed'] += 1
                
                self.progress['last_update'] = datetime.now().isoformat()
                self._save_progress()
            
            # Save queue state periodically
            if idx % 10 == 0:
                self._save_queue_state()
    
    def process_queue_parallel(self, max_items: Optional[int] = None, max_workers: Optional[int] = None):
        """
        Process queue in parallel using thread pool.
        
        Args:
            max_items: Maximum number of items to process
            max_workers: Maximum number of concurrent workers
        """
        pending_items = [item for item in self.queue if item.status != 'completed']
        
        if max_items:
            pending_items = pending_items[:max_items]
        
        if not max_workers:
            max_workers = self.settings.concurrent_downloads
        
        logger.info(f"Processing {len(pending_items)} documents with {max_workers} workers")
        
        self.progress['start_time'] = datetime.now().isoformat()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_item = {
                executor.submit(self.process_single_document, item): item
                for item in pending_items
            }
            
            # Process completed tasks
            for idx, future in enumerate(as_completed(future_to_item), 1):
                item = future_to_item[future]
                
                try:
                    success = future.result()
                    
                    with self.progress_lock:
                        if success:
                            self.progress['completed'] += 1
                        else:
                            self.progress['failed'] += 1
                        
                        self.progress['last_update'] = datetime.now().isoformat()
                        
                        # Log progress
                        total_processed = self.progress['completed'] + self.progress['failed']
                        logger.info(f"Progress: {total_processed}/{len(pending_items)} "
                                  f"(Completed: {self.progress['completed']}, "
                                  f"Failed: {self.progress['failed']})")
                        
                        self._save_progress()
                    
                    # Save queue state periodically
                    if idx % 10 == 0:
                        self._save_queue_state()
                        
                except Exception as e:
                    logger.error(f"Task failed for Book {item.book}, Page {item.page}: {e}")
                    with self.progress_lock:
                        self.progress['failed'] += 1
    
    def _save_queue_state(self):
        """Save current queue state to disk."""
        try:
            self.index_processor.queue = self.queue
            self.index_processor.save_queue(self.queue_file)
            logger.debug("Queue state saved")
        except Exception as e:
            logger.error(f"Failed to save queue state: {e}")
    
    def _save_progress(self):
        """Save progress to disk."""
        try:
            with open(self.progress_file, 'w') as f:
                json.dump(self.progress, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")
    
    def _load_progress(self):
        """Load progress from disk."""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    saved_progress = json.load(f)
                    self.progress.update(saved_progress)
                    logger.info(f"Loaded progress: {self.progress['completed']} completed, "
                              f"{self.progress['failed']} failed")
            except Exception as e:
                logger.error(f"Failed to load progress: {e}")
    
    def generate_report(self) -> Dict:
        """Generate processing report."""
        stats = self.index_processor.get_statistics()
        
        # Calculate timing
        elapsed_time = None
        if self.progress.get('start_time'):
            start = datetime.fromisoformat(self.progress['start_time'])
            elapsed = datetime.now() - start
            elapsed_time = str(elapsed).split('.')[0]  # Remove microseconds
        
        report = {
            'summary': {
                'total_documents': self.progress['total'],
                'completed': self.progress['completed'],
                'failed': self.progress['failed'],
                'skipped': self.progress['skipped'],
                'success_rate': f"{100 * self.progress['completed'] / max(1, self.progress['total']):.1f}%",
                'elapsed_time': elapsed_time
            },
            'queue_statistics': stats,
            'failed_documents': [
                {
                    'book': item.book,
                    'page': item.page,
                    'error': item.error_message,
                    'attempts': item.attempts
                }
                for item in self.queue if item.status == 'failed'
            ][:20]  # Limit to first 20 failures
        }
        
        return report
    
    def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up resources")
        self.scraper_factory.close_all()
        
        # Save final state
        self._save_queue_state()
        self._save_progress()
        
        # Generate and save report
        report = self.generate_report()
        report_file = self.settings.checkpoint_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Final report saved to {report_file}")
        logger.info(f"Processing complete: {report['summary']}")