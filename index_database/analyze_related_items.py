#!/usr/bin/env python3
"""
Analyze related_items column to understand data formats before cleaning.
"""

import sys
import os
from pathlib import Path
from collections import Counter
import re
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor

def connect_db():
    """Connect to the index database."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=os.getenv('DB_PORT', 5432),
        database=os.getenv('DB_NAME', 'madison_county_index'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )

def analyze_related_items():
    """Analyze related_items column data."""
    conn = connect_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    print("\n" + "="*80)
    print("RELATED ITEMS ANALYSIS")
    print("="*80)

    # Get total count
    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(related_items) as with_related,
               COUNT(*) - COUNT(related_items) as without_related
        FROM index_documents
    """)
    totals = cursor.fetchone()

    print(f"\nTotal records: {totals['total']:,}")
    print(f"With related_items: {totals['with_related']:,} ({totals['with_related']*100.0/totals['total']:.1f}%)")
    print(f"Without related_items: {totals['without_related']:,} ({totals['without_related']*100.0/totals['total']:.1f}%)")

    # Sample data
    print("\n" + "="*80)
    print("SAMPLE RELATED ITEMS (First 50 non-null values)")
    print("="*80)

    cursor.execute("""
        SELECT book, page, related_items
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND related_items != ''
        ORDER BY id
        LIMIT 50
    """)

    samples = cursor.fetchall()
    patterns = Counter()

    for i, row in enumerate(samples, 1):
        related = row['related_items']
        print(f"\n{i}. Book {row['book']}, Page {row['page']}")
        print(f"   Raw: {related[:200]}{'...' if len(related) > 200 else ''}")

        # Identify pattern
        if 'bk:' in related:
            patterns['has_bk_prefix'] += 1
        if '/' in related:
            patterns['has_slash'] += 1
        if ',' in related:
            patterns['has_comma'] += 1
        if ';' in related:
            patterns['has_semicolon'] += 1
        if '\n' in related:
            patterns['has_newline'] += 1

        # Count separators
        num_items = related.count('bk:')
        if num_items > 1:
            patterns['multiple_items'] += 1

    print("\n" + "="*80)
    print("PATTERN ANALYSIS")
    print("="*80)

    for pattern, count in patterns.most_common():
        print(f"{pattern:25} {count:>5} ({count*100.0/len(samples):.1f}%)")

    # Look for different formats
    print("\n" + "="*80)
    print("FORMAT VARIATIONS")
    print("="*80)

    cursor.execute("""
        SELECT DISTINCT
            CASE
                WHEN related_items LIKE '%bk:%/%' THEN 'Standard: NUMBER bk:BOOK/PAGE'
                WHEN related_items LIKE 'bk:%/%' THEN 'Short: bk:BOOK/PAGE'
                WHEN related_items LIKE '%,%' THEN 'Comma-separated'
                WHEN related_items LIKE '%;%' THEN 'Semicolon-separated'
                ELSE 'Other'
            END as format,
            COUNT(*) as count,
            MIN(related_items) as example
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND related_items != ''
        GROUP BY format
        ORDER BY count DESC
    """)

    formats = cursor.fetchall()
    for fmt in formats:
        print(f"\n{fmt['format']}")
        print(f"  Count: {fmt['count']:,}")
        print(f"  Example: {fmt['example'][:100]}...")

    # Sample for regex testing
    print("\n" + "="*80)
    print("REGEX PATTERN TESTING")
    print("="*80)

    cursor.execute("""
        SELECT related_items
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND related_items != ''
        ORDER BY RANDOM()
        LIMIT 20
    """)

    # Test different regex patterns
    pattern1 = re.compile(r'(\d+)\s+bk:(\d+)/(\d+)')  # Standard: NUMBER bk:BOOK/PAGE
    pattern2 = re.compile(r'bk:(\d+)/(\d+)')           # Short: bk:BOOK/PAGE

    test_samples = cursor.fetchall()

    print("\nPattern 1: (\\d+)\\s+bk:(\\d+)/(\\d+)  [NUMBER bk:BOOK/PAGE]")
    matched_p1 = 0
    for row in test_samples[:10]:
        related = row['related_items']
        matches = pattern1.findall(related)
        if matches:
            matched_p1 += 1
            print(f"  ✓ {related[:80]}...")
            for match in matches[:3]:  # Show first 3 matches
                print(f"    → Instrument: {match[0]}, Book: {match[1]}, Page: {match[2]}")
        else:
            print(f"  ✗ {related[:80]}...")

    print(f"\nMatched: {matched_p1}/10")

    print("\nPattern 2: bk:(\\d+)/(\\d+)  [bk:BOOK/PAGE only]")
    matched_p2 = 0
    for row in test_samples[10:]:
        related = row['related_items']
        matches = pattern2.findall(related)
        if matches:
            matched_p2 += 1
            print(f"  ✓ {related[:80]}...")
            for match in matches[:3]:
                print(f"    → Book: {match[0]}, Page: {match[1]}")
        else:
            print(f"  ✗ {related[:80]}...")

    print(f"\nMatched: {matched_p2}/10")

    # Length analysis
    print("\n" + "="*80)
    print("LENGTH ANALYSIS")
    print("="*80)

    cursor.execute("""
        SELECT
            MIN(LENGTH(related_items)) as min_len,
            MAX(LENGTH(related_items)) as max_len,
            AVG(LENGTH(related_items))::int as avg_len,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY LENGTH(related_items))::int as median_len
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND related_items != ''
    """)

    lengths = cursor.fetchone()
    print(f"Min length:    {lengths['min_len']:>6}")
    print(f"Max length:    {lengths['max_len']:>6}")
    print(f"Avg length:    {lengths['avg_len']:>6}")
    print(f"Median length: {lengths['median_len']:>6}")

    # Multiple references
    print("\n" + "="*80)
    print("MULTIPLE REFERENCES ANALYSIS")
    print("="*80)

    cursor.execute("""
        SELECT
            (LENGTH(related_items) - LENGTH(REPLACE(related_items, 'bk:', ''))) / 3 as num_refs,
            COUNT(*) as count
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND related_items != ''
        GROUP BY num_refs
        ORDER BY num_refs
        LIMIT 20
    """)

    ref_counts = cursor.fetchall()
    print("\nNumber of references per record:")
    for row in ref_counts:
        print(f"  {row['num_refs']} references: {row['count']:>8,} records")

    # Export samples for detailed analysis
    print("\n" + "="*80)
    print("EXPORTING SAMPLES")
    print("="*80)

    cursor.execute("""
        SELECT id, book, page, related_items
        FROM index_documents
        WHERE related_items IS NOT NULL
          AND related_items != ''
        ORDER BY RANDOM()
        LIMIT 100
    """)

    samples_export = cursor.fetchall()

    output_file = Path(__file__).parent / 'related_items_samples.json'
    with open(output_file, 'w') as f:
        json.dump([dict(row) for row in samples_export], f, indent=2, default=str)

    print(f"Exported 100 samples to: {output_file}")

    cursor.close()
    conn.close()

if __name__ == '__main__':
    try:
        analyze_related_items()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
