"""Process index spreadsheets to create download queue."""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime

import pandas as pd

from ..config.document_types import DocumentTypeResolver

logger = logging.getLogger(__name__)

@dataclass
class DownloadQueueItem:
    """Represents a single document to download."""
    book: str
    page: str
    document_type: str
    document_code: str
    portal: str
    source_file: str
    instrument_number: Optional[str] = None
    file_date: Optional[str] = None
    grantor: Optional[str] = None
    grantee: Optional[str] = None
    description: Optional[str] = None
    num_pages: Optional[int] = None
    priority: int = 5  # 1-10, lower is higher priority
    status: str = 'pending'  # pending, downloading, completed, failed
    attempts: int = 0
    error_message: Optional[str] = None
    checksum: Optional[str] = None
    gcs_path: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DownloadQueueItem':
        """Create from dictionary."""
        return cls(**data)
    
    def get_filename(self) -> str:
        """Get standardized filename."""
        return f"{self.book}-{self.page}.pdf"
    
    def get_gcs_path(self, doc_category: str = None) -> str:
        """Get GCS path for this document."""
        if not doc_category:
            # Determine category from document type
            if 'DEED OF TRUST' in self.document_type:
                doc_category = 'deeds-of-trust'
            elif 'WILL' in self.document_type:
                doc_category = 'wills'
            elif 'CHANCERY' in self.document_type.upper():
                doc_category = 'chancery'
            else:
                doc_category = 'deeds'
        
        return f"documents/optimized-pdfs/{doc_category}/book-{self.book}/{self.get_filename()}"


class IndexProcessor:
    """Process index spreadsheets to build download queue."""
    
    def __init__(self, index_dir: Path, checkpoint_file: Optional[Path] = None):
        """
        Initialize index processor.
        
        Args:
            index_dir: Directory containing index spreadsheets
            checkpoint_file: Path to checkpoint file for resumable processing
        """
        self.index_dir = Path(index_dir)
        self.checkpoint_file = checkpoint_file
        self.type_resolver = DocumentTypeResolver()
        self.queue: List[DownloadQueueItem] = []
        self.processed_files: set = set()
        
        # Load checkpoint if exists
        if checkpoint_file and checkpoint_file.exists():
            self.load_checkpoint()
    
    def determine_portal(self, book: Any) -> str:
        """
        Determine which portal to use based on book number.
        
        Args:
            book: Book identifier (string or number)
            
        Returns:
            Portal identifier ('historical', 'mid', 'duprocess')
        """
        # Handle string book identifiers (letters)
        if isinstance(book, str) and book.isalpha():
            return 'historical'
        
        # Convert to integer for numeric comparison
        try:
            book_num = int(book)
            if book_num < 238:
                return 'historical'
            elif book_num <= 3971:
                return 'mid'
            else:
                return 'duprocess'
        except (ValueError, TypeError):
            # Default to historical for non-numeric books
            return 'historical'
    
    def process_excel_file(self, file_path: Path) -> List[DownloadQueueItem]:
        """
        Process a single Excel file to extract download items.
        
        Args:
            file_path: Path to Excel file
            
        Returns:
            List of download queue items
        """
        logger.info(f"Processing index file: {file_path}")
        items = []
        
        try:
            df = pd.read_excel(file_path)
            
            # Check for required columns
            required_cols = ['Book', 'Page']
            if not all(col in df.columns for col in required_cols):
                logger.warning(f"Missing required columns in {file_path}")
                return items
            
            # Process each row
            for idx, row in df.iterrows():
                book = row.get('Book')
                page = row.get('Page')
                
                # Skip invalid entries
                if pd.isna(book) or pd.isna(page):
                    continue
                
                # Convert floats to integers if needed
                if isinstance(book, float) and book.is_integer():
                    book = int(book)
                if isinstance(page, float) and page.is_integer():
                    page = int(page)
                
                # Determine portal
                portal = self.determine_portal(book)
                
                # Skip DuProcess portal (Phase 1 exclusion)
                if portal == 'duprocess':
                    continue
                
                # Process document type if available
                doc_info = {'matched_type': 'DEED', 'code': '01'}
                if 'InstrumentType' in df.columns and not pd.isna(row.get('InstrumentType')):
                    doc_info = self.type_resolver.process_instrument_type(row['InstrumentType'])
                
                # Create queue item
                item = DownloadQueueItem(
                    book=str(book),
                    page=str(page),
                    document_type=doc_info['matched_type'],
                    document_code=doc_info['code'],
                    portal=portal,
                    source_file=str(file_path.name),
                    instrument_number=str(row.get('Instrument #', '')) if 'Instrument #' in df.columns else None,
                    file_date=str(row.get('FileDate', '')) if 'FileDate' in df.columns else None,
                    grantor=str(row.get('Grantor Party', '')) if 'Grantor Party' in df.columns else None,
                    grantee=str(row.get('Grantee Party', '')) if 'Grantee Party' in df.columns else None,
                    description=str(row.get('Description', '')) if 'Description' in df.columns else None,
                    num_pages=int(row.get('Num Pages')) if 'Num Pages' in df.columns and not pd.isna(row.get('Num Pages')) else None,
                    priority=self.calculate_priority(doc_info['matched_type'], portal)
                )
                
                items.append(item)
            
            logger.info(f"Extracted {len(items)} items from {file_path}")
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
        
        return items
    
    def calculate_priority(self, doc_type: str, portal: str) -> int:
        """
        Calculate download priority.
        
        Lower number = higher priority
        Priority 1: Wills
        Priority 2: Historical deeds
        Priority 3: MID deeds
        Priority 5: Everything else
        """
        if 'WILL' in doc_type.upper():
            return 1
        elif portal == 'historical':
            return 2
        elif portal == 'mid' and 'DEED' in doc_type.upper():
            return 3
        else:
            return 5
    
    def process_all_indexes(self) -> List[DownloadQueueItem]:
        """
        Process all Excel files in index directory.
        
        Returns:
            Complete download queue sorted by priority
        """
        # Find all Excel files
        excel_files = list(self.index_dir.glob('*.xlsx')) + list(self.index_dir.glob('*.xls'))
        logger.info(f"Found {len(excel_files)} index files")
        
        # Process each file
        for file_path in excel_files:
            if str(file_path) not in self.processed_files:
                items = self.process_excel_file(file_path)
                self.queue.extend(items)
                self.processed_files.add(str(file_path))
        
        # Sort by priority (lower number = higher priority)
        self.queue.sort(key=lambda x: (x.priority, x.book, x.page))
        
        logger.info(f"Total queue size: {len(self.queue)} documents")
        return self.queue
    
    def save_queue(self, output_path: Path):
        """
        Save queue to JSON file.
        
        Args:
            output_path: Path to save queue
        """
        queue_data = [item.to_dict() for item in self.queue]
        
        with open(output_path, 'w') as f:
            json.dump({
                'created_at': datetime.now().isoformat(),
                'total_items': len(queue_data),
                'items': queue_data
            }, f, indent=2)
        
        logger.info(f"Saved queue to {output_path}")
    
    def load_queue(self, input_path: Path):
        """
        Load queue from JSON file.
        
        Args:
            input_path: Path to queue file
        """
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        self.queue = [DownloadQueueItem.from_dict(item) for item in data['items']]
        logger.info(f"Loaded {len(self.queue)} items from queue")
    
    def save_checkpoint(self):
        """Save processing checkpoint."""
        if not self.checkpoint_file:
            return
        
        checkpoint_data = {
            'processed_files': list(self.processed_files),
            'queue_size': len(self.queue),
            'timestamp': datetime.now().isoformat()
        }
        
        with open(self.checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)
    
    def load_checkpoint(self):
        """Load processing checkpoint."""
        if not self.checkpoint_file or not self.checkpoint_file.exists():
            return
        
        with open(self.checkpoint_file, 'r') as f:
            data = json.load(f)
        
        self.processed_files = set(data.get('processed_files', []))
        logger.info(f"Loaded checkpoint: {len(self.processed_files)} files processed")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get queue statistics."""
        stats = {
            'total_items': len(self.queue),
            'by_portal': {},
            'by_document_type': {},
            'by_status': {},
            'by_priority': {}
        }
        
        for item in self.queue:
            # By portal
            stats['by_portal'][item.portal] = stats['by_portal'].get(item.portal, 0) + 1
            
            # By document type
            stats['by_document_type'][item.document_type] = stats['by_document_type'].get(item.document_type, 0) + 1
            
            # By status
            stats['by_status'][item.status] = stats['by_status'].get(item.status, 0) + 1
            
            # By priority
            stats['by_priority'][item.priority] = stats['by_priority'].get(item.priority, 0) + 1
        
        return stats