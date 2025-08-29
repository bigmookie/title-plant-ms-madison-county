"""Scraper for Historical portal (Books < 238)."""

import logging
from pathlib import Path
from typing import Tuple

from .base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

class HistoricalScraper(BaseScraper):
    """Scraper for Historical Books portal."""
    
    BASE_URL = "https://tools.madison-co.net/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
    
    def download_document(self, book: str, page: str, doc_type: str = None) -> Tuple[Path, str]:
        """
        Download document from Historical portal.
        
        Args:
            book: Book identifier (number < 238 or letter)
            page: Page number
            doc_type: Document type code (not used for historical)
            
        Returns:
            Tuple of (local_file_path, checksum)
            
        Raises:
            ScraperError: If download fails
        """
        logger.info(f"Downloading from Historical portal: Book {book}, Page {page}")
        
        # Validate book is in historical range
        if not self._is_historical_book(book):
            raise ScraperError(f"Book {book} is not in historical range (< 238 or letters)")
        
        # Build request parameters
        params = {
            "grantor": "",
            "doc_type": "",
            "book": str(book),
            "bpage": str(page),
            "month": "", 
            "day": "", 
            "year": "",
            "thru_month": "", 
            "thru_day": "", 
            "thru_year": "",
            "section": "", 
            "township": "", 
            "range": "",
            "code": "", 
            "lot": "",
            "iyear": "", 
            "instrument": "",
            "do_search": "Submit Query"
        }
        
        try:
            # Download the document
            content = self._download_file(self.BASE_URL, params=params)
            
            # Save to disk
            file_path, checksum = self._save_file(content, book, page)
            
            # Validate PDF
            if not self.validate_pdf(file_path):
                raise ScraperError("Downloaded file is not a valid PDF")
            
            return (file_path, checksum)
            
        except ScraperError:
            raise
        except Exception as e:
            raise ScraperError(f"Failed to download document: {e}")
    
    def _is_historical_book(self, book: str) -> bool:
        """
        Check if book is in historical range.
        
        Args:
            book: Book identifier
            
        Returns:
            True if historical, False otherwise
        """
        # Letters are always historical
        if isinstance(book, str) and book.isalpha():
            return True
        
        # Check numeric range
        try:
            book_num = int(book)
            return book_num < 238
        except (ValueError, TypeError):
            return False