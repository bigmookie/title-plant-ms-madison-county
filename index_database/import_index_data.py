#!/usr/bin/env python3
"""
Madison County Title Plant - Index Data Import Script

Imports pre-existing index data from:
1. DuProcess Indexes (1985-2025, all Excel files in madison_docs/DuProcess Indexes/)
2. Historic Deeds checklist (madison_docs/Deeds - Historic - Typewritten Only.xlsx)

This data is used for:
- Document download queue management
- Validation of production database (populated from OCR)
"""

import os
import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set
from datetime import datetime
from enum import Enum
import logging

import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
from tqdm import tqdm


# ============================================================================
# Configuration
# ============================================================================

# Database connection settings (via Cloud SQL Auth Proxy)
DB_CONFIG = {
    'host': '127.0.0.1',  # Cloud SQL Auth Proxy
    'port': 5432,
    'database': 'madison_county_index',
    'user': os.getenv('DB_USER', 'madison_index_app'),
    'password': os.getenv('DB_PASSWORD', ''),
}

# File paths
BASE_DIR = Path(__file__).parent.parent
DUPROCESS_DIR = BASE_DIR / 'madison_docs' / 'DuProcess Indexes'
HISTORIC_DEEDS_FILE = BASE_DIR / 'madison_docs' / 'Deeds - Historic - Typewritten Only.xlsx'

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('index_import.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# Document Type Mappings (from data-models-spec.md)
# ============================================================================

class DocumentType(str, Enum):
    """Document type enumeration from data-models-spec.md"""
    # CONVEYANCE
    DEED = "DEED"
    QUITCLAIM_DEED = "QUITCLAIM_DEED"
    TRUSTEES_DEED = "TRUSTEES_DEED"
    TAX_DEED = "TAX_DEED"
    TRANSFER_ON_DEATH_DEED = "TRANSFER_ON_DEATH_DEED"
    PATENT = "PATENT"
    LEASE = "LEASE"
    MINERAL_DEED = "MINERAL_DEED"
    ROYALTY_DEED = "ROYALTY_DEED"

    # SECURITY
    DEED_OF_TRUST = "DEED_OF_TRUST"
    MORTGAGE = "MORTGAGE"
    VENDORS_LIEN = "VENDORS_LIEN"
    ASSIGNMENT_OF_LEASES_AND_RENTS = "ASSIGNMENT_OF_LEASES_AND_RENTS"

    # SERVITUDES
    EASEMENT = "EASEMENT"
    RIGHT_OF_WAY = "RIGHT_OF_WAY"
    PROTECTIVE_COVENANT = "PROTECTIVE_COVENANT"
    CCRS = "CCRS"
    DEED_RESTRICTIONS = "DEED_RESTRICTIONS"

    # INVOLUNTARY LIENS
    CONSTRUCTION_LIEN = "CONSTRUCTION_LIEN"
    FEDERAL_TAX_LIEN = "FEDERAL_TAX_LIEN"
    TAX_SALE = "TAX_SALE"
    ASSESSMENT_LIEN = "ASSESSMENT_LIEN"
    JUDGMENT = "JUDGMENT"
    LIS_PENDENS = "LIS_PENDENS"
    UCC = "UCC"
    UCC_CONTINUATION = "UCC_CONTINUATION"
    UCC_TERMINATION = "UCC_TERMINATION"
    UCC_AMENDMENT = "UCC_AMENDMENT"
    UCC_PARTIAL_RELEASE = "UCC_PARTIAL_RELEASE"
    CONDOMINIUM_LIEN = "CONDOMINIUM_LIEN"

    # CHANGE
    RELEASE = "RELEASE"
    PARTIAL_RELEASE = "PARTIAL_RELEASE"
    ASSIGNMENT = "ASSIGNMENT"
    MODIFICATION_AGREEMENT = "MODIFICATION_AGREEMENT"
    SUBORDINATION = "SUBORDINATION"
    SUBSTITUTION_OF_TRUSTEE = "SUBSTITUTION_OF_TRUSTEE"
    SUPPLEMENT = "SUPPLEMENT"
    AMENDMENT = "AMENDMENT"
    CANCELLATION = "CANCELLATION"
    TAX_RELEASE = "TAX_RELEASE"

    # OTHER
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY"
    AFFIDAVIT = "AFFIDAVIT"
    AGREEMENT = "AGREEMENT"
    TRUST_AGREEMENT = "TRUST_AGREEMENT"
    PLAT = "PLAT"
    SUBDIVISION_PLAT = "SUBDIVISION_PLAT"
    LAST_WILL_AND_TESTAMENT = "LAST_WILL_AND_TESTAMENT"
    HEIRSHIP = "HEIRSHIP"
    DISCLAIMER = "DISCLAIMER"
    NOTICE = "NOTICE"
    CERTIFICATION = "CERTIFICATION"
    DECLARATION = "DECLARATION"

    # OIL, GAS & MINERAL
    OIL_GAS_LEASE = "OIL_GAS_LEASE"
    POOLING_AGREEMENT = "POOLING_AGREEMENT"
    UNITIZATION_AGREEMENT = "UNITIZATION_AGREEMENT"
    DIVISION_ORDER = "DIVISION_ORDER"

    UNKNOWN = "UNKNOWN"


# DuProcess instrument type mapping (from data-models-spec.md)
DUPROCESS_TYPE_MAPPING = {
    # Most common types (>10,000 occurrences)
    "DEED OF TRUST": DocumentType.DEED_OF_TRUST,
    "POWER OF ATTORNEY": DocumentType.POWER_OF_ATTORNEY,
    "DEED": DocumentType.DEED,
    "TAX RELEASE": DocumentType.TAX_RELEASE,
    "ASSIGNMENT OF DEED O": DocumentType.ASSIGNMENT,
    "UCC (CONVERTED)": DocumentType.UCC,
    "TAX SALE": DocumentType.TAX_SALE,
    "PARTIAL RELEASE": DocumentType.PARTIAL_RELEASE,
    "UCC TERM": DocumentType.UCC_TERMINATION,
    "ASSESSMENT LIEN": DocumentType.ASSESSMENT_LIEN,
    "RIGHT OF WAY": DocumentType.RIGHT_OF_WAY,
    "MODIFICATION AGREEME": DocumentType.MODIFICATION_AGREEMENT,
    "OIL GAS MINERAL LEAS": DocumentType.OIL_GAS_LEASE,
    "SUBSTITUTE TRUSTEE": DocumentType.SUBSTITUTION_OF_TRUSTEE,

    # Common types (1,000-10,000 occurrences)
    "EASEMENT": DocumentType.EASEMENT,
    "FEDERAL TAX LIEN": DocumentType.FEDERAL_TAX_LIEN,
    "LEASE ASSIGNMENT": DocumentType.ASSIGNMENT,
    "SUBORDINATION": DocumentType.SUBORDINATION,
    "AFFIDAVIT": DocumentType.AFFIDAVIT,
    "TRUSTEES DEED": DocumentType.TRUSTEES_DEED,
    "CONSTRUCTION LIEN": DocumentType.CONSTRUCTION_LIEN,
    "SUBDIVISION PLATS": DocumentType.SUBDIVISION_PLAT,
    "JUDGMENT OR ORDER": DocumentType.JUDGMENT,
    "FEDERAL TAX LIENS": DocumentType.FEDERAL_TAX_LIEN,
    "LIS PENDENS": DocumentType.LIS_PENDENS,
    "UCC CONT": DocumentType.UCC_CONTINUATION,
    "UCC ASGN": DocumentType.ASSIGNMENT,
    "MINERAL DEED": DocumentType.MINERAL_DEED,

    # Less common types
    "PROTECTIVE COVENANT": DocumentType.PROTECTIVE_COVENANT,
    "PATENT": DocumentType.PATENT,
    "TRANSFER ON DEATH DE": DocumentType.TRANSFER_ON_DEATH_DEED,
    "AFFIDAVIT OF HEIRSHI": DocumentType.HEIRSHIP,
    "NOTICE OF FEDERAL TA": DocumentType.FEDERAL_TAX_LIEN,
    "QUITCLAIM DEED": DocumentType.QUITCLAIM_DEED,
    "TAX DEED": DocumentType.TAX_DEED,
    "LAST WILL AND TESTAM": DocumentType.LAST_WILL_AND_TESTAMENT,
    "NOTICE OF LIEN": DocumentType.ASSESSMENT_LIEN,
    "DEED RESTRICTIONS": DocumentType.DEED_RESTRICTIONS,
    "UCC PART": DocumentType.UCC_PARTIAL_RELEASE,
    "DECLARATION": DocumentType.DECLARATION,
    "ROYALTY DEED": DocumentType.ROYALTY_DEED,
    "OIL GAS ROYALTY DEED": DocumentType.ROYALTY_DEED,
    "CONSTRUCTION LIENS": DocumentType.CONSTRUCTION_LIEN,
    "TAX SALE 2": DocumentType.TAX_SALE,
    "CONDOMINIUM LIEN": DocumentType.CONDOMINIUM_LIEN,
    "PLATS": DocumentType.PLAT,
    "VENDORS LIEN": DocumentType.VENDORS_LIEN,
    "UCC AMND": DocumentType.UCC_AMENDMENT,
    "TIMBER DEED": DocumentType.DEED,
    "DISCLAIMER": DocumentType.DISCLAIMER,
    "CORRECTIVE DEED": DocumentType.DEED,
    "AGREEMENT": DocumentType.AGREEMENT,
    "CANCELLATION": DocumentType.CANCELLATION,
    "SUPPLEMENT": DocumentType.SUPPLEMENT,
    "POOLING AGREEMENT": DocumentType.POOLING_AGREEMENT,
    "AMENDMENT": DocumentType.AMENDMENT,
    "MISCELLANEOUS": DocumentType.AGREEMENT,
    "OIL GAS AFFIDAVIT": DocumentType.AFFIDAVIT,
    "NOTICE": DocumentType.NOTICE,
    "ROYALTY TRANSFERS": DocumentType.ROYALTY_DEED,
    "CORRECTIVE DEED OF T": DocumentType.DEED_OF_TRUST,
    "CERTIFIED COPY": DocumentType.AGREEMENT,
    "LEASE": DocumentType.LEASE,
    "TIMBER LEASE": DocumentType.LEASE,
    "RENEWAL AND EXTENSIO": DocumentType.MODIFICATION_AGREEMENT,
    "TRUSTEE'S DEED": DocumentType.TRUSTEES_DEED,
    "TAX CERTIFICATE": DocumentType.TAX_SALE,
    "REVISION": DocumentType.MODIFICATION_AGREEMENT,
    "TRUST AGREEMENT": DocumentType.TRUST_AGREEMENT,
    "LIMITED WARRANTY DEE": DocumentType.DEED,
    "COURT ORDER": DocumentType.JUDGMENT,
    "CORRECTIVE AFFIDAVIT": DocumentType.AFFIDAVIT,
    "ROAD DEDICATION": DocumentType.RIGHT_OF_WAY,
    "UCC RELEASE": DocumentType.RELEASE,
    "DEED OF GIFT": DocumentType.DEED,
    "RELEASE OF VENDOR'S": DocumentType.RELEASE,
    "RATIFICATION": DocumentType.AGREEMENT,
    "ORDINANCE": DocumentType.AGREEMENT,
    "ASSIGNMENT OF LEASE": DocumentType.ASSIGNMENT,
    "SUBORDINATION AGREEM": DocumentType.SUBORDINATION,
    "REDEMPTION": DocumentType.DEED,
    "CORRECTIVE OIL GAS M": DocumentType.OIL_GAS_LEASE,
    "MINERAL LEASE": DocumentType.OIL_GAS_LEASE,
    "RELEASE DEED OF TRUS": DocumentType.RELEASE,
    "BOUNDARY LINE AGREEM": DocumentType.AGREEMENT,
    "UNITIZATION AGREEMEN": DocumentType.UNITIZATION_AGREEMENT,
    "OIL GAS MINERAL ROY": DocumentType.ROYALTY_DEED,
    "DEED OF CONFIRMATION": DocumentType.DEED,
    "TIMBER CONTRACT": DocumentType.LEASE,
    "MEMORANDUM": DocumentType.AGREEMENT,
    "STATE TAX LIEN": DocumentType.ASSESSMENT_LIEN,
    "IRS LIEN": DocumentType.FEDERAL_TAX_LIEN,
    "RELEASE OF LIS PENDE": DocumentType.RELEASE,
    "PARTIAL RECONVEYANCE": DocumentType.PARTIAL_RELEASE,
    "DEED OF ACQUITTANCE": DocumentType.DEED,
    "UCC SEARCH": DocumentType.UCC,
    "DIVISION ORDER": DocumentType.DIVISION_ORDER,
    "CORRECTIVE PATENT": DocumentType.PATENT,
    "APPOINTMENT OF SUCCE": DocumentType.SUBSTITUTION_OF_TRUSTEE,
    "CERTIFICATION": DocumentType.CERTIFICATION,
    "PERMIT": DocumentType.AGREEMENT,
    "RESOLUTION": DocumentType.AGREEMENT,
    "SPECIAL WARRANTY DEE": DocumentType.DEED,
    "PROBATE": DocumentType.JUDGMENT,
    "CONVEYANCE": DocumentType.DEED,
    "REDEMPTION DEED": DocumentType.DEED,
    "CERTIFICATE": DocumentType.CERTIFICATION,
    "CERTIFIED COPY ORDIN": DocumentType.AGREEMENT,
    "WILL": DocumentType.LAST_WILL_AND_TESTAMENT,
    "RELEASE FED TAX LIEN": DocumentType.TAX_RELEASE,
    "CONTRACT": DocumentType.AGREEMENT,
    "CORRECTIVE SUBDIVISI": DocumentType.SUBDIVISION_PLAT,
    "RELEASE OF EASEMENT": DocumentType.RELEASE,
    "AFFIDAVIT OF DEATH": DocumentType.AFFIDAVIT,
    "RECONVEYANCE": DocumentType.RELEASE,
    "CORRECTIVE QUITCLAIM": DocumentType.QUITCLAIM_DEED,
    "WAIVER": DocumentType.AGREEMENT,
    "PARTITION DEED": DocumentType.DEED,
    "RIGHT OF WAY AGREEME": DocumentType.RIGHT_OF_WAY,
    "MORTGAGE": DocumentType.MORTGAGE,
    "CORRECTIVE PARTIAL R": DocumentType.PARTIAL_RELEASE,
    "BILL OF SALE": DocumentType.DEED,
    "CONDEMNATION": DocumentType.JUDGMENT,
    "SHERIFF'S DEED": DocumentType.DEED,
    "RELEASE OF MORTGAGE": DocumentType.RELEASE,
    "OPTION": DocumentType.AGREEMENT,
    "DONATION": DocumentType.DEED,
    "RELEASE CONSTRUCTION": DocumentType.RELEASE,
    "MODIFICATION AND SUP": DocumentType.MODIFICATION_AGREEMENT,
    "DEED OF EXCHANGE": DocumentType.DEED,
    "RELEASE ASSESSMENT L": DocumentType.RELEASE,
    "APPOINTMENT": DocumentType.POWER_OF_ATTORNEY,
    "RELEASE OF JUDGEMENT": DocumentType.RELEASE,
    "CORRECTIVE ASSIGNMEN": DocumentType.ASSIGNMENT,
    "HEIRSHIP": DocumentType.HEIRSHIP,
    "RATIFICATION AND REN": DocumentType.MODIFICATION_AGREEMENT,
    "ASSIGNMENT OF CONTR": DocumentType.ASSIGNMENT,
    "CORRECTIVE TRANSFER": DocumentType.TRANSFER_ON_DEATH_DEED,
    "AFFIDAVIT OF IDENTIT": DocumentType.AFFIDAVIT,
    "RESERVATION": DocumentType.DEED,
    "WARRANTY DEED": DocumentType.DEED,
    "SUBORDINATION AND AT": DocumentType.SUBORDINATION,
    "SUBDIVISION CORRECTI": DocumentType.SUBDIVISION_PLAT,
    "RELEASE ABSTRACT OF": DocumentType.RELEASE,
    "SATISFACTION": DocumentType.RELEASE,
    "UCC INFO": DocumentType.UCC,
    "EXECUTION": DocumentType.JUDGMENT,
    "ASSIGNMENT OF MORTGA": DocumentType.ASSIGNMENT,
    "PARTIAL RELEASE DEED": DocumentType.PARTIAL_RELEASE,
    "LAND PATENT": DocumentType.PATENT,
    "OIL GAS MINERAL TRAN": DocumentType.MINERAL_DEED,
    "NOTICE OF TAX SALE": DocumentType.TAX_SALE,
    "CANCELLATION AND REL": DocumentType.CANCELLATION,
    "REVOCATION": DocumentType.POWER_OF_ATTORNEY,
    "CORRECTIVE WARRANTY": DocumentType.DEED,
    "ESCROW AGREEMENT": DocumentType.AGREEMENT,
    "ABSTRACT OF JUDGMENT": DocumentType.JUDGMENT,
    "SURRENDER": DocumentType.RELEASE,
    "SUBORDINATION OF VEN": DocumentType.SUBORDINATION,
    "EXTENSION AGREEMENT": DocumentType.MODIFICATION_AGREEMENT,
    "AMENDMENT TO EASEMEN": DocumentType.EASEMENT,
}


# ============================================================================
# Instrument Type Parsing
# ============================================================================

def parse_instrument_type(raw_type: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse InstrumentType field from DuProcess.

    Format: 'INSTRUMENT_NAME - [BOOK_TYPE CODE]'
    Example: 'DEED OF TRUST - [DOT 3972]'

    Returns:
        Tuple of (parsed_type, document_type)
        - parsed_type: Text before ' - ' (used for classification)
        - document_type: Mapped DocumentType enum value
    """
    if not raw_type or pd.isna(raw_type):
        return None, None

    raw_type_str = str(raw_type).strip()

    # Extract text before ' - '
    if ' - ' in raw_type_str:
        parsed = raw_type_str.split(' - ')[0].strip().upper()
    else:
        parsed = raw_type_str.upper()

    # Map to DocumentType enum
    doc_type = DUPROCESS_TYPE_MAPPING.get(parsed, DocumentType.UNKNOWN)

    return parsed, doc_type.value


# ============================================================================
# Data Conversion Helpers
# ============================================================================

def safe_int(value: Any) -> Optional[int]:
    """Safely convert value to integer, return None if invalid"""
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def safe_str(value: Any) -> Optional[str]:
    """Safely convert value to string, return None if empty/null"""
    if pd.isna(value):
        return None
    s = str(value).strip()
    return s if s and s != 'nan' else None


def safe_bool(value: Any) -> Optional[bool]:
    """Safely convert value to boolean"""
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def safe_timestamp(value: Any) -> Optional[datetime]:
    """Safely convert value to timestamp"""
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(value)
    except:
        return None


# ============================================================================
# Database Operations
# ============================================================================

class IndexDatabase:
    """Database connection and operations manager"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.conn = None
        self.cursor = None

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**self.config)
            self.cursor = self.conn.cursor()
            logger.info("Connected to database successfully")
        except psycopg2.Error as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Database connection closed")

    def check_existing_records(self, source: str) -> int:
        """Check how many records already exist for a source"""
        query = "SELECT COUNT(*) FROM index_documents WHERE source = %s"
        self.cursor.execute(query, (source,))
        count = self.cursor.fetchone()[0]
        return count

    def insert_batch(self, records: List[Dict[str, Any]], batch_size: int = 1000):
        """Insert records in batches"""
        if not records:
            return

        # Define column order for INSERT
        columns = [
            'source', 'source_file', 'gin', 'instrument_number', 'book_volume',
            'book', 'page', 'instrument_type_raw', 'instrument_type_parsed',
            'document_type', 'file_date', 'num_pages', 'party_type', 'party_seq',
            'searched_name', 'cross_party_name', 'grantor_party', 'grantee_party',
            'description', 'location', 'direction', 'legals', 'sub_div', 'block',
            'lot', 'sec', 'town', 'rng', 'square', 'remarks',
            'ne_of_ne', 'nw_of_ne', 'sw_of_ne', 'se_of_ne',
            'ne_of_nw', 'nw_of_nw', 'sw_of_nw', 'se_of_nw',
            'ne_of_sw', 'nw_of_sw', 'sw_of_sw', 'se_of_sw',
            'ne_of_se', 'nw_of_se', 'sw_of_se', 'se_of_se',
            'address', 'street_name', 'city', 'zip', 'parcel_num',
            'parcel_id', 'ppin', 'patent_num',
            'workflow_status', 'verified_status', 'doc_status', 'related_items'
        ]

        # Build INSERT statement with ON CONFLICT handling
        placeholders = ', '.join(['%s'] * len(columns))
        columns_str = ', '.join(columns)

        insert_query = f"""
            INSERT INTO index_documents ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT (book, page, source) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP,
                source_file = EXCLUDED.source_file
        """

        # Convert records to tuples
        values = [
            tuple(record.get(col) for col in columns)
            for record in records
        ]

        # Execute batch insert
        try:
            execute_batch(self.cursor, insert_query, values, page_size=batch_size)
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Batch insert failed: {e}")
            raise


# ============================================================================
# Data Loading Functions
# ============================================================================

def load_duprocess_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Load a single DuProcess Excel file and convert to records.

    Args:
        file_path: Path to Excel file

    Returns:
        List of record dictionaries ready for database insertion
    """
    try:
        df = pd.read_excel(file_path)
        logger.info(f"Loaded {len(df)} rows from {file_path.name}")
    except Exception as e:
        logger.error(f"Failed to load {file_path.name}: {e}")
        return []

    records = []

    for _, row in df.iterrows():
        # Parse instrument type
        raw_instrument_type = safe_str(row.get('InstrumentType'))
        parsed_type, doc_type = parse_instrument_type(raw_instrument_type)

        # Build record
        record = {
            'source': 'DuProcess',
            'source_file': file_path.name,
            'gin': safe_int(row.get('Gin')),
            'instrument_number': safe_int(row.get('Instrument #')),
            'book_volume': safe_str(row.get('Book/Volume')),
            'book': safe_int(row.get('Book')),
            'page': safe_int(row.get('Page')),
            'instrument_type_raw': raw_instrument_type,
            'instrument_type_parsed': parsed_type,
            'document_type': doc_type,
            'file_date': safe_timestamp(row.get('FileDate')),
            'num_pages': safe_int(row.get('Num Pages')),
            'party_type': safe_str(row.get('PartyType')),
            'party_seq': safe_int(row.get('PartySeq')),
            'searched_name': safe_str(row.get('Searched Name')),
            'cross_party_name': safe_str(row.get('Cross Party Name')),
            'grantor_party': safe_str(row.get('Grantor Party')),
            'grantee_party': safe_str(row.get('Grantee Party')),
            'description': safe_str(row.get('Description')),
            'location': safe_str(row.get('Location')),
            'direction': safe_str(row.get('Direction')),
            'legals': safe_str(row.get('Legals')),
            'sub_div': safe_str(row.get('Sub Div')),
            'block': safe_str(row.get('Block')),
            'lot': safe_str(row.get('Lot')),
            'sec': safe_int(row.get('Sec')),
            'town': safe_str(row.get('Town')),
            'rng': safe_str(row.get('Rng')),
            'square': safe_str(row.get('Square')),
            'remarks': safe_str(row.get('Remarks')),
            # Quarter sections
            'ne_of_ne': safe_bool(row.get('NEofNE')),
            'nw_of_ne': safe_bool(row.get('NWofNE')),
            'sw_of_ne': safe_bool(row.get('SWofNE')),
            'se_of_ne': safe_bool(row.get('SEofNE')),
            'ne_of_nw': safe_bool(row.get('NEofNW')),
            'nw_of_nw': safe_bool(row.get('NWofNW')),
            'sw_of_nw': safe_bool(row.get('SWofNW')),
            'se_of_nw': safe_bool(row.get('SEofNW')),
            'ne_of_sw': safe_bool(row.get('NEofSW')),
            'nw_of_sw': safe_bool(row.get('NWofSW')),
            'sw_of_sw': safe_bool(row.get('SWofSW')),
            'se_of_sw': safe_bool(row.get('SEofSW')),
            'ne_of_se': safe_bool(row.get('NEofSE')),
            'nw_of_se': safe_bool(row.get('NWofSE')),
            'sw_of_se': safe_bool(row.get('SWofSE')),
            'se_of_se': safe_bool(row.get('SEofSE')),
            # Modern identifiers
            'address': safe_str(row.get('Address')),
            'street_name': safe_str(row.get('Street Name')),
            'city': safe_str(row.get('City')),
            'zip': safe_str(row.get('Zip')),
            'parcel_num': safe_str(row.get('Parcel Num')),
            'parcel_id': safe_str(row.get('Parcel ID')),
            'ppin': safe_str(row.get('PPIN')),
            'patent_num': safe_str(row.get('Patent Num')),
            # Workflow fields
            'workflow_status': safe_str(row.get('Workflow Status')),
            'verified_status': safe_str(row.get('Verified Status')),
            'doc_status': safe_str(row.get('Doc Status')),
            'related_items': safe_str(row.get('Related Items (click related item below for viewing options)')),
        }

        # Skip records without valid book/page
        if record['book'] and record['page']:
            records.append(record)

    return records


def load_historic_deeds(file_path: Path) -> List[Dict[str, Any]]:
    """
    Load Historic Deeds checklist (book/page only).

    Args:
        file_path: Path to Excel file

    Returns:
        List of record dictionaries (minimal fields)
    """
    try:
        df = pd.read_excel(file_path)
        logger.info(f"Loaded {len(df)} rows from {file_path.name}")
    except Exception as e:
        logger.error(f"Failed to load {file_path.name}: {e}")
        return []

    records = []

    for _, row in df.iterrows():
        # Parse book and page
        book_str = safe_str(row.get('book'))
        page_str = safe_str(row.get('page'))

        # Try to convert to integers
        book = None
        page = None

        if book_str:
            # Handle book letters (like "YYY") - these might be special designations
            # For now, skip non-numeric books or map them
            try:
                book = int(book_str)
            except ValueError:
                # Could log or handle special book designations here
                continue

        if page_str:
            try:
                page = int(page_str)
            except ValueError:
                continue

        if book and page:
            record = {
                'source': 'Historical',
                'source_file': file_path.name,
                'book': book,
                'page': page,
                # All other fields will be NULL
                'gin': None,
                'instrument_number': None,
                'book_volume': None,
                'instrument_type_raw': None,
                'instrument_type_parsed': None,
                'document_type': None,
                'file_date': None,
                'num_pages': None,
                'party_type': None,
                'party_seq': None,
                'searched_name': None,
                'cross_party_name': None,
                'grantor_party': None,
                'grantee_party': None,
                'description': None,
                'location': None,
                'direction': None,
                'legals': None,
                'sub_div': None,
                'block': None,
                'lot': None,
                'sec': None,
                'town': None,
                'rng': None,
                'square': None,
                'remarks': None,
                'ne_of_ne': None,
                'nw_of_ne': None,
                'sw_of_ne': None,
                'se_of_ne': None,
                'ne_of_nw': None,
                'nw_of_nw': None,
                'sw_of_nw': None,
                'se_of_nw': None,
                'ne_of_sw': None,
                'nw_of_sw': None,
                'sw_of_sw': None,
                'se_of_sw': None,
                'ne_of_se': None,
                'nw_of_se': None,
                'sw_of_se': None,
                'se_of_se': None,
                'address': None,
                'street_name': None,
                'city': None,
                'zip': None,
                'parcel_num': None,
                'parcel_id': None,
                'ppin': None,
                'patent_num': None,
                'workflow_status': None,
                'verified_status': None,
                'doc_status': None,
                'related_items': None,
            }
            records.append(record)

    return records


# ============================================================================
# Main Import Logic
# ============================================================================

def import_all_data():
    """Main import function"""
    logger.info("=" * 80)
    logger.info("Madison County Title Plant - Index Data Import")
    logger.info("=" * 80)

    # Connect to database
    db = IndexDatabase(DB_CONFIG)
    try:
        db.connect()
    except Exception as e:
        logger.error(f"Cannot proceed without database connection: {e}")
        return

    try:
        # ====================================================================
        # 1. Import DuProcess Indexes
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("Importing DuProcess Indexes")
        logger.info("=" * 80)

        # Check existing records
        existing_duprocess = db.check_existing_records('DuProcess')
        logger.info(f"Existing DuProcess records: {existing_duprocess:,}")

        # Find all Excel files
        if not DUPROCESS_DIR.exists():
            logger.error(f"DuProcess directory not found: {DUPROCESS_DIR}")
        else:
            excel_files = sorted(DUPROCESS_DIR.glob("*.xlsx"))
            logger.info(f"Found {len(excel_files)} Excel files in {DUPROCESS_DIR}")

            # Process each file with progress bar
            total_records = 0
            for file_path in tqdm(excel_files, desc="Processing DuProcess files"):
                records = load_duprocess_file(file_path)
                if records:
                    db.insert_batch(records)
                    total_records += len(records)

            logger.info(f"Imported {total_records:,} DuProcess records")

        # ====================================================================
        # 2. Import Historic Deeds
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("Importing Historic Deeds")
        logger.info("=" * 80)

        # Check existing records
        existing_historic = db.check_existing_records('Historical')
        logger.info(f"Existing Historical records: {existing_historic:,}")

        if not HISTORIC_DEEDS_FILE.exists():
            logger.error(f"Historic Deeds file not found: {HISTORIC_DEEDS_FILE}")
        else:
            records = load_historic_deeds(HISTORIC_DEEDS_FILE)
            if records:
                logger.info(f"Inserting {len(records):,} Historic Deeds records...")
                db.insert_batch(records)
                logger.info(f"Imported {len(records):,} Historic Deeds records")

        # ====================================================================
        # 3. Summary Statistics
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("Import Summary")
        logger.info("=" * 80)

        # Total records by source
        db.cursor.execute("""
            SELECT source, COUNT(*) as count
            FROM index_documents
            GROUP BY source
            ORDER BY source
        """)
        for source, count in db.cursor.fetchall():
            logger.info(f"  {source}: {count:,} records")

        # Total records
        db.cursor.execute("SELECT COUNT(*) FROM index_documents")
        total = db.cursor.fetchone()[0]
        logger.info(f"\nTotal records in database: {total:,}")

        # Download queue status
        db.cursor.execute("""
            SELECT download_status, COUNT(*) as count
            FROM index_documents
            GROUP BY download_status
            ORDER BY
                CASE download_status
                    WHEN 'pending' THEN 1
                    WHEN 'in_progress' THEN 2
                    WHEN 'failed' THEN 3
                    WHEN 'completed' THEN 4
                    WHEN 'skipped' THEN 5
                END
        """)
        logger.info("\nDownload Queue Status:")
        for status, count in db.cursor.fetchall():
            logger.info(f"  {status}: {count:,}")

        logger.info("\n" + "=" * 80)
        logger.info("Import Complete! ✅")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        raise
    finally:
        db.close()


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Main entry point"""
    print("\nMadison County Title Plant - Index Data Import\n")

    # Check for required environment variables
    if not DB_CONFIG['password']:
        print("Error: DB_PASSWORD environment variable not set")
        print("\nPlease set database credentials:")
        print("  export DB_USER='madison_index_app'")
        print("  export DB_PASSWORD='your_password'")
        print("\nOr load from .db_credentials file:")
        print("  source index_database/.db_credentials")
        sys.exit(1)

    # Confirm before proceeding
    print("This will import all index data into the database.")
    print(f"  DuProcess Indexes: {DUPROCESS_DIR}")
    print(f"  Historic Deeds: {HISTORIC_DEEDS_FILE}")
    print(f"  Database: {DB_CONFIG['database']} @ {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print()

    response = input("Continue? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Aborted.")
        sys.exit(0)

    # Run import
    import_all_data()


if __name__ == '__main__':
    main()
