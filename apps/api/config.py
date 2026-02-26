"""Application configuration settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Database
    database_url: str = "postgresql://user:password@localhost:5432/legavex_platform"
    
    # JWT Authentication
    jwt_secret: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    
    # SMTP / Email
    smtp_host: str = "smtp.protonmail.ch"
    smtp_port: int = 587
    smtp_user: str = "legavex@proton.me"
    smtp_password: str = ""
    email_from_name: str = "LegaVex"
    email_enabled: bool = False  # Set to True when ready to send real emails
    
    # Business Logic
    offer_timeout_hours: int = 24
    
    # API
    api_prefix: str = "/api"
    debug: bool = False
    
    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
