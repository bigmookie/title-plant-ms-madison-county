# OCR Processing Specification

## Overview
This specification defines the OCR (Optical Character Recognition) pipeline for extracting and structuring text from Madison County land records. The system uses Google Document AI as the primary extraction engine, with optional AI post-processing for error correction and data structuring. The implementation focuses on confidence scoring, human-in-the-loop workflows, and best practices derived from production deployments.

## Authentication Strategy

### Primary Approach: Application Default Credentials (ADC)
Based on the working implementation in `document_reader.py` and Google's best practices, ADC is the recommended authentication method for both local development and production environments.

```python
# Local development setup (one-time)
# Run: gcloud auth application-default login

from google.api_core.client_options import ClientOptions
from google.cloud import documentai

# Configure regional endpoint (CRITICAL for non-US processors)
location = "us"  # or "eu" based on processor location
opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
client = documentai.DocumentProcessorServiceClient(client_options=opts)

# For production, attach a service account to the compute resource
# No code changes needed - ADC handles both scenarios seamlessly
```

### Service Account Best Practices
For production deployments:
- Create dedicated service accounts with minimal permissions
- Required IAM roles:
  - `roles/documentai.user` - For making processing requests
  - `roles/storage.objectAdmin` - For GCS bucket operations (batch processing)
- Never download service account keys; use workload identity instead
- For local testing with service accounts: `export GOOGLE_APPLICATION_CREDENTIALS=path/to/key.json`

## Document AI Architecture

### Processor Configuration
```python
class ProcessorConfig:
    PROJECT_ID = "madison-county-title-plant"  # Your GCP project ID
    LOCATION = "us"  # Must match processor creation location
    
    # Based on working example from document_reader.py
    PROCESSOR_ID = "2a9f06e7330cbb0a"  # Your actual processor ID
    
    # Processor types for different document categories
    PROCESSOR_TYPES = {
        "ocr": "DOCUMENT_OCR_PROCESSOR",  # Enterprise Document OCR
        "form": "FORM_PARSER_PROCESSOR",  # Form Parser
        "layout": "LAYOUT_PARSER_PROCESSOR",  # Layout Parser for RAG
        "custom": "CUSTOM_EXTRACTION_PROCESSOR"  # Custom trained model
    }
    
    # Processing limits (critical for routing logic)
    SYNC_LIMITS = {
        "max_pages": 15,  # Maximum pages for synchronous processing
        "max_file_size_mb": 40  # Maximum file size in MB
    }
    
    BATCH_LIMITS = {
        "max_pages": 500,  # For Enterprise Document OCR
        "max_files_per_request": 5000,
        "concurrent_batch_requests": 5
    }
    
    # Model routing thresholds
    ROUTING_THRESHOLDS = {
        "lightweight_model": 0.95,  # Use small model above this confidence
        "medium_model": 0.85,       # Escalate to medium model below this
        "large_model": 0.70,         # Escalate to large model below this
        "human_review": 0.60         # Send for human review below this
    }
```

### Image Preprocessing & Enhancement

#### Preprocessing Pipeline for Optimal OCR
```python
class ImagePreprocessor:
    """
    Advanced image preprocessing to improve OCR accuracy by 15-30%.
    Based on research showing deskewing alone improves accuracy by 5-15%.
    """
    
    def preprocess_document(self, pdf_path: Path) -> Path:
        """Full preprocessing pipeline for document images"""
        import cv2
        import numpy as np
        from pdf2image import convert_from_path
        
        # Convert PDF to images at optimal DPI
        images = convert_from_path(pdf_path, dpi=300)
        processed_images = []
        
        for img in images:
            # Convert PIL to OpenCV format
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            
            # 1. Binarization (improves contrast)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            binary = cv2.adaptiveThreshold(
                gray, 255, 
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            
            # 2. Deskewing (5-15% accuracy improvement)
            angle = self.determine_skew_angle(binary)
            if abs(angle) > 0.5:  # Only deskew if angle is significant
                deskewed = self.rotate_image(binary, angle)
            else:
                deskewed = binary
            
            # 3. Denoising (3-8% accuracy improvement)
            denoised = cv2.fastNlMeansDenoising(deskewed)
            
            # 4. Border removal (prevents OCR interference)
            cleaned = self.remove_borders(denoised)
            
            # 5. Resolution optimization
            if cleaned.shape[0] < 3000:  # Upscale low-res images
                cleaned = cv2.resize(
                    cleaned, None, fx=1.5, fy=1.5, 
                    interpolation=cv2.INTER_CUBIC
                )
            
            processed_images.append(cleaned)
        
        # Save processed images back to PDF
        processed_path = pdf_path.with_suffix('.preprocessed.pdf')
        self.images_to_pdf(processed_images, processed_path)
        return processed_path
    
    def determine_skew_angle(self, image: np.ndarray) -> float:
        """Detect document skew angle using Hough transform"""
        edges = cv2.Canny(image, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi/180, 200)
        
        if lines is not None:
            angles = []
            for rho, theta in lines[:20]:  # Use top 20 lines
                angle = np.degrees(theta) - 90
                angles.append(angle)
            
            # Return median angle to avoid outliers
            return np.median(angles)
        return 0.0
    
    def rotate_image(self, image: np.ndarray, angle: float) -> np.ndarray:
        """Rotate image to correct skew"""
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        
        # Calculate new dimensions to avoid cropping
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))
        
        # Adjust rotation matrix for new dimensions
        M[0, 2] += (new_w / 2) - center[0]
        M[1, 2] += (new_h / 2) - center[1]
        
        return cv2.warpAffine(
            image, M, (new_w, new_h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255
        )
    
    def remove_borders(self, image: np.ndarray) -> np.ndarray:
        """Remove black borders and lines that interfere with OCR"""
        # Find contours
        contours, _ = cv2.findContours(
            255 - image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        
        if contours:
            # Find largest contour (document)
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            
            # Crop to content with small margin
            margin = 10
            return image[
                max(0, y-margin):min(image.shape[0], y+h+margin),
                max(0, x-margin):min(image.shape[1], x+w+margin)
            ]
        return image
```

### Processing Pipeline

#### Phase 1: Raw Text Extraction with Enhanced Confidence Scoring
```python
def extract_raw_text(pdf_path: Path) -> documentai.Document:
    """
    Extract text with confidence scores using Document AI.
    Includes preprocessing for 15-30% accuracy improvement.
    """
    # Apply image preprocessing first
    preprocessor = ImagePreprocessor()
    preprocessed_path = preprocessor.preprocess_document(pdf_path)
    
    # Determine processing mode based on document size
    page_count = get_pdf_page_count(preprocessed_path)
    file_size_mb = os.path.getsize(preprocessed_path) / (1024 * 1024)
    
    if page_count <= 15 and file_size_mb <= 40:
        # Use synchronous processing for small documents
        document = process_document_sync(preprocessed_path)
    else:
        # Use batch processing for large documents
        document = process_document_batch(preprocessed_path)
    
    # Apply multi-engine voting for critical documents
    if is_critical_document(document):
        document = apply_multi_engine_voting(preprocessed_path, document)
    
    return document

def process_document_sync(pdf_path: Path) -> documentai.Document:
    """
    Synchronous processing for documents ≤15 pages
    """
    opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)
    
    with open(pdf_path, "rb") as f:
        raw_document = documentai.RawDocument(
            content=f.read(),
            mime_type="application/pdf"
        )
    
    request = documentai.ProcessRequest(
        name=name,
        raw_document=raw_document,
        # Request all fields needed for confidence scoring
        field_mask="text,pages,entities,pages.tokens,pages.confidence"
    )
    
    result = client.process_document(request=request)
    return result.document
```

#### Phase 2: Advanced AI Correction with Hybrid Model Strategy
```python
class HybridModelCorrector:
    """
    Implements tiered model approach for cost-effective high accuracy.
    Uses lightweight models for 90% of documents, escalates only when needed.
    """
    
    def __init__(self):
        self.lightweight_model = "gemini-1.5-flash"  # Fast, cheap
        self.medium_model = "gemini-1.5-pro"         # Balanced
        self.large_model = "gemini-1.5-ultra"        # High accuracy
        
    def apply_ai_correction(self, 
                           document: documentai.Document, 
                           doc_type: str) -> CorrectedDocument:
        """
        Apply tiered AI correction based on confidence scores.
        Implements prompt engineering and chain-of-thought for accuracy.
        """
        # Calculate overall document confidence
        doc_confidence = calculate_document_confidence(document)
        
        # Route to appropriate model based on confidence
        if doc_confidence.overall > 0.95:
            # High confidence - lightweight validation only
            return self.validate_with_lightweight_model(document, doc_type)
        
        elif doc_confidence.overall > 0.85:
            # Medium confidence - use optimized lightweight model with advanced prompting
            return self.correct_with_lightweight_model(document, doc_type)
        
        elif doc_confidence.overall > 0.70:
            # Low confidence - escalate to medium model
            return self.correct_with_medium_model(document, doc_type)
        
        else:
            # Very low confidence - use large model or human review
            return self.correct_with_large_model(document, doc_type)
    
    def correct_with_lightweight_model(self, 
                                      document: documentai.Document,
                                      doc_type: str) -> CorrectedDocument:
        """
        Use lightweight model with advanced prompt engineering.
        Implements chain-of-thought and few-shot examples.
        """
        # Prepare structured prompt with explicit instructions
        prompt = self.build_extraction_prompt(document.text, doc_type)
        
        # Add few-shot examples for the document type
        prompt = self.add_few_shot_examples(prompt, doc_type)
        
        # Request chain-of-thought reasoning
        cot_prompt = f"""
        {prompt}
        
        IMPORTANT: Follow these steps:
        1. First, identify the document type and key sections
        2. List the key information found for each field
        3. Verify dates and names against the original text
        4. Output the final JSON with all required fields
        
        If any field is unclear or missing, mark it as "UNCERTAIN".
        
        ### REASONING:
        [Your step-by-step analysis here]
        
        ### FINAL JSON OUTPUT:
        """
        
        # Get model response
        response = self.call_model(self.lightweight_model, cot_prompt)
        
        # Parse response and extract JSON
        extracted_data = self.parse_model_response(response)
        
        # Apply post-processing and validation
        validated_data = self.validate_and_correct(extracted_data, document.text)
        
        return CorrectedDocument(
            text=document.text,
            structured_data=validated_data,
            corrections_applied=True,
            confidence_scores=doc_confidence,
            model_used=self.lightweight_model
        )
    
    def build_extraction_prompt(self, text: str, doc_type: str) -> str:
        """Build document-type specific extraction prompt"""
        
        if doc_type == "DEED":
            return f"""
            Extract the following fields from this deed document:
            1. Document Title (e.g., WARRANTY DEED, QUITCLAIM DEED)
            2. Recording Date (format: YYYY-MM-DD)
            3. Grantor(s) - all parties conveying property
            4. Grantee(s) - all parties receiving property
            5. Legal Description - complete property description
            6. Consideration Amount (if stated)
            7. Reservations/Exceptions (mineral rights, easements, etc.)
            
            Document text:
            {text}
            
            Output as JSON with these exact field names.
            """
        
        elif doc_type == "DEED_OF_TRUST":
            return f"""
            Extract the following fields from this deed of trust:
            1. Trustor(s) - borrower names
            2. Beneficiary - lender name
            3. Trustee - trustee name
            4. Principal Amount
            5. Property Description
            6. Recording Information (book, page, date)
            
            Document text:
            {text}
            
            Output as JSON with these exact field names.
            """
        
        # Add more document types...
        return f"Extract key information from this {doc_type} document:\n{text}"
    
    def add_few_shot_examples(self, prompt: str, doc_type: str) -> str:
        """Add domain-specific few-shot examples"""
        
        examples = {
            "DEED": """
            Example Input: "This WARRANTY DEED made this 5th day of June, 2020, 
            between John Doe and Jane Doe, husband and wife (Grantors) and 
            Robert Smith (Grantee)... property described as: Lot 5, Block 3, 
            Madison Heights Subdivision..."
            
            Example Output:
            {
                "document_title": "WARRANTY DEED",
                "recording_date": "2020-06-05",
                "grantors": ["John Doe", "Jane Doe"],
                "grantees": ["Robert Smith"],
                "legal_description": "Lot 5, Block 3, Madison Heights Subdivision",
                "consideration": "NOT STATED",
                "reservations": "NONE"
            }
            """,
            # Add more examples...
        }
        
        if doc_type in examples:
            return f"{prompt}\n\nEXAMPLE:\n{examples[doc_type]}"
        return prompt
    
    def validate_and_correct(self, 
                            extracted_data: dict,
                            original_text: str) -> dict:
        """
        Apply domain rules and heuristics for validation.
        Cross-check extracted data against original text.
        """
        validator = LegalDocumentValidator()
        
        # Check names actually appear in text
        for field in ['grantors', 'grantees', 'trustor', 'beneficiary']:
            if field in extracted_data:
                names = extracted_data[field]
                if isinstance(names, list):
                    verified_names = []
                    for name in names:
                        if self.verify_name_in_text(name, original_text):
                            verified_names.append(name)
                        else:
                            # Try fuzzy matching
                            corrected = self.fuzzy_match_name(name, original_text)
                            if corrected:
                                verified_names.append(corrected)
                    extracted_data[field] = verified_names
        
        # Validate and normalize dates
        if 'recording_date' in extracted_data:
            date_str = extracted_data['recording_date']
            validated_date = validator.validate_date(date_str, original_text)
            extracted_data['recording_date'] = validated_date
        
        # Validate legal descriptions
        if 'legal_description' in extracted_data:
            legal_desc = extracted_data['legal_description']
            if not validator.is_valid_legal_description(legal_desc):
                # Try to extract using regex patterns
                extracted_desc = self.extract_legal_description_regex(original_text)
                if extracted_desc:
                    extracted_data['legal_description'] = extracted_desc
        
        # Apply business rules
        extracted_data = validator.apply_business_rules(extracted_data, doc_type)
        
        return extracted_data
```

## Retrieval-Augmented Generation (RAG) Integration

### RAG Pipeline for Enhanced Accuracy
```python
class RAGEnhancedExtractor:
    """
    Implements RAG to provide domain context and examples to models.
    Improves extraction accuracy by referencing similar processed documents.
    """
    
    def __init__(self):
        self.vector_store = self.initialize_vector_store()
        self.legal_glossary = self.load_legal_glossary()
        
    def initialize_vector_store(self):
        """Initialize vector database with processed documents"""
        from langchain.vectorstores import Chroma
        from langchain.embeddings import VertexAIEmbeddings
        
        embeddings = VertexAIEmbeddings(model_name="textembedding-gecko")
        
        # Load with previously processed and validated documents
        vector_store = Chroma(
            collection_name="madison_county_docs",
            embedding_function=embeddings,
            persist_directory="./vector_db"
        )
        
        return vector_store
    
    def enhance_with_context(self, 
                            document_text: str,
                            doc_type: str) -> str:
        """
        Retrieve relevant examples and context for the document.
        """
        # Find similar documents
        similar_docs = self.vector_store.similarity_search(
            document_text[:1000],  # Use first 1000 chars for search
            k=3,  # Get top 3 similar documents
            filter={"doc_type": doc_type}
        )
        
        # Find relevant legal definitions
        relevant_terms = self.extract_legal_terms(document_text)
        definitions = [
            self.legal_glossary.get(term, "") 
            for term in relevant_terms
        ]
        
        # Build enhanced context
        context = f"""
        REFERENCE DOCUMENTS:
        {self.format_similar_docs(similar_docs)}
        
        LEGAL DEFINITIONS:
        {self.format_definitions(relevant_terms, definitions)}
        
        EXTRACTION PATTERNS FROM SIMILAR DOCUMENTS:
        {self.extract_patterns(similar_docs)}
        """
        
        return context
    
    def extract_patterns(self, similar_docs: list) -> str:
        """Extract common patterns from similar documents"""
        patterns = []
        
        for doc in similar_docs:
            if 'structured_data' in doc.metadata:
                data = doc.metadata['structured_data']
                
                # Extract pattern examples
                if 'legal_description' in data:
                    patterns.append(f"Legal Description Pattern: {data['legal_description'][:100]}...")
                
                if 'granting_clause' in data:
                    patterns.append(f"Granting Clause: {data['granting_clause'][:50]}...")
        
        return "\n".join(patterns)
```

### Legal Domain Heuristics
```python
class LegalHeuristicsProcessor:
    """
    Apply domain-specific rules and patterns for Madison County documents.
    Serves as safety net and validation layer.
    """
    
    # Common patterns in Madison County documents
    PATTERNS = {
        'document_title': r'(WARRANTY DEED|QUITCLAIM DEED|DEED OF TRUST|MORTGAGE)',
        'granting_clause': r'does hereby\s+(grant|convey|transfer|quitclaim)',
        'legal_desc_start': r'(described as follows|bounded as follows|being)',
        'exceptions_start': r'(subject to|except|reserving|less and except)',
        'mineral_reservation': r'(reserving.*mineral|oil.*gas.*rights)',
        'consideration': r'consideration.*sum of.*dollars',
        'section_township': r'Section\s+(\d+).*Township\s+(\d+\s*[NS]).*Range\s+(\d+\s*[EW])',
        'lot_block': r'Lot\s+(\d+).*Block\s+([A-Z0-9]+)',
        'recording_info': r'Book\s+(\d+).*Page\s+(\d+)'
    }
    
    def extract_with_heuristics(self, text: str) -> dict:
        """
        Extract key information using regex patterns.
        Used as fallback or validation for AI extraction.
        """
        extracted = {}
        
        # Extract document title
        title_match = re.search(self.PATTERNS['document_title'], text, re.IGNORECASE)
        if title_match:
            extracted['document_title'] = title_match.group(1)
        
        # Extract legal description
        legal_desc = self.extract_legal_description(text)
        if legal_desc:
            extracted['legal_description'] = legal_desc
        
        # Extract parties
        extracted['parties'] = self.extract_parties(text)
        
        # Extract recording information
        recording = self.extract_recording_info(text)
        if recording:
            extracted.update(recording)
        
        # Check for reservations/exceptions
        extracted['reservations'] = self.extract_reservations(text)
        
        return extracted
    
    def extract_legal_description(self, text: str) -> Optional[str]:
        """
        Extract legal description using multiple strategies.
        """
        # Strategy 1: Look for section/township/range
        str_match = re.search(self.PATTERNS['section_township'], text)
        if str_match:
            return f"Section {str_match.group(1)}, Township {str_match.group(2)}, Range {str_match.group(3)}"
        
        # Strategy 2: Look for lot/block
        lot_match = re.search(self.PATTERNS['lot_block'], text)
        if lot_match:
            # Find subdivision name nearby
            subdivision = self.find_subdivision_name(text, lot_match.span())
            return f"Lot {lot_match.group(1)}, Block {lot_match.group(2)}, {subdivision}"
        
        # Strategy 3: Extract metes and bounds
        if 'beginning at' in text.lower() or 'commencing at' in text.lower():
            return self.extract_metes_bounds(text)
        
        # Strategy 4: Look for generic description pattern
        desc_start = re.search(self.PATTERNS['legal_desc_start'], text, re.IGNORECASE)
        if desc_start:
            # Extract next 500 characters as description
            start_pos = desc_start.end()
            return self.clean_legal_description(text[start_pos:start_pos+500])
        
        return None
    
    def validate_extraction(self, 
                          ai_extracted: dict,
                          heuristic_extracted: dict) -> dict:
        """
        Cross-validate AI extraction with heuristic extraction.
        Merge and correct discrepancies.
        """
        validated = ai_extracted.copy()
        
        # Validate document title
        if 'document_title' in heuristic_extracted:
            ai_title = ai_extracted.get('document_title', '').upper()
            heuristic_title = heuristic_extracted['document_title'].upper()
            
            if ai_title != heuristic_title:
                # Trust heuristic if it matches known patterns
                if heuristic_title in self.KNOWN_DOC_TITLES:
                    validated['document_title'] = heuristic_title
                    validated['title_confidence'] = 'CORRECTED'
        
        # Validate legal description presence
        if 'legal_description' not in ai_extracted and 'legal_description' in heuristic_extracted:
            validated['legal_description'] = heuristic_extracted['legal_description']
            validated['legal_desc_source'] = 'HEURISTIC'
        
        # Validate recording info
        if 'book' in heuristic_extracted and 'book' not in ai_extracted:
            validated['book'] = heuristic_extracted['book']
            validated['page'] = heuristic_extracted.get('page')
        
        return validated
```

## Document Type Handlers

### Deed Processing
```python
class DeedProcessor:
    """Specialized handler for deed documents"""
    
    EXPECTED_SECTIONS = [
        "grantor",
        "grantee", 
        "legal_description",
        "consideration",
        "recording_info",
        "acknowledgment"
    ]
    
    def extract_structured_data(self, ocr_result: DocumentAIResponse) -> DeedData:
        deed_data = DeedData()
        
        # Extract parties
        deed_data.grantor = self.extract_party(ocr_result, "grantor")
        deed_data.grantee = self.extract_party(ocr_result, "grantee")
        
        # Extract legal description with special handling
        deed_data.legal_description = self.extract_legal_description(
            ocr_result,
            use_boundary_detection=True
        )
        
        # Extract recording information
        deed_data.recording = self.extract_recording_info(ocr_result)
        
        return deed_data
    
    def extract_legal_description(self, ocr_result, use_boundary_detection=True):
        """
        Complex extraction for legal descriptions
        Handles: Metes & bounds, lot/block, section/township/range
        """
        patterns = {
            "metes_bounds": r"(beginning|commencing)\s+at.*?thence.*?",
            "lot_block": r"lot\s+\d+.*?block\s+\w+",
            "section": r"section\s+\d+.*?township\s+\d+.*?range\s+\d+"
        }
        # Implementation details...
```

### Will Processing
```python
class WillProcessor:
    """Specialized handler for will documents"""
    
    def extract_structured_data(self, ocr_result: DocumentAIResponse) -> WillData:
        will_data = WillData()
        
        # Extract testator information
        will_data.testator = self.extract_testator(ocr_result)
        
        # Extract beneficiaries and bequests
        will_data.beneficiaries = self.extract_beneficiaries(ocr_result)
        will_data.bequests = self.extract_bequests(ocr_result)
        
        # Extract executor information
        will_data.executor = self.extract_executor(ocr_result)
        
        # Extract witnesses
        will_data.witnesses = self.extract_witnesses(ocr_result)
        
        return will_data
```

## Quality Assurance

### Comprehensive Confidence Scoring
```python
from typing import List, Tuple, NamedTuple
from dataclasses import dataclass

@dataclass
class ConfidenceMetrics:
    """Detailed confidence metrics for document analysis"""
    overall: float
    page_level: List[float]
    token_level: List[float]
    entity_level: List[float]
    low_confidence_regions: List[Tuple[int, int, float]]  # (start, end, confidence)
    requires_review: bool
    review_reasons: List[str]

class ConfidenceScorer:
    """Enhanced confidence scoring based on Document AI best practices"""
    
    # Thresholds for human review
    REVIEW_THRESHOLDS = {
        'critical_field': 0.95,  # For critical fields like amounts, dates
        'standard_field': 0.85,  # For standard text fields
        'overall_document': 0.90,  # Overall document quality
        'page_minimum': 0.80,  # Minimum acceptable page confidence
    }
    
    def calculate_document_confidence(self, document: documentai.Document) -> ConfidenceMetrics:
        """
        Calculate comprehensive confidence metrics for human-in-the-loop decisions.
        Based on https://cloud.google.com/document-ai/docs/evaluate
        """
        page_scores = []
        token_scores = []
        entity_scores = []
        low_confidence_regions = []
        review_reasons = []
        
        # 1. Page-level confidence analysis
        for page in document.pages:
            if hasattr(page, 'confidence') and page.confidence:
                page_conf = float(page.confidence)
                page_scores.append(page_conf)
                
                if page_conf < self.REVIEW_THRESHOLDS['page_minimum']:
                    review_reasons.append(
                        f"Page {page.page_number} has low confidence: {page_conf:.2%}"
                    )
            
            # 2. Token-level confidence (most granular)
            for token in page.tokens:
                if hasattr(token, 'confidence') and token.confidence:
                    token_conf = float(token.confidence)
                    token_scores.append(token_conf)
                    
                    # Track low-confidence text regions
                    if token_conf < 0.80 and token.layout.text_anchor.text_segments:
                        for segment in token.layout.text_anchor.text_segments:
                            low_confidence_regions.append(
                                (segment.start_index, segment.end_index, token_conf)
                            )
        
        # 3. Entity-level confidence (for extracted fields)
        if hasattr(document, 'entities'):
            for entity in document.entities:
                if hasattr(entity, 'confidence') and entity.confidence:
                    entity_conf = float(entity.confidence)
                    entity_scores.append(entity_conf)
                    
                    # Check if critical fields need review
                    if self._is_critical_field(entity.type_):
                        if entity_conf < self.REVIEW_THRESHOLDS['critical_field']:
                            review_reasons.append(
                                f"Critical field '{entity.type_}' has low confidence: {entity_conf:.2%}"
                            )
                    elif entity_conf < self.REVIEW_THRESHOLDS['standard_field']:
                        review_reasons.append(
                            f"Field '{entity.type_}' has low confidence: {entity_conf:.2%}"
                        )
        
        # 4. Calculate overall confidence
        all_scores = page_scores + token_scores + entity_scores
        overall_confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
        
        # 5. Determine if human review is required
        requires_review = (
            overall_confidence < self.REVIEW_THRESHOLDS['overall_document'] or
            len(review_reasons) > 0
        )
        
        return ConfidenceMetrics(
            overall=overall_confidence,
            page_level=page_scores,
            token_level=token_scores[:100],  # Sample for memory efficiency
            entity_level=entity_scores,
            low_confidence_regions=low_confidence_regions[:50],  # Top 50 regions
            requires_review=requires_review,
            review_reasons=review_reasons
        )
    
    def _is_critical_field(self, field_type: str) -> bool:
        """Determine if a field is critical for accuracy"""
        critical_fields = {
            'recording_date', 'instrument_number', 'book', 'page',
            'grantor', 'grantee', 'consideration', 'legal_description',
            'total_amount', 'invoice_id', 'supplier_name'
        }
        return field_type.lower() in critical_fields
```

### Human-in-the-Loop (HITL) Integration
```python
class HITLManager:
    """
    Manages human review workflows based on confidence scores.
    Implements best practices from production deployments.
    """
    
    def __init__(self, confidence_scorer: ConfidenceScorer):
        self.scorer = confidence_scorer
        self.review_queue = []
    
    def should_route_for_review(self, 
                                document: documentai.Document,
                                doc_type: str) -> Tuple[bool, List[str]]:
        """
        Determine if document needs human review.
        Returns (should_review, reasons)
        """
        metrics = self.scorer.calculate_document_confidence(document)
        
        # Apply document-type specific rules
        type_specific_reasons = self._check_document_type_rules(document, doc_type)
        
        all_reasons = metrics.review_reasons + type_specific_reasons
        should_review = metrics.requires_review or len(type_specific_reasons) > 0
        
        return should_review, all_reasons
    
    def _check_document_type_rules(self, 
                                   document: documentai.Document,
                                   doc_type: str) -> List[str]:
        """Apply document-specific validation rules"""
        reasons = []
        
        if doc_type == "deed":
            # Deeds require high confidence for legal descriptions
            for entity in document.entities:
                if entity.type_ == "legal_description":
                    if entity.confidence < 0.98:
                        reasons.append(
                            f"Legal description requires manual verification (confidence: {entity.confidence:.2%})"
                        )
        
        elif doc_type == "will":
            # Wills require verification of all beneficiaries
            beneficiary_entities = [
                e for e in document.entities 
                if "beneficiary" in e.type_.lower()
            ]
            if any(e.confidence < 0.95 for e in beneficiary_entities):
                reasons.append("Beneficiary information requires manual verification")
        
        return reasons
    
    def create_review_task(self, 
                          document: documentai.Document,
                          document_id: str,
                          metrics: ConfidenceMetrics) -> dict:
        """
        Create a review task for human validation.
        Structure compatible with partner HITL solutions.
        """
        return {
            "task_id": f"review_{document_id}_{int(time.time())}",
            "document_id": document_id,
            "created_at": datetime.now().isoformat(),
            "priority": self._calculate_priority(metrics),
            "confidence_metrics": {
                "overall": metrics.overall,
                "requires_review": metrics.requires_review,
                "review_reasons": metrics.review_reasons
            },
            "fields_to_review": self._identify_fields_for_review(document, metrics),
            "status": "pending",
            "assigned_to": None
        }
    
    def _calculate_priority(self, metrics: ConfidenceMetrics) -> str:
        """Calculate review priority based on confidence"""
        if metrics.overall < 0.70:
            return "high"
        elif metrics.overall < 0.85:
            return "medium"
        else:
            return "low"
    
    def _identify_fields_for_review(self, 
                                   document: documentai.Document,
                                   metrics: ConfidenceMetrics) -> List[dict]:
        """Identify specific fields that need human review"""
        fields = []
        
        for entity in document.entities:
            if entity.confidence < 0.90:
                fields.append({
                    "field_name": entity.type_,
                    "extracted_value": entity.mention_text,
                    "confidence": entity.confidence,
                    "page_number": self._get_entity_page(entity, document),
                    "bounding_box": self._get_entity_bbox(entity)
                })
        
        return fields
```

## Error Handling

### OCR Failure Recovery
```python
class OCRFailureHandler:
    def handle_failure(self, document_id: str, error: Exception) -> RecoveryAction:
        """
        Determine recovery strategy based on error type
        """
        if isinstance(error, QuotaExceededError):
            return RecoveryAction.RETRY_LATER
        
        elif isinstance(error, CorruptedPDFError):
            # Try PDF repair
            repaired_path = self.repair_pdf(document_id)
            if repaired_path:
                return RecoveryAction.RETRY_WITH_REPAIRED
            return RecoveryAction.MARK_AS_FAILED
        
        elif isinstance(error, LowQualityImageError):
            # Try image enhancement
            enhanced_path = self.enhance_image_quality(document_id)
            if enhanced_path:
                return RecoveryAction.RETRY_WITH_ENHANCED
            return RecoveryAction.REQUEST_MANUAL_REVIEW
        
        else:
            return RecoveryAction.RETRY_WITH_BACKOFF
```

### Image Enhancement
```python
def enhance_document_image(image_path: Path) -> Path:
    """
    Enhance image quality for better OCR results
    """
    import cv2
    import numpy as np
    
    img = cv2.imread(str(image_path))
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Apply thresholding to get binary image
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Denoise
    denoised = cv2.fastNlMeansDenoising(thresh)
    
    # Deskew
    angle = determine_skew_angle(denoised)
    deskewed = rotate_image(denoised, angle)
    
    # Save enhanced image
    enhanced_path = image_path.with_suffix('.enhanced.png')
    cv2.imwrite(str(enhanced_path), deskewed)
    
    return enhanced_path
```

## Scalable Infrastructure for Bursty Workloads

### Auto-Scaling Architecture
```python
class ScalableOCRPipeline:
    """
    Cloud-native architecture for handling burst processing.
    Scales from 0 to thousands of documents per hour.
    """
    
    def __init__(self):
        self.queue_service = self.setup_queue_service()
        self.model_pool = self.setup_model_pool()
        self.metrics = self.setup_monitoring()
    
    def setup_queue_service(self):
        """Setup message queue for async processing"""
        from google.cloud import pubsub_v1
        
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        
        return {
            'publisher': publisher,
            'subscriber': subscriber,
            'topic': 'projects/{}/topics/ocr-requests'.format(PROJECT_ID),
            'subscription': 'projects/{}/subscriptions/ocr-workers'.format(PROJECT_ID)
        }
    
    def setup_model_pool(self):
        """Configure auto-scaling model serving"""
        return {
            'lightweight': {
                'min_instances': 1,  # Keep warm for fast response
                'max_instances': 20,  # Scale up during bursts
                'target_cpu': 70,
                'scale_down_delay': 300  # 5 minutes
            },
            'medium': {
                'min_instances': 0,  # Scale to zero when idle
                'max_instances': 10,
                'target_cpu': 60,
                'scale_down_delay': 600  # 10 minutes
            },
            'large': {
                'min_instances': 0,  # Only on-demand
                'max_instances': 5,
                'target_cpu': 50,
                'scale_down_delay': 900  # 15 minutes
            }
        }
    
    async def process_document_async(self, document_path: str):
        """
        Async processing with automatic scaling.
        """
        # Publish to queue
        message = {
            'document_path': document_path,
            'timestamp': datetime.now().isoformat(),
            'priority': self.calculate_priority(document_path)
        }
        
        future = self.queue_service['publisher'].publish(
            self.queue_service['topic'],
            json.dumps(message).encode('utf-8')
        )
        
        return future.result()
    
    def worker_process(self):
        """
        Worker that pulls from queue and processes documents.
        Auto-scales based on queue depth.
        """
        def callback(message):
            try:
                data = json.loads(message.data.decode('utf-8'))
                document_path = data['document_path']
                
                # Process document
                result = self.process_with_appropriate_model(document_path)
                
                # Store result
                self.store_result(result)
                
                # Acknowledge message
                message.ack()
                
            except Exception as e:
                # Log error and potentially retry
                logger.error(f"Processing failed: {e}")
                message.nack()
        
        # Subscribe to queue
        flow_control = pubsub_v1.types.FlowControl(max_messages=10)
        
        self.queue_service['subscriber'].subscribe(
            self.queue_service['subscription'],
            callback=callback,
            flow_control=flow_control
        )
    
    def calculate_priority(self, document_path: str) -> int:
        """
        Determine processing priority based on document characteristics.
        """
        # Higher priority for smaller, newer documents
        file_size = os.path.getsize(document_path)
        
        if file_size < 1_000_000:  # < 1MB
            return 1  # High priority
        elif file_size < 10_000_000:  # < 10MB
            return 2  # Medium priority
        else:
            return 3  # Low priority
```

### Serverless Function Deployment
```python
# Cloud Function for lightweight OCR processing
def ocr_cloud_function(request):
    """
    Google Cloud Function for OCR processing.
    Scales automatically based on demand.
    """
    import functions_framework
    from google.cloud import documentai
    
    # Parse request
    request_json = request.get_json()
    document_url = request_json['document_url']
    doc_type = request_json.get('doc_type', 'UNKNOWN')
    
    # Download document from GCS
    document_bytes = download_from_gcs(document_url)
    
    # Preprocess if needed
    if request_json.get('preprocess', False):
        document_bytes = preprocess_image(document_bytes)
    
    # Run OCR
    document = run_document_ai(document_bytes)
    
    # Extract with lightweight model
    if document.confidence > 0.95:
        # High confidence - use fast extraction
        extracted = quick_extract(document, doc_type)
    else:
        # Lower confidence - trigger escalation
        trigger_advanced_processing(document_url, document)
        extracted = {'status': 'escalated'}
    
    return {
        'document_url': document_url,
        'extracted_data': extracted,
        'confidence': document.confidence
    }

# Deploy with auto-scaling
# gcloud functions deploy ocr_cloud_function \
#   --runtime python39 \
#   --trigger-http \
#   --memory 2GB \
#   --max-instances 100 \
#   --min-instances 1
```

### Kubernetes Deployment for Model Serving
```yaml
# deployment.yaml for auto-scaling OCR service
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ocr-model-server
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ocr-model
  template:
    metadata:
      labels:
        app: ocr-model
    spec:
      containers:
      - name: model-server
        image: gcr.io/madison-county/ocr-model:latest
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
        env:
        - name: MODEL_TYPE
          value: "lightweight"
        - name: MAX_BATCH_SIZE
          value: "32"
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ocr-model-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ocr-model-server
  minReplicas: 1
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
      - type: Pods
        value: 10
        periodSeconds: 60
```

## Batch Processing

### Parallel Processing with Cost Optimization
```python
class BatchOCRProcessor:
    """
    Optimized batch processor with cost-aware routing.
    """
    
    def __init__(self, max_workers=5, batch_size=50):
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.rate_limiter = RateLimiter(calls_per_minute=300)
        self.cost_tracker = CostTracker()
    
    async def process_batch(self, documents: List[Path]) -> List[OCRResult]:
        """
        Process multiple documents in parallel with intelligent routing.
        """
        # Sort documents by complexity for optimal batching
        sorted_docs = self.sort_by_complexity(documents)
        
        # Split into batches by processing tier
        simple_batch = [d for d in sorted_docs if self.is_simple(d)]
        complex_batch = [d for d in sorted_docs if not self.is_simple(d)]
        
        results = []
        
        # Process simple documents with lightweight model
        if simple_batch:
            simple_results = await self.process_with_model(
                simple_batch, 
                model='lightweight',
                max_workers=self.max_workers * 2  # More parallel for fast model
            )
            results.extend(simple_results)
        
        # Process complex documents with appropriate model
        if complex_batch:
            complex_results = await self.process_with_model(
                complex_batch,
                model='adaptive',  # Choose model based on confidence
                max_workers=self.max_workers
            )
            results.extend(complex_results)
        
        # Track costs
        self.cost_tracker.record_batch(results)
        
        return results
    
    def sort_by_complexity(self, documents: List[Path]) -> List[Path]:
        """
        Sort documents by estimated complexity.
        Simple documents processed first for quick wins.
        """
        scored_docs = []
        
        for doc in documents:
            score = 0
            
            # File size indicator
            size_mb = os.path.getsize(doc) / (1024 * 1024)
            score += min(size_mb, 10)  # Cap at 10
            
            # Page count indicator
            page_count = get_pdf_page_count(doc)
            score += min(page_count, 20)  # Cap at 20
            
            # Document type complexity
            doc_type = self.infer_doc_type(doc.name)
            complexity_scores = {
                'DEED': 1,
                'DEED_OF_TRUST': 2,
                'PLAT': 5,
                'WILL': 3,
                'UNKNOWN': 10
            }
            score += complexity_scores.get(doc_type, 5)
            
            scored_docs.append((score, doc))
        
        # Sort by complexity score
        scored_docs.sort(key=lambda x: x[0])
        
        return [doc for _, doc in scored_docs]
```

### Progress Tracking
```python
class OCRProgressTracker:
    def __init__(self, total_documents: int):
        self.total = total_documents
        self.processed = 0
        self.failed = 0
        self.start_time = time.time()
    
    def update(self, success: bool):
        if success:
            self.processed += 1
        else:
            self.failed += 1
        
        # Calculate metrics
        elapsed = time.time() - self.start_time
        rate = self.processed / elapsed if elapsed > 0 else 0
        eta = (self.total - self.processed) / rate if rate > 0 else 0
        
        # Log progress
        logger.info(f"Progress: {self.processed}/{self.total} "
                   f"({self.processed/self.total*100:.1f}%) "
                   f"Rate: {rate:.1f} docs/sec "
                   f"ETA: {eta/60:.1f} minutes")
```

## Output Format

### Structured JSON Output
```json
{
    "document_id": "0001_0001_DEED",
    "ocr_metadata": {
        "processor_version": "1.0.0",
        "processing_timestamp": "2024-01-01T00:00:00Z",
        "confidence_score": 0.92,
        "page_count": 2,
        "corrections_applied": false
    },
    "raw_text": "Full OCR text...",
    "structured_data": {
        "document_type": "DEED",
        "parties": {
            "grantor": ["John Smith", "Jane Smith"],
            "grantee": ["Robert Jones"]
        },
        "legal_description": {
            "type": "LOT_BLOCK",
            "text": "Lot 5, Block 3, Madison Heights Subdivision",
            "parsed": {
                "lot": "5",
                "block": "3",
                "subdivision": "Madison Heights"
            }
        },
        "dates": {
            "execution": "1950-03-15",
            "recording": "1950-03-20"
        },
        "recording_info": {
            "book": "1",
            "page": "1",
            "instrument_number": "1950-00001"
        }
    },
    "validation": {
        "status": "VALID",
        "errors": [],
        "warnings": ["Low confidence in date extraction"]
    }
}
```

## Cost Optimization

### Tiered Pricing Model
```python
class CostOptimizer:
    """
    Comprehensive cost optimization for OCR pipeline.
    Balances accuracy requirements with processing costs.
    """
    
    # Cost per 1000 API calls (approximate)
    MODEL_COSTS = {
        'document_ai': 1.50,      # Per 1000 pages after free tier
        'gemini_flash': 0.075,     # Per 1M tokens (~250 pages)
        'gemini_pro': 1.25,        # Per 1M tokens
        'gemini_ultra': 7.00,      # Per 1M tokens
        'human_review': 50.00      # Per document
    }
    
    def estimate_processing_cost(self, 
                                document_count: int,
                                confidence_distribution: dict) -> dict:
        """
        Estimate costs based on tiered processing strategy.
        """
        # Document AI OCR cost (all documents)
        ocr_pages = document_count * 3  # Avg 3 pages per doc
        ocr_cost = self.calculate_document_ai_cost(ocr_pages)
        
        # Model processing costs based on confidence distribution
        model_costs = {
            'lightweight': confidence_distribution.get('high', 0.7) * document_count * 0.01,
            'medium': confidence_distribution.get('medium', 0.2) * document_count * 0.10,
            'large': confidence_distribution.get('low', 0.08) * document_count * 0.50,
            'human': confidence_distribution.get('very_low', 0.02) * document_count * 50.00
        }
        
        total_cost = ocr_cost + sum(model_costs.values())
        
        return {
            'ocr_cost': ocr_cost,
            'model_costs': model_costs,
            'total_cost': total_cost,
            'cost_per_document': total_cost / document_count,
            'potential_savings': self.calculate_savings_opportunities(document_count)
        }
    
    def calculate_document_ai_cost(self, pages: int) -> float:
        """
        Calculate Document AI costs with tier pricing.
        """
        if pages <= 1000:
            return 0  # Free tier
        
        billable = pages - 1000
        
        if billable <= 999000:
            return (billable / 1000) * 1.50
        else:
            # First million at $1.50, rest at $0.60
            return (999000 / 1000) * 1.50 + ((billable - 999000) / 1000) * 0.60
    
    def calculate_savings_opportunities(self, document_count: int) -> dict:
        """
        Identify cost reduction opportunities.
        """
        return {
            'preprocessing_savings': document_count * 0.02,  # Better OCR = less AI correction
            'caching_savings': document_count * 0.15 * 0.10,  # 15% duplicates
            'batch_processing': document_count * 0.005,       # API overhead reduction
            'confidence_improvement': document_count * 0.03   # Better prompts = less escalation
        }
```

### Optimization Strategies

#### 1. Intelligent Preprocessing
```python
def optimize_preprocessing(document: Path) -> Path:
    """
    Apply preprocessing only when beneficial for cost/accuracy.
    """
    # Quick quality check
    quality_score = assess_document_quality(document)
    
    if quality_score > 0.9:
        # Already high quality - skip preprocessing
        return document
    
    elif quality_score > 0.7:
        # Medium quality - light preprocessing
        return apply_light_preprocessing(document)
    
    else:
        # Low quality - full preprocessing pipeline
        return apply_full_preprocessing(document)
```

#### 2. Smart Caching
```python
class SmartCache:
    """
    Multi-level caching to avoid redundant processing.
    """
    
    def __init__(self):
        self.ocr_cache = {}      # Raw OCR results
        self.extraction_cache = {} # Extracted data
        self.vector_cache = {}    # Document embeddings for RAG
    
    def get_or_process(self, document_hash: str, processor_func):
        """
        Check cache before processing.
        """
        # Check if we've seen this exact document
        if document_hash in self.extraction_cache:
            return self.extraction_cache[document_hash]
        
        # Check if we have OCR but need extraction
        if document_hash in self.ocr_cache:
            result = processor_func(self.ocr_cache[document_hash])
            self.extraction_cache[document_hash] = result
            return result
        
        # Not in cache - process fully
        return None
```

#### 3. Batch Optimization
```python
def optimize_batch_processing(documents: List[Path]) -> dict:
    """
    Group documents for optimal batch processing.
    """
    batches = {
        'simple': [],      # High confidence, small size
        'standard': [],    # Medium complexity
        'complex': [],     # Large or low quality
        'priority': []     # User-flagged priority
    }
    
    for doc in documents:
        category = categorize_document(doc)
        batches[category].append(doc)
    
    # Process each batch with appropriate strategy
    results = {}
    
    # Simple: Maximum parallelization with lightweight model
    if batches['simple']:
        results['simple'] = process_parallel(
            batches['simple'], 
            model='lightweight',
            workers=20
        )
    
    # Standard: Balanced approach
    if batches['standard']:
        results['standard'] = process_parallel(
            batches['standard'],
            model='adaptive',
            workers=10
        )
    
    # Complex: Careful processing with fallback options
    if batches['complex']:
        results['complex'] = process_sequential(
            batches['complex'],
            model='tiered',
            enable_fallback=True
        )
    
    return results
```

#### 4. Dynamic Model Selection
```python
def select_optimal_model(document: Document, requirements: dict) -> str:
    """
    Choose the most cost-effective model for requirements.
    """
    accuracy_required = requirements.get('min_accuracy', 0.95)
    max_cost = requirements.get('max_cost_per_doc', 1.00)
    turnaround = requirements.get('max_processing_time', 60)
    
    # Fast path for high-confidence documents
    if document.confidence > 0.98:
        return 'validation_only'  # Just validate, no AI needed
    
    # Balance accuracy, cost, and speed
    if accuracy_required >= 0.99:
        # Highest accuracy required
        if max_cost > 5.00:
            return 'large_model_with_verification'
        else:
            return 'medium_model_with_rag'
    
    elif accuracy_required >= 0.95:
        # Standard accuracy
        if turnaround < 10:
            return 'lightweight_model'  # Fast
        else:
            return 'lightweight_with_fallback'  # Accurate
    
    else:
        # Lower accuracy acceptable
        return 'lightweight_model_only'
```

#### 5. Incremental Processing
```python
def incremental_extraction(document: Document) -> dict:
    """
    Extract fields incrementally, stopping when confidence is sufficient.
    """
    extracted = {}
    remaining_fields = get_required_fields(document.type)
    
    # Step 1: Try regex/heuristics (free)
    heuristic_results = extract_with_patterns(document.text, remaining_fields)
    for field, value in heuristic_results.items():
        if value['confidence'] > 0.95:
            extracted[field] = value
            remaining_fields.remove(field)
    
    if not remaining_fields:
        return extracted  # Done - no AI needed!
    
    # Step 2: Try lightweight model
    lightweight_results = extract_with_lightweight(
        document.text, 
        remaining_fields
    )
    for field, value in lightweight_results.items():
        if value['confidence'] > 0.90:
            extracted[field] = value
            remaining_fields.remove(field)
    
    if not remaining_fields:
        return extracted
    
    # Step 3: Escalate remaining fields only
    for field in remaining_fields:
        extracted[field] = extract_with_advanced_model(
            document.text,
            field,
            context=extracted  # Use already extracted fields as context
        )
    
    return extracted
```

### Cost Monitoring Dashboard
```python
class CostMonitor:
    """
    Real-time cost tracking and optimization recommendations.
    """
    
    def generate_cost_report(self, period: str = 'daily') -> dict:
        """
        Generate cost analysis report.
        """
        metrics = self.collect_metrics(period)
        
        return {
            'total_cost': metrics['total_cost'],
            'breakdown': {
                'ocr': metrics['ocr_cost'],
                'ai_models': metrics['model_costs'],
                'storage': metrics['storage_cost'],
                'compute': metrics['compute_cost']
            },
            'efficiency': {
                'cost_per_document': metrics['total_cost'] / metrics['doc_count'],
                'cache_hit_rate': metrics['cache_hits'] / metrics['total_requests'],
                'escalation_rate': metrics['escalations'] / metrics['doc_count'],
                'accuracy': metrics['validation_accuracy']
            },
            'recommendations': self.generate_recommendations(metrics),
            'projected_monthly': metrics['total_cost'] * 30 if period == 'daily' else metrics['total_cost']
        }
    
    def generate_recommendations(self, metrics: dict) -> List[str]:
        """
        Generate cost optimization recommendations.
        """
        recommendations = []
        
        if metrics['escalation_rate'] > 0.15:
            recommendations.append(
                "High escalation rate ({}%). Consider fine-tuning lightweight model.".format(
                    metrics['escalation_rate'] * 100
                )
            )
        
        if metrics['cache_hit_rate'] < 0.10:
            recommendations.append(
                "Low cache utilization. Review caching strategy for repeated documents."
            )
        
        if metrics['ocr_cost'] > metrics['model_costs']:
            recommendations.append(
                "OCR costs dominate. Consider batch processing and preprocessing optimization."
            )
        
        return recommendations
```

## Monitoring & Metrics

### Key Performance Indicators
```python
KPIs = {
    "ocr_accuracy": "Average confidence score across documents",
    "processing_speed": "Documents processed per hour",
    "error_rate": "Percentage of failed OCR attempts",
    "cost_per_document": "Average Document AI cost per document",
    "correction_rate": "Percentage requiring AI correction"
}
```

### Quality Metrics
```python
def calculate_quality_metrics(batch_results: List[OCRResult]) -> QualityReport:
    return QualityReport(
        avg_confidence=mean([r.confidence for r in batch_results]),
        min_confidence=min([r.confidence for r in batch_results]),
        failed_count=sum(1 for r in batch_results if r.status == "FAILED"),
        low_quality_count=sum(1 for r in batch_results if r.confidence < 0.7),
        avg_processing_time=mean([r.processing_time for r in batch_results])
    )
```

## Testing Strategy

### Unit Tests
```python
def test_legal_description_extraction():
    """Test extraction of various legal description formats"""
    test_cases = [
        ("Lot 5, Block 3", {"lot": "5", "block": "3"}),
        ("Section 12, Township 3N, Range 5E", 
         {"section": "12", "township": "3N", "range": "5E"})
    ]
    # Test implementation...
```

### Integration Tests
- Test Document AI API connectivity
- Validate processor configurations
- Test error handling and retries
- Verify output format compliance

### Quality Tests
- Manual review of sample extractions
- Comparison with ground truth data
- Cross-validation with alternative OCR engines

## Future Enhancements

### Custom Model Training
- Train Document AI custom extractor for Madison County formats
- Fine-tune for historical document fonts
- Specialized models for handwritten sections

### Advanced Features
- Multi-language support for historical documents
- Handwriting recognition for signatures
- Table extraction for deed indexes
- Automatic document classification

### Performance Improvements
- GPU-accelerated preprocessing
- Distributed processing across regions
- Real-time OCR for user uploads
- Incremental processing for document updates