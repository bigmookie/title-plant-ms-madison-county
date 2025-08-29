"""Base scraper class with retry logic and error handling."""

import time
import logging
import hashlib
from pathlib import Path
from typing import Optional, Tuple, Any
from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from ..config.settings import Settings

logger = logging.getLogger(__name__)

class ScraperError(Exception):
    """Custom exception for scraper errors."""
    pass

class BaseScraper(ABC):
    """Base class for all document scrapers."""
    
    def __init__(self, settings: Settings):
        """
        Initialize base scraper.
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.session = self._create_session()
        self.download_dir = settings.temp_download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.settings.max_retries,
            backoff_factor=self.settings.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set default timeout
        session.timeout = self.settings.request_timeout
        
        return session
    
    @abstractmethod
    def download_document(self, book: str, page: str, doc_type: str = None) -> Tuple[Path, str]:
        """
        Download a document from the portal.
        
        Args:
            book: Book identifier
            page: Page number
            doc_type: Document type code (optional)
            
        Returns:
            Tuple of (local_file_path, checksum)
            
        Raises:
            ScraperError: If download fails
        """
        pass
    
    def download_with_retry(self, book: str, page: str, doc_type: str = None) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
        """
        Download document with exponential backoff retry.
        
        Args:
            book: Book identifier
            page: Page number
            doc_type: Document type code
            
        Returns:
            Tuple of (local_file_path, checksum, error_message)
        """
        last_error = None
        
        for attempt in range(self.settings.max_retries):
            try:
                # Add rate limiting delay
                if attempt > 0:
                    delay = self.settings.retry_delay * (2 ** attempt)
                    logger.info(f"Retry attempt {attempt + 1}, waiting {delay} seconds")
                    time.sleep(delay)
                else:
                    # Rate limit even on first attempt
                    time.sleep(self.settings.rate_limit_delay)
                
                # Attempt download
                file_path, checksum = self.download_document(book, page, doc_type)
                return (file_path, checksum, None)
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Download failed for Book {book}, Page {page}: {e}")
                
                if attempt == self.settings.max_retries - 1:
                    logger.error(f"All retry attempts failed for Book {book}, Page {page}")
                    return (None, None, last_error)
        
        return (None, None, last_error)
    
    def _download_file(self, url: str, params: dict = None, headers: dict = None) -> bytes:
        """
        Download file content from URL.
        
        Args:
            url: URL to download from
            params: Query parameters
            headers: Request headers
            
        Returns:
            File content as bytes
            
        Raises:
            ScraperError: If download fails
        """
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.settings.request_timeout
            )
            response.raise_for_status()
            
            # Check if response is PDF
            content_type = response.headers.get('Content-Type', '').lower()
            if 'pdf' not in content_type and not response.content.startswith(b'%PDF-'):
                raise ScraperError(f"Response is not a PDF (content-type: {content_type})")
            
            return response.content
            
        except requests.exceptions.RequestException as e:
            raise ScraperError(f"Request failed: {e}")
    
    def _save_file(self, content: bytes, book: str, page: str) -> Tuple[Path, str]:
        """
        Save file content to disk and calculate checksum.
        
        Args:
            content: File content
            book: Book identifier
            page: Page number
            
        Returns:
            Tuple of (file_path, checksum)
        """
        # Generate filename
        filename = f"{book}-{page}.pdf"
        file_path = self.download_dir / filename
        
        # Save file
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Calculate checksum
        checksum = hashlib.sha256(content).hexdigest()
        
        logger.info(f"Saved {filename} ({len(content)} bytes, checksum: {checksum[:8]}...)")
        
        return (file_path, checksum)
    
    def validate_pdf(self, file_path: Path) -> bool:
        """
        Validate that file is a valid PDF.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            True if valid PDF, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4)
                return header == b'%PDF'
        except Exception:
            return False
    
    def cleanup_temp_file(self, file_path: Path):
        """
        Remove temporary file.
        
        Args:
            file_path: Path to file to remove
        """
        try:
            if file_path and file_path.exists():
                file_path.unlink()
                logger.debug(f"Removed temporary file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to remove temporary file {file_path}: {e}")