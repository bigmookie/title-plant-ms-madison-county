"""PDF optimization module for compression and standardization."""

import logging
from pathlib import Path
from typing import Tuple, Optional
import subprocess
import shutil

from pypdf import PdfReader, PdfWriter
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

class PDFOptimizer:
    """Optimize PDFs for storage efficiency."""
    
    def __init__(self, compression_quality: int = 85, target_dpi: int = 150):
        """
        Initialize PDF optimizer.
        
        Args:
            compression_quality: JPEG compression quality (1-100)
            target_dpi: Target DPI for images in PDF
        """
        self.compression_quality = compression_quality
        self.target_dpi = target_dpi
        self.ghostscript_available = self._check_ghostscript()
    
    def _check_ghostscript(self) -> bool:
        """Check if Ghostscript is available for advanced optimization."""
        try:
            result = subprocess.run(['gs', '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Ghostscript available: {result.stdout.strip()}")
                return True
        except FileNotFoundError:
            pass
        
        logger.warning("Ghostscript not found. Using fallback optimization.")
        return False
    
    def optimize(self, input_path: Path, output_path: Optional[Path] = None) -> Tuple[Path, int, int]:
        """
        Optimize PDF file.
        
        Args:
            input_path: Path to input PDF
            output_path: Path for output PDF (if None, overwrites input)
            
        Returns:
            Tuple of (output_path, original_size, optimized_size)
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        
        original_size = input_path.stat().st_size
        
        # Use output_path or create temp file
        if output_path is None:
            output_path = input_path.with_suffix('.optimized.pdf')
            replace_original = True
        else:
            replace_original = False
        
        # Try Ghostscript optimization first (best compression)
        if self.ghostscript_available:
            success = self._optimize_with_ghostscript(input_path, output_path)
            if success:
                optimized_size = output_path.stat().st_size
                
                # Replace original if needed
                if replace_original:
                    shutil.move(str(output_path), str(input_path))
                    output_path = input_path
                
                logger.info(f"Optimized {input_path.name}: {original_size:,} -> {optimized_size:,} bytes "
                          f"({100 * (1 - optimized_size/original_size):.1f}% reduction)")
                
                return (output_path, original_size, optimized_size)
        
        # Fallback to PyMuPDF optimization
        optimized_size = self._optimize_with_pymupdf(input_path, output_path)
        
        # Replace original if needed
        if replace_original:
            shutil.move(str(output_path), str(input_path))
            output_path = input_path
        
        logger.info(f"Optimized {input_path.name}: {original_size:,} -> {optimized_size:,} bytes "
                  f"({100 * (1 - optimized_size/original_size):.1f}% reduction)")
        
        return (output_path, original_size, optimized_size)
    
    def _optimize_with_ghostscript(self, input_path: Path, output_path: Path) -> bool:
        """
        Optimize PDF using Ghostscript.
        
        Args:
            input_path: Input PDF path
            output_path: Output PDF path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ghostscript command for PDF optimization
            cmd = [
                'gs',
                '-sDEVICE=pdfwrite',
                '-dCompatibilityLevel=1.4',
                '-dPDFSETTINGS=/ebook',  # Good balance of quality and size
                '-dNOPAUSE',
                '-dBATCH',
                '-dQUIET',
                f'-dJPEGQ={self.compression_quality}',
                f'-dColorImageResolution={self.target_dpi}',
                f'-dGrayImageResolution={self.target_dpi}',
                f'-dMonoImageResolution={self.target_dpi}',
                '-dColorImageDownsampleType=/Bicubic',
                '-dGrayImageDownsampleType=/Bicubic',
                '-dMonoImageDownsampleType=/Bicubic',
                '-dColorImageDownsampleThreshold=1.0',
                '-dGrayImageDownsampleThreshold=1.0',
                '-dMonoImageDownsampleThreshold=1.0',
                '-dCompressFonts=true',
                '-dEmbedAllFonts=false',
                '-dSubsetFonts=true',
                '-dDetectDuplicateImages=true',
                f'-sOutputFile={output_path}',
                str(input_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0 and output_path.exists():
                return True
            else:
                logger.warning(f"Ghostscript optimization failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("Ghostscript optimization timed out")
            return False
        except Exception as e:
            logger.warning(f"Ghostscript optimization error: {e}")
            return False
    
    def _optimize_with_pymupdf(self, input_path: Path, output_path: Path) -> int:
        """
        Optimize PDF using PyMuPDF as fallback.
        
        Args:
            input_path: Input PDF path
            output_path: Output PDF path
            
        Returns:
            Size of optimized file
        """
        try:
            # Open PDF with PyMuPDF
            pdf_document = fitz.open(str(input_path))
            
            # Create new optimized PDF
            new_pdf = fitz.open()
            
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                
                # Get page as pixmap with target DPI
                mat = fitz.Matrix(self.target_dpi / 72.0, self.target_dpi / 72.0)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convert to PDF page
                img_pdf = fitz.open("pdf", pix.pdfdata())
                new_pdf.insert_pdf(img_pdf)
                img_pdf.close()
            
            # Save with compression
            new_pdf.save(
                str(output_path),
                garbage=4,  # Maximum garbage collection
                deflate=True,  # Compress streams
                clean=True,  # Clean up
                linear=True  # Optimize for web
            )
            
            new_pdf.close()
            pdf_document.close()
            
            return output_path.stat().st_size
            
        except Exception as e:
            logger.error(f"PyMuPDF optimization failed: {e}")
            # If optimization fails, just copy the original
            shutil.copy2(input_path, output_path)
            return output_path.stat().st_size
    
    def batch_optimize(self, input_dir: Path, output_dir: Path = None) -> dict:
        """
        Batch optimize all PDFs in a directory.
        
        Args:
            input_dir: Directory containing PDFs
            output_dir: Output directory (if None, optimizes in place)
            
        Returns:
            Dictionary with optimization statistics
        """
        stats = {
            'total_files': 0,
            'successful': 0,
            'failed': 0,
            'original_size': 0,
            'optimized_size': 0,
            'errors': []
        }
        
        pdf_files = list(input_dir.glob('*.pdf'))
        stats['total_files'] = len(pdf_files)
        
        logger.info(f"Starting batch optimization of {len(pdf_files)} files")
        
        for pdf_file in pdf_files:
            try:
                output_path = None
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / pdf_file.name
                
                _, orig_size, opt_size = self.optimize(pdf_file, output_path)
                
                stats['successful'] += 1
                stats['original_size'] += orig_size
                stats['optimized_size'] += opt_size
                
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"{pdf_file.name}: {str(e)}")
                logger.error(f"Failed to optimize {pdf_file.name}: {e}")
        
        # Calculate reduction percentage
        if stats['original_size'] > 0:
            reduction = 100 * (1 - stats['optimized_size'] / stats['original_size'])
            logger.info(f"Batch optimization complete: {stats['successful']} successful, "
                       f"{stats['failed']} failed, {reduction:.1f}% total reduction")
        
        return stats