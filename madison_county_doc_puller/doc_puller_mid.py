import os
import re
import requests
import pandas as pd
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from bs4 import BeautifulSoup
from io import BytesIO
from pypdf import PdfMerger

# Document type lookup dictionary
doc_type_lookup = {
    'DEED': '01',
    'DEED OF TRUST': '02',
    'ASSIGNMENT OF DEED OF TRUST': '03',
    'POWER OF ATTORNEY': '04',
    'PARTIAL RELEASE': '05',
    'LEASE ASSIGNMENT': '06',
    'EASEMENT': '07',
    'TAX RELEASE': '08',
    'TRUSTEES DEED': '09',
    'RELEASE': '95',
    'SUBSTITUTE TRUSTEE': '11',
    'RIGHT OF WAY': '12',
    'POWER OF ATTORNEY-GENERAL': '13',
    'PROTECTIVE COVENANT': '14',
    'AMENDED PROTECTIVE COVENANT': '15',
    'AGREEMENT': '16',
    'MINERAL DEED': '17',
    'RATIFICATION': '18',
    'RENTAL ASSIGNMENT': '19',
    'MINERAL RIGHT & ROYALTY TRANSF': '20',
    'OIL GAS MINERAL LEASE': '21',
    'TRUST AGREEMENT': '22',
    'RELEASE - RIGHT OF WAY': '23',
    'FINANCING STATEMENT': '24',
    'DISCLAIMER': '25',
    'OPTION': '26',
    'PATENT': '27',
    'DECLARATION': '28',
    'AMENDED DECLARATION': '29',
    'CONTRACT TO SELL': '30',
    'AFFIDAVIT': '31',
    'JUDGMENT OR ORDER': '32',
    'SUBORDINATION': '33',
    'INDENTURE': '34',
    'TAX SALE': '35',
    'ASSUMPTION AGREEMENT': '36',
    'LEASE CONTRACT': '37',
    'ASSIGN OIL GAS & MINERAL LEASE': '38',
    'UCC FINANCING STATEMENT': '40',
    'UCC CONTINUATION': '41',
    'UCC AMENDMENT': '42',
    'UCC ASSIGNMENT': '43',
    'UCC PARTIAL RELEASE': '44',
    'UCC TERMINATION': '45',
    'AMENDMENT': '46',
    'ASSIGNMENT': '47',
    'RECEIVER': '48',
    'RENTAL DIVISION ORDER': '49',
    'REVOCATION & CANCELL OF PA': '50',
    'CONSTRUCTION LIEN': '51',
    'LIS PENDENS': '52',
    'AGREEMENT-DEEDS': '53',
    'ASSIGNMENT - DEEDS': '54',
    'RELEASE OF OIL GAS & MINERAL L': '55',
    'AMENDMENT OF OIL & GAS LEASE': '56',
    'PLAT FILED': '57',
    'DECLARATION OF ROAD CLOSURE': '58',
    'AMENDMENT TO LEASE': '59',
    'CERT DISCHARGE FEDERAL TAX LIE': '60',
    "MORTGAGEE'S WAIVER AND CONSENT": '61',
    'CONDOMINIUM LIEN': '62',
    'ASSESSMENT LIEN': '63',
    'CANCEL OF ASSESSMENT': '64',
    'CHANGE OF DEPOSITORY': '65',
    'NOTICE OF FORFEITURE': '66',
    "VENDOR'S LIEN": '67',
    'LAST WILL AND TESTAMENT': '68',
    'CERTIFICATION LANDMARK DESIG': '69',
    'MODIFICATION AGREEMENT': '70',
    'CERT OF SALE/SEIZED PROPERTY': '71',
    'RELEASE OF RIGHT OF REFUSAL': '72',
    'UCC SUBORDINATION': '73',
    'MAP': '74',
    'CERTIFICATION OF MOBILE HOME': '75',
    'ENVIRONMENTAL PROTECTION AGENC': '76',
    'RECISSION OF FORECLOSURE': '77',
    'CHARGE BACK': '78',
    'HOMESTEAD DISALLOWANCE': '79',
    'PARTIAL RELEASE OF ASSESSMENT': '80',
    'NOTICE OF LIEN': '81',
    'FEDERAL TAX LIEN': '82',
    'PARTIAL RELEASE TIMBER DEED': '83',
    'VOID LEASES 16TH SECTION': '85',
    'WAIVER': '86',
    'EMINENT DOMAIN': '87',
    'ASSIGNMENT OF LEASES RENTS & P': '88',
    'LIEN': '89',
    'RIGHT OF FIRST REFUSAL': '90',
    'SURVEYS': '91',
    'MISCELLANEOUS "W"': '92',
    'PROTECTIVE COV TERMINATION': '93',
    'LIVING WILL': '94',
    'HEIRSHIP': '96',
    'RELEASE OF CONSTRUCTION LIEN': '97',
    'SUPPLEMENT TO COVENANTS': '98',
    'RELEASE OF LIS PENDINGS': '99',
    'TERM OF FINANCING STATEMENT': 'A1',
    'ARCHITECTURAL REVIEW': 'A2',
    'MISCELLANEOUS "T"': 'A3',
    'AFFIDAVIT "T"': 'A4',
    'DEED RESTRICTIONS': 'A5',
    'NOTICE TO RENEW LEASE CONTRACT': 'A6',
    'ROYALTY DEED': 'A7'
}

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
    """Download and concatenate PDFs for books >237 by parsing HTML results and fetching image links."""
    base_url = "https://tools.madison-co.net"
    search_url = f"{base_url}/elected-offices/chancery-clerk/court-house-search/drupal-deed-record-lookup.php"
    params = {
        "grantor": "",
        "doc_type": doc_type_lookup.get('DEED', '01'),  # Default to 'DEED' code
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
        # Fetch the results page
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' in content_type:
            # Parse HTML for download links
            soup = BeautifulSoup(response.text, 'html.parser')
            download_links = soup.find_all('a', string=re.compile(r'Download Image \d+'))
            
            if not download_links:
                return None, "No download links found in results"
            
            pdf_contents = []
            for link in download_links:
                href = link['href']
                full_url = base_url + href if not href.startswith('http') else href
                img_response = requests.get(full_url, timeout=10)
                img_response.raise_for_status()
                
                img_content_type = img_response.headers.get('Content-Type', '').lower()
                if 'pdf' in img_content_type or img_response.content.startswith(b'%PDF-'):
                    pdf_contents.append(img_response.content)
                else:
                    return None, "One or more downloaded files not PDF"
            
            if not pdf_contents:
                return None, "No valid PDFs downloaded"
            
            # Concatenate PDFs
            merger = PdfMerger()
            for pdf_bytes in pdf_contents:
                merger.append(BytesIO(pdf_bytes))
            
            filename = f"{book}-{page}.pdf"
            file_path = os.path.join(download_dir, filename)
            with open(file_path, 'wb') as f:
                merger.write(f)
            merger.close()
            
            return f"Success: Downloaded and concatenated {len(pdf_contents)} PDF page(s) to {file_path}", None
        else:
            # Unexpected: direct PDF for high book?
            return None, "Unexpected response type (not HTML)"
    
    except Exception as e:  # Broad catch for any errors, including pypdf issues
        return None, f"Error: {str(e)}"

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
        
        # Process each row (assuming books in 238-3971 range)
        with open(log_file, 'w') as log:  # Create/clear log
            for _, row in df.iterrows():
                book = row['Book']
                page = row['Page']
                # Convert float to int if applicable
                if isinstance(book, float) and book.is_integer():
                    book = int(book)
                if isinstance(page, float) and page.is_integer():
                    page = int(page)
                if is_valid_book(book) and (isinstance(book, str) or book > 237):
                    success, error = download_deed_document(book, page, download_dir)
                    if success:
                        print(success)
                    else:
                        log.write(f"Failed: Book {book}, Page {page} - {error}\n")
                        print(f"Failed to download Book {book}, Page {page}: {error}")
                else:
                    log.write(f"Failed: Book {book}, Page {page} - Invalid book format or range\n")
                    print(f"Skipped invalid Book {book}, Page {page}")