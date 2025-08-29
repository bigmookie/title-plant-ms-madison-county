#!/usr/bin/env python3
"""
Madison County Title Plant - Phase 1 Document Download System

Main entry point for downloading, optimizing, and uploading documents to Google Cloud Storage.
"""

import argparse
import logging
import sys
import json
from pathlib import Path
from typing import Optional

from madison_title_plant.orchestrator import DocumentPipelineOrchestrator
from madison_title_plant.config.settings import get_settings

# Configure logging
def setup_logging(log_level: str = 'INFO', log_file: Optional[Path] = None):
    """Configure logging for the application."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=handlers
    )
    
    # Reduce noise from some libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Madison County Title Plant - Document Download System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build queue from indexes and start processing
  python main.py process
  
  # Process with parallel downloads
  python main.py process --parallel --workers 5
  
  # Process only first 100 documents
  python main.py process --limit 100
  
  # Rebuild queue from indexes
  python main.py build-queue --force
  
  # Show statistics
  python main.py stats
  
  # Test download of single document
  python main.py test --book 237 --page 1
        """
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Process command
    process_parser = subparsers.add_parser('process', help='Process document queue')
    process_parser.add_argument('--parallel', action='store_true', 
                               help='Use parallel processing')
    process_parser.add_argument('--workers', type=int, default=5,
                               help='Number of parallel workers (default: 5)')
    process_parser.add_argument('--limit', type=int,
                               help='Limit number of documents to process')
    process_parser.add_argument('--rebuild-queue', action='store_true',
                               help='Rebuild queue from indexes before processing')
    
    # Build queue command
    build_parser = subparsers.add_parser('build-queue', help='Build download queue from indexes')
    build_parser.add_argument('--force', action='store_true',
                             help='Force rebuild even if queue exists')
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show queue and processing statistics')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Test download single document')
    test_parser.add_argument('--book', required=True, help='Book number')
    test_parser.add_argument('--page', required=True, help='Page number')
    test_parser.add_argument('--portal', choices=['historical', 'mid'], 
                            help='Portal to use (auto-detect if not specified)')
    
    # Report command
    report_parser = subparsers.add_parser('report', help='Generate processing report')
    report_parser.add_argument('--output', help='Output file for report (JSON)')
    
    # Global options
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level (default: INFO)')
    parser.add_argument('--log-file', help='Log file path')
    
    args = parser.parse_args()
    
    # Setup logging
    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(args.log_level, log_file)
    
    logger = logging.getLogger(__name__)
    
    # Execute command
    try:
        if args.command == 'process':
            logger.info("Starting document processing pipeline")
            
            orchestrator = DocumentPipelineOrchestrator()
            
            # Initialize queue
            orchestrator.initialize_queue(force_rebuild=args.rebuild_queue)
            
            # Process documents
            if args.parallel:
                orchestrator.process_queue_parallel(
                    max_items=args.limit,
                    max_workers=args.workers
                )
            else:
                orchestrator.process_queue_sequential(max_items=args.limit)
            
            # Cleanup and generate report
            orchestrator.cleanup()
            
        elif args.command == 'build-queue':
            logger.info("Building download queue from indexes")
            
            orchestrator = DocumentPipelineOrchestrator()
            count = orchestrator.initialize_queue(force_rebuild=args.force)
            
            logger.info(f"Queue built with {count} pending items")
            
            # Show statistics
            stats = orchestrator.index_processor.get_statistics()
            print("\nQueue Statistics:")
            print(f"  Total items: {stats['total_items']}")
            print("\n  By Portal:")
            for portal, count in stats['by_portal'].items():
                print(f"    {portal}: {count}")
            print("\n  By Priority:")
            for priority, count in sorted(stats['by_priority'].items()):
                print(f"    Priority {priority}: {count}")
            
        elif args.command == 'stats':
            logger.info("Generating statistics")
            
            orchestrator = DocumentPipelineOrchestrator()
            orchestrator.initialize_queue()
            
            stats = orchestrator.index_processor.get_statistics()
            report = orchestrator.generate_report()
            
            print("\n" + "="*50)
            print("MADISON COUNTY TITLE PLANT - STATISTICS")
            print("="*50)
            
            print("\nProcessing Summary:")
            for key, value in report['summary'].items():
                print(f"  {key.replace('_', ' ').title()}: {value}")
            
            print("\nQueue Statistics:")
            print(f"  Total Items: {stats['total_items']}")
            
            print("\n  By Status:")
            for status, count in stats['by_status'].items():
                print(f"    {status}: {count}")
            
            print("\n  By Portal:")
            for portal, count in stats['by_portal'].items():
                print(f"    {portal}: {count}")
            
            print("\n  Top Document Types:")
            sorted_types = sorted(stats['by_document_type'].items(), 
                                key=lambda x: x[1], reverse=True)[:10]
            for doc_type, count in sorted_types:
                print(f"    {doc_type}: {count}")
            
            if report['failed_documents']:
                print(f"\n  Recent Failures: {len(report['failed_documents'])}")
                for failure in report['failed_documents'][:5]:
                    print(f"    Book {failure['book']}, Page {failure['page']}: {failure['error']}")
            
        elif args.command == 'test':
            logger.info(f"Testing download for Book {args.book}, Page {args.page}")
            
            settings = get_settings()
            from madison_title_plant.scrapers.scraper_factory import ScraperFactory
            from madison_title_plant.processors.pdf_optimizer import PDFOptimizer
            
            # Determine portal
            if args.portal:
                portal = args.portal
            else:
                # Auto-detect based on book number
                try:
                    book_num = int(args.book)
                    portal = 'historical' if book_num < 238 else 'mid'
                except ValueError:
                    portal = 'historical'  # Letters are historical
            
            logger.info(f"Using {portal} portal")
            
            # Download
            factory = ScraperFactory(settings)
            scraper = factory.get_scraper(portal)
            
            local_path, checksum, error = scraper.download_with_retry(
                args.book, args.page
            )
            
            if error:
                logger.error(f"Download failed: {error}")
                sys.exit(1)
            
            logger.info(f"Downloaded to: {local_path}")
            logger.info(f"Checksum: {checksum}")
            
            # Optimize
            optimizer = PDFOptimizer()
            optimized_path, orig_size, opt_size = optimizer.optimize(local_path)
            
            logger.info(f"Optimized: {orig_size:,} -> {opt_size:,} bytes "
                       f"({100 * (1 - opt_size/orig_size):.1f}% reduction)")
            
            print(f"\nTest successful!")
            print(f"  Original size: {orig_size:,} bytes")
            print(f"  Optimized size: {opt_size:,} bytes")
            print(f"  Reduction: {100 * (1 - opt_size/orig_size):.1f}%")
            print(f"  File: {optimized_path}")
            
        elif args.command == 'report':
            logger.info("Generating report")
            
            orchestrator = DocumentPipelineOrchestrator()
            orchestrator.initialize_queue()
            
            report = orchestrator.generate_report()
            
            if args.output:
                output_path = Path(args.output)
                with open(output_path, 'w') as f:
                    json.dump(report, f, indent=2)
                logger.info(f"Report saved to {output_path}")
            else:
                print(json.dumps(report, indent=2))
        
        else:
            parser.print_help()
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()