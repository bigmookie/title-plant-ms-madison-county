"""Settings and configuration management."""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class Settings:
    """Application settings."""
    
    # Google Cloud Settings
    gcp_project_id: str
    gcs_bucket_name: str
    gcp_credentials_path: Optional[str]
    document_ai_processor_id: str
    document_ai_location: str
    
    # Local Storage Settings
    temp_download_dir: Path
    checkpoint_dir: Path
    log_dir: Path
    
    # Scraper Settings
    max_retries: int
    retry_delay: float
    request_timeout: int
    concurrent_downloads: int
    rate_limit_delay: float
    
    # PDF Optimization Settings
    pdf_compression_quality: int
    pdf_dpi: int
    
    # Index Processing Settings
    index_dir: Path
    
    @classmethod
    def from_env(cls) -> 'Settings':
        """Create settings from environment variables."""
        # Create base directories
        base_dir = Path.cwd()
        
        return cls(
            # Google Cloud Settings
            gcp_project_id=os.getenv('GOOGLE_CLOUD_PROJECT', 'madison-county-title'),
            gcs_bucket_name=os.getenv('GCS_BUCKET_NAME', 'madison-county-title-plant'),
            gcp_credentials_path=os.getenv('GOOGLE_APPLICATION_CREDENTIALS'),
            document_ai_processor_id=os.getenv('DOCUMENT_AI_PROCESSOR_ID', '2a9f06e7330cbb0a'),
            document_ai_location=os.getenv('DOCUMENT_AI_LOCATION', 'us'),
            
            # Local Storage Settings
            temp_download_dir=Path(os.getenv('TEMP_DOWNLOAD_DIR', str(base_dir / 'temp' / 'downloads'))),
            checkpoint_dir=Path(os.getenv('CHECKPOINT_DIR', str(base_dir / 'checkpoints'))),
            log_dir=Path(os.getenv('LOG_DIR', str(base_dir / 'logs'))),
            
            # Scraper Settings
            max_retries=int(os.getenv('MAX_RETRIES', '3')),
            retry_delay=float(os.getenv('RETRY_DELAY', '1.0')),
            request_timeout=int(os.getenv('REQUEST_TIMEOUT', '30')),
            concurrent_downloads=int(os.getenv('CONCURRENT_DOWNLOADS', '5')),
            rate_limit_delay=float(os.getenv('RATE_LIMIT_DELAY', '0.5')),
            
            # PDF Optimization Settings
            pdf_compression_quality=int(os.getenv('PDF_COMPRESSION_QUALITY', '85')),
            pdf_dpi=int(os.getenv('PDF_DPI', '150')),
            
            # Index Processing Settings
            index_dir=Path(os.getenv('INDEX_DIR', str(base_dir / 'madison_docs' / 'DuProcess Indexes'))),
        )
    
    def ensure_directories(self):
        """Ensure all required directories exist."""
        for dir_path in [self.temp_download_dir, self.checkpoint_dir, self.log_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

# Singleton pattern for settings
_settings: Optional[Settings] = None

def get_settings() -> Settings:
    """Get application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        _settings.ensure_directories()
    return _settings