#!/usr/bin/env python3
"""
Manual document uploader for GCS.

This script provides a GUI interface to:
1. Select PDF documents to upload
2. Confirm/enter book and page numbers for each document
3. Upload to GCS with proper naming convention (XXXX-XXXX.pdf)
4. Update the appropriate CSV inventory file
"""

import os
import sys
import csv
import logging
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from dotenv import load_dotenv

# Add project modules to path
sys.path.insert(0, str(Path(__file__).parent))

from madison_county_doc_puller.gcs_manager import GCSManager
from madison_county_doc_puller.pdf_optimizer import PDFOptimizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


@dataclass
class DocumentInfo:
    """Information about a document to upload."""
    local_path: Path
    book: int
    page: int
    doc_type: str = "unknown"


def get_folder_prefix(book: int) -> str:
    """Determine GCS folder prefix based on book number."""
    if book < 238:
        return "historical"
    elif book < 1000:
        return "mid-early"
    else:
        return "mid-recent"


def get_csv_file(book: int) -> str:
    """Determine which CSV file to update based on book number."""
    project_root = Path(__file__).parent
    if book < 238:
        return str(project_root / "available_deeds_historical.csv")
    elif book < 1000:
        return str(project_root / "available_deeds_mid_early.csv")
    else:
        return str(project_root / "available_deeds_mid_recent.csv")


def format_gcs_path(book: int, page: int, doc_type: str) -> str:
    """Format the GCS path for a document."""
    folder_prefix = get_folder_prefix(book)
    return f"documents/{folder_prefix}/{doc_type}/{book:04d}-{page:04d}.pdf"


def format_filename(book: int, page: int) -> str:
    """Format the filename for a document (XXXX-XXXX.pdf)."""
    return f"{book:04d}-{page:04d}.pdf"


def try_parse_book_page_from_filename(filename: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Attempt to parse book and page from filename.

    Supports formats:
    - XXXX-XXXX.pdf (e.g., 0401-0342.pdf)
    - Book_XXX_Page_XXX.pdf
    - Various other common formats
    """
    import re

    # Try XXXX-XXXX format
    match = re.match(r'^(\d{4})-(\d{4})\.pdf$', filename, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))

    # Try Book_XXX_Page_XXX format
    match = re.search(r'book[_\s]*(\d+)[_\s]*page[_\s]*(\d+)', filename, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))

    # Try simple number-number format
    match = re.match(r'^(\d+)-(\d+)\.pdf$', filename, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))

    return None, None


class BookPageDialog(tk.Toplevel):
    """Dialog to confirm or enter book and page numbers."""

    def __init__(self, parent, filename: str, suggested_book: Optional[int] = None,
                 suggested_page: Optional[int] = None):
        super().__init__(parent)
        self.title("Confirm Book and Page")
        self.result = None

        # Make dialog modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.geometry("400x250")

        # File info
        tk.Label(self, text="File:", font=('TkDefaultFont', 10, 'bold')).grid(
            row=0, column=0, sticky='e', padx=10, pady=10)
        tk.Label(self, text=filename, wraplength=280).grid(
            row=0, column=1, sticky='w', padx=10, pady=10)

        # Book entry
        tk.Label(self, text="Book Number:", font=('TkDefaultFont', 10, 'bold')).grid(
            row=1, column=0, sticky='e', padx=10, pady=10)
        self.book_var = tk.StringVar(value=str(suggested_book) if suggested_book else "")
        self.book_entry = tk.Entry(self, textvariable=self.book_var, width=10)
        self.book_entry.grid(row=1, column=1, sticky='w', padx=10, pady=10)

        # Page entry
        tk.Label(self, text="Page Number:", font=('TkDefaultFont', 10, 'bold')).grid(
            row=2, column=0, sticky='e', padx=10, pady=10)
        self.page_var = tk.StringVar(value=str(suggested_page) if suggested_page else "")
        self.page_entry = tk.Entry(self, textvariable=self.page_var, width=10)
        self.page_entry.grid(row=2, column=1, sticky='w', padx=10, pady=10)

        # Document type dropdown
        tk.Label(self, text="Document Type:", font=('TkDefaultFont', 10, 'bold')).grid(
            row=3, column=0, sticky='e', padx=10, pady=10)
        self.doc_type_var = tk.StringVar(value="deed")
        doc_types = ["deed", "deed-of-trust", "unknown", "release", "assignment",
                     "power-of-attorney", "easement", "lease", "other"]
        self.doc_type_combo = ttk.Combobox(self, textvariable=self.doc_type_var,
                                           values=doc_types, width=20)
        self.doc_type_combo.grid(row=3, column=1, sticky='w', padx=10, pady=10)

        # Preview of GCS path
        self.preview_label = tk.Label(self, text="", fg="gray")
        self.preview_label.grid(row=4, column=0, columnspan=2, pady=5)

        # Update preview when values change
        self.book_var.trace('w', self._update_preview)
        self.page_var.trace('w', self._update_preview)
        self.doc_type_var.trace('w', self._update_preview)
        self._update_preview()

        # Buttons
        button_frame = tk.Frame(self)
        button_frame.grid(row=5, column=0, columnspan=2, pady=20)

        tk.Button(button_frame, text="OK", command=self._on_ok, width=10).pack(side='left', padx=5)
        tk.Button(button_frame, text="Skip", command=self._on_skip, width=10).pack(side='left', padx=5)
        tk.Button(button_frame, text="Cancel All", command=self._on_cancel, width=10).pack(side='left', padx=5)

        # Focus book entry
        self.book_entry.focus_set()

        # Bind Enter key
        self.bind('<Return>', lambda e: self._on_ok())
        self.bind('<Escape>', lambda e: self._on_cancel())

        # Wait for dialog to close
        self.wait_window()

    def _update_preview(self, *args):
        """Update the GCS path preview."""
        try:
            book = int(self.book_var.get()) if self.book_var.get() else 0
            page = int(self.page_var.get()) if self.page_var.get() else 0
            doc_type = self.doc_type_var.get()
            if book > 0 and page > 0:
                gcs_path = format_gcs_path(book, page, doc_type)
                self.preview_label.config(text=f"GCS Path: {gcs_path}")
            else:
                self.preview_label.config(text="Enter book and page numbers")
        except ValueError:
            self.preview_label.config(text="Invalid number format")

    def _on_ok(self):
        """Handle OK button click."""
        try:
            book = int(self.book_var.get())
            page = int(self.page_var.get())
            doc_type = self.doc_type_var.get()

            if book <= 0 or page <= 0:
                messagebox.showerror("Invalid Input", "Book and page must be positive numbers")
                return

            self.result = (book, page, doc_type)
            self.destroy()
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numbers for book and page")

    def _on_skip(self):
        """Handle Skip button click."""
        self.result = "skip"
        self.destroy()

    def _on_cancel(self):
        """Handle Cancel button click."""
        self.result = "cancel"
        self.destroy()


def add_to_csv(csv_file: str, book: int, page: int, doc_type: str,
               gcs_path: str, size_bytes: int):
    """Add a new entry to the CSV file in sorted order."""
    rows = []
    header = None

    # Read existing CSV
    if os.path.exists(csv_file):
        with open(csv_file, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                rows.append(row)
    else:
        header = ['Book', 'Page', 'Document Type', 'GCS Path', 'Size (bytes)']

    # Create new row
    new_row = [str(book), str(page), doc_type, gcs_path, str(size_bytes)]

    # Check if entry already exists
    for i, row in enumerate(rows):
        if len(row) >= 2 and int(row[0]) == book and int(row[1]) == page:
            # Update existing entry
            rows[i] = new_row
            logger.info(f"Updated existing entry in CSV: Book {book}, Page {page}")
            break
    else:
        # Add new entry
        rows.append(new_row)
        logger.info(f"Added new entry to CSV: Book {book}, Page {page}")

    # Sort by book, then page
    rows.sort(key=lambda r: (int(r[0]), int(r[1])))

    # Write back to CSV
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class ManualUploader:
    """Main uploader application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # Hide main window

        # Initialize GCS manager
        bucket_name = os.getenv('GCS_BUCKET_NAME', 'madison-county-title-plant')
        credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

        logger.info(f"Connecting to GCS bucket: {bucket_name}")
        self.gcs_manager = GCSManager(bucket_name, credentials_path)

        # Initialize PDF optimizer (optional)
        try:
            self.pdf_optimizer = PDFOptimizer(quality='ebook')
            self.optimize_enabled = True
            logger.info("PDF optimization enabled")
        except Exception as e:
            logger.warning(f"PDF optimization disabled: {e}")
            self.pdf_optimizer = None
            self.optimize_enabled = False

    def select_files(self) -> List[Path]:
        """Open file dialog to select PDF files."""
        filetypes = [
            ('PDF files', '*.pdf'),
            ('All files', '*.*')
        ]

        files = filedialog.askopenfilenames(
            title="Select documents to upload",
            filetypes=filetypes
        )

        return [Path(f) for f in files]

    def get_document_info(self, file_path: Path) -> Optional[DocumentInfo]:
        """Get book and page info for a document via dialog."""
        # Try to parse from filename
        suggested_book, suggested_page = try_parse_book_page_from_filename(file_path.name)

        # Show dialog
        dialog = BookPageDialog(
            self.root,
            file_path.name,
            suggested_book,
            suggested_page
        )

        if dialog.result == "cancel":
            return None
        elif dialog.result == "skip":
            return "skip"
        else:
            book, page, doc_type = dialog.result
            return DocumentInfo(
                local_path=file_path,
                book=book,
                page=page,
                doc_type=doc_type
            )

    def upload_document(self, doc_info: DocumentInfo) -> bool:
        """Upload a single document to GCS and update CSV."""
        try:
            file_to_upload = doc_info.local_path
            original_size = file_to_upload.stat().st_size

            # Optimize PDF if enabled
            if self.optimize_enabled and self.pdf_optimizer:
                optimize_prompt = messagebox.askyesno(
                    "Optimize PDF?",
                    f"Do you want to optimize {doc_info.local_path.name} before uploading?\n\n"
                    f"Current size: {original_size:,} bytes"
                )

                if optimize_prompt:
                    # Create optimized version
                    optimized_path = doc_info.local_path.parent / f"{doc_info.local_path.stem}_optimized.pdf"
                    _, original_size, optimized_size = self.pdf_optimizer.optimize(
                        doc_info.local_path,
                        optimized_path
                    )
                    file_to_upload = optimized_path
                    logger.info(f"Optimized: {original_size:,} -> {optimized_size:,} bytes")

            # Determine GCS path
            gcs_path = format_gcs_path(doc_info.book, doc_info.page, doc_info.doc_type)

            # Check if file already exists in GCS
            if self.gcs_manager.file_exists(gcs_path):
                overwrite = messagebox.askyesno(
                    "File Exists",
                    f"A file already exists at:\n{gcs_path}\n\nOverwrite?"
                )
                if not overwrite:
                    logger.info(f"Skipped (already exists): {gcs_path}")
                    return False

            # Upload to GCS
            metadata = {
                'book': str(doc_info.book),
                'page': str(doc_info.page),
                'document_type': doc_info.doc_type,
                'original_filename': doc_info.local_path.name,
                'manual_upload': 'true'
            }

            gcs_url, checksum = self.gcs_manager.upload_file(
                file_to_upload,
                gcs_path,
                metadata=metadata
            )

            # Get file size for CSV
            file_size = file_to_upload.stat().st_size

            # Update CSV
            csv_file = get_csv_file(doc_info.book)
            add_to_csv(csv_file, doc_info.book, doc_info.page, doc_info.doc_type,
                      gcs_path, file_size)

            # Clean up optimized file if we created one
            if file_to_upload != doc_info.local_path and file_to_upload.exists():
                file_to_upload.unlink()

            logger.info(f"Successfully uploaded: {gcs_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to upload {doc_info.local_path}: {e}")
            messagebox.showerror("Upload Failed", f"Failed to upload {doc_info.local_path.name}:\n{e}")
            return False

    def run(self):
        """Run the uploader."""
        # Select files
        files = self.select_files()

        if not files:
            logger.info("No files selected")
            return

        logger.info(f"Selected {len(files)} file(s)")

        # Process each file
        uploaded = 0
        skipped = 0
        failed = 0

        for file_path in files:
            # Get document info
            doc_info = self.get_document_info(file_path)

            if doc_info is None:
                # Cancel all
                logger.info("Upload cancelled by user")
                break
            elif doc_info == "skip":
                skipped += 1
                continue

            # Upload
            if self.upload_document(doc_info):
                uploaded += 1
            else:
                failed += 1

        # Show summary
        summary = f"Upload Complete\n\n"
        summary += f"Uploaded: {uploaded}\n"
        summary += f"Skipped: {skipped}\n"
        summary += f"Failed: {failed}"

        messagebox.showinfo("Summary", summary)
        logger.info(summary.replace('\n', ' '))

        # Cleanup
        self.root.destroy()


def main():
    """Main entry point."""
    print("=" * 60)
    print("Madison County Manual Document Uploader")
    print("=" * 60)

    try:
        uploader = ManualUploader()
        uploader.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        messagebox.showerror("Error", f"An error occurred:\n{e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
