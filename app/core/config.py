"""Application configuration settings using Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Any, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration settings for Nexora.

    Loads configuration from environment variables prefixed with NEXORA_ or CRAWLBOT_
    or from a local .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NEXORA_",
        extra="ignore",
    )

    # App
    app_name: str = "Nexora"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    # Crawling
    max_crawl_depth: int = 3
    max_pages: int = 500
    request_timeout: float = 30.0
    max_concurrency: int = 5
    delay_between_requests: float = 1.0
    max_response_size: int = 10 * 1024 * 1024  # 10MB

    # Extraction
    default_extraction_strategy: str = "trafilatura"  # or 'bs4'

    # Output
    output_dir: str = "output"
    log_level: str = "INFO"

    # OpenAI / AI Features
    openai_api_key: str = ""
    openai_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"
    ai_concurrency: int = 3
    semantic_repair_confidence_threshold: float = 0.75


    # Phase 4: Developer Platform, Vector Integrations & Security
    api_key: Optional[str] = None
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    incremental_manifest_dir: str = "data/manifests"

    # Phase 5: SaaS Platform, Multi-Tenancy & Usage Quotas
    multi_tenant_enabled: bool = True
    default_plan: str = "trial"
    max_job_runtime_minutes: int = 60
    secret_key: Optional[str] = None
    workspaces_dir: str = "data/workspaces"
    usage_dir: str = "data/usage"
    secrets_dir: str = "data/secrets"

    # URL filtering
    default_exclude_patterns: list[str] = [
        r"/wp-admin/",
        r"/wp-login",
        r"/admin/",
        r"/login",
        r"/logout",
        r"/cart",
        r"/checkout",
        r"/my-account",
        r"\.pdf$",
        r"\.zip$",
        r"\.exe$",
        r"\.dmg$",
        r"\.jpg$",
        r"\.jpeg$",
        r"\.png$",
        r"\.gif$",
        r"\.svg$",
        r"\.mp3$",
        r"\.mp4$",
        r"\.avi$",
        r"\.mov$",
        r"\?replytocom=",
        r"#respond",
        r"/feed/",
        r"/rss/",
        r"/xmlrpc\.php",
        r"/wp-json/",
    ]

    @model_validator(mode="before")
    @classmethod
    def load_nexora_env_fallbacks(cls, data: Any) -> Any:
        if isinstance(data, dict):
            fields = [
                "api_key", "secret_key", "openai_api_key", "openai_base_url",
                "embedding_model", "llm_model", "ai_concurrency", "qdrant_url",
                "qdrant_api_key", "app_env", "host", "port", "output_dir", "log_level",
                "max_crawl_depth", "max_pages", "request_timeout", "max_concurrency",
                "delay_between_requests", "app_name", "multi_tenant_enabled"
            ]
            for f in fields:
                if not data.get(f):
                    val = os.getenv(f"NEXORA_{f.upper()}") or os.getenv(f"CRAWLBOT_{f.upper()}")
                    if val is not None:
                        data[f] = val
        return data


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton instance.

    Returns:
        Settings: Application configuration instance.
    """
    return Settings()
