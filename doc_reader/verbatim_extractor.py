import os
import argparse
from pathlib import Path

# For PDF support, uncomment and install these dependencies
# import pypdf

def read_pdf(path: Path) -> str:
    """Return concatenated text of all pages in a PDF."""
    try:
        import pypdf
    except ImportError:
        print("Error: pypdf module not found. Please install it with 'pip install pypdf' to read PDF files.")
        return ""
        
    with path.open("rb") as fh:
        reader = pypdf.PdfReader(fh)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

def read_text_file(path: Path) -> str:
    """Read and return text from a plain text file."""
    return path.read_text(encoding="utf-8", errors="ignore")

def read_document(path: str) -> str:
    """
    Read document text based on file extension.
    Currently supports: PDF, TXT
    """
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return read_pdf(p)
    else:
        return read_text_file(p)

def chunk_text(text: str, chunk_size: int = 10000) -> list[str]:
    """
    Split text into chunks with given size.
    For very large documents.
    """
    # Simple chunking by characters
    chunks = []
    start = 0
    
    while start < len(text):
        end = min(start + chunk_size, len(text))
        
        # Try to end at a sentence or paragraph boundary if possible
        if end < len(text):
            # Look for paragraph break first
            para_break = text.rfind('\n\n', start, end)
            if para_break != -1 and para_break > start + (chunk_size // 2):
                end = para_break + 2
            else:
                # Look for sentence end
                for punct in ['.', '!', '?']:
                    punct_pos = text.rfind(punct, start, end)
                    if punct_pos != -1 and punct_pos > start + (chunk_size // 2):
                        end = punct_pos + 1
                        break
        
        chunks.append(text[start:end])
        start = end
    
    return chunks

def main():
    """Main entry point for the verbatim text extractor."""
    parser = argparse.ArgumentParser(description="Verbatim Text Extractor")
    parser.add_argument("--file", required=True, help="Path to the document (PDF, TXT)")
    parser.add_argument("--output", help="Output file path (default is input + '.extracted.txt')")
    parser.add_argument("--chunk-size", type=int, default=0, 
                       help="Split large documents into chunks of this size (0 means no chunking)")
    
    args = parser.parse_args()
    
    # Read document
    print(f"Reading document: {args.file}")
    document_text = read_document(args.file)
    print(f"Document read successfully ({len(document_text)} characters)")
    
    # Save output - use same name as input file but with .extracted.txt extension
    if args.output:
        output_path = args.output
    else:
        # Extract base filename without extension and use it for output
        base_path = os.path.splitext(os.path.basename(args.file))[0]
        output_path = f"{base_path}.extracted.txt"
    
    # Process in chunks if specified and needed
    if args.chunk_size > 0 and len(document_text) > args.chunk_size:
        chunks = chunk_text(document_text, args.chunk_size)
        print(f"Document split into {len(chunks)} chunks for processing")
        
        with open(output_path, "w", encoding="utf-8") as f:
            for i, chunk in enumerate(chunks):
                print(f"Processing chunk {i+1}/{len(chunks)}...")
                f.write(chunk)  # Write each chunk verbatim
    else:
        # Write the entire document at once
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(document_text)
    
    print(f"Output saved to: {output_path}")
    
    # Print preview to console (first 500 chars)
    print("\nResult preview:")
    print(document_text[:500] + ("..." if len(document_text) > 500 else ""))

if __name__ == "__main__":
    main()