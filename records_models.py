from enum import Enum
from dataclasses import dataclass, field
from datetime import date
from typing import Set, Optional

# -----------------------------
# Enumerations
# -----------------------------

class DocumentCategory(str, Enum):
    """
    Represents broad legal functions a recorded document can serve.
    """
    CONVEYANCE = "CONVEYANCE"
    SECURITY = "SECURITY"
    SERVITUDES = "SERVITUDES"
    INVOLUNTARY_LIENS = "INVOLUNTARY_LIENS"
    CHANGE = "CHANGE"
    OTHER = "OTHER"


class DocumentType(str, Enum):
    """
    Represents the specific type of recorded document, grouped by default categories.
    """
    # 1) CONVEYANCE
    DEED = "DEED"          # e.g. fee, mineral, tax
    PATENT = "PATENT"      # tax patent, USA patent
    LEASE = "LEASE"

    # 2) SECURITY
    DEED_OF_TRUST = "DEED_OF_TRUST"
    MORTGAGE = "MORTGAGE"
    ASSIGNMENT_OF_LEASES_AND_RENTS = "ASSIGNMENT_OF_LEASES_AND_RENTS"

    # 3) SERVITUDES
    CCRS = "CCRS"                      # Covenants, Conditions & Restrictions
    PROTECTIVE_COVENANTS = "PROTECTIVE_COVENANTS"
    EASEMENT = "EASEMENT"
    RIGHT_OF_WAY = "RIGHT_OF_WAY"

    # 4) INVOLUNTARY LIENS
    CONSTRUCTION_LIEN = "CONSTRUCTION_LIEN"    # Mechanic's Lien
    FEDERAL_TAX_LIEN = "FEDERAL_TAX_LIEN"
    JUDGMENT = "JUDGMENT"
    LIS_PENDENS = "LIS_PENDENS"
    UCC = "UCC"
    HOA_ASSESSMENT_LIEN = "HOA_ASSESSMENT_LIEN"

    # 5) CHANGE
    RELEASE = "RELEASE"
    PARTIAL_RELEASE = "PARTIAL_RELEASE"
    MODIFICATION_AGREEMENT = "MODIFICATION_AGREEMENT"
    ASSIGNMENT = "ASSIGNMENT"
    SUBORDINATION_AGREEMENT = "SUBORDINATION_AGREEMENT"
    SUBSTITUTION_OF_TRUSTEE = "SUBSTITUTION_OF_TRUSTEE"

    # 6) OTHER
    COURT_DECREE = "COURT_DECREE"
    AFFIDAVIT = "AFFIDAVIT"
    AGREEMENT = "AGREEMENT"
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY"
    TRUST_AGREEMENT = "TRUST_AGREEMENT"
    PLATS = "PLATS"
    PLANS = "PLANS"


class SubjectMatter(str, Enum):
    """
    Represents the resource or interest that is the subject of the document.
    Useful for oil, gas, mineral, timber, etc.
    """
    SURFACE = "SURFACE"
    MINERAL = "MINERAL"
    ROYALTY = "ROYALTY"
    TIMBER = "TIMBER"


# -----------------------------
# Default Category Mapping
# -----------------------------

doc_type_to_categories = {
    # CONVEYANCE
    DocumentType.DEED: {DocumentCategory.CONVEYANCE},
    DocumentType.PATENT: {DocumentCategory.CONVEYANCE},
    DocumentType.LEASE: {DocumentCategory.CONVEYANCE},

    # SECURITY
    DocumentType.DEED_OF_TRUST: {DocumentCategory.SECURITY},
    DocumentType.MORTGAGE: {DocumentCategory.SECURITY},
    DocumentType.ASSIGNMENT_OF_LEASES_AND_RENTS: {DocumentCategory.SECURITY},

    # SERVITUDES
    DocumentType.CCRS: {DocumentCategory.SERVITUDES},
    DocumentType.PROTECTIVE_COVENANTS: {DocumentCategory.SERVITUDES},
    DocumentType.EASEMENT: {DocumentCategory.SERVITUDES},
    DocumentType.RIGHT_OF_WAY: {DocumentCategory.SERVITUDES},

    # INVOLUNTARY LIENS
    DocumentType.CONSTRUCTION_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.FEDERAL_TAX_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.JUDGMENT: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.LIS_PENDENS: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.UCC: {DocumentCategory.INVOLUNTARY_LIENS},
    DocumentType.HOA_ASSESSMENT_LIEN: {DocumentCategory.INVOLUNTARY_LIENS},

    # CHANGE
    DocumentType.RELEASE: {DocumentCategory.CHANGE},
    DocumentType.PARTIAL_RELEASE: {DocumentCategory.CHANGE},
    DocumentType.MODIFICATION_AGREEMENT: {DocumentCategory.CHANGE},
    DocumentType.ASSIGNMENT: {DocumentCategory.CHANGE},
    DocumentType.SUBORDINATION_AGREEMENT: {DocumentCategory.CHANGE},
    DocumentType.SUBSTITUTION_OF_TRUSTEE: {DocumentCategory.CHANGE},

    # OTHER
    DocumentType.COURT_DECREE: {DocumentCategory.OTHER},
    DocumentType.AFFIDAVIT: {DocumentCategory.OTHER},
    DocumentType.AGREEMENT: {DocumentCategory.OTHER},
    DocumentType.POWER_OF_ATTORNEY: {DocumentCategory.OTHER},
    DocumentType.TRUST_AGREEMENT: {DocumentCategory.OTHER},
    DocumentType.PLATS: {DocumentCategory.OTHER},
    DocumentType.PLANS: {DocumentCategory.OTHER},
}


# -----------------------------
# Main Data Model
# -----------------------------

@dataclass
class RecordedDocument:
    """
    Represents a recorded document with a single DocumentType,
    one or more categories, and optional subject matters like minerals or timber.
    """
    document_id: str
    doc_type: DocumentType
    categories: Set[DocumentCategory] = field(default_factory=set)
    subject_matters: Set[SubjectMatter] = field(default_factory=set)

    instrument_number: Optional[str] = None
    recording_date: date = field(default_factory=date.today)
    short_description: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self):
        # If categories are not explicitly set, derive from doc_type
        if not self.categories:
            default_cats = doc_type_to_categories.get(self.doc_type, set())
            self.categories = set(default_cats)


"""
Below is an extended model that integrates oil/gas/mineral (OGM) interests (and similarly timber interests) into the same document-type + categories framework you've already established. The key is to recognize that "OGM" and "timber" are subject matters, not necessarily different legal functions (like "conveyance" or "security"). You can handle them with an additional dimension—for example, a "SubjectMatter" list or set—while still using DocumentType and DocumentCategory for the legal form and function.

1. Core Idea: Separate "Subject Matter" from "Document Type" and "Categories"
DocumentType: Tells you if it's a Deed, Lease, Assignment, etc.
DocumentCategory: Tells you the legal function(s)—Conveyance, Security, Servitudes, Change, Involuntary Liens, or Other.
Subject Matter (new dimension): Indicates what is being conveyed or leased—surface estate, mineral estate, royalty interest, timber rights, etc.
Why separate them? Because you can have, for example, a Deed that conveys mineral rights, or a Lease that grants timber-cutting rights. In both cases, it's still a "Lease" or "Deed" from a legal standpoint (i.e., DocumentType = DEED or LEASE), and it might also be a "Conveyance" or "Servitude" from a functional standpoint—but the underlying subject matter is different.

2. Adding a "Subject Matter" Dimension
Let's define a small enum or list for SubjectMatter:

python
Copy
Edit
from enum import Enum

class SubjectMatter(str, Enum):
    SURFACE = "SURFACE"         # Default if it's just ordinary real estate
    MINERAL = "MINERAL"         # Oil/gas/mineral rights
    ROYALTY = "ROYALTY"         # Royalty interest
    TIMBER = "TIMBER"           # Timber rights
    # You can add more as needed, e.g. WATER, SOLAR, etc.
Note: You could make these more granular if you commonly distinguish, for instance, "Oil & Gas" from "Other Minerals." But many offices just lump them all under "Mineral," or call it "OGM."

A. One-to-Many or Many-to-Many?
A document might only convey timber rights or it might convey both surface and mineral rights.
Hence, you might want multiple SubjectMatters in one instrument. Example: a "Mineral and Surface Deed" conveys everything.
You could store a set of SubjectMatter in your code (much like categories), or you could do a many-to-many link table in a database.

3. Integrating Subject Matter into Your Existing Model
Here's a condensed Python snippet demonstrating how you can incorporate subject_matters alongside doc_type and categories.

A. Expanded Data Class
python
Copy
Edit
from dataclasses import dataclass, field
from datetime import date
from typing import Set, Optional

# (Assume DocumentType, DocumentCategory, SubjectMatter Enums exist)

@dataclass
class RecordedDocument:
    document_id: str
    doc_type: DocumentType                       # e.g. DEED, LEASE, ASSIGNMENT
    categories: Set[DocumentCategory] = field(default_factory=set)
    subject_matters: Set[SubjectMatter] = field(default_factory=set)
    
    recording_date: date = field(default_factory=date.today)
    instrument_number: Optional[str] = None
    short_description: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self):
        # If categories aren't provided, default from doc_type as before
        if not self.categories:
            default_cats = doc_type_to_categories.get(self.doc_type, set())
            self.categories = set(default_cats)
        
        # If no subject matter is provided, it might default to SURFACE, 
        # or remain empty. It's up to your business logic.
        # if not self.subject_matters:
        #    self.subject_matters.add(SubjectMatter.SURFACE)
B. Examples
Mineral Deed
Legally, it's a "Deed" (DocumentType.DEED).
Functionally, it's a "Conveyance" (categories = {CONVEYANCE}).
Subject matter is MINERAL.
python
Copy
Edit
mineral_deed = RecordedDocument(
    document_id="DOC-100",
    doc_type=DocumentType.DEED,                # It's a Deed
    subject_matters={SubjectMatter.MINERAL},   # Specifically conveys mineral rights
    short_description="Mineral Deed from Alice to Bob"
)
print(mineral_deed.doc_type)          # DEED
print(mineral_deed.categories)        # {CONVEYANCE}
print(mineral_deed.subject_matters)   # {MINERAL}
Timber Lease
Legally, it's a "Lease" (DocumentType.LEASE).
Functionally, it's also a "Conveyance" (of limited interest).
Subject matter is TIMBER.
python
Copy
Edit
timber_lease = RecordedDocument(
    document_id="DOC-200",
    doc_type=DocumentType.LEASE,
    subject_matters={SubjectMatter.TIMBER},
    short_description="Timber Lease for 5 years"
)
print(timber_lease.doc_type)          # LEASE
print(timber_lease.categories)        # {CONVEYANCE}
print(timber_lease.subject_matters)   # {TIMBER}
Oil & Gas Lease that also includes a mortgage-like clause

doc_type = LEASE, but we add categories = {CONVEYANCE, SECURITY} because it might also secure performance.
subject_matters = {MINERAL} or more specifically "OIL_GAS" if you separate that out.
Deed Reserving Timber and Mineral Rights

doc_type = DEED
categories = {CONVEYANCE}
subject_matters = {SURFACE, TIMBER, MINERAL} (maybe the deed conveys some but reserves other interests—your notes can capture the nuance).
Pooling Agreement (OGM context)

doc_type might be "AGREEMENT" (under your "OTHER" category by default).
subject_matters = {MINERAL}
If it also sets up or modifies easements, you might add category = {SERVITUDES}.
4. Handling Reservations, Assignments, and Similar OGM/TIMBER Nuances
Reservations: Typically found inside a deed or lease. In your model, that's still doc_type=DEED (or LEASE). The specific reservation is an attribute in the notes or short_description, and the subject_matters reflect the type of interest reserved (MINERAL, TIMBER, etc.).
Assignments: If it's an Assignment doc (e.g., assigning a mineral lease or timber contract), then doc_type=ASSIGNMENT with default category = {CHANGE}. The subject matter is MINERAL or TIMBER.
Agreements: Pooling agreements, unitization agreements, seismic agreements, etc., typically fall under doc_type=AGREEMENT with category = {OTHER} by default—and subject_matters can be {MINERAL} or {TIMBER}, depending on the resource.
5. Putting It All Together
With this approach:

You maintain a clean, minimal set of DocumentType values: e.g., DEED, LEASE, MORTGAGE, ASSIGNMENT, etc.
You have your DocumentCategory for legal functions (Conveyance, Security, Servitude, Involuntary_Liens, Change, Other).
You add a SubjectMatter dimension for OGM, timber, or surface interests. This can be a set—meaning one instrument might handle MINERAL and TIMBER in the same transaction.
The notes/description fields capture any unique complexities (reservations, partial interests, etc.).
Advantages
Avoids Category Bloat: You don't create separate doc_types for "Mineral Deed," "Royalty Deed," "Timber Deed," etc. Instead, you say doc_type=DEED + subject_matters={MINERAL, TIMBER, ...}
Improves Search & Reporting: You can filter by doc_type=DEED (to see all deeds), or filter by subject_matters containing MINERAL (to see all OGM-related docs), or filter by categories=SECURITY (to see all docs acting as security instruments).
Extensible: If tomorrow you start dealing with "Water Rights" or "Solar Easements," you can simply add a new subject matter (SubjectMatter.WATER or SubjectMatter.SOLAR) without breaking your existing schema.
Summary
To properly account for oil, gas, mineral, and timber interests (fee, lease, assignment, reservation, pooling, etc.):

Retain your existing concept of a single DocumentType (DEED, LEASE, etc.) + multi-Category classification (Conveyance, Security, Servitude, etc.).
Add a SubjectMatter attribute (or set of attributes) to indicate what resource(s) the instrument covers—MINERAL, TIMBER, ROYALTY, etc.
Use your existing fields (e.g., "notes" or "short_description") to capture specific references to reservations, pooling clauses, or partial interests.
This layered approach keeps the system both organized and flexible, allowing multi-dimensional searches without creating an explosion of specialized "Mineral Deed," "Timber Deed," "Mineral Lease," "Timber Lease," etc. document types.
"""
