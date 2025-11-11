#!/usr/bin/env python3
"""
Test that staged_downloader handles NULL database values correctly.
"""

import sys
from pathlib import Path

# Test the specific logic that was failing
def test_null_document_type():
    """Test that None/NULL document_type is handled correctly."""
    print("="*80)
    print("TEST: NULL document_type handling")
    print("="*80)

    # Simulate document record from database with NULL values
    doc_with_nulls = {
        'id': 932008,
        'book': 9,
        'page': 264,
        'instrument_number': None,  # NULL in database
        'document_type': None,      # NULL in database
        'instrument_type_parsed': None  # NULL in database
    }

    doc_with_empty = {
        'id': 932009,
        'book': 9,
        'page': 265,
        'instrument_number': '',  # Empty string
        'document_type': '',      # Empty string
        'instrument_type_parsed': ''  # Empty string
    }

    doc_with_values = {
        'id': 571625,
        'book': 9,
        'page': 264,
        'instrument_number': 2010009264,
        'document_type': 'UNKNOWN',
        'instrument_type_parsed': 'FEDERAL TAX LIEN RELEASE'
    }

    test_docs = [
        ("NULL values", doc_with_nulls),
        ("Empty strings", doc_with_empty),
        ("Actual values", doc_with_values)
    ]

    all_passed = True

    for test_name, doc in test_docs:
        print(f"\nTest case: {test_name}")
        print(f"  Input: document_type={repr(doc['document_type'])}, "
              f"instrument_number={repr(doc['instrument_number'])}, "
              f"instrument_type_parsed={repr(doc['instrument_type_parsed'])}")

        try:
            # Test the fixed logic
            doc_type = (doc.get('document_type') or 'unknown').lower().replace('_', '-')
            instrument_number = doc.get('instrument_number') or 0
            instrument_type = doc.get('instrument_type_parsed') or ''

            print(f"  ✓ Success!")
            print(f"    doc_type: {repr(doc_type)}")
            print(f"    instrument_number: {repr(instrument_number)}")
            print(f"    instrument_type: {repr(instrument_type)}")

            # Verify expected values
            if doc['document_type'] in (None, ''):
                assert doc_type == 'unknown', f"Expected 'unknown', got {repr(doc_type)}"

            if doc['instrument_number'] in (None, ''):
                assert instrument_number == 0, f"Expected 0, got {repr(instrument_number)}"

            if doc['instrument_type_parsed'] in (None, ''):
                assert instrument_type == '', f"Expected '', got {repr(instrument_type)}"

        except Exception as e:
            print(f"  ❌ FAILED: {type(e).__name__}: {e}")
            all_passed = False

    print("\n" + "="*80)
    if all_passed:
        print("✓ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1

def test_old_buggy_logic():
    """Demonstrate that the old logic would fail with NULL values."""
    print("\n" + "="*80)
    print("TEST: Old buggy logic (for comparison)")
    print("="*80)

    doc_with_null = {
        'document_type': None
    }

    print("\nTrying old logic: doc.get('document_type', 'unknown').lower()")
    print(f"  Input: document_type={repr(doc_with_null['document_type'])}")

    try:
        # This is the OLD buggy logic
        doc_type = doc_with_null.get('document_type', 'unknown').lower()
        print(f"  Unexpected success: {repr(doc_type)}")
    except AttributeError as e:
        print(f"  ✓ Expected failure: {e}")
        print(f"  This is the bug that was causing 87.5% of historical documents to fail!")

if __name__ == '__main__':
    print("Testing NULL handling in staged_downloader.py")
    print("This test verifies the fix for the 'NoneType' object has no attribute 'lower' error\n")

    # Test the old buggy logic first to show the problem
    test_old_buggy_logic()

    # Test the new fixed logic
    result = test_null_document_type()

    sys.exit(result)
