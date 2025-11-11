#!/usr/bin/env python3
"""
Test script to diagnose document downloader issues.
Tests specific documents that were failing during the historical download.
"""

import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from simple_doc_downloader import MadisonCountyDownloader

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,  # Use DEBUG for detailed output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_document(downloader, test_name, **kwargs):
    """Test downloading a document and report results."""
    print("\n" + "="*80)
    print(f"TEST: {test_name}")
    print("="*80)

    try:
        if 'instrument_number' in kwargs:
            result = downloader.download_by_instrument(
                kwargs['instrument_number'],
                kwargs.get('expected_book'),
                kwargs.get('expected_page')
            )
        else:
            result = downloader.download_by_book_page(
                kwargs['book'],
                kwargs['page']
            )

        print(f"✓ Success: {result.success}")
        print(f"  Instrument: {result.instrument_number}")
        print(f"  Expected: Book {result.expected_book}, Page {result.expected_page}")
        print(f"  Actual: Book {result.actual_book}, Page {result.actual_page}")
        print(f"  Mismatch: {result.book_page_mismatch}")
        print(f"  Local path: {result.local_path}")
        if result.error:
            print(f"  ❌ Error: {result.error}")
        if result.metadata:
            print(f"  Metadata:")
            print(f"    Grantor: {result.metadata.grantor}")
            print(f"    Grantee: {result.metadata.grantee}")
            print(f"    Nature: {result.metadata.doc_nature}")

        return result.success

    except Exception as e:
        print(f"❌ EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run diagnostic tests."""
    print("="*80)
    print("DOCUMENT DOWNLOADER DIAGNOSTIC TEST")
    print("="*80)

    # Create test download directory
    test_dir = Path(__file__).parent / "test_downloads"
    test_dir.mkdir(exist_ok=True)

    downloader = MadisonCountyDownloader(download_dir=str(test_dir))

    results = []

    # Test 1: Document that was failing (Book 9, Page 264)
    results.append(test_document(
        downloader,
        "Book 9, Page 264 (was failing)",
        book=9,
        page=264
    ))

    # Test 2: Book 9, Page 265 (reported no instrument number)
    results.append(test_document(
        downloader,
        "Book 9, Page 265 (no instrument warning)",
        book=9,
        page=265
    ))

    # Test 3: Book 235 document (reportedly worked)
    results.append(test_document(
        downloader,
        "Book 235, Page 1 (should work)",
        book=235,
        page=1
    ))

    # Test 4: Book 237 document (reportedly worked)
    results.append(test_document(
        downloader,
        "Book 237, Page 1 (should work)",
        book=237,
        page=1
    ))

    # Test 5: Book 1 document (very early historical)
    results.append(test_document(
        downloader,
        "Book 1, Page 1 (earliest historical)",
        book=1,
        page=1
    ))

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Tests passed: {sum(results)}/{len(results)}")
    print(f"Tests failed: {len(results) - sum(results)}/{len(results)}")

    if all(results):
        print("\n✓ All tests passed!")
    else:
        print("\n❌ Some tests failed. Review output above for details.")

    downloader.close()

    return 0 if all(results) else 1

if __name__ == '__main__':
    sys.exit(main())
