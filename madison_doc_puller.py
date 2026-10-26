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
    A deed of trust book may be marked with a DT prefix: DT [book]/[page]
    Lettered books are supported: CCC/165
    Book type defaults to "deed" if not specified.
    Books < 238 and lettered books are "deed" unless marked DT.

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
from typing import Optional, List, Dict, Tuple, Union
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

# Book series. Deed of trust books are numbered separately from deed books,
# so DT 151/206 and Deed Book 151, Page 206 are different documents.
DEED = "deed"
DEED_OF_TRUST = "deed-of-trust"

# Series labels accepted before or after a book/page reference in input files
# (other labels are normalized with normalize_doc_type)
DOC_TYPE_ALIASES = {
    "d": DEED,
    "db": DEED,
    "deed book": DEED,
    "dt": DEED_OF_TRUST,
    "dot": DEED_OF_TRUST,
}

# Court records are filed by case number, not book/page, so a line labeled
# with one of these (e.g., "Cause 1994-175") is not a land record reference
COURT_RECORD_KINDS = {
    "cause": "chancery cause",
    "case": "chancery case",
    "chancery": "chancery case",
    "will": "will",
}

# Lookup portal "Type" code for records in deed of trust books
DEED_OF_TRUST_TYPE_CODE = "T"

# The oldest deed books are lettered: A-Z, AA-ZZ, AAA-ZZZ
LETTERED_BOOK_PATTERN = re.compile(r'^([A-Z])\1{0,2}$')

# A book is a number or a lettered book designation (e.g., "CCC")
BookId = Union[int, str]


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DocumentMetadata:
    """Metadata extracted from document lookup response."""
    book: BookId
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
    book: BookId
    page: int
    actual_book: Optional[BookId]
    actual_page: Optional[int]
    local_path: Optional[str]
    error: Optional[str]
    metadata: Optional[DocumentMetadata]
    is_new_download: bool = True
    source: str = "web"  # "gcs" or "web"


# =============================================================================
# GCS Helper Functions
# =============================================================================

def get_folder_prefix(book: BookId) -> str:
    """
    Determine the folder prefix based on book number.

    Args:
        book: Book number or lettered book

    Returns:
        Folder prefix string (historical, mid-early, or mid-recent)
    """
    if isinstance(book, str) or book < 238:
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


def parse_book(value) -> Optional[BookId]:
    """
    Parse a book number (e.g., "0151" -> 151) or lettered book (e.g., "ccc" -> "CCC").

    Returns:
        int for numbered books, uppercase str for lettered books, None if invalid
    """
    text = str(value).strip().upper()
    if text.isdigit():
        return int(text)
    if LETTERED_BOOK_PATTERN.match(text):
        return text
    return None


def document_filename(book: BookId, page: int) -> str:
    """Filename used in GCS, e.g. 0151-0206.pdf or CCC-0165.pdf."""
    book_part = book if isinstance(book, str) else f"{book:04d}"
    return f"{book_part}-{page:04d}.pdf"


def local_filename(book: BookId, page: int, doc_type: str = DEED) -> str:
    """
    Local filename for a document. Deeds of trust get a DT- prefix so they
    never collide with the deed at the same book/page.
    """
    prefix = "DT-" if normalize_doc_type(doc_type) == DEED_OF_TRUST else ""
    return prefix + document_filename(book, page)


def format_reference(book: BookId, page: int, doc_type: str = DEED) -> str:
    """Human-readable reference, e.g. "Book 14, Page 466" or "DT Book 502, Page 308"."""
    prefix = "DT " if normalize_doc_type(doc_type) == DEED_OF_TRUST else ""
    return f"{prefix}Book {book}, Page {page}"


def build_gcs_path(book: BookId, page: int, doc_type: str = DEED) -> str:
    """
    Build the GCS path for a document.

    Path format: documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf

    Args:
        book: Book number or lettered book
        page: Page number
        doc_type: Document type (default: "deed")

    Returns:
        GCS path string
    """
    folder_prefix = get_folder_prefix(book)
    normalized_type = normalize_doc_type(doc_type)
    filename = document_filename(book, page)

    return f"documents/{folder_prefix}/{normalized_type}/{filename}"


def find_gcs_blob(bucket, book: BookId, page: int, doc_type: str):
    """
    Find a document's blob in the bucket.

    Deed-book documents are filed under their instrument type (deed, unknown,
    easement, ...), so every type folder is checked. Deed of trust books are a
    separate series, so a deed of trust only matches the deed-of-trust folder
    and a deed never does.

    Returns:
        The blob, or None if not found
    """
    normalized_type = normalize_doc_type(doc_type)
    blob = bucket.blob(build_gcs_path(book, page, doc_type))
    if blob.exists():
        return blob

    if normalized_type == DEED_OF_TRUST:
        return None

    prefix = f"documents/{get_folder_prefix(book)}/"
    filename = document_filename(book, page)
    folders = bucket.list_blobs(prefix=prefix, delimiter="/")
    list(folders)  # Folder prefixes are only populated once the listing is consumed

    for folder in sorted(folders.prefixes):
        if folder[len(prefix):].strip("/") in (normalized_type, DEED_OF_TRUST):
            continue
        candidate = bucket.blob(f"{folder}{filename}")
        if candidate.exists():
            return candidate

    return None


def try_gcs_download(
    book: BookId,
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

        blob = find_gcs_blob(bucket, book, page, doc_type)
        if blob is None:
            return None

        # Download to local file
        local_path = output_dir / local_filename(book, page, doc_type)

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
    book: BookId,
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

    def download_by_book_page(self, book: BookId, page: int, doc_type: str = DEED) -> DownloadResult:
        """
        Download document by book and page numbers.
        First checks GCS, then falls back to web portal.

        Args:
            book: Book number or lettered book
            page: Page number
            doc_type: Book series / document type ("deed", "deed-of-trust", ...)

        Returns:
            DownloadResult with download status and metadata
        """
        # Check if file already exists locally
        file_path = self.download_dir / local_filename(book, page, doc_type)

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

    def _download_from_web(self, book: BookId, page: int, doc_type: str = DEED) -> DownloadResult:
        """
        Download document from web portal.

        Args:
            book: Book number or lettered book
            page: Page number
            doc_type: Book series / document type

        Returns:
            DownloadResult with download status
        """
        file_path = self.download_dir / local_filename(book, page, doc_type)

        # The portal's doc_type filter takes instrument codes ("01" = DEED,
        # "02" = DEED OF TRUST, ...) and deed and deed of trust books each hold
        # many instrument types, so search unfiltered and pick the record from
        # the requested book series in select_result().
        params = {
            "grantor": "",
            "doc_type": "",
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
                # A bare PDF carries no Type, so it could be the deed at the
                # same book/page rather than the requested deed of trust
                if normalize_doc_type(doc_type) == DEED_OF_TRUST:
                    return DownloadResult(
                        success=False,
                        book=book,
                        page=page,
                        actual_book=None,
                        actual_page=None,
                        local_path=None,
                        error="Lookup returned a PDF without record details, so it can't be confirmed as a deed of trust",
                        metadata=None,
                        is_new_download=False,
                        source="web"
                    )

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
            results = self._parse_html_results(response.text)
            metadata = select_result(results, book, page, doc_type)

            if metadata and metadata.image_id:
                local_path = self._download_pdf(metadata, doc_type)
                if local_path:
                    # Upload to GCS if enabled
                    if self.upload_to_gcs_flag:
                        upload_to_gcs(
                            local_path=local_path,
                            book=metadata.book,
                            page=metadata.page,
                            doc_type=doc_type or DEED,
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
                if metadata:
                    error = "Record found but it has no image to download"
                elif results:
                    series = "deed of trust" if normalize_doc_type(doc_type) == DEED_OF_TRUST else "deed"
                    error = (f"Lookup returned {len(results)} record(s) but none is a {series} "
                             f"at Book {book}, Page {page}")
                elif "No results found" in response.text or "no records" in response.text.lower():
                    error = "No document found at this book/page"
                else:
                    error = "No PDF link found in response"

                if isinstance(book, str):
                    error += ("; lettered books may only be on the Historical Books portal "
                              "(Deed Books > Search by book and page)")

                return DownloadResult(
                    success=False,
                    book=book,
                    page=page,
                    actual_book=None,
                    actual_page=None,
                    local_path=None,
                    error=error,
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
        except requests.exceptions.ConnectionError:
            return DownloadResult(
                success=False,
                book=book,
                page=page,
                actual_book=None,
                actual_page=None,
                local_path=None,
                error=f"Could not connect to {BASE_URL} - the county records site appears to be down. Try again later.",
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

    @staticmethod
    def _parse_html_results(html: str) -> List[DocumentMetadata]:
        """
        Parse every record on a lookup results page.

        Each record is an h2 (grantor/grantee), a "Nature:" line, a table of
        Type/Book/Page/Date cells, then its "Download Image" links.

        Args:
            html: HTML response text

        Returns:
            List of DocumentMetadata, in page order
        """
        soup = BeautifulSoup(html, 'html.parser')
        results = []

        for table in soup.find_all('table'):
            doc_type = None
            book = None
            page = None
            date_recorded = None
            instrument_number = None

            for cell in table.find_all('td'):
                text = cell.get_text().strip()
                if text.startswith('Type:'):
                    doc_type = text[len('Type:'):].strip()
                elif text.startswith('Book:'):
                    book = parse_book(text[len('Book:'):])
                elif text.startswith('Page:'):
                    page_match = re.search(r'Page:\s*(\d+)', text)
                    page = int(page_match.group(1)) if page_match else None
                elif text.startswith('Date'):
                    date_match = re.search(r'Date\s+Recorded:\s*(.+)', text)
                    date_recorded = date_match.group(1).strip() if date_match else None
                elif text.startswith('Instrument'):
                    inst_match = re.search(r'Instrument.*?:\s*(\d+)', text)
                    instrument_number = int(inst_match.group(1)) if inst_match else None

            if book is None or page is None:
                continue

            # Grantor/grantee from the record's h2
            grantor = ""
            grantee = ""
            h2 = table.find_previous('h2')
            if h2:
                h2_text = h2.get_text()
                grantor_match = re.search(r'Grantor:\s*(.+?)(?:Grantee:|$)', h2_text, re.DOTALL)
                grantee_match = re.search(r'Grantee:\s*(.+?)$', h2_text, re.DOTALL)

                grantor = grantor_match.group(1).strip() if grantor_match else ""
                grantee = grantee_match.group(1).strip() if grantee_match else ""

            # Nature (instrument type)
            doc_nature = ""
            nature_label = table.find_previous(string=re.compile(r'Nature:'))
            if nature_label:
                nature_em = nature_label.find_next('em')
                doc_nature = nature_em.get_text().strip() if nature_em else ""

            # First image link before the next record's table
            image_id = None
            for element in table.next_elements:
                if element.name == 'table':
                    break
                if element.name == 'a':
                    image_match = re.search(r'pdf-records\.php\?image=(\d+)', element.get('href', ''))
                    if image_match:
                        image_id = image_match.group(1)
                        break

            results.append(DocumentMetadata(
                book=book,
                page=page,
                grantor=grantor,
                grantee=grantee,
                doc_type=doc_type or "",
                doc_nature=doc_nature,
                date_recorded=date_recorded or "",
                image_id=image_id,
                instrument_number=instrument_number
            ))

        return results

    def _download_pdf(self, metadata: DocumentMetadata, doc_type: str = DEED) -> Optional[Path]:
        """
        Download PDF using image_id from metadata.

        Args:
            metadata: Document metadata with image_id
            doc_type: Book series, used for the local filename

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
        file_path = self.download_dir / local_filename(metadata.book, metadata.page, doc_type)

        with open(file_path, 'wb') as f:
            f.write(response.content)

        return file_path

    def close(self):
        """Close the requests session."""
        self.session.close()


def select_result(
    results: List[DocumentMetadata],
    book: BookId,
    page: int,
    doc_type: str = DEED
) -> Optional[DocumentMetadata]:
    """
    Pick the lookup record for the requested book series, book, and page.

    A book/page search can return records from both deed books and deed of
    trust books (portal Type "T"), so only records from the requested series
    and book are accepted. An exact page match is preferred.

    Returns:
        Matching DocumentMetadata, or None
    """
    want_deed_of_trust = normalize_doc_type(doc_type) == DEED_OF_TRUST
    candidates = [
        r for r in results
        if r.book == book
        and (r.doc_type.upper() == DEED_OF_TRUST_TYPE_CODE) == want_deed_of_trust
    ]

    for r in candidates:
        if r.page == page:
            return r
    return candidates[0] if candidates else None


# =============================================================================
# Document Reference Parsing
# =============================================================================

def parse_document_reference(ref: str) -> Dict[str, Optional[BookId]]:
    """
    Parse a document reference string into book and page.

    Supported formats:
        "500/100" -> book 500, page 100
        "500-100" -> book 500, page 100
        "500 100" -> book 500, page 100
        "CCC/165" -> book "CCC", page 165 (lettered book)
        "500" (single number) -> book 500, page None

    Returns:
        Dictionary with keys: book, page
    """
    result = {"book": None, "page": None}

    if not ref:
        return result

    ref = str(ref).strip()

    def parse_pair(book_part: str, page_part: str):
        book = parse_book(book_part)
        page_part = page_part.strip()
        if book is not None and page_part.isdigit():
            result["book"] = book
            result["page"] = int(page_part)

    # Pattern: slash format (500/100)
    if '/' in ref:
        parts = ref.split('/')
        if len(parts) == 2:
            parse_pair(parts[0], parts[1])
        return result

    # Pattern: hyphen format (500-100)
    if '-' in ref:
        parts = ref.split('-')
        if len(parts) == 2:
            parse_pair(parts[0], parts[1])
        return result

    # Pattern: space format (500 100)
    if ' ' in ref:
        parts = ref.split()
        if len(parts) >= 2:
            parse_pair(parts[0], parts[1])
        return result

    # Single number (just book)
    result["book"] = parse_book(ref)

    return result


def court_record_kind(line: str) -> Optional[str]:
    """
    Identify a line that refers to a court record rather than a land record.

    The label is the first word of the line, or the first word after the
    reference when the line starts with it ("1994-175 cause").

    Returns:
        The court record kind (e.g., "chancery cause"), or None
    """
    tokens = line.lower().split()
    for i, token in enumerate(tokens):
        parsed = parse_document_reference(token)
        if parsed["book"] is not None and parsed["page"] is not None:
            tokens = tokens[:i] + tokens[i + 1:]
            break

    if not tokens:
        return None
    return COURT_RECORD_KINDS.get(tokens[0].strip(":,.-"))


def parse_reference_line(line: str) -> Optional[Dict]:
    """
    Parse one document reference with an optional book series label.

    Supported formats:
        "500/100", "500-100", "CCC/165"  -> deed book
        "DT 502/308"                     -> deed of trust book (label first)
        "502/308 deed-of-trust"          -> label last
        "501-50 plat"                    -> other document type

    Books < 238 and lettered books are deed books unless labeled as a
    deed of trust. Court records ("Cause 1994-175") are not references.

    Returns:
        Dictionary with keys: book, page, doc_type; None if no reference found
    """
    if court_record_kind(line):
        return None

    tokens = line.split()
    for i, token in enumerate(tokens):
        parsed = parse_document_reference(token)
        if parsed["book"] is not None and parsed["page"] is not None:
            label = " ".join(tokens[:i] + tokens[i + 1:]).lower()
            break
    else:
        return None

    book = parsed["book"]
    doc_type = DOC_TYPE_ALIASES.get(label, normalize_doc_type(label)) if label else DEED

    if doc_type != DEED_OF_TRUST and (isinstance(book, str) or book < 238):
        doc_type = DEED

    return {"book": book, "page": parsed["page"], "doc_type": doc_type}


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
        doc_type = DEED

        # Check if Column A contains book/page combined format
        first_val = str(row[0]).strip()
        kind = court_record_kind(first_val)
        if kind:
            print(f"  Skipping row {row_num} ({kind} - not in the land records): {first_val}")
            continue

        if '/' in first_val or '-' in first_val or ' ' in first_val:
            parsed = parse_reference_line(first_val) or parse_document_reference(first_val)
            book = parsed["book"]
            page = parsed["page"]
            doc_type = parsed.get("doc_type", DEED)
        else:
            # Assume Column A is book, Column B is page
            try:
                book = int(float(first_val))
            except (ValueError, TypeError):
                book = parse_book(first_val)
                if book is None:
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
                "doc_type": doc_type,
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
        DT 502/308  (deed of trust book)
        CCC/165     (lettered deed book)
        238/15
        100/50  (book < 238 is a deed book unless marked DT)

    If no book type is specified, defaults to "deed".
    Books numbered less than 238 and lettered books are treated as deed
    books unless marked as a deed of trust.

    Returns:
        List of dictionaries with book, page, and doc_type
    """
    documents = []

    # utf-8-sig drops the BOM Windows Notepad may add
    with open(txt_path, 'r', encoding='utf-8-sig') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            kind = court_record_kind(line)
            if kind:
                print(f"  Skipping line {line_num} ({kind} - not in the land records): {line}")
                continue

            parsed = parse_reference_line(line)

            if parsed:
                documents.append({
                    **parsed,
                    "row": line_num,
                    "original_ref": line
                })
            elif any(keyword in line.lower() for keyword in ['book', 'page', 'document', 'reference']):
                print(f"  Skipping header line: {line}")
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
                doc_type = doc.get("doc_type", "deed")
                label = format_reference(doc["book"], doc["page"], doc_type)
                print(f"\n[{idx}/{len(documents)}] Downloading {label}...")

                result = downloader.download_by_book_page(doc["book"], doc["page"], doc_type)

                download_results.append({
                    "ref": doc["original_ref"],
                    "label": label,
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
                label = format_reference(doc["book"], doc["page"], doc.get("doc_type", "deed"))

                try:
                    doc, result = future.result()

                    download_results.append({
                        "ref": doc["original_ref"],
                        "label": label,
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

                    print(f"[{idx}/{len(documents)}] {label}: {status}")

                except Exception as e:
                    download_results.append({
                        "ref": doc["original_ref"],
                        "label": label,
                        "book": doc["book"],
                        "page": doc["page"],
                        "success": False,
                        "source": "error",
                        "message": str(e),
                        "filepath": None
                    })
                    failed += 1
                    print(f"[{idx}/{len(documents)}] {label}: Error - {e}")

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
            lines.append(f"  {status} {r['label']} -> {filename}")
        lines.append("")

    # List failed downloads
    failed_results = [r for r in download_results if not r["success"]]
    if failed_results:
        lines.append("-" * 70)
        lines.append("FAILED DOWNLOADS")
        lines.append("-" * 70)
        for r in failed_results:
            lines.append(f"  [FAILED] {r['label']}")
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
  DT [book]/[page]          - deed of trust book, e.g., "DT 502/308"
  Lettered books            - e.g., "CCC/165"
  Book type defaults to "deed". Books < 238 and lettered books are "deed"
  unless marked DT.
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
