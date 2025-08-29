import pandas as pd
import os
from pathlib import Path
from collections import Counter
import sys
from typing import Dict, List, Optional


def analyze_single_file(file_path: str, column_name: str = 'InstrumentType') -> pd.Series:
    """
    Analyze a single Excel file and return value counts for specified column.
    
    Args:
        file_path: Path to the Excel file
        column_name: Name of column to analyze
        
    Returns:
        Series with value counts or empty Series if error
    """
    try:
        df = pd.read_excel(file_path)
        if column_name in df.columns:
            return df[column_name].value_counts()
        else:
            print(f"  Warning: Column '{column_name}' not found in {os.path.basename(file_path)}")
            return pd.Series()
    except Exception as e:
        print(f"  Error reading {os.path.basename(file_path)}: {e}")
        return pd.Series()


def analyze_all_indexes(
    directory: str = 'madison_docs/DuProcess Indexes',
    column_name: str = 'InstrumentType',
    show_progress: bool = True
) -> pd.DataFrame:
    """
    Analyze all Excel files in directory and aggregate value counts for a column.
    
    Args:
        directory: Directory containing Excel files
        column_name: Column to analyze
        show_progress: Whether to show progress messages
        
    Returns:
        DataFrame with aggregated results
    """
    index_dir = Path(directory)
    if not index_dir.exists():
        print(f"Error: Directory '{directory}' not found")
        return pd.DataFrame()
    
    # Get all Excel files
    excel_files = sorted(index_dir.glob('*.xlsx'))
    if not excel_files:
        print(f"No Excel files found in '{directory}'")
        return pd.DataFrame()
    
    print(f"Found {len(excel_files)} Excel files")
    print(f"Analyzing column: '{column_name}'")
    print("-" * 50)
    
    # Aggregate all value counts
    all_counts = Counter()
    files_processed = 0
    files_with_column = 0
    
    for i, file_path in enumerate(excel_files, 1):
        if show_progress and i % 50 == 0:
            print(f"Processing file {i}/{len(excel_files)}...")
        
        value_counts = analyze_single_file(str(file_path), column_name)
        if not value_counts.empty:
            files_with_column += 1
            for value, count in value_counts.items():
                all_counts[value] += count
        files_processed += 1
    
    print(f"\nProcessed {files_processed} files")
    print(f"Files with column '{column_name}': {files_with_column}")
    
    # Convert to DataFrame for better display
    if all_counts:
        df_results = pd.DataFrame(
            list(all_counts.items()),
            columns=['Value', 'Count']
        ).sort_values('Count', ascending=False)
        df_results['Percentage'] = (df_results['Count'] / df_results['Count'].sum() * 100).round(2)
        return df_results
    else:
        return pd.DataFrame()


def extract_document_types(directory: str = 'madison_docs/DuProcess Indexes') -> pd.DataFrame:
    """
    Extract document types (part before ' -') from InstrumentType column across all files.
    
    Args:
        directory: Directory containing Excel files
        
    Returns:
        DataFrame with document type counts
    """
    index_dir = Path(directory)
    excel_files = sorted(index_dir.glob('*.xlsx'))
    
    print(f"Extracting document types from {len(excel_files)} files...")
    print("-" * 50)
    
    doc_type_counts = Counter()
    
    for i, file_path in enumerate(excel_files, 1):
        if i % 50 == 0:
            print(f"Processing file {i}/{len(excel_files)}...")
        
        try:
            df = pd.read_excel(file_path)
            if 'InstrumentType' in df.columns:
                for val in df['InstrumentType'].dropna():
                    val_str = str(val).strip()
                    if ' -' in val_str:
                        doc_type = val_str.split(' -')[0].strip()
                    else:
                        doc_type = val_str
                    if doc_type:
                        doc_type_counts[doc_type] += 1
        except Exception as e:
            print(f"  Error processing {os.path.basename(file_path)}: {e}")
    
    # Convert to DataFrame
    if doc_type_counts:
        df_results = pd.DataFrame(
            list(doc_type_counts.items()),
            columns=['DocumentType', 'Count']
        ).sort_values('Count', ascending=False)
        df_results['Percentage'] = (df_results['Count'] / df_results['Count'].sum() * 100).round(2)
        return df_results
    else:
        return pd.DataFrame()


def save_results(df: pd.DataFrame, output_file: str = 'index_analysis_results.csv'):
    """Save analysis results to CSV file."""
    try:
        df.to_csv(output_file, index=False)
        print(f"\nResults saved to '{output_file}'")
    except Exception as e:
        print(f"Error saving results: {e}")


def main():
    """Main function with command-line interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze DuProcess Index files')
    parser.add_argument(
        '--column',
        default='InstrumentType',
        help='Column name to analyze (default: InstrumentType)'
    )
    parser.add_argument(
        '--directory',
        default='madison_docs/DuProcess Indexes',
        help='Directory containing Excel files'
    )
    parser.add_argument(
        '--extract-types',
        action='store_true',
        help='Extract document types from InstrumentType column'
    )
    parser.add_argument(
        '--output',
        help='Output CSV file for results'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit output to top N results'
    )
    
    args = parser.parse_args()
    
    if args.extract_types:
        print("Extracting document types from InstrumentType column\n")
        results = extract_document_types(args.directory)
    else:
        print(f"Analyzing column '{args.column}' across all files\n")
        results = analyze_all_indexes(args.directory, args.column)
    
    if not results.empty:
        if args.limit:
            results = results.head(args.limit)
        
        print("\nResults:")
        print("=" * 60)
        print(results.to_string(index=False))
        
        print(f"\nTotal unique values: {len(results)}")
        print(f"Total count: {results['Count'].sum():,}")
        
        if args.output:
            save_results(results, args.output)
    else:
        print("No results to display")


if __name__ == '__main__':
    # If no command-line arguments, run a demo analysis
    if len(sys.argv) == 1:
        print("Demo: Analyzing InstrumentType column\n")
        
        # Analyze full InstrumentType values
        print("1. Full InstrumentType values (top 20):")
        print("=" * 60)
        results = analyze_all_indexes(column_name='InstrumentType')
        if not results.empty:
            print(results.head(20).to_string(index=False))
        
        print("\n\n2. Extracted Document Types:")
        print("=" * 60)
        doc_types = extract_document_types()
        if not doc_types.empty:
            print(doc_types.to_string(index=False))
    else:
        main()