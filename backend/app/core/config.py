"""TRAFFICINTEL AI - Core Configuration

Production-grade settings management using Pydantic Settings.
Strict separation of environments, secure defaults, zero fake data defaults.
"""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    PROJECT_NAME: str = "TRAFFICINTEL AI"
    TAGLINE: str = "REAL-TIME INTELLIGENCE FOR SAFER, SMARTER TRAFFIC"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Environment
    ENVIRONMENT: str = Field(default="production", description="Environment: production, staging, or development")
    DEBUG: bool = False
    
    # Database: Default to local sqlite database with dual-dialect compatibility, or Postgres when configured
    DATABASE_URL: str = Field(
        default="sqlite:///./trafficintel.db",
        description="SQLAlchemy database connection string (e.g. postgresql://user:pass@localhost:5432/trafficintel)"
    )
    
    # Security & Auth
    SECRET_KEY: str = Field(default="09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7", description="JWT secret key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 hours
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]
    
    # Safety Engine Defaults (Deterministic Safety Thresholds in Seconds)
    MIN_GREEN_DEFAULT: int = 7
    MAX_GREEN_DEFAULT: int = 65
    YELLOW_TIME_DEFAULT: int = 4
    RED_CLEARANCE_DEFAULT: int = 2
    PED_WALK_DEFAULT: int = 7
    PED_CLEARANCE_DEFAULT: int = 15
    COMMAND_FRESHNESS_WINDOW_SEC: float = 5.0  # Reject commands older than 5 seconds
    
    # Telemetry Freshness Thresholds (Seconds)
    DATA_FRESH_THRESHOLD_SEC: int = 15
    DATA_AGING_THRESHOLD_SEC: int = 60
    DATA_STALE_THRESHOLD_SEC: int = 180
    
    # Weather Provider
    OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1/forecast"
    
    # LLM / AI Configuration
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
