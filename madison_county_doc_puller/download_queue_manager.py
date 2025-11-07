"""
Madison County Document Download - Queue Manager

Manages the download queue from the index database, handling:
- Fetching documents by stage and priority
- Status tracking (pending → in_progress → completed/failed)
- Checkpoint/resumability
- Statistics and progress tracking

Usage:
    from download_queue_manager import DownloadQueueManager

    queue = DownloadQueueManager(db_conn, stage='stage-1')
    batch = queue.fetch_next_batch(limit=100)
    for doc in batch:
        # Download logic...
        queue.mark_completed(doc['id'], gcs_path='/path/to/file.pdf')
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ============================================================================
# Portal Routing
# ============================================================================

def determine_portal(book: int) -> str:
    """
    Determine which portal to use based on book number.

    Rules:
    - Books < 238: Historical portal
    - Books 238-3971: MID portal
    - Books >= 3972: NEW portal (excluded in Phase 1)

    Args:
        book: Book number

    Returns:
        Portal identifier: 'historical', 'mid', or 'new'
    """
    if book < 238:
        return 'historical'
    elif book >= 238 and book < 3972:
        return 'mid'
    elif book >= 3972:
        return 'new'
    else:
        raise ValueError(f"Invalid book number: {book}")

# ============================================================================
# Stage Configuration
# ============================================================================

STAGE_CONFIGS = {
    'stage-0-test': {
        'name': 'Test Run',
        'description': 'Validate infrastructure with minimal documents',
        'limit': 20,
        'filters': {
            'priority': None,  # Any priority
            'book_ranges': [(1, 50), (238, 300)],  # Sample from each portal
        }
    },
    'stage-1-small': {
        'name': 'Small Scale',
        'description': 'Download 2,000 documents (Priority 1 & 2)',
        'limit': 2000,
        'filters': {
            'priority': [1, 2],
            'book_ranges': [(1, 50), (238, 300)],
        }
    },
    'stage-2-medium': {
        'name': 'Medium Scale',
        'description': 'Download 50,000 documents (All Priority 1 & 2, sample of 3)',
        'limit': 50000,
        'filters': {
            'priority': [1, 2],  # Will add Priority 3 sample separately
            'book_ranges': None,  # All books
        }
    },
    'stage-3-large': {
        'name': 'Large Scale',
        'description': 'Download remaining MID portal documents',
        'limit': None,  # No limit - process all
        'filters': {
            'priority': [3],
            'book_ranges': [(238, 3971)],
        }
    },
    'stage-4-retry': {
        'name': 'Retry Failed',
        'description': 'Retry previously failed downloads',
        'limit': None,
        'filters': {
            'status': 'failed',
            'max_attempts': 5,
        }
    }
}

# ============================================================================
# Download Queue Manager
# ============================================================================

class DownloadQueueManager:
    """
    Manages document download queue from index database.

    Handles fetching documents, status tracking, checkpoints, and statistics.
    """

    def __init__(self, conn, stage: str = 'stage-1-small', batch_size: int = 100):
        """
        Initialize queue manager.

        Args:
            conn: Database connection
            stage: Stage identifier (e.g., 'stage-1-small')
            batch_size: Number of documents to fetch per batch
        """
        self.conn = conn
        self.stage = stage
        self.batch_size = batch_size

        if stage not in STAGE_CONFIGS:
            raise ValueError(f"Unknown stage: {stage}. Valid stages: {list(STAGE_CONFIGS.keys())}")

        self.config = STAGE_CONFIGS[stage]
        self.last_fetched_id = None

        logger.info(f"Initialized queue manager for {self.config['name']}")

    def fetch_next_batch(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Fetch next batch of documents to download.

        Args:
            limit: Override batch size (optional)

        Returns:
            List of document records as dictionaries
        """
        limit = limit or self.batch_size
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        # Build WHERE clause based on stage configuration
        where_clauses = ["download_status = 'pending'"]
        params = []

        # Priority filter
        if self.config['filters'].get('priority'):
            priorities = self.config['filters']['priority']
            where_clauses.append(f"download_priority IN ({','.join(['%s'] * len(priorities))})")
            params.extend(priorities)

        # Book range filter
        if self.config['filters'].get('book_ranges'):
            book_conditions = []
            for min_book, max_book in self.config['filters']['book_ranges']:
                book_conditions.append("(book >= %s AND book < %s)")
                params.extend([min_book, max_book])
            where_clauses.append(f"({' OR '.join(book_conditions)})")

        # Resume from last checkpoint
        if self.last_fetched_id:
            where_clauses.append("id > %s")
            params.append(self.last_fetched_id)

        # Stage limit
        if self.config['limit']:
            # Check how many already processed in this stage
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM index_documents
                WHERE download_status IN ('completed', 'in_progress')
                  AND updated_at > (CURRENT_TIMESTAMP - INTERVAL '7 days')
            """)
            processed = cursor.fetchone()['count']

            if processed >= self.config['limit']:
                logger.info(f"Stage limit reached: {processed}/{self.config['limit']}")
                cursor.close()
                return []

        # Build query
        where_clause = " AND ".join(where_clauses)
        query = f"""
            SELECT
                id, source, book, page,
                instrument_number,
                instrument_type_parsed, document_type,
                download_priority, download_attempts,
                file_date, grantor_party, grantee_party
            FROM index_documents
            WHERE {where_clause}
            ORDER BY download_priority, book, page
            LIMIT %s
        """
        params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        if results:
            self.last_fetched_id = results[-1]['id']
            logger.info(f"Fetched {len(results)} documents (last ID: {self.last_fetched_id})")
        else:
            logger.info("No more documents in queue")

        cursor.close()
        return [dict(row) for row in results]

    def mark_in_progress(self, doc_id: int) -> bool:
        """
        Mark document as in_progress.

        Args:
            doc_id: Document ID

        Returns:
            True if successful
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                UPDATE index_documents
                SET download_status = 'in_progress',
                    download_attempts = download_attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (doc_id,))

            self.conn.commit()
            return True

        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error marking doc {doc_id} as in_progress: {e}")
            return False
        finally:
            cursor.close()

    def mark_completed(self, doc_id: int, gcs_path: str, file_size_bytes: int = None,
                      checksum: str = None, actual_book: int = None, actual_page: int = None,
                      book_page_mismatch: bool = False) -> bool:
        """
        Mark document as successfully downloaded.

        Args:
            doc_id: Document ID
            gcs_path: Path to file in Google Cloud Storage
            file_size_bytes: File size in bytes (optional)
            checksum: File checksum (optional)
            actual_book: Actual book number from document (optional)
            actual_page: Actual page number from document (optional)
            book_page_mismatch: True if book/page differs from index (optional)

        Returns:
            True if successful
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                UPDATE index_documents
                SET download_status = 'completed',
                    downloaded_at = CURRENT_TIMESTAMP,
                    gcs_path = %s,
                    actual_book = %s,
                    actual_page = %s,
                    book_page_mismatch = %s,
                    download_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (gcs_path, actual_book, actual_page, book_page_mismatch, doc_id))

            self.conn.commit()
            return True

        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error marking doc {doc_id} as completed: {e}")
            return False
        finally:
            cursor.close()

    def mark_failed(self, doc_id: int, error_message: str, retry: bool = True) -> bool:
        """
        Mark document download as failed.

        Args:
            doc_id: Document ID
            error_message: Error description
            retry: If True, set status to 'pending' for retry; else 'failed'

        Returns:
            True if successful
        """
        cursor = self.conn.cursor()

        # Determine if should retry based on attempt count
        cursor.execute("SELECT download_attempts FROM index_documents WHERE id = %s", (doc_id,))
        row = cursor.fetchone()

        if not row:
            cursor.close()
            return False

        attempts = row[0]
        max_attempts = 5

        # Set status based on retry logic
        if retry and attempts < max_attempts:
            status = 'pending'  # Will retry
            logger.info(f"Doc {doc_id} failed (attempt {attempts}/{max_attempts}), will retry")
        else:
            status = 'failed'  # Permanent failure
            logger.warning(f"Doc {doc_id} permanently failed after {attempts} attempts")

        try:
            cursor.execute("""
                UPDATE index_documents
                SET download_status = %s,
                    download_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (status, error_message[:500], doc_id))  # Truncate error message

            self.conn.commit()
            return True

        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error marking doc {doc_id} as failed: {e}")
            return False
        finally:
            cursor.close()

    def mark_skipped(self, doc_id: int, reason: str) -> bool:
        """
        Mark document as skipped (e.g., already exists, invalid data).

        Args:
            doc_id: Document ID
            reason: Skip reason

        Returns:
            True if successful
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                UPDATE index_documents
                SET download_status = 'skipped',
                    download_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (reason[:500], doc_id))

            self.conn.commit()
            return True

        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error marking doc {doc_id} as skipped: {e}")
            return False
        finally:
            cursor.close()

    def get_queue_statistics(self) -> Dict:
        """
        Get current queue statistics for this stage.

        Returns:
            Dictionary with queue stats
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        stats = {}

        # Overall counts by status
        cursor.execute("""
            SELECT download_status, COUNT(*) as count
            FROM index_documents
            GROUP BY download_status
        """)
        stats['by_status'] = {row['download_status']: row['count'] for row in cursor.fetchall()}

        # By priority for pending
        cursor.execute("""
            SELECT download_priority, COUNT(*) as count
            FROM index_documents
            WHERE download_status = 'pending'
            GROUP BY download_priority
            ORDER BY download_priority
        """)
        stats['pending_by_priority'] = {row['download_priority']: row['count'] for row in cursor.fetchall()}

        # By portal for pending
        cursor.execute("""
            SELECT
                CASE
                    WHEN book < 238 THEN 'historical'
                    WHEN book >= 238 AND book < 3972 THEN 'mid'
                    ELSE 'new'
                END as portal,
                COUNT(*) as count
            FROM index_documents
            WHERE download_status = 'pending'
            GROUP BY portal
        """)
        stats['pending_by_portal'] = {row['portal']: row['count'] for row in cursor.fetchall()}

        # Recent activity (last hour)
        cursor.execute("""
            SELECT
                download_status,
                COUNT(*) as count
            FROM index_documents
            WHERE updated_at > (CURRENT_TIMESTAMP - INTERVAL '1 hour')
            GROUP BY download_status
        """)
        stats['last_hour'] = {row['download_status']: row['count'] for row in cursor.fetchall()}

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
            LIMIT 10
        """)
        stats['top_errors'] = [{'error': row['download_error'], 'count': row['count']} for row in cursor.fetchall()]

        # Book/page mismatch statistics
        cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE book_page_mismatch = TRUE) as mismatch_count,
                COUNT(*) FILTER (WHERE book_page_mismatch = FALSE) as match_count,
                COUNT(*) as total_validated
            FROM index_documents
            WHERE download_status = 'completed'
              AND actual_book IS NOT NULL
        """)
        mismatch_data = cursor.fetchone()
        stats['validation'] = {
            'total_validated': mismatch_data['total_validated'],
            'mismatches': mismatch_data['mismatch_count'],
            'matches': mismatch_data['match_count'],
            'mismatch_rate': (mismatch_data['mismatch_count'] / mismatch_data['total_validated'] * 100)
                if mismatch_data['total_validated'] > 0 else 0
        }

        cursor.close()
        return stats

    def save_checkpoint(self) -> Dict:
        """
        Save current progress as checkpoint.

        Returns:
            Checkpoint data
        """
        checkpoint = {
            'stage': self.stage,
            'timestamp': datetime.now().isoformat(),
            'last_fetched_id': self.last_fetched_id,
            'statistics': self.get_queue_statistics()
        }

        logger.info(f"Checkpoint saved: ID={self.last_fetched_id}")
        return checkpoint

    def load_checkpoint(self, checkpoint: Dict):
        """
        Resume from checkpoint.

        Args:
            checkpoint: Checkpoint data from save_checkpoint()
        """
        if checkpoint['stage'] != self.stage:
            logger.warning(f"Checkpoint stage mismatch: {checkpoint['stage']} != {self.stage}")

        self.last_fetched_id = checkpoint.get('last_fetched_id')
        logger.info(f"Resumed from checkpoint: ID={self.last_fetched_id}")

    def reset_in_progress_records(self) -> int:
        """
        Reset any records stuck in 'in_progress' status back to 'pending'.
        Useful for crash recovery.

        Returns:
            Number of records reset
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                UPDATE index_documents
                SET download_status = 'pending',
                    updated_at = CURRENT_TIMESTAMP
                WHERE download_status = 'in_progress'
                  AND updated_at < (CURRENT_TIMESTAMP - INTERVAL '30 minutes')
            """)

            count = cursor.rowcount
            self.conn.commit()

            if count > 0:
                logger.info(f"Reset {count} stale 'in_progress' records to 'pending'")

            return count

        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error resetting in_progress records: {e}")
            return 0
        finally:
            cursor.close()

    def estimate_completion(self) -> Dict:
        """
        Estimate time to completion based on recent throughput.

        Returns:
            Dictionary with estimates
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        # Get pending count
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM index_documents
            WHERE download_status = 'pending'
        """)
        pending = cursor.fetchone()['count']

        # Get throughput (last hour)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM index_documents
            WHERE download_status = 'completed'
              AND downloaded_at > (CURRENT_TIMESTAMP - INTERVAL '1 hour')
        """)
        last_hour = cursor.fetchone()['count']

        # Calculate estimates
        estimates = {
            'pending_documents': pending,
            'completed_last_hour': last_hour,
            'documents_per_hour': last_hour if last_hour > 0 else None,
            'estimated_hours_remaining': pending / last_hour if last_hour > 0 else None,
            'estimated_days_remaining': (pending / last_hour) / 24 if last_hour > 0 else None
        }

        cursor.close()
        return estimates
