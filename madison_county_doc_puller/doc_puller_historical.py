import os
import re
import requests
import pandas as pd
from tkinter import Tk
from tkinter.filedialog import askopenfilename

def get_spreadsheet_path() -> str:
    """Open a file dialog to select spreadsheet."""
    Tk().withdraw()
    return askopenfilename(
        title="Select Spreadsheet",
        filetypes=[("Spreadsheet Files", "*.csv *.xls *.xlsx")]
    )

def is_valid_book(book):
    """Check if book is letters only or numeric < 3972."""
    if isinstance(book, str) and book.isalpha():
        return True
    try:
        book_num = int(book)
        return book_num < 3972
    except ValueError:
        return False

def download_deed_document(book, page, download_dir):
    """Download the PDF if valid, else return error message."""
    url = "https://tools.madison-co.net/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
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
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        
        if 'pdf' in content_type or response.content.startswith(b'%PDF-'):
            # Always use [Book]-[Page].pdf format, no leading zeros
            filename = f"{book}-{page}.pdf"
            file_path = os.path.join(download_dir, filename)
            with open(file_path, 'wb') as f:
                f.write(response.content)
            return f"Success: Downloaded PDF to {file_path}", None
        else:
            return None, "Response not a PDF"
    except requests.exceptions.RequestException as e:
        return None, f"Download error: {str(e)}"

# Main execution
if __name__ == "__main__":
    spreadsheet_path = get_spreadsheet_path()
    if not spreadsheet_path:
        print("No spreadsheet selected. Exiting.")
    else:
        download_dir = os.path.dirname(spreadsheet_path)
        log_file = os.path.join(download_dir, "failed_downloads.txt")
        
        # Read spreadsheet
        ext = os.path.splitext(spreadsheet_path)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(spreadsheet_path)
        else:  # .xls or .xlsx
            df = pd.read_excel(spreadsheet_path)
        
        # Process each row
        with open(log_file, 'w') as log:  # Create/clear log
            for _, row in df.iterrows():
                book = row['Book']
                page = row['Page']
                # Convert float to int if applicable
                if isinstance(book, float) and book.is_integer():
                    book = int(book)
                if isinstance(page, float) and page.is_integer():
                    page = int(page)
                if is_valid_book(book):
                    success, error = download_deed_document(book, page, download_dir)
                    if success:
                        print(success)
                    else:
                        log.write(f"Failed: Book {book}, Page {page} - {error}\n")
                        print(f"Failed to download Book {book}, Page {page}: {error}")
                else:
                    log.write(f"Failed: Book {book}, Page {page} - Invalid book format\n")
                    print(f"Skipped invalid Book {book}, Page {page}")