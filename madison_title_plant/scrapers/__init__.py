"""Web scrapers for document download."""

from .base_scraper import BaseScraper, ScraperError
from .historical_scraper import HistoricalScraper
from .mid_scraper import MIDScraper
from .scraper_factory import ScraperFactory

__all__ = [
    'BaseScraper',
    'ScraperError',
    'HistoricalScraper', 
    'MIDScraper',
    'ScraperFactory'
]