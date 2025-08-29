"""Scraper for MID portal (Books 238-3971)."""

import re
import logging
from pathlib import Path
from typing import Tuple, List
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from pypdf import PdfMerger

from .base_scraper import BaseScraper, ScraperError
from ..config.document_types import DOCUMENT_TYPE_CODES

logger = logging.getLogger(__name__)

class MIDScraper(BaseScraper):
    """Scraper for MID portal (Books 238-3971)."""
    
    BASE_URL = "https://tools.madison-co.net"
    SEARCH_URL = f"{BASE_URL}/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
    
    def download_document(self, book: str, page: str, doc_type: str = None) -> Tuple[Path, str]:
        """
        Download document from MID portal.
        
        For books >= 238, the portal returns HTML with links to multiple PDF images
        that need to be downloaded and concatenated.
        
        Args:
            book: Book number (238-3971)
            page: Page number
            doc_type: Document type code (e.g., '01' for DEED)
            
        Returns:
            Tuple of (local_file_path, checksum)
            
        Raises:
            ScraperError: If download fails
        """
        logger.info(f"Downloading from MID portal: Book {book}, Page {page}, Type {doc_type}")
        
        # Validate book is in MID range
        if not self._is_mid_book(book):
            raise ScraperError(f"Book {book} is not in MID range (238-3971)")
        
        # Build request parameters
        params = {
            "grantor": "",
            "doc_type": doc_type or "01",  # Default to DEED if not specified
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
            # Get the search results page
            response = self.session.get(
                self.SEARCH_URL,
                params=params,
                timeout=self.settings.request_timeout
            )
            response.raise_for_status()
            
            # Check if direct PDF (shouldn't happen for MID range, but handle it)
            content_type = response.headers.get('Content-Type', '').lower()
            if 'pdf' in content_type or response.content.startswith(b'%PDF-'):
                logger.info("Received direct PDF response")
                return self._save_file(response.content, book, page)
            
            # Parse HTML for download links
            soup = BeautifulSoup(response.text, 'html.parser')
            download_links = self._extract_download_links(soup)
            
            if not download_links:
                # Check for "no results" message
                if "No records found" in response.text or "No documents found" in response.text:
                    raise ScraperError(f"No documents found for Book {book}, Page {page}")
                else:
                    raise ScraperError("No download links found in results page")
            
            logger.info(f"Found {len(download_links)} PDF pages to download")
            
            # Download all PDF pages
            pdf_contents = []
            for idx, link in enumerate(download_links, 1):
                logger.debug(f"Downloading page {idx}/{len(download_links)}")
                pdf_content = self._download_pdf_image(link)
                pdf_contents.append(pdf_content)
            
            # Concatenate PDFs if multiple pages
            if len(pdf_contents) == 1:
                final_content = pdf_contents[0]
            else:
                final_content = self._concatenate_pdfs(pdf_contents)
            
            # Save to disk
            file_path, checksum = self._save_file(final_content, book, page)
            
            # Validate PDF
            if not self.validate_pdf(file_path):
                raise ScraperError("Downloaded file is not a valid PDF")
            
            return (file_path, checksum)
            
        except ScraperError:
            raise
        except Exception as e:
            raise ScraperError(f"Failed to download document: {e}")
    
    def _is_mid_book(self, book: str) -> bool:
        """
        Check if book is in MID range (238-3971).
        
        Args:
            book: Book identifier
            
        Returns:
            True if in MID range, False otherwise
        """
        try:
            book_num = int(book)
            return 238 <= book_num <= 3971
        except (ValueError, TypeError):
            return False
    
    def _extract_download_links(self, soup: BeautifulSoup) -> List[str]:
        """
        Extract PDF download links from HTML results page.
        
        Args:
            soup: BeautifulSoup parsed HTML
            
        Returns:
            List of download URLs
        """
        links = []
        
        # Look for download links with pattern "Download Image X"
        download_links = soup.find_all('a', string=re.compile(r'Download Image \d+'))
        
        for link in download_links:
            href = link.get('href', '')
            if href:
                # Make URL absolute if relative
                if not href.startswith('http'):
                    href = self.BASE_URL + href if href.startswith('/') else self.BASE_URL + '/' + href
                links.append(href)
        
        return links
    
    def _download_pdf_image(self, url: str) -> bytes:
        """
        Download a single PDF image.
        
        Args:
            url: URL to download
            
        Returns:
            PDF content as bytes
            
        Raises:
            ScraperError: If download fails or content is not PDF
        """
        try:
            response = self.session.get(url, timeout=self.settings.request_timeout)
            response.raise_for_status()
            
            # Verify it's a PDF
            content_type = response.headers.get('Content-Type', '').lower()
            if 'pdf' not in content_type and not response.content.startswith(b'%PDF-'):
                raise ScraperError(f"Downloaded content is not a PDF from {url}")
            
            return response.content
            
        except requests.exceptions.RequestException as e:
            raise ScraperError(f"Failed to download PDF from {url}: {e}")
    
    def _concatenate_pdfs(self, pdf_contents: List[bytes]) -> bytes:
        """
        Concatenate multiple PDF pages into a single PDF.
        
        Args:
            pdf_contents: List of PDF content bytes
            
        Returns:
            Combined PDF as bytes
            
        Raises:
            ScraperError: If concatenation fails
        """
        try:
            merger = PdfMerger()
            
            for pdf_bytes in pdf_contents:
                merger.append(BytesIO(pdf_bytes))
            
            # Write to bytes
            output = BytesIO()
            merger.write(output)
            merger.close()
            
            return output.getvalue()
            
        except Exception as e:
            raise ScraperError(f"Failed to concatenate PDFs: {e}")