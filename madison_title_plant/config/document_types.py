"""Document type definitions and fuzzy matching."""

import re
from typing import Optional, Dict
from difflib import SequenceMatcher

# Document type lookup dictionary (from doc_puller_mid.py)
DOCUMENT_TYPE_CODES: Dict[str, str] = {
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

# Known truncation mappings from index analysis
TRUNCATION_MAPPINGS = {
    'ASSIGNMENT OF DEED O': 'ASSIGNMENT OF DEED OF TRUST',
    'AMENDED PROTECTIVE C': 'AMENDED PROTECTIVE COVENANT',
    'MINERAL RIGHT  ROYA': 'MINERAL RIGHT & ROYALTY TRANSF',
    'POWER OF ATTORNEY-GE': 'POWER OF ATTORNEY-GENERAL',
    'REVOCATION  CANCELL': 'REVOCATION & CANCELL OF PA',
    'RELEASE - RIGHT OF W': 'RELEASE - RIGHT OF WAY',
    'CERT DISCHARGE FEDERAL TAX LIE': 'CERT DISCHARGE FEDERAL TAX LIEN',
}

class DocumentTypeResolver:
    """Resolve document types from instrument type strings."""
    
    def __init__(self, min_similarity: float = 0.85):
        """Initialize resolver with minimum similarity threshold."""
        self.min_similarity = min_similarity
        self.document_types = DOCUMENT_TYPE_CODES
        self.truncation_mappings = TRUNCATION_MAPPINGS
    
    def extract_document_type(self, instrument_type: str) -> Optional[str]:
        """
        Extract document type from InstrumentType field.
        
        Format: "[doc_type] - [other info]"
        
        Args:
            instrument_type: Raw InstrumentType value from index
            
        Returns:
            Extracted document type or None
        """
        if not instrument_type:
            return None
        
        # Extract part before " -"
        match = re.match(r'^([^-]+)\s*-', str(instrument_type))
        if match:
            return match.group(1).strip()
        
        # If no dash, return the whole string stripped
        return str(instrument_type).strip()
    
    def fuzzy_match_type(self, doc_type: str) -> tuple[str, str]:
        """
        Fuzzy match document type to standardized type.
        
        Args:
            doc_type: Document type extracted from index
            
        Returns:
            Tuple of (matched_type, code) or (original_type, '01') if no match
        """
        if not doc_type:
            return ('DEED', '01')  # Default to DEED
        
        doc_type = doc_type.upper().strip()
        
        # Check exact match first
        if doc_type in self.document_types:
            return (doc_type, self.document_types[doc_type])
        
        # Check known truncation mappings
        if doc_type in self.truncation_mappings:
            full_type = self.truncation_mappings[doc_type]
            return (full_type, self.document_types.get(full_type, '01'))
        
        # Try fuzzy matching
        best_match = None
        best_score = 0
        
        for full_type in self.document_types.keys():
            # Check if truncated type is a prefix
            if full_type.startswith(doc_type):
                score = len(doc_type) / len(full_type)
                if score > best_score and score >= 0.7:
                    best_match = full_type
                    best_score = score
            else:
                # Use sequence matcher for more complex matching
                score = SequenceMatcher(None, doc_type, full_type).ratio()
                if score > best_score and score >= self.min_similarity:
                    best_match = full_type
                    best_score = score
        
        if best_match:
            return (best_match, self.document_types[best_match])
        
        # Default to DEED if no match found
        return (doc_type, '01')
    
    def process_instrument_type(self, instrument_type: str) -> dict:
        """
        Process InstrumentType field to extract and resolve document type.
        
        Args:
            instrument_type: Raw InstrumentType value from index
            
        Returns:
            Dictionary with extracted and resolved document type info
        """
        extracted = self.extract_document_type(instrument_type)
        matched_type, code = self.fuzzy_match_type(extracted)
        
        return {
            'raw': instrument_type,
            'extracted': extracted,
            'matched_type': matched_type,
            'code': code,
            'confidence': 1.0 if extracted == matched_type else 0.85
        }