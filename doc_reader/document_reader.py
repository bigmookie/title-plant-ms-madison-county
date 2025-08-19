import os
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from typing import Optional, List, Dict, Any, Union
import datetime
import uuid
import pypdf

# Google Cloud imports
from google.cloud import documentai, storage
from google.api_core.client_options import ClientOptions

# AI API imports
from openai import OpenAI
from google import genai
from google.genai import types
import anthropic

# --- Configuration ---
# Google Document AI settings
PROJECT_ID = 'deed-reader'
LOCATION = 'us'
PROCESSOR_ID = '2a9f06e7330cbb0a'

# Google Cloud Storage settings for batch processing
GCS_BUCKET_NAME = "deed-reader-bucket"
GCS_UPLOAD_PREFIX = "deed-reader-pdf-uploads"
GCS_OUTPUT_PREFIX = "deed-reader-batch-output"

# API keys for services (from environment variables with fallbacks)
OPENAI_API_KEY = 'insert-key-here'
GEMINI_API_KEY = 'insert-key-here'
CLAUDE_API_KEY = 'insert-key-here'

# Model configurations
OPENAI_MODEL = 'gpt-4o'
OPENAI_MAX_TOKENS = 16384

GEMINI_MODEL = 'gemini-2.5-pro-preview-03-25'
GEMINI_MAX_TOKENS = 8192

CLAUDE_MODEL = "claude-3-7-sonnet-20250219"
CLAUDE_MAX_TOKENS = 8000

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0
DEFAULT_AI_SERVICE = None

# Initialize clients (lazily for Document AI, eagerly for Gemini)
# GEMINI_CLIENT = None # Removed old global
CLAUDE_CLIENT = None
DOCUMENT_AI_CLIENT = None

# Initialize Gemini client if API key is available
GEMINI_CLIENT = None
if GEMINI_API_KEY:
    try:
        GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
        print("Gemini client initialized.")
    except Exception as e:
        print(f"Warning: Failed to initialize Gemini client: {e}")
else:
    print("Warning: Gemini API key not set. Export GEMINI_API_KEY with your key.")


# --- Document AI Functions ---
def get_document_ai_client() -> documentai.DocumentProcessorServiceClient:
    """Initialize and return the Document AI client."""
    global DOCUMENT_AI_CLIENT
    
    if DOCUMENT_AI_CLIENT is None:
        opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
        DOCUMENT_AI_CLIENT = documentai.DocumentProcessorServiceClient(client_options=opts)
    
    return DOCUMENT_AI_CLIENT

def get_pdf_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF file."""
    with open(pdf_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        return len(reader.pages)

def generate_job_id(filename: str) -> str:
    """Generate a unique job ID based on timestamp and filename."""
    date_prefix = datetime.datetime.now().strftime("%Y%m%d")
    base_name = Path(filename).stem
    short_uuid = str(uuid.uuid4())[:8]
    return f"{date_prefix}_{base_name}_{short_uuid}"

def upload_to_gcs(local_file_path: str, bucket_name: str, prefix: str, job_id: str) -> str:
    """Upload a file to Google Cloud Storage."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    job_prefix = f"{prefix}/{job_id}"
    blob = bucket.blob(f"{job_prefix}/{Path(local_file_path).name}")
    blob.upload_from_filename(local_file_path)
    return f"gs://{bucket_name}/{blob.name}"

def batch_process_documents(
    project_id: str,
    location: str,
    processor_id: str,
    gcs_output_uri: str,
    gcs_input_uri: str,
    input_mime_type: str = "application/pdf",
):
    """Batch-process documents using Document AI."""
    client = get_document_ai_client()
    name = client.processor_path(project_id, location, processor_id)
    
    # Configure Input(s)
    input_docs = documentai.GcsDocuments(documents=[
        documentai.GcsDocument(
            gcs_uri=gcs_input_uri,
            mime_type=input_mime_type
        )
    ])
    input_config = documentai.BatchDocumentsInputConfig(gcs_documents=input_docs)
    
    # Configure Output
    output_config = documentai.DocumentOutputConfig(
        gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=gcs_output_uri
        )
    )
    
    # Build the BatchProcessRequest
    request = documentai.BatchProcessRequest(
        name=name,
        input_documents=input_config,
        document_output_config=output_config,
    )
    
    print("Starting batch processing...")
    operation = client.batch_process_documents(request=request)
    print("Waiting for the operation to complete (this may take a while)...")
    operation.result()  # This blocks until finished
    print("Batch processing complete.")

def get_batch_documents_from_gcs(bucket_name: str, prefix: str, job_id: str) -> list:
    """Retrieve processed documents from GCS after batch processing."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    job_prefix = f"{prefix}/{job_id}"
    docs = []
    
    print(f"Looking for documents under: gs://{bucket_name}/{job_prefix}")
    
    for blob in bucket.list_blobs(prefix=job_prefix):
        if blob.content_type == "application/json":
            content = blob.download_as_bytes()
            document = documentai.Document.from_json(
                content,
                ignore_unknown_fields=True
            )
            docs.append(document)
    
    return docs

def extract_text_with_document_ai(file_path: str) -> str:
    """
    Extract text from a PDF using Google Document AI.
    Uses synchronous processing for small files and batch processing for large ones.
    """
    print(f"Analyzing PDF: {Path(file_path).name}")
    num_pages = get_pdf_page_count(file_path)
    print(f"PDF has {num_pages} page(s)")
    
    # For small documents (≤15 pages), use synchronous processing
    if num_pages <= 15:
        print("Using synchronous processing...")
        client = get_document_ai_client()
        name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)
        
        with open(file_path, "rb") as f:
            content = f.read()
        
        raw_document = documentai.RawDocument(content=content, mime_type="application/pdf")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        return result.document.text
    
    # For larger documents, use batch processing with GCS
    else:
        print("Using batch processing for large document...")
        job_id = generate_job_id(file_path)
        
        # Upload to GCS
        gcs_input_uri = upload_to_gcs(file_path, GCS_BUCKET_NAME, GCS_UPLOAD_PREFIX, job_id)
        gcs_output_uri = f"gs://{GCS_BUCKET_NAME}/{GCS_OUTPUT_PREFIX}/{job_id}/"
        
        print(f"Uploaded to: {gcs_input_uri}")
        print(f"Results will be stored at: {gcs_output_uri}")
        
        # Process with Document AI
        batch_process_documents(
            PROJECT_ID,
            LOCATION,
            PROCESSOR_ID,
            gcs_output_uri,
            gcs_input_uri
        )
        
        # Retrieve and combine results
        documents = get_batch_documents_from_gcs(GCS_BUCKET_NAME, GCS_OUTPUT_PREFIX, job_id)
        if documents:
            print(f"Retrieved {len(documents)} document(s) from batch processing")
            return "\n".join(doc.text for doc in documents)
        else:
            raise Exception("No documents found after batch processing")

# --- AI Service Functions ---
def initialize_ai_service(choice: Optional[str] = None) -> str:
    """
    Initialize the selected AI service.
    If choice is not provided, prompt the user to select.
    
    Returns:
        The selected service name
    """
    global DEFAULT_AI_SERVICE, GEMINI_CLIENT, CLAUDE_CLIENT
    
    # Check for missing API keys
    if choice == "1" and not OPENAI_API_KEY:
        print("Warning: OpenAI API key not set. Export OPENAI_API_KEY with your key.")
    elif choice == "2" and not GEMINI_API_KEY:
        print("Warning: Gemini API key not set. Export GEMINI_API_KEY with your key.")
    elif choice == "3" and not CLAUDE_API_KEY:
        print("Warning: Claude API key not set. Export CLAUDE_API_KEY with your key.")
    
    if choice is None:
        print("\nWhich AI service would you like to use for text processing?")
        print(f"[1] OpenAI ({OPENAI_MODEL})")
        print(f"[2] Google ({GEMINI_MODEL})")
        print(f"[3] Anthropic ({CLAUDE_MODEL})")
        print(f"[4] None (Save raw extracted text only)")
        
        while True:
            choice = input("Enter your choice (1, 2, 3, or 4): ").strip()
            if choice in ["1", "2", "3", "4"]:
                # Check for missing API keys after selection
                if choice == "1" and not OPENAI_API_KEY:
                    print("Warning: OpenAI API key not set. Export OPENAI_API_KEY with your key.")
                elif choice == "2" and not GEMINI_API_KEY:
                    print("Warning: Gemini API key not set. Export GEMINI_API_KEY with your key.")
                elif choice == "3" and not CLAUDE_API_KEY:
                    print("Warning: Claude API key not set. Export CLAUDE_API_KEY with your key.")
                break
            print("Invalid choice. Please enter 1, 2, 3, or 4.")
    
    if choice == "1":
        DEFAULT_AI_SERVICE = "openai"
        print(f"Using OpenAI {OPENAI_MODEL}")
    elif choice == "2":
        DEFAULT_AI_SERVICE = "gemini"
        print(f"Using Google {GEMINI_MODEL}")
    elif choice == "3":
        DEFAULT_AI_SERVICE = "claude"
        print(f"Using Anthropic {CLAUDE_MODEL}")
    elif choice == "4":
        DEFAULT_AI_SERVICE = "none"
        print("Skipping AI processing. Raw extracted text will be saved.")
    else:
        raise ValueError("Invalid choice. Must be '1', '2', '3', or '4'.")
    
    return DEFAULT_AI_SERVICE

def gpt_completion(prompt: str, system_prompt: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """Get completion from OpenAI."""
    if not OPENAI_API_KEY:
        raise ValueError("OpenAI API Key not configured. Set OPENAI_API_KEY environment variable.")
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=OPENAI_MAX_TOKENS,
            top_p=DEFAULT_TOP_P
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return f"Error processing with OpenAI: {e}"

def gemini_completion(prompt: str, system_prompt: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """Get completion from Google Gemini."""
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key not configured. Set GEMINI_API_KEY environment variable.")
    if GEMINI_CLIENT is None:
        raise RuntimeError("Gemini client failed to initialize. Check API key and installation.")

    try:
        # Configure generation settings using types.GenerateContentConfig
        # Pass system_instruction here
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            top_p=DEFAULT_TOP_P,
            max_output_tokens=GEMINI_MAX_TOKENS,
            system_instruction=system_prompt or None # Pass None if system_prompt is empty or None
        )

        # Generate content using the client's model method
        # Corrected: Use client.models.generate_content and the 'config' parameter
        response = GEMINI_CLIENT.models.generate_content(
            model=GEMINI_MODEL, # Pass model name string directly
            contents=prompt,    # User prompt goes into contents
            config=cfg          # Pass the configuration object using the 'config' parameter
        )

        # Optional: Check for blocked content or empty response
        # You might want to add more specific checks based on the response structure
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
             raise ValueError(f"Content generation blocked. Reason: {response.prompt_feedback.block_reason}")
        if not response.candidates:
             # This might happen due to safety filters or other issues
             raise ValueError("No content generated by the model (candidates list is empty).")


        # Access text from the response
        return response.text

    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        # Attempt to extract more detail from potential API errors
        error_details = getattr(e, 'message', str(e)) # Try 'message' attribute common in google-api-core errors
        return f"Error processing with Gemini: {error_details}"

def claude_completion(prompt: str, system_prompt: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """Get completion from Anthropic Claude."""
    global CLAUDE_CLIENT
    
    if not CLAUDE_API_KEY:
        raise ValueError("Claude API Key not configured. Set CLAUDE_API_KEY environment variable.")
    
    try:
        # Initialize Claude client if needed
        if CLAUDE_CLIENT is None:
            CLAUDE_CLIENT = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # Create message
        response = CLAUDE_CLIENT.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            temperature=temperature,
            system=system_prompt or "You are a helpful assistant.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract text from Claude response
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        
        return "".join(text_parts)
    
    except Exception as e:
        print(f"Error calling Claude API: {e}")
        return f"Error processing with Claude: {e}"

def ai_completion(prompt: str, system_prompt: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """
    Get completion from the selected AI service.
    """
    global DEFAULT_AI_SERVICE
    
    if DEFAULT_AI_SERVICE is None or DEFAULT_AI_SERVICE == "none":
        return prompt
    
    if DEFAULT_AI_SERVICE == "openai":
        return gpt_completion(prompt, system_prompt, temperature)
    elif DEFAULT_AI_SERVICE == "gemini":
        return gemini_completion(prompt, system_prompt, temperature)
    elif DEFAULT_AI_SERVICE == "claude":
        return claude_completion(prompt, system_prompt, temperature)
    else:
        raise ValueError(f"Unknown AI service: {DEFAULT_AI_SERVICE}")

def chunk_text(text: str, chunk_size: int = 6000, overlap: int = 200) -> List[str]:
    """
    Split text into chunks with given size and overlap.
    Attempts to break at paragraph or sentence boundaries.
    """
    # For token estimation, we use characters with an average ratio
    # This is approximate: 1 token ≈ 4 characters for English text
    char_size = chunk_size * 4
    overlap_chars = overlap * 4
    
    # Simple chunking by characters with boundary detection
    chunks = []
    start = 0
    
    while start < len(text):
        end = min(start + char_size, len(text))
        
        # Try to end at a paragraph or sentence boundary
        if end < len(text):
            # Look for paragraph break first (higher priority)
            para_break = text.rfind('\n\n', start, end)
            if para_break != -1 and para_break > start + (char_size // 2):
                end = para_break + 2
            else:
                # Try to find sentence endings
                best_break = -1
                for punct in ['.', '!', '?']:
                    for suffix in [' ', '\n']:
                        pos = text.rfind(punct + suffix, start, end)
                        if pos != -1 and pos > best_break:
                            best_break = pos
                
                if best_break != -1 and best_break > start + (char_size // 2):
                    end = best_break + 1
        
        chunks.append(text[start:end])
        start = end - overlap_chars if end < len(text) else end
    
    return chunks

def process_with_ai(document_text: str) -> str:
    """
    Process document text with AI to correct OCR errors.
    Handles both short and long documents by chunking if needed.
    """
    if DEFAULT_AI_SERVICE == "none":
        return document_text

    # Get approximate token limits for the selected AI model
    # Use character count as a proxy, adjust multiplier as needed
    # These are rough estimates and depend heavily on the content.
    # Consider using a dedicated tokenizer library for more accuracy if needed.
    chars_per_token_estimate = 4
    max_chars_approx = {
        "openai": (OPENAI_MAX_TOKENS - 1000) * chars_per_token_estimate, # Leave buffer for prompt/overhead
        "gemini": (GEMINI_MAX_TOKENS - 1000) * chars_per_token_estimate,
        "claude": (CLAUDE_MAX_TOKENS - 1000) * chars_per_token_estimate
    }.get(DEFAULT_AI_SERVICE, 24000) # Default fallback chars

    # Estimate if we need chunking
    if len(document_text) <= max_chars_approx:
        # Process in one go for short documents
        print("Processing document in a single chunk...")
        return correct_ocr_with_ai(document_text)

    # Chunk the document for processing
    print("Document is large. Processing in chunks...")
    # Use model's token limit for chunking basis if available
    chunk_token_limit = {
         "openai": OPENAI_MAX_TOKENS - 1000, # Leave buffer for prompt/overhead
         "gemini": GEMINI_MAX_TOKENS - 1000,
         "claude": CLAUDE_MAX_TOKENS - 1000
    }.get(DEFAULT_AI_SERVICE, 6000) # Fallback chunk size in tokens

    chunks = chunk_text(document_text, chunk_size=chunk_token_limit) # chunk_size here is in estimated tokens
    print(f"Document split into {len(chunks)} chunks")

    # Process each chunk
    processed_chunks = []
    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i+1}/{len(chunks)}...")
        processed_chunk = correct_ocr_with_ai(chunk)
        processed_chunks.append(processed_chunk)

    # Return combined processed text
    # Consider smarter joining if overlap was used effectively
    return "\n\n".join(processed_chunks) # Join chunks with double newline

def correct_ocr_with_ai(text: str) -> str:
    """
    Process extracted text with AI to correct OCR errors.
    """
    prompt = (
        "The following text was extracted from a document using OCR (Google Document AI). "
        "Please correct obvious OCR errors while preserving the exact original wording, "
        "formatting, and layout. Do not summarize, interpret, or modify the content beyond "
        "fixing clear OCR mistakes.\n\n"
        f"Document Text: {text}"
    )
    
    system_prompt = (
        "You are an expert at correcting OCR errors. Your task is to fix only obvious OCR mistakes "
        "while preserving the original document's wording, formatting, and layout exactly. "
        "Do not summarize, interpret, or modify the content in any way beyond fixing clear OCR errors."
    )
    
    return ai_completion(prompt, system_prompt, temperature=DEFAULT_TEMPERATURE)

# --- File Selection ---
def select_file() -> Optional[str]:
    """Open a file dialog to select a PDF document."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    file_path = filedialog.askopenfilename(
        title="Select PDF Document",
        filetypes=[
            ("PDF files", "*.pdf"),
            ("All files", "*.*")
        ]
    )
    
    if not file_path:
        print("No file selected.")
        return None
    
    return file_path

# --- Main Function ---
def main():
    """Main entry point for the PDF to text converter."""
    parser = argparse.ArgumentParser(description="Extract text from PDF using Google Document AI and optionally process with AI")
    parser.add_argument("--file", help="Path to the PDF document")
    parser.add_argument("--model", choices=["1", "2", "3", "4"],
                        help="AI service: 1=OpenAI, 2=Google, 3=Claude, 4=None (raw extraction)")
    parser.add_argument("--output", help="Output file path (default: same name as input with .txt extension)")

    args = parser.parse_args()

    # Get file path
    file_path = args.file
    if not file_path:
        file_path = select_file()
        if not file_path:
            return  # Exit if no file selected

    # Initialize AI service
    try:
        initialize_ai_service(args.model)
    except ValueError as e:
        print(f"Error initializing AI service: {e}")
        return
    except Exception as e: # Catch broader exceptions during init
        print(f"Unexpected error during AI service initialization: {e}")
        return

    # Process the PDF
    try:
        # Extract text using Document AI
        document_text = extract_text_with_document_ai(file_path)
        print(f"Text extraction complete: {len(document_text)} characters")

        # Process with AI if selected
        print("Processing extracted text (using AI if selected)...")
        processed_text = process_with_ai(document_text)

        # Determine output path
        if args.output:
            output_path = args.output
        else:
            # Save in same folder as input with .txt extension
            path_obj = Path(file_path)
            output_path = str(path_obj.with_suffix('.txt'))

        # Save the text
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(processed_text)

        print(f"Text saved to: {output_path}")

        # Print preview
        preview_length = min(500, len(processed_text))
        print("\nResult preview:")
        print(processed_text[:preview_length] + ("..." if len(processed_text) > preview_length else ""))

    except Exception as e:
        print(f"\n--- Error processing document ---")
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        print(f"Error details: {e}")
        print("-------------------------------")
        return

if __name__ == "__main__":
    main()
