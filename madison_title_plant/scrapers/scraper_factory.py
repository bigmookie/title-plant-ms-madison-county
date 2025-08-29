"""Factory for creating appropriate scraper instances."""

import logging
from typing import Optional

from .base_scraper import BaseScraper
from .historical_scraper import HistoricalScraper
from .mid_scraper import MIDScraper
from ..config.settings import Settings

logger = logging.getLogger(__name__)

class ScraperFactory:
    """Factory for creating scraper instances based on portal type."""
    
    def __init__(self, settings: Settings):
        """
        Initialize factory with settings.
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self._scrapers = {}
    
    def get_scraper(self, portal: str) -> BaseScraper:
        """
        Get or create scraper for specified portal.
        
        Args:
            portal: Portal identifier ('historical', 'mid', 'wills')
            
        Returns:
            Scraper instance
            
        Raises:
            ValueError: If portal is not supported
        """
        # Return cached scraper if exists
        if portal in self._scrapers:
            return self._scrapers[portal]
        
        # Create new scraper
        if portal == 'historical':
            scraper = HistoricalScraper(self.settings)
        elif portal == 'mid':
            scraper = MIDScraper(self.settings)
        elif portal == 'wills':
            # TODO: Implement WillsScraper
            # For now, use HistoricalScraper as wills are in the historical portal
            scraper = HistoricalScraper(self.settings)
        else:
            raise ValueError(f"Unsupported portal: {portal}")
        
        # Cache and return
        self._scrapers[portal] = scraper
        return scraper
    
    def close_all(self):
        """Close all scraper sessions."""
        for scraper in self._scrapers.values():
            if hasattr(scraper, 'session') and scraper.session:
                scraper.session.close()
        self._scrapers.clear()