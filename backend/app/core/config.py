"""TRAFFICINTEL AI - Core Configuration

Production-grade settings management using Pydantic Settings.
Strict separation of environments, secure defaults, zero fake data defaults.
"""

import json

from typing import Annotated, List
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic import Field, field_validator, model_validator


# Shipped placeholder key. Safe for local development, never for production:
# it is published in this repository, so any token signed with it is forgeable.
INSECURE_DEFAULT_SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"


class Settings(BaseSettings):
    PROJECT_NAME: str = "TRAFFICINTEL AI"
    TAGLINE: str = "REAL-TIME INTELLIGENCE FOR SAFER, SMARTER TRAFFIC"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Environment
    ENVIRONMENT: str = Field(default="development", description="Environment: production, staging, or development")
    DEBUG: bool = False
    
    # Database: Default to local sqlite database with dual-dialect compatibility, or Postgres when configured
    DATABASE_URL: str = Field(
        default="sqlite:///./trafficintel.db",
        description="SQLAlchemy database connection string (e.g. postgresql://user:pass@localhost:5432/trafficintel)"
    )
    
    # Connection pooling (server-backed dialects only; ignored for SQLite).
    # Sized for a control room - a handful of operators plus the polling thread
    # and background workers - not for public web traffic.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT_SEC: int = 30
    DB_POOL_RECYCLE_SEC: int = 1800
    DB_CONNECT_TIMEOUT_SEC: int = 10
    # A query still running after this is not going to help the operator who
    # asked for it; it is holding a connection the rest of the shift needs.
    DB_STATEMENT_TIMEOUT_SEC: float = 30.0

    # Security & Auth
    SECRET_KEY: str = Field(default=INSECURE_DEFAULT_SECRET_KEY, description="JWT secret key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 hours
    
    # CORS. Defaults are the local dev console only. A real deployment sets
    # this to the console's actual origin; the validator below refuses to start
    # a production instance still trusting localhost, because a stale dev
    # default is an access-control hole that nothing in the UI would reveal.
    #
    # NoDecode is load-bearing: without it pydantic-settings JSON-parses a
    # complex field from the environment BEFORE any validator runs, so a plain
    # comma-separated value raises an unreadable parse error at import time
    # rather than reaching the splitter below. Deployment tooling supplies
    # environment variables as plain strings, so that is the common case.
    BACKEND_CORS_ORIGINS: Annotated[List[str], NoDecode] = [
        "http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173",
    ]
    
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
    
    # NTCIP 1202 Signal Controller Integration (SNMPv1 over UDP)
    NTCIP_DEFAULT_PORT: int = 161
    NTCIP_TIMEOUT_SEC: float = 2.0
    NTCIP_RETRIES: int = 1
    NTCIP_READ_COMMUNITY: str = "public"
    NTCIP_WRITE_COMMUNITY: str = "private"

    # Controller polling. Observed phase state is the raw material for every
    # signal performance measure; without it those measures report
    # NOT_COMPUTABLE rather than guessing.
    CONTROLLER_POLL_ENABLED: bool = True
    CONTROLLER_POLL_INTERVAL_SEC: float = 2.0

    # Observability
    STRUCTURED_LOGGING: bool = True

    # Alert delivery (email). With no SMTP host configured, EMAIL delivery
    # records SKIPPED_NOT_CONFIGURED rather than reporting a delivery that
    # never happened.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "trafficintel@localhost"
    SMTP_USE_TLS: bool = True

    # GTFS-Realtime transit feeds (protobuf). Empty = not configured; the
    # platform then reports TRANSIT_FEED_NOT_CONFIGURED and never simulates a bus.
    GTFS_RT_VEHICLE_POSITIONS_URL: str = ""
    GTFS_RT_TRIP_UPDATES_URL: str = ""
    GTFS_RT_API_KEY_HEADER: str = ""
    GTFS_RT_API_KEY: str = ""
    GTFS_RT_TIMEOUT_SEC: float = 5.0

    # Weather Provider
    OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1/forecast"
    
    # LLM / AI Configuration
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        """Accepts a comma-separated string as well as a JSON list.

        Deployment tooling supplies environment variables as plain strings, and
        a CORS list that silently parses to a single malformed origin fails as
        a browser error in the console rather than as a startup error here.
        """
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return []

        # NoDecode means nothing parses JSON for us any more, so both accepted
        # forms are handled here or neither works.
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "BACKEND_CORS_ORIGINS looks like JSON but does not parse: {}. "
                    "Use a JSON array ([\"https://a.gov\"]) or a plain "
                    "comma-separated list (https://a.gov,https://b.gov).".format(exc)
                ) from exc
            if not isinstance(parsed, list):
                raise ValueError(
                    "BACKEND_CORS_ORIGINS parsed as {}, not a list of origins."
                    .format(type(parsed).__name__)
                )
            return [str(origin).strip() for origin in parsed if str(origin).strip()]

        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _reject_localhost_cors_in_production(self) -> "Settings":
        """Refuses to boot a production deployment still trusting localhost."""
        if self.ENVIRONMENT.lower() != "production":
            return self
        local = [
            origin for origin in self.BACKEND_CORS_ORIGINS
            if "localhost" in origin or "127.0.0.1" in origin
        ]
        if local:
            raise ValueError(
                "BACKEND_CORS_ORIGINS still contains development origins {} while "
                "ENVIRONMENT=production. Set it to the console's real origin "
                "(BACKEND_CORS_ORIGINS=\"https://traffic.example.gov\"). Leaving the "
                "dev default in place lets any page served from a developer "
                "machine make credentialed requests against the live "
                "network.".format(local)
            )
        if "*" in self.BACKEND_CORS_ORIGINS:
            raise ValueError(
                "BACKEND_CORS_ORIGINS is a wildcard while ENVIRONMENT=production. "
                "The console sends bearer tokens, and browsers reject a wildcard "
                "on credentialed requests, so this would fail at runtime as well "
                "as being unsafe."
            )
        return self

    @model_validator(mode="after")
    def _reject_debug_in_production(self) -> "Settings":
        """DEBUG in production leaks tracebacks and internal paths to operators."""
        if self.ENVIRONMENT.lower() == "production" and self.DEBUG:
            raise ValueError(
                "DEBUG=true while ENVIRONMENT=production. Debug responses expose "
                "tracebacks and internal file paths to anyone who can reach the API."
            )
        return self

    @model_validator(mode="after")
    def _reject_insecure_production_secret(self) -> "Settings":
        """Refuses to boot a production deployment on the published placeholder key."""
        if self.ENVIRONMENT.lower() == "production" and self.SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the published placeholder value while ENVIRONMENT=production. "
                "Generate a real key (python -c \"import secrets; print(secrets.token_hex(32))\") "
                "and set it in .env before starting a production deployment."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
