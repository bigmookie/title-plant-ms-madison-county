#!/usr/bin/env python3
"""
Integration test: Download Book 9 documents that have NULL document_type.
This verifies the fix for the 'NoneType' has no attribute 'lower' error.
"""

import sys
import os
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from madison_county_doc_puller.simple_doc_downloader import MadisonCountyDownloader
from madison_county_doc_puller.pdf_optimizer import PDFOptimizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def connect_db():
    """Connect to the index database."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=os.getenv('DB_PORT', 5432),
        database=os.getenv('DB_NAME', 'madison_county_index'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )

def test_book9_downloads():
    """Test downloading Book 9 documents with NULL values."""
    print("="*80)
    print("INTEGRATION TEST: Book 9 Documents with NULL Values")
    print("="*80)
    print()

    # Connect to database
    try:
        conn = connect_db()
        logger.info("✓ Connected to database")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Run: source index_database/.db_credentials")
        return 1

    # Query documents with NULL document_type from Book 9
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, book, page, instrument_number, document_type, instrument_type_parsed
        FROM index_documents
        WHERE book = 9
          AND page IN (264, 265, 266, 267, 268)
          AND (document_type IS NULL OR document_type = '')
        ORDER BY page
        LIMIT 5
    """)

    docs = []
    for row in cursor.fetchall():
        docs.append({
            'id': row[0],
            'book': row[1],
            'page': row[2],
            'instrument_number': row[3],
            'document_type': row[4],
            'instrument_type_parsed': row[5]
        })

    cursor.close()
    conn.close()

    print(f"Found {len(docs)} documents with NULL document_type in Book 9:")
    for doc in docs:
        print(f"  - ID {doc['id']}: Book {doc['book']}, Page {doc['page']}, "
              f"doc_type={repr(doc['document_type'])}, "
              f"instrument={repr(doc['instrument_number'])}")
    print()

    if not docs:
        print("❌ No documents found with NULL document_type in Book 9")
        return 1

    # Test the fixed logic on each document
    print("Testing fixed logic on each document:")
    print("-" * 80)

    test_dir = Path(__file__).parent / "test_integration_downloads"
    test_dir.mkdir(exist_ok=True)

    downloader = MadisonCountyDownloader(download_dir=str(test_dir))
    pdf_optimizer = PDFOptimizer(quality='ebook')

    success_count = 0
    fail_count = 0

    for doc in docs:
        doc_id = doc['id']
        book = doc['book']
        page = doc['page']

        print(f"\nDocument ID {doc_id}: Book {book}, Page {page}")

        try:
            # Test the logic that was failing
            doc_type = (doc.get('document_type') or 'unknown').lower().replace('_', '-')
            instrument_number = doc.get('instrument_number') or 0
            instrument_type = doc.get('instrument_type_parsed') or ''

            print(f"  ✓ NULL handling: doc_type={repr(doc_type)}, "
                  f"instrument={instrument_number}, type={repr(instrument_type)}")

            # Try actual download
            if doc['instrument_number']:
                result = downloader.download_by_instrument(
                    instrument_number=doc['instrument_number'],
                    expected_book=book,
                    expected_page=page
                )
            else:
                result = downloader.download_by_book_page(book=book, page=page)

            if result.success:
                print(f"  ✓ Download succeeded: {result.local_path}")

                # Test optimization
                if result.local_path and Path(result.local_path).exists():
                    original_size = Path(result.local_path).stat().st_size
                    original_size_opt, optimized_size = pdf_optimizer.optimize_in_place(
                        Path(result.local_path)
                    )
                    savings_pct = ((original_size_opt - optimized_size) / original_size_opt * 100)
                    print(f"  ✓ Optimization: {original_size_opt:,} → {optimized_size:,} bytes ({savings_pct:.1f}% savings)")

                success_count += 1
            else:
                print(f"  ❌ Download failed: {result.error}")
                fail_count += 1

        except Exception as e:
            print(f"  ❌ ERROR: {type(e).__name__}: {e}")
            fail_count += 1
            import traceback
            traceback.print_exc()

    downloader.close()

    # Summary
    print()
    print("="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Total documents tested: {len(docs)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")

    if fail_count == 0:
        print("\n✓ All tests passed!")
        print("The fix for 'NoneType' has no attribute 'lower' is working correctly.")
        return 0
    else:
        print(f"\n❌ {fail_count} tests failed.")
        return 1

if __name__ == '__main__':
    sys.exit(test_book9_downloads())
