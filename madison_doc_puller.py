#!/usr/bin/env python3
"""
Madison County, MS Document Puller with GCS Integration

This script downloads documents from:
1. Google Cloud Storage (GCS) bucket - if the image exists
2. Madison County land records portal - as a fallback

Usage:
    # Interactive mode - opens file dialog to select Excel or text file
    python madison_doc_puller.py

    # Command line mode - single document
    python madison_doc_puller.py --book 500 --page 100

    # Batch mode with Excel file
    python madison_doc_puller.py --excel docs.xlsx

    # Batch mode with text file
    python madison_doc_puller.py --txt docs.txt

    # Control number of parallel workers
    python madison_doc_puller.py --excel docs.xlsx --workers 4

    # Skip GCS check and go directly to web portal
    python madison_doc_puller.py --book 500 --page 100 --skip-gcs

    # Upload newly downloaded documents to GCS
    python madison_doc_puller.py --excel docs.xlsx --upload-to-gcs

Excel Spreadsheet Format:
    Column A: Book number
    Column B: Page number
    -OR-
    Column A: "Book/Page" format (e.g., "500/100" or "500-100")

Text File Format:
    [book]/[page] [book_type] or [book]-[page] [book_type]
    Book type defaults to "deed book" if not specified.
    Books < 238 are always "deed book".

Required packages:
    pip install requests beautifulsoup4 openpyxl python-dotenv google-cloud-storage
"""

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install with: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: 'beautifulsoup4' package is required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("Warning: 'python-dotenv' not installed. GCS features may not work.")
    load_dotenv = None


# =============================================================================
# Load Environment Variables Early
# =============================================================================

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

# Load .env from the script's directory
if load_dotenv:
    env_path = SCRIPT_DIR / '.env'
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Try current directory as fallback
        load_dotenv()


def convert_path_for_platform(path_str: str) -> str:
    """
    Convert path between WSL and Windows formats based on current platform.

    Args:
        path_str: Path string (may be WSL or Windows format)

    Returns:
        Path string in the correct format for the current platform
    """
    if not path_str:
        return path_str

    path_str = path_str.strip('"').strip("'")

    # Check if we're on Windows (not WSL)
    is_windows = sys.platform == 'win32'

    if is_windows:
        # Convert WSL path to Windows path
        # /mnt/c/Users/... -> C:\Users\...
        if path_str.startswith('/mnt/'):
            parts = path_str.split('/')
            if len(parts) >= 3:
                drive_letter = parts[2].upper()
                rest_of_path = '/'.join(parts[3:])
                path_str = f"{drive_letter}:/{rest_of_path}"
    else:
        # Convert Windows path to WSL path
        # C:\Users\... -> /mnt/c/Users/...
        if len(path_str) >= 2 and path_str[1] == ':':
            drive_letter = path_str[0].lower()
            rest_of_path = path_str[2:].replace('\\', '/')
            path_str = f"/mnt/{drive_letter}{rest_of_path}"

    return path_str


# =============================================================================
# Constants and Configuration
# =============================================================================

BASE_URL = "https://tools.madison-co.net"
LOOKUP_URL = f"{BASE_URL}/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
PDF_URL = f"{BASE_URL}/elected-offices/chancery-clerk/court-house-search/pdf-records.php"

# Rate limiting
DEFAULT_DELAY = 0.5  # Seconds between requests

# GCS Configuration
DEFAULT_BUCKET_NAME = "madison-county-title-plant"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DocumentMetadata:
    """Metadata extracted from document lookup response."""
    book: int
    page: int
    grantor: str
    grantee: str
    doc_type: str
    doc_nature: str
    date_recorded: str
    image_id: Optional[str]
    instrument_number: Optional[int] = None


@dataclass
class DownloadResult:
    """Result of document download attempt."""
    success: bool
    book: int
    page: int
    actual_book: Optional[int]
    actual_page: Optional[int]
    local_path: Optional[str]
    error: Optional[str]
    metadata: Optional[DocumentMetadata]
    is_new_download: bool = True
    source: str = "web"  # "gcs" or "web"


# =============================================================================
# GCS Helper Functions
# =============================================================================

def get_folder_prefix(book: int) -> str:
    """
    Determine the folder prefix based on book number.

    Args:
        book: Book number

    Returns:
        Folder prefix string (historical, mid-early, or mid-recent)
    """
    if book < 238:
        return "historical"
    elif book < 1000:
        return "mid-early"
    else:
        return "mid-recent"


def normalize_doc_type(doc_type: str) -> str:
    """
    Normalize document type for GCS path.

    Args:
        doc_type: Raw document type string

    Returns:
        Normalized document type (lowercase, hyphens instead of spaces/underscores)
    """
    if not doc_type:
        return "unknown"

    # Convert to lowercase and replace spaces/underscores with hyphens
    normalized = doc_type.lower().strip()
    normalized = re.sub(r'[\s_]+', '-', normalized)
    # Remove any non-alphanumeric characters except hyphens
    normalized = re.sub(r'[^a-z0-9-]', '', normalized)
    # Remove consecutive hyphens
    normalized = re.sub(r'-+', '-', normalized)
    # Strip leading/trailing hyphens
    normalized = normalized.strip('-')

    return normalized if normalized else "unknown"


def build_gcs_path(book: int, page: int, doc_type: str = "deed") -> str:
    """
    Build the GCS path for a document.

    Path format: documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf

    Args:
        book: Book number
        page: Page number
        doc_type: Document type (default: "deed")

    Returns:
        GCS path string
    """
    folder_prefix = get_folder_prefix(book)
    normalized_type = normalize_doc_type(doc_type)
    filename = f"{book:04d}-{page:04d}.pdf"

    return f"documents/{folder_prefix}/{normalized_type}/{filename}"


def try_gcs_download(
    book: int,
    page: int,
    doc_type: str,
    output_dir: Path,
    bucket_name: str = DEFAULT_BUCKET_NAME,
    credentials_path: Optional[str] = None
) -> Optional[Path]:
    """
    Attempt to download document from GCS.

    Args:
        book: Book number
        page: Page number
        doc_type: Document type
        output_dir: Local output directory
        bucket_name: GCS bucket name
        credentials_path: Path to service account credentials

    Returns:
        Path to downloaded file, or None if not found
    """
    try:
        from google.cloud import storage
        from google.cloud.exceptions import NotFound
    except ImportError:
        return None  # Silently return if GCS not available

    try:
        # Resolve credentials path
        creds_path = credentials_path or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

        if creds_path:
            # Convert path for current platform (WSL vs Windows)
            creds_path = convert_path_for_platform(creds_path)

            # Validate file exists
            if not Path(creds_path).exists():
                # Only print warning once per session
                if not getattr(try_gcs_download, '_warned_no_creds', False):
                    print(f"Warning: GCS credentials not found at {creds_path}")
                    print("  Falling back to web portal downloads.")
                    try_gcs_download._warned_no_creds = True
                return None

            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Build GCS path
        gcs_path = build_gcs_path(book, page, doc_type)
        blob = bucket.blob(gcs_path)

        # Check if exists
        if not blob.exists():
            # Try alternative doc types if not found
            alternative_types = ["deed", "deed-of-trust", "unknown"]
            for alt_type in alternative_types:
                if alt_type != normalize_doc_type(doc_type):
                    alt_path = build_gcs_path(book, page, alt_type)
                    alt_blob = bucket.blob(alt_path)
                    if alt_blob.exists():
                        blob = alt_blob
                        gcs_path = alt_path
                        break
            else:
                # Also try listing files with the book-page pattern
                prefix = f"documents/{get_folder_prefix(book)}/"
                filename_pattern = f"{book:04d}-{page:04d}.pdf"
                blobs = list(bucket.list_blobs(prefix=prefix))

                for b in blobs:
                    if b.name.endswith(filename_pattern):
                        blob = b
                        gcs_path = b.name
                        break
                else:
                    return None

        # Download to local file
        filename = f"{book:04d}-{page:04d}.pdf"
        local_path = output_dir / filename

        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        blob.download_to_filename(str(local_path))

        return local_path

    except NotFound:
        return None
    except Exception as e:
        print(f"GCS error for Book {book}, Page {page}: {e}")
        return None


def upload_to_gcs(
    local_path: Path,
    book: int,
    page: int,
    doc_type: str,
    bucket_name: str = DEFAULT_BUCKET_NAME,
    credentials_path: Optional[str] = None,
    metadata: Optional[DocumentMetadata] = None
) -> Optional[str]:
    """
    Upload document to GCS.

    Args:
        local_path: Path to local file
        book: Book number
        page: Page number
        doc_type: Document type
        bucket_name: GCS bucket name
        credentials_path: Path to service account credentials
        metadata: Optional document metadata

    Returns:
        GCS path if successful, None otherwise
    """
    try:
        from google.cloud import storage
    except ImportError:
        print("Warning: google-cloud-storage not installed. Upload disabled.")
        return None

    try:
        # Resolve credentials path
        creds_path = credentials_path or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

        if creds_path:
            # Convert path for current platform (WSL vs Windows)
            creds_path = convert_path_for_platform(creds_path)

            if not Path(creds_path).exists():
                print(f"Warning: GCS credentials not found at {creds_path}")
                return None

            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Build GCS path
        gcs_path = build_gcs_path(book, page, doc_type)
        blob = bucket.blob(gcs_path)

        # Prepare metadata
        blob_metadata = {
            'book': str(book),
            'page': str(page),
            'document_type': doc_type,
            'upload_time': datetime.now().isoformat(),
            'original_filename': local_path.name
        }

        if metadata:
            blob_metadata.update({
                'grantor': metadata.grantor or '',
                'grantee': metadata.grantee or '',
                'date_recorded': metadata.date_recorded or '',
                'instrument_number': str(metadata.instrument_number) if metadata.instrument_number else ''
            })

        blob.metadata = blob_metadata

        # Upload
        blob.upload_from_filename(str(local_path), content_type='application/pdf')

        return gcs_path

    except Exception as e:
        print(f"GCS upload error for {local_path}: {e}")
        return None


# =============================================================================
# Madison County Document Downloader
# =============================================================================

class MadisonCountyDownloader:
    """
    Document downloader for Madison County, MS land records portal.
    Uses HTTP requests to download PDFs by book and page.
    First checks GCS bucket for existing copies.
    """

    def __init__(
        self,
        download_dir: str = "./downloads",
        timeout: int = 30,
        check_gcs: bool = True,
        upload_to_gcs: bool = False,
        bucket_name: str = DEFAULT_BUCKET_NAME,
        credentials_path: Optional[str] = None
    ):
        """
        Initialize downloader.

        Args:
            download_dir: Directory to save downloaded PDFs
            timeout: Request timeout in seconds
            check_gcs: Whether to check GCS for existing documents first
            upload_to_gcs: Whether to upload newly downloaded documents to GCS
            bucket_name: GCS bucket name
            credentials_path: Path to GCS credentials
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True, parents=True)
        self.timeout = timeout
        self.check_gcs = check_gcs
        self.upload_to_gcs_flag = upload_to_gcs
        self.bucket_name = bucket_name
        self.credentials_path = credentials_path

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def download_by_book_page(self, book: int, page: int, doc_type: str = "deed") -> DownloadResult:
        """
        Download document by book and page numbers.
        First checks GCS, then falls back to web portal.

        Args:
            book: Book number
            page: Page number
            doc_type: Document type code (optional filter)

        Returns:
            DownloadResult with download status and metadata
        """
        # Check if file already exists locally
        filename = f"{book:04d}-{page:04d}.pdf"
        file_path = self.download_dir / filename

        if file_path.exists():
            return DownloadResult(
                success=True,
                book=book,
                page=page,
                actual_book=book,
                actual_page=page,
                local_path=str(file_path),
                error=None,
                metadata=None,
                is_new_download=False,
                source="local"
            )

        # Try GCS first if enabled
        if self.check_gcs:
            gcs_result = try_gcs_download(
                book=book,
                page=page,
                doc_type=doc_type,
                output_dir=self.download_dir,
                bucket_name=self.bucket_name,
                credentials_path=self.credentials_path
            )

            if gcs_result:
                return DownloadResult(
                    success=True,
                    book=book,
                    page=page,
                    actual_book=book,
                    actual_page=page,
                    local_path=str(gcs_result),
                    error=None,
                    metadata=None,
                    is_new_download=True,
                    source="gcs"
                )

        # Fall back to web portal
        return self._download_from_web(book, page, doc_type)

    def _download_from_web(self, book: int, page: int, doc_type: str = "") -> DownloadResult:
        """
        Download document from web portal.

        Args:
            book: Book number
            page: Page number
            doc_type: Document type code

        Returns:
            DownloadResult with download status
        """
        filename = f"{book:04d}-{page:04d}.pdf"
        file_path = self.download_dir / filename

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
                LOOKUP_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            # Check if it's a direct PDF response
            content_type = response.headers.get('Content-Type', '').lower()

            if 'pdf' in content_type or response.content.startswith(b'%PDF-'):
                # Direct PDF download
                with open(file_path, 'wb') as f:
                    f.write(response.content)

                # Upload to GCS if enabled
                if self.upload_to_gcs_flag:
                    upload_to_gcs(
                        local_path=file_path,
                        book=book,
                        page=page,
                        doc_type=doc_type or "deed",
                        bucket_name=self.bucket_name,
                        credentials_path=self.credentials_path
                    )

                return DownloadResult(
                    success=True,
                    book=book,
                    page=page,
                    actual_book=book,
                    actual_page=page,
                    local_path=str(file_path),
                    error=None,
                    metadata=None,
                    is_new_download=True,
                    source="web"
                )

            # HTML response - need to parse and extract PDF link
            metadata = self._parse_html_response(response.text)

            if metadata and metadata.image_id:
                local_path = self._download_pdf(metadata)
                if local_path:
                    # Upload to GCS if enabled
                    if self.upload_to_gcs_flag:
                        upload_to_gcs(
                            local_path=local_path,
                            book=metadata.book,
                            page=metadata.page,
                            doc_type=metadata.doc_type or doc_type or "deed",
                            bucket_name=self.bucket_name,
                            credentials_path=self.credentials_path,
                            metadata=metadata
                        )

                    return DownloadResult(
                        success=True,
                        book=book,
                        page=page,
                        actual_book=metadata.book,
                        actual_page=metadata.page,
                        local_path=str(local_path),
                        error=None,
                        metadata=metadata,
                        is_new_download=True,
                        source="web"
                    )
                else:
                    return DownloadResult(
                        success=False,
                        book=book,
                        page=page,
                        actual_book=metadata.book,
                        actual_page=metadata.page,
                        local_path=None,
                        error="Failed to download PDF",
                        metadata=metadata,
                        is_new_download=False,
                        source="web"
                    )
            else:
                # Check if no results found
                if "No results found" in response.text or "no records" in response.text.lower():
                    return DownloadResult(
                        success=False,
                        book=book,
                        page=page,
                        actual_book=None,
                        actual_page=None,
                        local_path=None,
                        error="No document found at this book/page",
                        metadata=None,
                        is_new_download=False,
                        source="web"
                    )
                return DownloadResult(
                    success=False,
                    book=book,
                    page=page,
                    actual_book=None,
                    actual_page=None,
                    local_path=None,
                    error="No PDF link found in response",
                    metadata=metadata,
                    is_new_download=False,
                    source="web"
                )

        except requests.exceptions.Timeout:
            return DownloadResult(
                success=False,
                book=book,
                page=page,
                actual_book=None,
                actual_page=None,
                local_path=None,
                error=f"Request timeout after {self.timeout}s",
                metadata=None,
                is_new_download=False,
                source="web"
            )
        except requests.exceptions.RequestException as e:
            return DownloadResult(
                success=False,
                book=book,
                page=page,
                actual_book=None,
                actual_page=None,
                local_path=None,
                error=f"Request error: {str(e)}",
                metadata=None,
                is_new_download=False,
                source="web"
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                book=book,
                page=page,
                actual_book=None,
                actual_page=None,
                local_path=None,
                error=f"Unexpected error: {str(e)}",
                metadata=None,
                is_new_download=False,
                source="web"
            )

    def _parse_html_response(self, html: str) -> Optional[DocumentMetadata]:
        """
        Parse HTML response to extract document metadata.

        Args:
            html: HTML response text

        Returns:
            DocumentMetadata if parsed successfully, None otherwise
        """
        soup = BeautifulSoup(html, 'html.parser')

        try:
            # Extract grantor/grantee from h2 tag
            h2 = soup.find('h2')
            grantor = ""
            grantee = ""

            if h2:
                h2_text = h2.get_text()
                grantor_match = re.search(r'Grantor:\s*(.+?)(?:Grantee:|$)', h2_text, re.DOTALL)
                grantee_match = re.search(r'Grantee:\s*(.+?)$', h2_text, re.DOTALL)

                grantor = grantor_match.group(1).strip() if grantor_match else ""
                grantee = grantee_match.group(1).strip() if grantee_match else ""

            # Extract nature (document type)
            nature_match = re.search(r'Nature:\s*<em>(.+?)</em>', html)
            doc_nature = nature_match.group(1).strip() if nature_match else ""

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
            date_recorded = None
            instrument_number = None

            for cell in cell_texts:
                if cell.startswith('Type:'):
                    doc_type_match = re.search(r'Type:\s*(.+)', cell)
                    doc_type = doc_type_match.group(1).strip() if doc_type_match else None
                elif cell.startswith('Book:'):
                    book_match = re.search(r'Book:\s*(\d+)', cell)
                    book = int(book_match.group(1)) if book_match else None
                elif cell.startswith('Page:'):
                    page_match = re.search(r'Page:\s*(\d+)', cell)
                    page = int(page_match.group(1)) if page_match else None
                elif cell.startswith('Date'):
                    date_match = re.search(r'Date\s+Recorded:\s*(.+)', cell)
                    date_recorded = date_match.group(1).strip() if date_match else None
                elif cell.startswith('Instrument'):
                    inst_match = re.search(r'Instrument.*?:\s*(\d+)', cell)
                    instrument_number = int(inst_match.group(1)) if inst_match else None

            # Extract PDF image_id from download link
            image_link = soup.find('a', href=re.compile(r'pdf-records\.php\?image='))
            image_id = None

            if image_link:
                href = image_link.get('href', '')
                image_match = re.search(r'image=(\d+)', href)
                image_id = image_match.group(1) if image_match else None

            if book and page:
                return DocumentMetadata(
                    book=book,
                    page=page,
                    grantor=grantor,
                    grantee=grantee,
                    doc_type=doc_type or "",
                    doc_nature=doc_nature,
                    date_recorded=date_recorded or "",
                    image_id=image_id,
                    instrument_number=instrument_number
                )

            return None

        except Exception:
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

        url = f"{PDF_URL}?image={metadata.image_id}"

        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()

        # Verify it's a PDF
        if not (response.headers.get('Content-Type', '').lower().startswith('application/pdf')
                or response.content.startswith(b'%PDF-')):
            return None

        # Use actual book/page from metadata
        filename = f"{metadata.book:04d}-{metadata.page:04d}.pdf"
        file_path = self.download_dir / filename

        with open(file_path, 'wb') as f:
            f.write(response.content)

        return file_path

    def close(self):
        """Close the requests session."""
        self.session.close()


# =============================================================================
# Document Reference Parsing
# =============================================================================

def parse_document_reference(ref: str) -> Dict[str, Optional[int]]:
    """
    Parse a document reference string into book and page.

    Supported formats:
        "500/100" -> book 500, page 100
        "500-100" -> book 500, page 100
        "500 100" -> book 500, page 100
        "500" (single number) -> book 500, page None

    Returns:
        Dictionary with keys: book, page
    """
    result = {"book": None, "page": None}

    if not ref:
        return result

    ref = str(ref).strip()

    # Pattern: slash format (500/100)
    if '/' in ref:
        parts = ref.split('/')
        if len(parts) == 2:
            try:
                result["book"] = int(parts[0].strip())
                result["page"] = int(parts[1].strip())
            except ValueError:
                pass
        return result

    # Pattern: hyphen format (500-100)
    if '-' in ref:
        parts = ref.split('-')
        if len(parts) == 2:
            try:
                result["book"] = int(parts[0].strip())
                result["page"] = int(parts[1].strip())
            except ValueError:
                pass
        return result

    # Pattern: space format (500 100)
    if ' ' in ref:
        parts = ref.split()
        if len(parts) >= 2:
            try:
                result["book"] = int(parts[0].strip())
                result["page"] = int(parts[1].strip())
            except ValueError:
                pass
        return result

    # Single number (just book)
    try:
        result["book"] = int(ref)
    except ValueError:
        pass

    return result


def sanitize_filename(filename: str) -> str:
    """Remove or replace characters that are invalid in filenames."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename


# =============================================================================
# Excel File Processing
# =============================================================================

def process_excel_file(excel_path: str) -> List[Dict[str, Optional[int]]]:
    """
    Read document references from an Excel file.

    Expected format (either):
        Option 1:
            Column A: Book number
            Column B: Page number

        Option 2:
            Column A: "Book/Page" format (e.g., "500/100")

    Returns:
        List of dictionaries with book and page
    """
    try:
        import openpyxl
    except ImportError:
        print("Error: 'openpyxl' package is required for Excel support.")
        print("Install with: pip install openpyxl")
        sys.exit(1)

    documents = []

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb.active

    # Common header keywords to skip
    header_keywords = [
        'book', 'page', 'document', 'reference', 'ref', 'doc',
        'header', 'column', 'id', 'number', 'num'
    ]

    for row_num, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
        if not row or row[0] is None:
            continue

        first_cell = str(row[0]).strip().lower()

        # Check if it matches any header keyword
        is_header = any(keyword == first_cell for keyword in header_keywords)
        has_digits = any(c.isdigit() for c in first_cell)

        if is_header or (row_num == 1 and not has_digits):
            print(f"  Skipping header row: {row[0]}")
            continue

        # Try to parse
        book = None
        page = None

        # Check if Column A contains book/page combined format
        first_val = str(row[0]).strip()
        if '/' in first_val or '-' in first_val or ' ' in first_val:
            parsed = parse_document_reference(first_val)
            book = parsed["book"]
            page = parsed["page"]
        else:
            # Assume Column A is book, Column B is page
            try:
                book = int(float(str(row[0]).strip()))
            except (ValueError, TypeError):
                continue

            if len(row) > 1 and row[1] is not None:
                try:
                    page = int(float(str(row[1]).strip()))
                except (ValueError, TypeError):
                    pass

        if book is not None and page is not None:
            documents.append({
                "book": book,
                "page": page,
                "row": row_num,
                "original_ref": f"{book}/{page}"
            })

    wb.close()
    return documents


def process_txt_file(txt_path: str) -> List[Dict[str, Optional[int]]]:
    """
    Read document references from a text file.

    Expected format (one per line):
        500/100 deed book
        501-50 plat
        238/15
        100/50  (book < 238 is always deed book)

    If no book type is specified, defaults to "deed book".
    Books numbered less than 238 are always treated as deed books.

    Returns:
        List of dictionaries with book, page, and doc_type
    """
    documents = []

    with open(txt_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Skip header-like lines
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ['book', 'page', 'document', 'reference']):
                print(f"  Skipping header line: {line}")
                continue

            # Parse book/page and optional book type
            # Format: [book]/[page] [book_type] or [book]-[page] [book_type]
            book = None
            page = None
            book_type = "deed"  # Default

            # Split on whitespace to separate book/page from book type
            parts = line.split()
            if not parts:
                continue

            book_page_part = parts[0]

            # Extract book type if provided (everything after the book/page)
            if len(parts) > 1:
                book_type = " ".join(parts[1:])

            # Parse book/page using existing function
            parsed = parse_document_reference(book_page_part)
            book = parsed["book"]
            page = parsed["page"]

            # Books < 238 are always deed book
            if book is not None and book < 238:
                book_type = "deed"

            if book is not None and page is not None:
                documents.append({
                    "book": book,
                    "page": page,
                    "doc_type": book_type,
                    "row": line_num,
                    "original_ref": line
                })
            else:
                print(f"  Warning: Could not parse line {line_num}: {line}")

    return documents


def select_input_file() -> Optional[str]:
    """Open a file dialog to select an Excel or text file."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("Error: tkinter is not available for file selection.")
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    file_path = filedialog.askopenfilename(
        title="Select Document List (Excel or Text)",
        filetypes=[
            ("Supported files", "*.xlsx *.xls *.txt"),
            ("Excel files", "*.xlsx *.xls"),
            ("Text files", "*.txt"),
            ("All files", "*.*")
        ]
    )

    root.destroy()
    return file_path if file_path else None


# =============================================================================
# Batch Download Functions
# =============================================================================

def download_worker(
    doc: Dict,
    output_dir: str,
    timeout: int = 30,
    check_gcs: bool = True,
    upload_to_gcs: bool = False,
    bucket_name: str = DEFAULT_BUCKET_NAME,
    credentials_path: Optional[str] = None
) -> Tuple[Dict, DownloadResult]:
    """
    Worker function for downloading a single document.
    Creates its own session for thread safety.

    Args:
        doc: Document dict with book, page, and optional doc_type
        output_dir: Output directory
        timeout: Request timeout
        check_gcs: Whether to check GCS first
        upload_to_gcs: Whether to upload to GCS
        bucket_name: GCS bucket name
        credentials_path: Path to GCS credentials

    Returns:
        Tuple of (doc, DownloadResult)
    """
    downloader = MadisonCountyDownloader(
        download_dir=output_dir,
        timeout=timeout,
        check_gcs=check_gcs,
        upload_to_gcs=upload_to_gcs,
        bucket_name=bucket_name,
        credentials_path=credentials_path
    )
    try:
        doc_type = doc.get("doc_type", "deed")
        result = downloader.download_by_book_page(doc["book"], doc["page"], doc_type)
        return (doc, result)
    finally:
        downloader.close()


def run_batch_download(
    input_path: str,
    max_workers: int = None,
    delay: float = DEFAULT_DELAY,
    check_gcs: bool = True,
    upload_to_gcs: bool = False,
    bucket_name: str = DEFAULT_BUCKET_NAME,
    credentials_path: Optional[str] = None
):
    """Process an Excel or text file and download all documents."""
    print(f"\nReading input file: {input_path}")

    # Determine file type and process accordingly
    ext = os.path.splitext(input_path)[1].lower()
    if ext == '.txt':
        documents = process_txt_file(input_path)
    elif ext in ('.xlsx', '.xls'):
        documents = process_excel_file(input_path)
    else:
        print(f"Error: Unsupported file type '{ext}'. Use .xlsx, .xls, or .txt")
        return

    if not documents:
        print("No documents found in the spreadsheet.")
        return

    print(f"Found {len(documents)} document(s) to process")
    print(f"GCS check enabled: {check_gcs}")
    print(f"Upload to GCS: {upload_to_gcs}")

    # Create output directory
    input_dir = os.path.dirname(os.path.abspath(input_path))
    output_dir = os.path.join(input_dir, "docs")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # Determine workers
    if max_workers is None:
        max_workers = min(4, cpu_count())
    max_workers = min(max_workers, len(documents), 10)

    print(f"Using {max_workers} worker(s)")

    # Track results
    download_results = []
    successful = 0
    failed = 0
    skipped = 0
    from_gcs = 0
    from_web = 0

    start_time = time.time()

    if max_workers == 1:
        # Sequential download
        downloader = MadisonCountyDownloader(
            download_dir=output_dir,
            check_gcs=check_gcs,
            upload_to_gcs=upload_to_gcs,
            bucket_name=bucket_name,
            credentials_path=credentials_path
        )

        try:
            for idx, doc in enumerate(documents, start=1):
                print(f"\n[{idx}/{len(documents)}] Downloading Book {doc['book']}, Page {doc['page']}...")

                doc_type = doc.get("doc_type", "deed")
                result = downloader.download_by_book_page(doc["book"], doc["page"], doc_type)

                download_results.append({
                    "ref": doc["original_ref"],
                    "book": doc["book"],
                    "page": doc["page"],
                    "success": result.success,
                    "source": result.source,
                    "message": result.error if result.error else (
                        "Already exists" if not result.is_new_download else f"Downloaded from {result.source}"
                    ),
                    "filepath": result.local_path
                })

                if result.success:
                    if result.is_new_download:
                        print(f"  SUCCESS: Downloaded from {result.source} to {os.path.basename(result.local_path)}")
                        successful += 1
                        if result.source == "gcs":
                            from_gcs += 1
                        else:
                            from_web += 1
                    else:
                        print(f"  SKIPPED: Already exists locally")
                        skipped += 1
                else:
                    print(f"  FAILED: {result.error}")
                    failed += 1

                # Rate limiting (only for web downloads)
                if idx < len(documents) and result.source == "web":
                    time.sleep(delay)

        finally:
            downloader.close()
    else:
        # Parallel download
        print(f"\nStarting parallel download...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    download_worker,
                    doc,
                    output_dir,
                    30,
                    check_gcs,
                    upload_to_gcs,
                    bucket_name,
                    credentials_path
                ): doc
                for doc in documents
            }

            for idx, future in enumerate(as_completed(futures), start=1):
                doc = futures[future]

                try:
                    doc, result = future.result()

                    download_results.append({
                        "ref": doc["original_ref"],
                        "book": doc["book"],
                        "page": doc["page"],
                        "success": result.success,
                        "source": result.source,
                        "message": result.error if result.error else (
                            "Already exists" if not result.is_new_download else f"Downloaded from {result.source}"
                        ),
                        "filepath": result.local_path
                    })

                    status = ""
                    if result.success:
                        if result.is_new_download:
                            status = f"Downloaded from {result.source}"
                            successful += 1
                            if result.source == "gcs":
                                from_gcs += 1
                            else:
                                from_web += 1
                        else:
                            status = "Skipped (exists)"
                            skipped += 1
                    else:
                        status = f"Failed: {result.error}"
                        failed += 1

                    print(f"[{idx}/{len(documents)}] Book {doc['book']}, Page {doc['page']}: {status}")

                except Exception as e:
                    download_results.append({
                        "ref": doc["original_ref"],
                        "book": doc["book"],
                        "page": doc["page"],
                        "success": False,
                        "source": "error",
                        "message": str(e),
                        "filepath": None
                    })
                    failed += 1
                    print(f"[{idx}/{len(documents)}] Book {doc['book']}, Page {doc['page']}: Error - {e}")

    elapsed = time.time() - start_time

    # Generate report
    report_path = generate_summary_report(
        input_path=input_path,
        output_dir=output_dir,
        documents=documents,
        download_results=download_results,
        elapsed_time=elapsed,
        from_gcs=from_gcs,
        from_web=from_web
    )

    # Summary
    print(f"\n{'='*60}")
    print(f"{'SUMMARY':^60}")
    print(f"{'='*60}")
    print(f"Total documents: {len(documents)}")
    print(f"New downloads: {successful}")
    print(f"  - From GCS: {from_gcs}")
    print(f"  - From Web: {from_web}")
    print(f"Already existed: {skipped}")
    print(f"Failed: {failed}")
    print(f"Time elapsed: {elapsed:.1f} seconds")
    print(f"Output directory: {output_dir}")
    print(f"Report saved: {report_path}")


def generate_summary_report(
    input_path: str,
    output_dir: str,
    documents: List[Dict],
    download_results: List[Dict],
    elapsed_time: float,
    from_gcs: int = 0,
    from_web: int = 0
) -> str:
    """
    Generate and save a summary report as a text file.

    Returns:
        Path to the generated report file
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"download_report_{report_timestamp}.txt"
    report_path = os.path.join(output_dir, report_filename)

    # Calculate statistics
    successful = sum(1 for r in download_results if r["success"] and "Downloaded" in r.get("message", ""))
    skipped = sum(1 for r in download_results if r["success"] and r.get("message") == "Already exists")
    failed = sum(1 for r in download_results if not r["success"])

    lines = []
    lines.append("=" * 70)
    lines.append("MADISON COUNTY DOCUMENT PULLER - SUMMARY REPORT")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Report Generated: {timestamp}")
    lines.append(f"Source File:      {os.path.basename(input_path)}")
    lines.append(f"Output Directory: {output_dir}")
    lines.append(f"Time Elapsed:     {elapsed_time:.1f} seconds")
    lines.append("")
    lines.append("-" * 70)
    lines.append("DOWNLOAD STATISTICS")
    lines.append("-" * 70)
    lines.append(f"Total Documents Requested:  {len(documents)}")
    lines.append(f"Successfully Downloaded:    {successful}")
    lines.append(f"  - From GCS:               {from_gcs}")
    lines.append(f"  - From Web Portal:        {from_web}")
    lines.append(f"Already Existed (Skipped):  {skipped}")
    lines.append(f"Failed:                     {failed}")
    lines.append("")

    # List successful downloads
    successful_results = [r for r in download_results if r["success"]]
    if successful_results:
        lines.append("-" * 70)
        lines.append("SUCCESSFUL DOWNLOADS")
        lines.append("-" * 70)
        for r in successful_results:
            if r.get("message") == "Already exists":
                status = "[SKIPPED]"
            elif r.get("source") == "gcs":
                status = "[GCS]"
            else:
                status = "[WEB]"
            filename = os.path.basename(r["filepath"]) if r["filepath"] else "N/A"
            lines.append(f"  {status} Book {r['book']}, Page {r['page']} -> {filename}")
        lines.append("")

    # List failed downloads
    failed_results = [r for r in download_results if not r["success"]]
    if failed_results:
        lines.append("-" * 70)
        lines.append("FAILED DOWNLOADS")
        lines.append("-" * 70)
        for r in failed_results:
            lines.append(f"  [FAILED] Book {r['book']}, Page {r['page']}")
            lines.append(f"           Reason: {r['message']}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    # Write report to file
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return report_path


# =============================================================================
# Single Document Download
# =============================================================================

def run_single_download(args):
    """Handle single document download from command line arguments."""
    book = args.book
    page = args.page

    if not book or not page:
        print("Error: Both --book and --page are required")
        sys.exit(1)

    print(f"\nMadison County Document Puller (with GCS)")
    print("=" * 40)
    print(f"Book: {book}")
    print(f"Page: {page}")
    print(f"GCS check: {'Disabled' if args.skip_gcs else 'Enabled'}")

    # Set output directory
    output_dir = args.output_dir or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    print(f"Output: {output_dir}")

    # Load environment for GCS credentials
    bucket_name = DEFAULT_BUCKET_NAME
    credentials_path = None

    if load_dotenv:
        load_dotenv()
        bucket_name = os.getenv('GCS_BUCKET_NAME', DEFAULT_BUCKET_NAME)
        credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

    downloader = MadisonCountyDownloader(
        download_dir=output_dir,
        check_gcs=not args.skip_gcs,
        upload_to_gcs=args.upload_to_gcs,
        bucket_name=bucket_name,
        credentials_path=credentials_path
    )

    try:
        if args.info_only:
            print("\nFetching document info...")
            result = downloader.download_by_book_page(book, page)

            print(f"\n{'='*60}")
            print(f"{'DOCUMENT INFORMATION':^60}")
            print(f"{'='*60}")

            if result.metadata:
                print(f"Book: {result.metadata.book}")
                print(f"Page: {result.metadata.page}")
                print(f"Document Type: {result.metadata.doc_type}")
                print(f"Nature: {result.metadata.doc_nature}")
                print(f"Grantor: {result.metadata.grantor}")
                print(f"Grantee: {result.metadata.grantee}")
                print(f"Date Recorded: {result.metadata.date_recorded}")
                if result.metadata.instrument_number:
                    print(f"Instrument #: {result.metadata.instrument_number}")
                print(f"Image ID: {result.metadata.image_id}")
            else:
                print("No document found or unable to parse metadata")

            print(f"{'='*60}")
        else:
            print("\nDownloading document...")
            result = downloader.download_by_book_page(book, page)

            if result.success:
                if result.is_new_download:
                    file_size = os.path.getsize(result.local_path)
                    print(f"\nSUCCESS: Downloaded from {result.source} to {result.local_path}")
                    print(f"File size: {file_size:,} bytes")
                else:
                    print(f"\nFile already exists: {result.local_path}")

                if result.metadata:
                    print(f"\nDocument Info:")
                    print(f"  Type: {result.metadata.doc_type}")
                    print(f"  Nature: {result.metadata.doc_nature}")
                    print(f"  Grantor: {result.metadata.grantor}")
                    print(f"  Grantee: {result.metadata.grantee}")
            else:
                print(f"\nFAILED: {result.error}")
                sys.exit(1)

    finally:
        downloader.close()


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Download documents from Madison County, MS Land Records (with GCS integration)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode - select file via dialog
  python madison_doc_puller.py

  # Batch mode with Excel file
  python madison_doc_puller.py --excel documents.xlsx

  # Batch mode with text file
  python madison_doc_puller.py --txt documents.txt

  # Batch mode with parallel workers
  python madison_doc_puller.py --excel documents.xlsx --workers 4

  # Single document download
  python madison_doc_puller.py --book 500 --page 100

  # Skip GCS check (download from web only)
  python madison_doc_puller.py --book 500 --page 100 --skip-gcs

  # Upload newly downloaded docs to GCS
  python madison_doc_puller.py --excel documents.xlsx --upload-to-gcs

  # View document info only (no download)
  python madison_doc_puller.py --book 500 --page 100 --info-only

GCS Integration:
  By default, the script first checks the GCS bucket for existing documents
  before falling back to the web portal. Use --skip-gcs to disable this.

  GCS path format: documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf

  Folder prefixes:
    - historical: book < 238
    - mid-early:  238 <= book < 1000
    - mid-recent: book >= 1000

Excel Format:
  Option 1:
    Column A: Book number
    Column B: Page number

  Option 2:
    Column A: Combined format (e.g., "500/100" or "500-100")

Text File Format:
  [book]/[page] [book_type] - e.g., "500/100 deed book", "501-50 plat"
  Book type defaults to "deed". Books < 238 are always "deed".
        """
    )

    # Mode selection
    mode_group = parser.add_argument_group("Mode Selection")
    mode_group.add_argument(
        "--excel", "-e",
        help="Path to Excel file for batch processing"
    )
    mode_group.add_argument(
        "--txt", "-t",
        help="Path to text file for batch processing (one book/page per line)"
    )

    # Search options (for single document mode)
    search_group = parser.add_argument_group("Single Document Options")
    search_group.add_argument(
        "--book", "-b",
        type=int,
        help="Book number"
    )
    search_group.add_argument(
        "--page", "-p",
        type=int,
        help="Page number"
    )

    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output-dir", "-o",
        help="Output directory for downloaded files"
    )
    output_group.add_argument(
        "--info-only",
        action="store_true",
        help="Only show document info, don't download"
    )

    # GCS options
    gcs_group = parser.add_argument_group("GCS Options")
    gcs_group.add_argument(
        "--skip-gcs",
        action="store_true",
        help="Skip GCS check, download directly from web portal"
    )
    gcs_group.add_argument(
        "--upload-to-gcs",
        action="store_true",
        help="Upload newly downloaded documents to GCS"
    )
    gcs_group.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET_NAME,
        help=f"GCS bucket name (default: {DEFAULT_BUCKET_NAME})"
    )

    # Processing options
    process_group = parser.add_argument_group("Processing Options")
    process_group.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        help=f"Number of parallel workers for batch downloads (default: min(4, CPU count))"
    )
    process_group.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Delay between requests in seconds (default: {DEFAULT_DELAY})"
    )

    args = parser.parse_args()

    # Load environment variables
    if load_dotenv:
        load_dotenv()

    # Get GCS config from environment or args
    bucket_name = args.bucket or os.getenv('GCS_BUCKET_NAME', DEFAULT_BUCKET_NAME)
    credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

    # Determine mode
    if args.excel:
        # Batch mode with Excel file
        run_batch_download(
            args.excel,
            args.workers,
            args.delay,
            check_gcs=not args.skip_gcs,
            upload_to_gcs=args.upload_to_gcs,
            bucket_name=bucket_name,
            credentials_path=credentials_path
        )
    elif args.txt:
        # Batch mode with text file
        run_batch_download(
            args.txt,
            args.workers,
            args.delay,
            check_gcs=not args.skip_gcs,
            upload_to_gcs=args.upload_to_gcs,
            bucket_name=bucket_name,
            credentials_path=credentials_path
        )
    elif args.book and args.page:
        # Single document mode
        run_single_download(args)
    elif args.book or args.page:
        # Partial book/page specified
        print("Error: Both --book and --page must be specified together")
        sys.exit(1)
    else:
        # Interactive mode - open file dialog
        print("Madison County Document Puller (with GCS)")
        print("=" * 40)
        print("\nNo arguments provided. Opening file selector...")

        input_path = select_input_file()

        if input_path:
            run_batch_download(
                input_path,
                args.workers,
                args.delay,
                check_gcs=not args.skip_gcs,
                upload_to_gcs=args.upload_to_gcs,
                bucket_name=bucket_name,
                credentials_path=credentials_path
            )
        else:
            print("\nNo file selected.")
            print("\nFor command-line usage, run with --help")
            sys.exit(0)


if __name__ == "__main__":
    main()
