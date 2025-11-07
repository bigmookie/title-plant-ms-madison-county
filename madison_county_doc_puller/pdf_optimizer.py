"""PDF optimization using Ghostscript."""

import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class PDFOptimizer:
    """Optimize PDFs using Ghostscript for reduced file size and storage costs."""

    def __init__(self, quality: str = 'ebook'):
        """
        Initialize PDF optimizer.

        Args:
            quality: Ghostscript quality setting
                - 'screen': 72 dpi, smallest size
                - 'ebook': 150 dpi, good quality (default)
                - 'printer': 300 dpi, high quality
                - 'prepress': 300 dpi, highest quality
        """
        self.quality = quality
        self._verify_ghostscript()

    def _verify_ghostscript(self):
        """Verify Ghostscript is installed."""
        try:
            result = subprocess.run(
                ['gs', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Ghostscript found: {result.stdout.strip()}")
            else:
                raise FileNotFoundError("Ghostscript not working")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.error("Ghostscript not found. Install with: sudo apt-get install ghostscript")
            raise

    def optimize(
        self,
        input_path: Path,
        output_path: Optional[Path] = None
    ) -> Tuple[Path, int, int]:
        """
        Optimize PDF file.

        Args:
            input_path: Path to input PDF
            output_path: Path for output PDF (default: input_path with _optimized suffix)

        Returns:
            Tuple of (output_path, original_size, optimized_size)

        Raises:
            FileNotFoundError: If input file doesn't exist
            subprocess.CalledProcessError: If optimization fails
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # Get original size
        original_size = input_path.stat().st_size

        # Determine output path
        if output_path is None:
            output_path = input_path.parent / f"{input_path.stem}_optimized.pdf"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Ghostscript optimization command
        gs_command = [
            'gs',
            '-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.4',
            f'-dPDFSETTINGS=/{self.quality}',
            '-dNOPAUSE',
            '-dQUIET',
            '-dBATCH',
            '-dDetectDuplicateImages=true',
            '-dCompressFonts=true',
            '-r150',  # 150 DPI for images
            f'-sOutputFile={output_path}',
            str(input_path)
        ]

        logger.info(f"Optimizing {input_path.name} with quality={self.quality}")

        try:
            result = subprocess.run(
                gs_command,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                check=True
            )

            # Get optimized size
            optimized_size = output_path.stat().st_size

            # Calculate savings
            savings = original_size - optimized_size
            savings_pct = (savings / original_size * 100) if original_size > 0 else 0

            logger.info(
                f"Optimized {input_path.name}: "
                f"{original_size:,} → {optimized_size:,} bytes "
                f"({savings_pct:.1f}% reduction)"
            )

            return (output_path, original_size, optimized_size)

        except subprocess.CalledProcessError as e:
            logger.error(f"Ghostscript optimization failed: {e.stderr}")
            raise
        except subprocess.TimeoutExpired:
            logger.error(f"Optimization timeout for {input_path.name}")
            if output_path.exists():
                output_path.unlink()
            raise

    def optimize_in_place(self, file_path: Path) -> Tuple[int, int]:
        """
        Optimize PDF and replace original.

        Args:
            file_path: Path to PDF file

        Returns:
            Tuple of (original_size, optimized_size)
        """
        # Create temporary output
        temp_output = file_path.parent / f"{file_path.stem}_temp.pdf"

        try:
            output_path, original_size, optimized_size = self.optimize(
                file_path,
                temp_output
            )

            # Replace original with optimized
            file_path.unlink()
            temp_output.rename(file_path)

            return (original_size, optimized_size)

        except Exception as e:
            # Clean up temp file on error
            if temp_output.exists():
                temp_output.unlink()
            raise


def optimize_pdf(
    input_path: Path,
    output_path: Optional[Path] = None,
    quality: str = 'ebook'
) -> Tuple[Path, int, int]:
    """
    Convenience function to optimize a PDF.

    Args:
        input_path: Path to input PDF
        output_path: Path for output PDF (optional)
        quality: Quality setting ('screen', 'ebook', 'printer', 'prepress')

    Returns:
        Tuple of (output_path, original_size, optimized_size)
    """
    optimizer = PDFOptimizer(quality=quality)
    return optimizer.optimize(input_path, output_path)


if __name__ == '__main__':
    """Test PDF optimizer."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 pdf_optimizer.py <input.pdf> [output.pdf] [quality]")
        print("Quality options: screen, ebook (default), printer, prepress")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)

    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    quality = sys.argv[3] if len(sys.argv) > 3 else 'ebook'

    try:
        output_path, original, optimized = optimize_pdf(input_file, output_file, quality)
        print(f"\n✓ Success!")
        print(f"  Input:     {input_file}")
        print(f"  Output:    {output_path}")
        print(f"  Original:  {original:,} bytes")
        print(f"  Optimized: {optimized:,} bytes")
        print(f"  Savings:   {(original - optimized) / original * 100:.1f}%")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
