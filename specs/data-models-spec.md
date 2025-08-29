# Data Models & Database Design Specification

## Overview
This specification defines the data models, database schema, and entity relationships for the Madison County Title Plant. The design emphasizes data integrity, efficient querying for title chains, and flexibility for various document types.

## Core Design Principles

### 1. Temporal Data Integrity
- All entities include temporal tracking (created_at, updated_at)
- Immutable document records with versioning for corrections
- Audit trail for all data modifications

### 2. Normalization Strategy
- 3rd Normal Form for transactional data
- Controlled denormalization for search performance
- Materialized views for complex title chains

### 3. Extensibility
- JSON fields for variable document attributes
- Enum-based classification system
- Plugin architecture for new document types

## Entity Models

### Document Entity
```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Set

# Document Categories - Broad legal functions
class DocumentCategory(str, Enum):
    """
    Represents broad legal functions a recorded document can serve.
    A single document can belong to multiple categories.
    """
    CONVEYANCE = "CONVEYANCE"           # Transfers ownership/interest
    SECURITY = "SECURITY"               # Secures debt/obligation
    SERVITUDES = "SERVITUDES"           # Easements, restrictions, covenants
    INVOLUNTARY_LIENS = "INVOLUNTARY_LIENS"  # Liens not by agreement
    CHANGE = "CHANGE"                   # Modifies existing documents
    OTHER = "OTHER"                     # Administrative, informational

# Document Types - Specific instrument types
class DocumentType(str, Enum):
    """
    Specific types of recorded documents found in Madison County.
    Based on analysis of 995,743 DuProcess index records.
    """
    # CONVEYANCE (Primary function: transfer ownership)
    DEED = "DEED"                       # General warranty, special warranty, etc.
    QUITCLAIM_DEED = "QUITCLAIM_DEED"
    TRUSTEES_DEED = "TRUSTEES_DEED"    
    TAX_DEED = "TAX_DEED"
    TRANSFER_ON_DEATH_DEED = "TRANSFER_ON_DEATH_DEED"
    PATENT = "PATENT"                   # Government conveyance
    LEASE = "LEASE"
    MINERAL_DEED = "MINERAL_DEED"
    ROYALTY_DEED = "ROYALTY_DEED"
    
    # SECURITY (Primary function: secure debt)
    DEED_OF_TRUST = "DEED_OF_TRUST"    # 25% of all documents
    MORTGAGE = "MORTGAGE"
    VENDORS_LIEN = "VENDORS_LIEN"
    ASSIGNMENT_OF_LEASES_AND_RENTS = "ASSIGNMENT_OF_LEASES_AND_RENTS"
    
    # SERVITUDES (Burdens on property)
    EASEMENT = "EASEMENT"
    RIGHT_OF_WAY = "RIGHT_OF_WAY"
    PROTECTIVE_COVENANT = "PROTECTIVE_COVENANT"
    CCRS = "CCRS"                       # Covenants, Conditions & Restrictions
    DEED_RESTRICTIONS = "DEED_RESTRICTIONS"
    
    # INVOLUNTARY LIENS
    CONSTRUCTION_LIEN = "CONSTRUCTION_LIEN"
    FEDERAL_TAX_LIEN = "FEDERAL_TAX_LIEN"
    TAX_SALE = "TAX_SALE"              # 2.23% of documents
    ASSESSMENT_LIEN = "ASSESSMENT_LIEN"
    JUDGMENT = "JUDGMENT"
    LIS_PENDENS = "LIS_PENDENS"
    UCC = "UCC"                         # 4.35% of documents
    UCC_CONTINUATION = "UCC_CONTINUATION"
    UCC_TERMINATION = "UCC_TERMINATION"
    UCC_AMENDMENT = "UCC_AMENDMENT"
    UCC_PARTIAL_RELEASE = "UCC_PARTIAL_RELEASE"
    CONDOMINIUM_LIEN = "CONDOMINIUM_LIEN"
    
    # CHANGE (Modifies existing documents)
    RELEASE = "RELEASE"
    PARTIAL_RELEASE = "PARTIAL_RELEASE"
    ASSIGNMENT = "ASSIGNMENT"           # Including Assignment of DOT (4.61%)
    MODIFICATION_AGREEMENT = "MODIFICATION_AGREEMENT"
    SUBORDINATION = "SUBORDINATION"
    SUBSTITUTION_OF_TRUSTEE = "SUBSTITUTION_OF_TRUSTEE"
    SUPPLEMENT = "SUPPLEMENT"
    AMENDMENT = "AMENDMENT"
    CANCELLATION = "CANCELLATION"
    TAX_RELEASE = "TAX_RELEASE"        # 7% of documents
    
    # OTHER (Administrative, informational)
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY"  # 20% of documents
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
    
    # OIL, GAS & MINERAL specific
    OIL_GAS_LEASE = "OIL_GAS_LEASE"
    POOLING_AGREEMENT = "POOLING_AGREEMENT"
    UNITIZATION_AGREEMENT = "UNITIZATION_AGREEMENT"
    DIVISION_ORDER = "DIVISION_ORDER"
    
    UNKNOWN = "UNKNOWN"

# Subject Matter - What resource/interest is affected
class SubjectMatter(str, Enum):
    """
    The resource or interest that is the subject of the document.
    A document can affect multiple subject matters.
    """
    SURFACE = "SURFACE"                 # Surface estate/improvements
    MINERAL = "MINERAL"                 # Oil, gas, mineral rights
    ROYALTY = "ROYALTY"                 # Royalty interests
    TIMBER = "TIMBER"                   # Timber rights
    WATER = "WATER"                     # Water rights
    AIR = "AIR"                         # Air rights
    SOLAR = "SOLAR"                     # Solar rights

class DocumentStatus(Enum):
    PENDING = "PENDING"
    DOWNLOADED = "DOWNLOADED"
    OCR_PROCESSING = "OCR_PROCESSING"
    OCR_COMPLETE = "OCR_COMPLETE"
    VALIDATED = "VALIDATED"
    INDEXED = "INDEXED"
    ERROR = "ERROR"

@dataclass
class Document:
    """
    Core document entity supporting multi-dimensional classification.
    A single document can serve multiple legal functions and affect multiple interests.
    
    Example: A warranty deed that:
    - Conveys property (CONVEYANCE category)
    - Retains vendor's lien (SECURITY category)  
    - Reserves easement (SERVITUDES category)
    - Reserves 1/2 minerals (affects MINERAL subject matter)
    """
    document_id: str  # Format: {book}-{page}
    book: int
    page: int
    
    # Multi-dimensional classification
    document_type: DocumentType         # Primary instrument type
    categories: Set[DocumentCategory] = field(default_factory=set)
    subject_matters: Set[SubjectMatter] = field(default_factory=set)
    
    # DuProcess specific
    duprocess_instrument_type: Optional[str] = None  # Original string from index
    book_type: Optional[str] = None     # DEED, DEED OF TRUST, UCC, etc.
    
    status: DocumentStatus = DocumentStatus.PENDING
    
    # Recording information
    recording_date: Optional[datetime] = None
    instrument_number: Optional[str] = None
    
    # File references (aligned with storage-spec.md)
    gcs_optimized_path: Optional[str] = None
    gcs_ocr_path: Optional[str] = None
    gcs_approved_ocr_path: Optional[str] = None
    
    # Metadata
    file_size_bytes: int = 0
    page_count: int = 0
    ocr_confidence: Optional[float] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    downloaded_at: Optional[datetime] = None
    ocr_completed_at: Optional[datetime] = None
    
    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Flexible attributes for complex scenarios
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Auto-populate categories based on document type if not specified"""
        if not self.categories and self.document_type:
            self.categories = get_default_categories(self.document_type)
        
        # Default to SURFACE if no subject matter specified
        if not self.subject_matters:
            self.subject_matters = {SubjectMatter.SURFACE}
```

### Document Type Mappings
```python
# Default category mappings for document types
DEFAULT_CATEGORY_MAPPINGS = {
    # CONVEYANCE types
    DocumentType.DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.QUITCLAIM_DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.TRUSTEES_DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.TAX_DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.TRANSFER_ON_DEATH_DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.PATENT: {DocumentCategory.CONVEYANCE},
    DocumentType.LEASE: {DocumentCategory.CONVEYANCE},
    DocumentType.MINERAL_DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.ROYALTY_DEED: {DocumentCategory.CONVEYANCE},
    
    # SECURITY types
    DocumentType.DEED_OF_TRUST: {DocumentCategory.SECURITY},
    DocumentType.MORTGAGE: {DocumentCategory.SECURITY},
    DocumentType.VENDORS_LIEN: {DocumentCategory.SECURITY},
    DocumentType.ASSIGNMENT_OF_LEASES_AND_RENTS: {DocumentCategory.SECURITY},
    
    # SERVITUDES types
    DocumentType.EASEMENT: {DocumentCategory.SERVITUDES},
    DocumentType.RIGHT_OF_WAY: {DocumentCategory.SERVITUDES},
    DocumentType.PROTECTIVE_COVENANT: {DocumentCategory.SERVITUDES},
    DocumentType.CCRS: {DocumentCategory.SERVITUDES},
    DocumentType.DEED_RESTRICTIONS: {DocumentCategory.SERVITUDES},
    
    # INVOLUNTARY LIENS
    DocumentType.CONSTRUCTION_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.FEDERAL_TAX_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.TAX_SALE: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.ASSESSMENT_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.JUDGMENT: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.LIS_PENDENS: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.UCC: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.CONDOMINIUM_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},
    
    # CHANGE types
    DocumentType.RELEASE: {DocumentCategory.CHANGE},
    DocumentType.PARTIAL_RELEASE: {DocumentCategory.CHANGE},
    DocumentType.ASSIGNMENT: {DocumentCategory.CHANGE},
    DocumentType.MODIFICATION_AGREEMENT: {DocumentCategory.CHANGE},
    DocumentType.SUBORDINATION: {DocumentCategory.CHANGE},
    DocumentType.SUBSTITUTION_OF_TRUSTEE: {DocumentCategory.CHANGE},
    DocumentType.TAX_RELEASE: {DocumentCategory.CHANGE},
    
    # OTHER types
    DocumentType.POWER_OF_ATTORNEY: {DocumentCategory.OTHER},
    DocumentType.AFFIDAVIT: {DocumentCategory.OTHER},
    DocumentType.AGREEMENT: {DocumentCategory.OTHER},
    DocumentType.PLAT: {DocumentCategory.OTHER},
    DocumentType.SUBDIVISION_PLAT: {DocumentCategory.OTHER},
}

# Mapping DuProcess instrument types to our clean enums
# Based on 995,743 records from Madison County DuProcess indexes
DUPROCESS_TYPE_MAPPING = {
    # Most common types (>10,000 occurrences)
    "DEED OF TRUST": DocumentType.DEED_OF_TRUST,                    # 248,872 (25.00%)
    "POWER OF ATTORNEY": DocumentType.POWER_OF_ATTORNEY,            # 199,247 (20.01%)
    "DEED": DocumentType.DEED,                                      # 195,764 (19.66%)
    "TAX RELEASE": DocumentType.TAX_RELEASE,                        # 69,673 (7.00%)
    "ASSIGNMENT OF DEED O": DocumentType.ASSIGNMENT,                # 45,955 (4.61%)
    "UCC (CONVERTED)": DocumentType.UCC,                            # 43,287 (4.35%)
    "TAX SALE": DocumentType.TAX_SALE,                              # 22,206 (2.23%)
    "PARTIAL RELEASE": DocumentType.PARTIAL_RELEASE,                # 19,623 (1.97%)
    "UCC TERM": DocumentType.UCC_TERMINATION,                       # 19,522 (1.96%)
    "ASSESSMENT LIEN": DocumentType.ASSESSMENT_LIEN,                # 18,322 (1.84%)
    "RIGHT OF WAY": DocumentType.RIGHT_OF_WAY,                      # 16,869 (1.69%)
    "MODIFICATION AGREEME": DocumentType.MODIFICATION_AGREEMENT,     # 13,849 (1.39%)
    "OIL GAS MINERAL LEAS": DocumentType.OIL_GAS_LEASE,             # 11,666 (1.17%)
    "SUBSTITUTE TRUSTEE": DocumentType.SUBSTITUTION_OF_TRUSTEE,     # 10,646 (1.07%)
    
    # Common types (1,000-10,000 occurrences)
    "EASEMENT": DocumentType.EASEMENT,                              # 8,857 (0.89%)
    "FEDERAL TAX LIEN": DocumentType.FEDERAL_TAX_LIEN,              # 8,764 (0.88%)
    "LEASE ASSIGNMENT": DocumentType.ASSIGNMENT,                    # 4,931 (0.50%)
    "SUBORDINATION": DocumentType.SUBORDINATION,                    # 4,889 (0.49%)
    "AFFIDAVIT": DocumentType.AFFIDAVIT,                           # 4,521 (0.45%)
    "TRUSTEES DEED": DocumentType.TRUSTEES_DEED,                    # 3,901 (0.39%)
    "CONSTRUCTION LIEN": DocumentType.CONSTRUCTION_LIEN,            # 3,843 (0.39%)
    "SUBDIVISION PLATS": DocumentType.SUBDIVISION_PLAT,             # 3,139 (0.32%)
    "JUDGMENT OR ORDER": DocumentType.JUDGMENT,                     # 3,089 (0.31%)
    "FEDERAL TAX LIENS": DocumentType.FEDERAL_TAX_LIEN,             # 2,788 (0.28%)
    "LIS PENDENS": DocumentType.LIS_PENDENS,                        # 1,338 (0.13%)
    "UCC CONT": DocumentType.UCC_CONTINUATION,                      # 1,310 (0.13%)
    "UCC ASGN": DocumentType.ASSIGNMENT,                            # 1,227 (0.12%)
    "MINERAL DEED": DocumentType.MINERAL_DEED,                      # 1,145 (0.11%)
    
    # Less common types (<1,000 occurrences)
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
    "TIMBER DEED": DocumentType.DEED,  # Specify TIMBER in subject_matters
    "DISCLAIMER": DocumentType.DISCLAIMER,
    "CORRECTIVE DEED": DocumentType.DEED,  # Mark as CHANGE category
    "AGREEMENT": DocumentType.AGREEMENT,
    "CANCELLATION": DocumentType.CANCELLATION,
    "SUPPLEMENT": DocumentType.SUPPLEMENT,
    "POOLING AGREEMENT": DocumentType.POOLING_AGREEMENT,
    "AMENDMENT": DocumentType.AMENDMENT,
    "MISCELLANEOUS": DocumentType.AGREEMENT,
    "OIL GAS AFFIDAVIT": DocumentType.AFFIDAVIT,
    "NOTICE": DocumentType.NOTICE,
    "ROYALTY TRANSFERS": DocumentType.ROYALTY_DEED,
    "CORRECTIVE DEED OF T": DocumentType.DEED_OF_TRUST,  # Mark as CHANGE
    "CERTIFIED COPY": DocumentType.AGREEMENT,
    "LEASE": DocumentType.LEASE,
    "TIMBER LEASE": DocumentType.LEASE,  # Specify TIMBER in subject_matters
    "RENEWAL AND EXTENSIO": DocumentType.MODIFICATION_AGREEMENT,
    "TRUSTEE'S DEED": DocumentType.TRUSTEES_DEED,
    "TAX CERTIFICATE": DocumentType.TAX_SALE,
    "REVISION": DocumentType.MODIFICATION_AGREEMENT,
    "TRUST AGREEMENT": DocumentType.TRUST_AGREEMENT,
    "LIMITED WARRANTY DEE": DocumentType.DEED,
    "COURT ORDER": DocumentType.JUDGMENT,
    "CORRECTIVE AFFIDAVIT": DocumentType.AFFIDAVIT,  # Mark as CHANGE
    "ROAD DEDICATION": DocumentType.RIGHT_OF_WAY,
    "UCC RELEASE": DocumentType.RELEASE,
    "DEED OF GIFT": DocumentType.DEED,
    "RELEASE OF VENDOR'S": DocumentType.RELEASE,
    "RATIFICATION": DocumentType.AGREEMENT,
    "ORDINANCE": DocumentType.AGREEMENT,
    "ASSIGNMENT OF LEASE": DocumentType.ASSIGNMENT,
    "SUBORDINATION AGREEM": DocumentType.SUBORDINATION,
    "REDEMPTION": DocumentType.DEED,
    "CORRECTIVE OIL GAS M": DocumentType.OIL_GAS_LEASE,  # Mark as CHANGE
    "MINERAL LEASE": DocumentType.OIL_GAS_LEASE,
    "RELEASE DEED OF TRUS": DocumentType.RELEASE,
    "BOUNDARY LINE AGREEM": DocumentType.AGREEMENT,
    "UNITIZATION AGREEMEN": DocumentType.UNITIZATION_AGREEMENT,
    "OIL GAS MINERAL ROY": DocumentType.ROYALTY_DEED,
    "DEED OF CONFIRMATION": DocumentType.DEED,
    "TIMBER CONTRACT": DocumentType.LEASE,  # Specify TIMBER
    "MEMORANDUM": DocumentType.AGREEMENT,
    "STATE TAX LIEN": DocumentType.ASSESSMENT_LIEN,
    "IRS LIEN": DocumentType.FEDERAL_TAX_LIEN,
    "RELEASE OF LIS PENDE": DocumentType.RELEASE,
    "PARTIAL RECONVEYANCE": DocumentType.PARTIAL_RELEASE,
    "DEED OF ACQUITTANCE": DocumentType.DEED,
    "UCC SEARCH": DocumentType.UCC,
    "DIVISION ORDER": DocumentType.DIVISION_ORDER,
    "CORRECTIVE PATENT": DocumentType.PATENT,  # Mark as CHANGE
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
    "CORRECTIVE SUBDIVISI": DocumentType.SUBDIVISION_PLAT,  # Mark as CHANGE
    "RELEASE OF EASEMENT": DocumentType.RELEASE,
    "AFFIDAVIT OF DEATH": DocumentType.AFFIDAVIT,
    "RECONVEYANCE": DocumentType.RELEASE,
    "CORRECTIVE QUITCLAIM": DocumentType.QUITCLAIM_DEED,  # Mark as CHANGE
    "WAIVER": DocumentType.AGREEMENT,
    "PARTITION DEED": DocumentType.DEED,
    "RIGHT OF WAY AGREEME": DocumentType.RIGHT_OF_WAY,
    "MORTGAGE": DocumentType.MORTGAGE,
    "CORRECTIVE PARTIAL R": DocumentType.PARTIAL_RELEASE,  # Mark as CHANGE
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
    "CORRECTIVE ASSIGNMEN": DocumentType.ASSIGNMENT,  # Mark as CHANGE
    "HEIRSHIP": DocumentType.HEIRSHIP,
    "RATIFICATION AND REN": DocumentType.MODIFICATION_AGREEMENT,
    "ASSIGNMENT OF CONTR": DocumentType.ASSIGNMENT,
    "CORRECTIVE TRANSFER": DocumentType.TRANSFER_ON_DEATH_DEED,  # Mark as CHANGE
    "AFFIDAVIT OF IDENTIT": DocumentType.AFFIDAVIT,
    "RESERVATION": DocumentType.DEED,  # Special handling needed
    "WARRANTY DEED": DocumentType.DEED,
    "SUBORDINATION AND AT": DocumentType.SUBORDINATION,
    "SUBDIVISION CORRECTI": DocumentType.SUBDIVISION_PLAT,  # Mark as CHANGE
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
    "REVOCATION": DocumentType.POWER_OF_ATTORNEY,  # Mark as CHANGE
    "CORRECTIVE WARRANTY": DocumentType.DEED,  # Mark as CHANGE
    "ESCROW AGREEMENT": DocumentType.AGREEMENT,
    "ABSTRACT OF JUDGMENT": DocumentType.JUDGMENT,
    "SURRENDER": DocumentType.RELEASE,
    "SUBORDINATION OF VEN": DocumentType.SUBORDINATION,
    "EXTENSION AGREEMENT": DocumentType.MODIFICATION_AGREEMENT,
    "AMENDMENT TO EASEMEN": DocumentType.EASEMENT,  # Mark as CHANGE
    
    # Default mapping for unknown types
    "UNKNOWN": DocumentType.UNKNOWN,
}

def parse_duprocess_instrument(instrument_string: str) -> tuple[DocumentType, Set[DocumentCategory], Set[SubjectMatter], str]:
    """
    Parse DuProcess instrument type string and determine categories and subject matters.
    
    Format: 'INSTRUMENT_NAME - [BOOK_TYPE CODE]'
    
    Returns: (DocumentType, categories, subject_matters, book_type)
    """
    # Extract the main instrument name (before ' - ')
    parts = instrument_string.split(' - ')
    instrument_name = parts[0].strip().upper()
    
    # Map to document type
    doc_type = DUPROCESS_TYPE_MAPPING.get(
        instrument_name, 
        DocumentType.UNKNOWN
    )
    
    # Start with default categories
    categories = get_default_categories(doc_type)
    
    # Initialize subject matters
    subject_matters = set()
    
    # Handle special cases
    
    # 1. Corrective documents should add CHANGE category
    if instrument_name.startswith('CORRECTIVE'):
        categories.add(DocumentCategory.CHANGE)
    
    # 2. Timber-specific documents
    if 'TIMBER' in instrument_name:
        subject_matters.add(SubjectMatter.TIMBER)
    
    # 3. Oil, Gas, Mineral documents
    if any(term in instrument_name for term in ['OIL', 'GAS', 'MINERAL']):
        subject_matters.add(SubjectMatter.MINERAL)
    
    # 4. Royalty documents
    if 'ROYALTY' in instrument_name:
        subject_matters.add(SubjectMatter.ROYALTY)
    
    # 5. UCC documents might secure equipment on property
    if instrument_name.startswith('UCC'):
        categories.add(DocumentCategory.INVOLUNTARY_LIENS)
    
    # 6. Vendor's lien in deed
    if 'VENDOR' in instrument_name:
        categories.add(DocumentCategory.SECURITY)
    
    # 7. Assignment documents modify existing interests
    if 'ASSIGNMENT' in instrument_name or 'ASGN' in instrument_name:
        categories.add(DocumentCategory.CHANGE)
    
    # Default to SURFACE if no specific subject matter identified
    if not subject_matters:
        subject_matters.add(SubjectMatter.SURFACE)
    
    # Extract book type from brackets if present
    book_type = ""
    if len(parts) > 1 and '[' in parts[1]:
        book_type = parts[1].split('[')[1].split(']')[0].split()[0]
    
    return doc_type, categories, subject_matters, book_type

def get_default_categories(doc_type: DocumentType) -> Set[DocumentCategory]:
    """Get default categories for a document type"""
    return DEFAULT_CATEGORY_MAPPINGS.get(doc_type, {DocumentCategory.OTHER})
```

### Party Entity
```python
class PartyType(Enum):
    INDIVIDUAL = "INDIVIDUAL"
    CORPORATION = "CORPORATION"
    LLC = "LLC"
    PARTNERSHIP = "PARTNERSHIP"
    TRUST = "TRUST"
    ESTATE = "ESTATE"
    GOVERNMENT = "GOVERNMENT"
    UNKNOWN = "UNKNOWN"

class PartyRole(Enum):
    GRANTOR = "GRANTOR"
    GRANTEE = "GRANTEE"
    TRUSTOR = "TRUSTOR"
    BENEFICIARY = "BENEFICIARY"
    TRUSTEE = "TRUSTEE"
    MORTGAGOR = "MORTGAGOR"
    MORTGAGEE = "MORTGAGEE"
    TESTATOR = "TESTATOR"
    EXECUTOR = "EXECUTOR"
    WITNESS = "WITNESS"
    NOTARY = "NOTARY"
    ATTORNEY_IN_FACT = "ATTORNEY_IN_FACT"

@dataclass
class Party:
    """Entity representing a person or organization"""
    party_id: str  # UUID
    party_type: PartyType
    
    # Name variations
    full_name: str
    normalized_name: str  # For matching
    first_name: Optional[str]
    middle_name: Optional[str]
    last_name: Optional[str]
    suffix: Optional[str]
    
    # Organization fields
    organization_name: Optional[str]
    organization_type: Optional[str]
    
    # Additional identifiers
    tax_id: Optional[str]
    address: Optional[str]
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    
    # Name variations for fuzzy matching
    aliases: List[str] = None
    
    def get_search_keys(self) -> List[str]:
        """Generate search keys for party matching"""
        keys = [self.normalized_name]
        if self.aliases:
            keys.extend(self.aliases)
        # Add phonetic variations
        keys.append(generate_soundex(self.full_name))
        keys.append(generate_metaphone(self.full_name))
        return keys
```

### Property Entity
```python
class PropertyType(Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    AGRICULTURAL = "AGRICULTURAL"
    INDUSTRIAL = "INDUSTRIAL"
    VACANT_LAND = "VACANT_LAND"
    MIXED_USE = "MIXED_USE"
    UNKNOWN = "UNKNOWN"

class LegalDescriptionType(Enum):
    METES_AND_BOUNDS = "METES_AND_BOUNDS"
    LOT_AND_BLOCK = "LOT_AND_BLOCK"
    SECTION_TOWNSHIP_RANGE = "SECTION_TOWNSHIP_RANGE"
    GOVERNMENT_LOT = "GOVERNMENT_LOT"
    CONDOMINIUM = "CONDOMINIUM"
    MIXED = "MIXED"

@dataclass
class Property:
    """Property entity with legal description"""
    property_id: str  # UUID
    property_type: PropertyType
    
    # Legal description
    legal_description_type: LegalDescriptionType
    legal_description_text: str
    
    # Parsed components
    section: Optional[int]
    township: Optional[str]
    range: Optional[str]
    lot: Optional[str]
    block: Optional[str]
    subdivision: Optional[str]
    
    # Modern identifiers
    parcel_number: Optional[str]
    tax_id: Optional[str]
    street_address: Optional[str]
    
    # Geographic data
    latitude: Optional[float]
    longitude: Optional[float]
    polygon: Optional[str]  # WKT format
    acreage: Optional[float]
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    
    # Computed field for searching
    search_hash: str  # Hash of normalized legal description
```

### Transaction Entity
```python
class TransactionType(Enum):
    SALE = "SALE"
    GIFT = "GIFT"
    INHERITANCE = "INHERITANCE"
    FORECLOSURE = "FORECLOSURE"
    TAX_SALE = "TAX_SALE"
    COURT_ORDER = "COURT_ORDER"
    CORRECTION = "CORRECTION"
    UNKNOWN = "UNKNOWN"

@dataclass
class Transaction:
    """Represents a property transaction"""
    transaction_id: str  # UUID
    document_id: str  # Foreign key to Document
    transaction_type: TransactionType
    
    # Transaction details
    transaction_date: datetime
    recording_date: datetime
    consideration_amount: Optional[float]
    consideration_text: Optional[str]
    
    # Property reference
    property_id: str  # Foreign key to Property
    
    # Parties (many-to-many through TransactionParty)
    # Implemented via relationship table
    
    # Legal status
    is_arms_length: Optional[bool]
    has_liens: bool = False
    has_exceptions: bool = False
    
    # Chain tracking
    chain_position: Optional[int]  # Position in title chain
    breaks_chain: bool = False  # Indicates title defect
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    notes: Optional[str]
```

### Relationship Tables

```python
@dataclass
class TransactionParty:
    """Links parties to transactions with roles"""
    transaction_id: str
    party_id: str
    party_role: PartyRole
    ownership_percentage: Optional[float]
    is_primary: bool = False
    
@dataclass
class DocumentLink:
    """Links related documents"""
    parent_document_id: str
    child_document_id: str
    relationship_type: str  # e.g., "RELEASES", "ASSIGNS", "CORRECTS"
    
@dataclass
class PartyAlias:
    """Tracks name variations for the same party"""
    primary_party_id: str
    alias_party_id: str
    confidence_score: float
    verification_status: str  # "VERIFIED", "PROBABLE", "POSSIBLE"
```

## Database Schema

### PostgreSQL Schema
```sql
-- Core tables
CREATE TABLE documents (
    document_id VARCHAR(50) PRIMARY KEY,
    book INTEGER NOT NULL,
    page INTEGER NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    recording_date TIMESTAMP,
    instrument_number VARCHAR(50),
    gcs_raw_path TEXT,
    gcs_optimized_path TEXT,
    file_size_bytes BIGINT,
    page_count INTEGER,
    ocr_confidence DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB,
    
    -- Indexes for common queries
    INDEX idx_book_page (book, page),
    INDEX idx_recording_date (recording_date),
    INDEX idx_document_type (document_type),
    INDEX idx_status (status)
);

CREATE TABLE parties (
    party_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_type VARCHAR(50) NOT NULL,
    full_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    first_name VARCHAR(100),
    middle_name VARCHAR(100),
    last_name VARCHAR(100),
    organization_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Full text search
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(full_name, '') || ' ' || 
                              coalesce(organization_name, ''))
    ) STORED,
    
    INDEX idx_normalized_name (normalized_name),
    INDEX idx_search_vector (search_vector) USING GIN
);

CREATE TABLE properties (
    property_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_type VARCHAR(50),
    legal_description_type VARCHAR(50),
    legal_description_text TEXT NOT NULL,
    section INTEGER,
    township VARCHAR(10),
    range VARCHAR(10),
    lot VARCHAR(50),
    block VARCHAR(50),
    subdivision VARCHAR(200),
    parcel_number VARCHAR(50),
    street_address TEXT,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    polygon GEOGRAPHY,
    acreage DECIMAL(10, 2),
    search_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_search_hash (search_hash),
    INDEX idx_parcel_number (parcel_number),
    INDEX idx_subdivision (subdivision),
    INDEX idx_location (latitude, longitude)
);

CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id VARCHAR(50) REFERENCES documents(document_id),
    property_id UUID REFERENCES properties(property_id),
    transaction_type VARCHAR(50),
    transaction_date TIMESTAMP,
    recording_date TIMESTAMP,
    consideration_amount DECIMAL(15, 2),
    is_arms_length BOOLEAN,
    chain_position INTEGER,
    breaks_chain BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_property_date (property_id, recording_date),
    INDEX idx_chain (property_id, chain_position)
);

CREATE TABLE transaction_parties (
    transaction_id UUID REFERENCES transactions(transaction_id),
    party_id UUID REFERENCES parties(party_id),
    party_role VARCHAR(50) NOT NULL,
    ownership_percentage DECIMAL(5, 2),
    is_primary BOOLEAN DEFAULT FALSE,
    
    PRIMARY KEY (transaction_id, party_id, party_role)
);
```

### Materialized Views for Performance
```sql
-- Title chain view for quick retrieval
CREATE MATERIALIZED VIEW title_chains AS
SELECT 
    p.property_id,
    p.legal_description_text,
    array_agg(
        json_build_object(
            'transaction_id', t.transaction_id,
            'document_id', t.document_id,
            'recording_date', t.recording_date,
            'transaction_type', t.transaction_type,
            'grantors', grantors.parties,
            'grantees', grantees.parties
        ) ORDER BY t.recording_date
    ) as chain
FROM properties p
JOIN transactions t ON t.property_id = p.property_id
LEFT JOIN LATERAL (
    SELECT json_agg(parties.full_name) as parties
    FROM transaction_parties tp
    JOIN parties ON parties.party_id = tp.party_id
    WHERE tp.transaction_id = t.transaction_id
    AND tp.party_role = 'GRANTOR'
) grantors ON true
LEFT JOIN LATERAL (
    SELECT json_agg(parties.full_name) as parties
    FROM transaction_parties tp
    JOIN parties ON parties.party_id = tp.party_id
    WHERE tp.transaction_id = t.transaction_id
    AND tp.party_role = 'GRANTEE'
) grantees ON true
GROUP BY p.property_id, p.legal_description_text;

-- Refresh strategy
CREATE INDEX idx_title_chains_property ON title_chains(property_id);
```

## Entity Resolution

### Party Matching Algorithm
```python
class PartyMatcher:
    """Resolves party entities across documents"""
    
    def match_party(self, new_party: Party) -> Optional[Party]:
        """
        Find existing party match using multiple strategies
        """
        # Exact match
        exact = self.exact_match(new_party.normalized_name)
        if exact:
            return exact
        
        # Fuzzy match
        candidates = self.fuzzy_match(new_party.full_name, threshold=0.85)
        if candidates:
            return self.select_best_match(new_party, candidates)
        
        # Phonetic match
        phonetic = self.phonetic_match(new_party.full_name)
        if phonetic:
            return phonetic
        
        # Corporate variation match
        if new_party.party_type in [PartyType.CORPORATION, PartyType.LLC]:
            corp_match = self.corporate_match(new_party.organization_name)
            if corp_match:
                return corp_match
        
        return None
    
    def normalize_name(self, name: str) -> str:
        """Normalize name for matching"""
        # Remove punctuation
        name = re.sub(r'[^\w\s]', '', name)
        # Convert to uppercase
        name = name.upper()
        # Remove common suffixes
        name = re.sub(r'\b(JR|SR|III|II|IV)\b', '', name)
        # Remove extra spaces
        name = ' '.join(name.split())
        return name
```

### Property Matching
```python
class PropertyMatcher:
    """Resolves property entities across documents"""
    
    def match_property(self, legal_desc: str) -> Optional[Property]:
        """
        Match property based on legal description
        """
        # Generate search hash
        search_hash = self.generate_search_hash(legal_desc)
        
        # Try exact hash match
        exact = self.find_by_hash(search_hash)
        if exact:
            return exact
        
        # Parse and match components
        parsed = self.parse_legal_description(legal_desc)
        if parsed.get('subdivision') and parsed.get('lot'):
            return self.match_by_subdivision(
                parsed['subdivision'],
                parsed['lot'],
                parsed.get('block')
            )
        
        if parsed.get('section'):
            return self.match_by_section_township_range(
                parsed['section'],
                parsed['township'],
                parsed['range']
            )
        
        # Fuzzy match on description text
        return self.fuzzy_match_description(legal_desc, threshold=0.9)
```

## Indexing Strategy

### Search Indexes
```python
SEARCH_INDEXES = {
    "parties": {
        "fields": ["full_name", "normalized_name", "organization_name"],
        "type": "full_text",
        "weights": {"full_name": 1.0, "organization_name": 0.8}
    },
    "properties": {
        "fields": ["legal_description_text", "subdivision", "street_address"],
        "type": "combined",  # Full text + geographic
        "spatial_field": "polygon"
    },
    "documents": {
        "fields": ["document_type", "recording_date", "book", "page"],
        "type": "composite",
        "sort_fields": ["recording_date DESC", "book ASC", "page ASC"]
    }
}
```

### Elasticsearch Integration (Optional)
```python
class ElasticsearchIndexer:
    """Optional Elasticsearch for advanced search"""
    
    def create_document_index(self):
        return {
            "mappings": {
                "properties": {
                    "document_id": {"type": "keyword"},
                    "book": {"type": "integer"},
                    "page": {"type": "integer"},
                    "document_type": {"type": "keyword"},
                    "recording_date": {"type": "date"},
                    "parties": {
                        "type": "nested",
                        "properties": {
                            "name": {"type": "text"},
                            "role": {"type": "keyword"}
                        }
                    },
                    "legal_description": {
                        "type": "text",
                        "analyzer": "legal_description_analyzer"
                    },
                    "ocr_text": {
                        "type": "text",
                        "analyzer": "standard"
                    }
                }
            }
        }
```

## Data Validation

### Validation Rules
```python
class DataValidator:
    """Validates data integrity"""
    
    VALIDATION_RULES = {
        "document": {
            "book": lambda x: 1 <= x <= 9999,
            "page": lambda x: 1 <= x <= 9999,
            "recording_date": lambda x: x <= datetime.now(),
            "ocr_confidence": lambda x: 0 <= x <= 1
        },
        "party": {
            "full_name": lambda x: len(x) >= 2,
            "party_type": lambda x: x in PartyType
        },
        "property": {
            "legal_description_text": lambda x: len(x) >= 10,
            "acreage": lambda x: x > 0 if x else True,
            "latitude": lambda x: -90 <= x <= 90 if x else True,
            "longitude": lambda x: -180 <= x <= 180 if x else True
        }
    }
    
    def validate_entity(self, entity_type: str, data: dict) -> ValidationResult:
        rules = self.VALIDATION_RULES.get(entity_type, {})
        errors = []
        
        for field, rule in rules.items():
            if field in data:
                try:
                    if not rule(data[field]):
                        errors.append(f"Invalid {field}: {data[field]}")
                except Exception as e:
                    errors.append(f"Validation error for {field}: {str(e)}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )
```

## Migration Strategy

### Initial Data Load
```python
class DataMigrator:
    """Handles initial data population"""
    
    def migrate_from_spreadsheets(self, excel_path: Path):
        """Import existing index data"""
        df = pd.read_excel(excel_path)
        
        for _, row in df.iterrows():
            # Create document
            doc = Document(
                document_id=f"{row['Book']:04d}_{row['Page']:04d}_{row['InstrumentType']}",
                book=row['Book'],
                page=row['Page'],
                document_type=self.map_document_type(row['InstrumentType']),
                status=DocumentStatus.PENDING
            )
            
            # Extract and create parties
            grantors = self.extract_parties(row['Grantor'], PartyRole.GRANTOR)
            grantees = self.extract_parties(row['Grantee'], PartyRole.GRANTEE)
            
            # Save to database
            self.save_document(doc)
            self.save_parties(grantors + grantees)
```

## Performance Optimization

### Query Optimization
```sql
-- Optimized title chain query
WITH RECURSIVE title_chain AS (
    -- Base case: most recent transaction
    SELECT t.*, 1 as depth
    FROM transactions t
    WHERE t.property_id = $1
    AND t.recording_date = (
        SELECT MAX(recording_date) 
        FROM transactions 
        WHERE property_id = $1
    )
    
    UNION ALL
    
    -- Recursive case: find previous transactions
    SELECT t.*, tc.depth + 1
    FROM transactions t
    JOIN title_chain tc ON t.property_id = tc.property_id
    WHERE t.recording_date < tc.recording_date
    AND tc.depth < 100  -- Prevent infinite recursion
)
SELECT * FROM title_chain
ORDER BY recording_date DESC;
```

### Caching Strategy
```python
class QueryCache:
    """Cache frequently accessed queries"""
    
    def __init__(self):
        self.cache = Redis()
        self.ttl = 3600  # 1 hour
    
    def get_title_chain(self, property_id: str) -> Optional[List[Transaction]]:
        key = f"chain:{property_id}"
        cached = self.cache.get(key)
        
        if cached:
            return json.loads(cached)
        
        # Fetch from database
        chain = self.fetch_title_chain(property_id)
        
        # Cache result
        self.cache.setex(key, self.ttl, json.dumps(chain))
        
        return chain
```

## Testing Strategy

### Unit Tests
```python
def test_party_normalization():
    """Test name normalization logic"""
    matcher = PartyMatcher()
    assert matcher.normalize_name("John Smith Jr.") == "JOHN SMITH"
    assert matcher.normalize_name("ABC, LLC") == "ABC LLC"

def test_legal_description_parsing():
    """Test legal description parser"""
    parser = LegalDescriptionParser()
    result = parser.parse("Lot 5, Block 3, Madison Heights")
    assert result['lot'] == "5"
    assert result['block'] == "3"
    assert result['subdivision'] == "Madison Heights"
```

### Data Integrity Tests
```python
def test_title_chain_continuity():
    """Ensure no gaps in title chains"""
    chains = db.query("SELECT * FROM title_chains")
    for chain in chains:
        transactions = chain['chain']
        for i in range(1, len(transactions)):
            # Grantee of previous should be grantor of current
            prev_grantees = transactions[i-1]['grantees']
            curr_grantors = transactions[i]['grantors']
            assert any(g in curr_grantors for g in prev_grantees)
```