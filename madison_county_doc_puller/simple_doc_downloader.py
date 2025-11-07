#!/usr/bin/env python3
"""
Madison County Document Downloader - Simplified Requests-Based Version

Downloads documents using instrument numbers (instead of book/page) via HTTP requests.
Validates book/page from HTML response and handles any discrepancies.

Key improvements over Selenium version:
- 10-20x faster (no browser overhead)
- More reliable (no browser automation issues)
- Uses instrument numbers (avoids padded page number issues)
- Validates book/page from response
- Simpler code and dependencies

Usage:
    from simple_doc_downloader import MadisonCountyDownloader

    downloader = MadisonCountyDownloader()
    result = downloader.download_by_instrument(62379)
"""

import os
import re
import time
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class DocumentMetadata:
    """Metadata extracted from document lookup response."""
    instrument_number: int
    book: int
    page: int
    grantor: str
    grantee: str
    doc_type: str
    doc_nature: str
    date_recorded: str
    image_id: Optional[str]  # For PDF download
    subdivision_code: Optional[str] = None
    lot: Optional[str] = None
    section: Optional[str] = None
    township: Optional[str] = None
    range: Optional[str] = None

@dataclass
class DownloadResult:
    """Result of document download attempt."""
    success: bool
    instrument_number: int
    expected_book: Optional[int]
    expected_page: Optional[int]
    actual_book: Optional[int]
    actual_page: Optional[int]
    book_page_mismatch: bool
    local_path: Optional[str]
    error: Optional[str]
    metadata: Optional[DocumentMetadata]

# ============================================================================
# Madison County Document Downloader
# ============================================================================

class MadisonCountyDownloader:
    """
    Simplified document downloader using requests instead of Selenium.
    Downloads by instrument number and validates book/page from response.
    """

    BASE_URL = "https://tools.madison-co.net"
    LOOKUP_URL = f"{BASE_URL}/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
    PDF_URL = f"{BASE_URL}/elected-offices/chancery-clerk/court-house-search/pdf-records.php"

    def __init__(self, download_dir: str = "./downloads", timeout: int = 30):
        """
        Initialize downloader.

        Args:
            download_dir: Directory to save downloaded PDFs
            timeout: Request timeout in seconds
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True, parents=True)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def download_by_instrument(
        self,
        instrument_number: int,
        expected_book: Optional[int] = None,
        expected_page: Optional[int] = None
    ) -> DownloadResult:
        """
        Download document by instrument number.

        Args:
            instrument_number: Instrument number to download
            expected_book: Expected book number (for validation)
            expected_page: Expected page number (for validation)

        Returns:
            DownloadResult with download status and metadata
        """
        logger.info(f"Downloading instrument {instrument_number}")

        try:
            # Step 1: Query by instrument number
            metadata = self._fetch_document_metadata(instrument_number)

            if not metadata:
                return DownloadResult(
                    success=False,
                    instrument_number=instrument_number,
                    expected_book=expected_book,
                    expected_page=expected_page,
                    actual_book=None,
                    actual_page=None,
                    book_page_mismatch=False,
                    local_path=None,
                    error="Document not found or no metadata returned",
                    metadata=None
                )

            # Step 2: Check for book/page mismatch
            book_page_mismatch = False
            if expected_book and expected_page:
                if metadata.book != expected_book or metadata.page != expected_page:
                    book_page_mismatch = True
                    logger.warning(
                        f"Book/page mismatch for instrument {instrument_number}: "
                        f"Expected {expected_book}/{expected_page}, "
                        f"Got {metadata.book}/{metadata.page}"
                    )

            # Step 3: Download PDF if image_id available
            local_path = None
            if metadata.image_id:
                local_path = self._download_pdf(metadata)
            else:
                return DownloadResult(
                    success=False,
                    instrument_number=instrument_number,
                    expected_book=expected_book,
                    expected_page=expected_page,
                    actual_book=metadata.book,
                    actual_page=metadata.page,
                    book_page_mismatch=book_page_mismatch,
                    local_path=None,
                    error="No image_id found in response (no PDF available)",
                    metadata=metadata
                )

            return DownloadResult(
                success=True,
                instrument_number=instrument_number,
                expected_book=expected_book,
                expected_page=expected_page,
                actual_book=metadata.book,
                actual_page=metadata.page,
                book_page_mismatch=book_page_mismatch,
                local_path=str(local_path),
                error=None,
                metadata=metadata
            )

        except requests.exceptions.Timeout:
            return DownloadResult(
                success=False,
                instrument_number=instrument_number,
                expected_book=expected_book,
                expected_page=expected_page,
                actual_book=None,
                actual_page=None,
                book_page_mismatch=False,
                local_path=None,
                error=f"Request timeout after {self.timeout}s",
                metadata=None
            )
        except requests.exceptions.RequestException as e:
            return DownloadResult(
                success=False,
                instrument_number=instrument_number,
                expected_book=expected_book,
                expected_page=expected_page,
                actual_book=None,
                actual_page=None,
                book_page_mismatch=False,
                local_path=None,
                error=f"Request error: {str(e)}",
                metadata=None
            )
        except Exception as e:
            logger.error(f"Unexpected error downloading instrument {instrument_number}: {e}", exc_info=True)
            return DownloadResult(
                success=False,
                instrument_number=instrument_number,
                expected_book=expected_book,
                expected_page=expected_page,
                actual_book=None,
                actual_page=None,
                book_page_mismatch=False,
                local_path=None,
                error=f"Unexpected error: {str(e)}",
                metadata=None
            )

    def download_by_book_page(
        self,
        book: int,
        page: int,
        doc_type: str = ""
    ) -> DownloadResult:
        """
        Download document by book and page (legacy method).
        Note: Using instrument number is preferred for reliability.

        Args:
            book: Book number
            page: Page number
            doc_type: Document type code (optional)

        Returns:
            DownloadResult with download status
        """
        logger.info(f"Downloading book {book}, page {page}")

        params = {
            "grantor": "",
            "doc_type": doc_type,
            "book": str(book),
            "bpage": str(page),
            "month": "", "day": "", "year": "",
            "thru_month": "", "thru_day": "", "thru_year": "",
            "section": "", "township": "", "range": "",
            "code": "", "lot": "",
            "iyear": "", "instrument": "",
            "do_search": "Submit Query"
        }

        try:
            response = self.session.get(
                self.LOOKUP_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            # Check if it's a direct PDF response
            content_type = response.headers.get('Content-Type', '').lower()

            if 'pdf' in content_type or response.content.startswith(b'%PDF-'):
                # Direct PDF download
                filename = f"{book:04d}-{page:04d}.pdf"
                file_path = self.download_dir / filename

                with open(file_path, 'wb') as f:
                    f.write(response.content)

                return DownloadResult(
                    success=True,
                    instrument_number=None,
                    expected_book=book,
                    expected_page=page,
                    actual_book=book,
                    actual_page=page,
                    book_page_mismatch=False,
                    local_path=str(file_path),
                    error=None,
                    metadata=None
                )
            else:
                # HTML response - need to parse and extract PDF link
                metadata = self._parse_html_response(response.text)

                if metadata and metadata.image_id:
                    local_path = self._download_pdf(metadata)
                    return DownloadResult(
                        success=True,
                        instrument_number=metadata.instrument_number,
                        expected_book=book,
                        expected_page=page,
                        actual_book=metadata.book,
                        actual_page=metadata.page,
                        book_page_mismatch=(metadata.book != book or metadata.page != page),
                        local_path=str(local_path),
                        error=None,
                        metadata=metadata
                    )
                else:
                    return DownloadResult(
                        success=False,
                        instrument_number=None,
                        expected_book=book,
                        expected_page=page,
                        actual_book=None,
                        actual_page=None,
                        book_page_mismatch=False,
                        local_path=None,
                        error="No PDF found in HTML response",
                        metadata=metadata
                    )

        except Exception as e:
            return DownloadResult(
                success=False,
                instrument_number=None,
                expected_book=book,
                expected_page=page,
                actual_book=None,
                actual_page=None,
                book_page_mismatch=False,
                local_path=None,
                error=str(e),
                metadata=None
            )

    def _fetch_document_metadata(self, instrument_number: int) -> Optional[DocumentMetadata]:
        """
        Fetch document metadata by instrument number.

        Args:
            instrument_number: Instrument number to query

        Returns:
            DocumentMetadata if found, None otherwise
        """
        params = {
            "grantor": "",
            "doc_type": "",
            "book": "",
            "bpage": "",
            "month": "", "day": "", "year": "",
            "thru_month": "", "thru_day": "", "thru_year": "",
            "section": "", "township": "", "range": "",
            "code": "", "lot": "",
            "iyear": "",
            "instrument": str(instrument_number),
            "do_search": "Submit Query"
        }

        response = self.session.get(
            self.LOOKUP_URL,
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()

        return self._parse_html_response(response.text, instrument_number)

    def _parse_html_response(
        self,
        html: str,
        instrument_number: Optional[int] = None
    ) -> Optional[DocumentMetadata]:
        """
        Parse HTML response to extract document metadata.

        Args:
            html: HTML response text
            instrument_number: Known instrument number (optional)

        Returns:
            DocumentMetadata if parsed successfully, None otherwise
        """
        soup = BeautifulSoup(html, 'html.parser')

        try:
            # Extract grantor/grantee from h2 tag
            h2 = soup.find('h2')
            if not h2:
                return None

            h2_text = h2.get_text()

            # Parse: "Grantor: <em>NAME<br />Grantee: <em>NAME"
            grantor_match = re.search(r'Grantor:\s*(.+?)(?:Grantee:|$)', h2_text, re.DOTALL)
            grantee_match = re.search(r'Grantee:\s*(.+?)$', h2_text, re.DOTALL)

            grantor = grantor_match.group(1).strip() if grantor_match else ""
            grantee = grantee_match.group(1).strip() if grantee_match else ""

            # Extract nature (document type)
            nature_match = re.search(r'Nature:\s*<em>(.+?)</em>', html)
            doc_nature = nature_match.group(1).strip() if nature_match else ""

            # Extract subdivision code and lot
            subdivision_match = re.search(r'SubDivision Code:\s*<em>(.+?)</em>', html)
            lot_match = re.search(r'Lot:\s*<em>(.+?)</em>', html)

            subdivision_code = subdivision_match.group(1).strip() if subdivision_match else None
            lot = lot_match.group(1).strip() if lot_match else None

            # Extract from table
            table = soup.find('table')
            if not table:
                return None

            # Parse table cells
            cells = table.find_all('td')
            cell_texts = [cell.get_text().strip() for cell in cells]

            # Extract values
            doc_type = None
            book = None
            page = None
            section = None
            township = None
            range_val = None
            date_recorded = None

            for cell in cell_texts:
                if cell.startswith('Type:'):
                    doc_type = re.search(r'Type:\s*(.+)', cell)
                    doc_type = doc_type.group(1).strip() if doc_type else None
                elif cell.startswith('Book:'):
                    book_match = re.search(r'Book:\s*(\d+)', cell)
                    book = int(book_match.group(1)) if book_match else None
                elif cell.startswith('Page:'):
                    page_match = re.search(r'Page:\s*(\d+)', cell)
                    page = int(page_match.group(1)) if page_match else None
                elif cell.startswith('Section:'):
                    section_match = re.search(r'Section:\s*(.+)', cell)
                    section = section_match.group(1).strip() if section_match else None
                elif cell.startswith('Township:'):
                    township_match = re.search(r'Township:\s*(.+)', cell)
                    township = township_match.group(1).strip() if township_match else None
                elif cell.startswith('Range:'):
                    range_match = re.search(r'Range:\s*(.+)', cell)
                    range_val = range_match.group(1).strip() if range_match else None
                elif cell.startswith('Date'):
                    date_match = re.search(r'Date\s+Recorded:\s*(.+)', cell)
                    date_recorded = date_match.group(1).strip() if date_match else None

            # Extract PDF image_id from download link
            image_link = soup.find('a', href=re.compile(r'pdf-records\.php\?image='))
            image_id = None

            if image_link:
                href = image_link.get('href', '')
                image_match = re.search(r'image=(\d+)', href)
                image_id = image_match.group(1) if image_match else None

            if book and page:
                return DocumentMetadata(
                    instrument_number=instrument_number or 0,
                    book=book,
                    page=page,
                    grantor=grantor,
                    grantee=grantee,
                    doc_type=doc_type or "",
                    doc_nature=doc_nature,
                    date_recorded=date_recorded or "",
                    image_id=image_id,
                    subdivision_code=subdivision_code,
                    lot=lot,
                    section=section,
                    township=township,
                    range=range_val
                )

            return None

        except Exception as e:
            logger.error(f"Error parsing HTML response: {e}", exc_info=True)
            return None

    def _download_pdf(self, metadata: DocumentMetadata) -> Optional[Path]:
        """
        Download PDF using image_id from metadata.

        Args:
            metadata: Document metadata with image_id

        Returns:
            Path to downloaded file, or None if failed
        """
        if not metadata.image_id:
            return None

        url = f"{self.PDF_URL}?image={metadata.image_id}"

        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()

        # Verify it's a PDF
        if not (response.headers.get('Content-Type', '').lower().startswith('application/pdf')
                or response.content.startswith(b'%PDF-')):
            logger.error(f"Response is not a PDF for image_id {metadata.image_id}")
            return None

        # Use actual book/page from metadata (validated)
        filename = f"{metadata.book:04d}-{metadata.page:04d}.pdf"
        file_path = self.download_dir / filename

        with open(file_path, 'wb') as f:
            f.write(response.content)

        logger.info(f"Downloaded PDF to {file_path}")
        return file_path

    def close(self):
        """Close the requests session."""
        self.session.close()


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Download Madison County documents')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--instrument', type=int, help='Instrument number to download')
    group.add_argument('--book-page', nargs=2, metavar=('BOOK', 'PAGE'),
                      help='Book and page numbers to download')

    parser.add_argument('--download-dir', default='./downloads',
                       help='Download directory (default: ./downloads)')
    parser.add_argument('--expected-book', type=int, help='Expected book number (for validation)')
    parser.add_argument('--expected-page', type=int, help='Expected page number (for validation)')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    downloader = MadisonCountyDownloader(download_dir=args.download_dir)

    try:
        if args.instrument:
            result = downloader.download_by_instrument(
                args.instrument,
                args.expected_book,
                args.expected_page
            )
        else:
            book, page = map(int, args.book_page)
            result = downloader.download_by_book_page(book, page)

        print("\n" + "="*80)
        print("DOWNLOAD RESULT")
        print("="*80)
        print(f"Success: {result.success}")
        print(f"Instrument: {result.instrument_number}")
        print(f"Expected: Book {result.expected_book}, Page {result.expected_page}")
        print(f"Actual: Book {result.actual_book}, Page {result.actual_page}")
        print(f"Mismatch: {result.book_page_mismatch}")
        print(f"Local path: {result.local_path}")
        if result.error:
            print(f"Error: {result.error}")
        if result.metadata:
            print(f"\nMetadata:")
            print(f"  Grantor: {result.metadata.grantor}")
            print(f"  Grantee: {result.metadata.grantee}")
            print(f"  Nature: {result.metadata.doc_nature}")
            print(f"  Date: {result.metadata.date_recorded}")
        print("="*80)

    finally:
        downloader.close()
