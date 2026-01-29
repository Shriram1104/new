"""
Application settings and configuration management.
Uses pydantic-settings for environment variable management.
"""

from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Google Cloud Configuration
    google_cloud_project: str = Field(..., description="GCP Project ID")
    google_cloud_region: str = Field(default="us-central1", description="GCP Region")
    google_application_credentials: Optional[str] = Field(
        default=None, 
        description="Path to service account JSON"
    )
    
    # Gemini API Configuration
    google_api_key: Optional[str] = Field(default=None, description="Google AI Studio API Key")
    
    # Model Configuration
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model to use (available: gemini-2.0-flash-exp, gemini-1.5-flash, gemini-1.5-pro)"
    )

    master_tuned_endpoint: Optional[str] = Field(
        default=None,
        description="Full Resource Name of the Fine-Tuned Vertex AI Endpoint for Master Agent"
    )
    
    use_vertex_ai: bool = Field(
        default=True,
        description="Use Vertex AI instead of Google AI Studio (recommended for production)"
    )
    gemini_temperature: float = Field(default=0, ge=0, le=2.0)
    gemini_max_tokens: int = Field(default=2048, ge=1, le=8192)
    
    # Datastore Configuration
    farmer_datastore_id: str = Field(..., description="Farmer schemes datastore ID")
    msme_datastore_id: str = Field(..., description="MSME schemes datastore ID")
    msme_unstructured_id: str = Field(..., description="MSME schemes unstructured ID")
    datastore_location: str = Field(default="global", description="Datastore location")
    
    # Session Configuration
    session_service: str = Field(
        default="inmemory",
        description="Session service type: inmemory or firestore"
    )
    session_timeout_minutes: int = Field(default=30, ge=5, le=1440)
    
    # API Server Configuration
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080, ge=1024, le=65535)
    api_workers: int = Field(default=4, ge=1, le=32)
    api_reload: bool = Field(default=False)
    
    # ADK Web Configuration
    adk_web_port: int = Field(default=8000, ge=1024, le=65535)
    adk_web_host: str = Field(default="localhost")
    
    # Logging Configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    log_format: str = Field(
        default="json",
        description="Log format: json or text"
    )
    
    # Feature Flags
    enable_context_enrichment: bool = Field(default=True)
    enable_progressive_disclosure: bool = Field(default=True)
    enable_multi_language: bool = Field(default=True)
    enable_session_continuity: bool = Field(default=True)

    # Search Quality Settings
    # Discovery Engine retrieval score can be low even for good matches; keep this permissive.
    min_scheme_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Amount tolerance: allow schemes whose max amount is slightly below user's requirement.
    # Example: user asks 15L, tolerance 0.20 => accept schemes >= 12L.
    loan_amount_lower_tolerance: float = Field(default=0.20, ge=0.0, le=0.50)

    # Progressive Disclosure Settings
    schemes_per_page: int = Field(default=3, ge=1, le=10)
    max_scheme_pages: int = Field(default=5, ge=1, le=20)
    
    # Language Support
    supported_languages: str = Field(
        default="en,hi,mr,gu,ta,te,kn,ml,bn,pa,or"
    )
    default_language: str = Field(default="en")
    
    # Rate Limiting
    rate_limit_per_minute: int = Field(default=60, ge=1)
    rate_limit_per_hour: int = Field(default=500, ge=1)
    
    # Monitoring
    enable_cloud_trace: bool = Field(default=False)
    enable_cloud_monitoring: bool = Field(default=False)
    
    # Development Settings
    debug: bool = Field(default=False)
    testing: bool = Field(default=False)
    
    @property
    def supported_languages_list(self) -> List[str]:
        """Get list of supported languages."""
        return [lang.strip() for lang in self.supported_languages.split(",")]
    
    @property
    def max_schemes_display(self) -> int:
        """Maximum number of schemes to display across all pages."""
        return self.schemes_per_page * self.max_scheme_pages
    
    def is_language_supported(self, language_code: str) -> bool:
        """Check if a language is supported."""
        return language_code.lower() in self.supported_languages_list
    
    @property
    def model_string(self) -> str:
        """
        Get the appropriate model string based on configuration.
        
        For Vertex AI, returns the model name directly (ADK handles the routing)
        For Google AI Studio, returns model name for API usage
        """
        # ADK detects Vertex AI from GOOGLE_APPLICATION_CREDENTIALS
        # No need for vertex_ai: prefix - just return model name
        return self.gemini_model


# Global settings instance
settings = Settings()
