"""Environment-based settings; production requires access protection."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    demo_username: str = "viewer"
    demo_password: str = ""
    enable_api_docs: bool = True
    max_request_bytes: int = 52 * 1024 * 1024
    upload_requests_per_minute: int = 0
    max_concurrent_uploads: int = 2
    llm_provider: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 45
    vision_api_key: str = ""
    vision_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    vision_model: str = "doubao-seed-2-1-pro-260915"
    vision_timeout_seconds: int = 120

    @classmethod
    def from_env(cls) -> Settings:
        environment = os.getenv("APP_ENV", "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test, or production")
        production = environment == "production"
        docs_value = os.getenv("ENABLE_API_DOCS", "false" if production else "true").lower()
        if docs_value not in {"true", "false"}:
            raise ValueError("ENABLE_API_DOCS must be true or false")
        settings = cls(
            environment=environment,
            demo_username=os.getenv("DEMO_USERNAME", "viewer"),
            demo_password=os.getenv("DEMO_PASSWORD", ""),
            enable_api_docs=docs_value == "true",
            max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", str(52 * 1024 * 1024))),
            upload_requests_per_minute=int(os.getenv("UPLOAD_REQUESTS_PER_MINUTE", "10" if production else "0")),
            max_concurrent_uploads=int(os.getenv("MAX_CONCURRENT_UPLOADS", "2")),
            llm_provider=os.getenv("LLM_PROVIDER", "").strip().lower(),
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "45")),
            vision_api_key=os.getenv("VISION_API_KEY", "").strip(),
            vision_base_url=os.getenv("VISION_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip(),
            vision_model=os.getenv("VISION_MODEL", "doubao-seed-2-1-pro-260915").strip(),
            vision_timeout_seconds=int(os.getenv("VISION_TIMEOUT_SECONDS", "120")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.demo_username or ":" in self.demo_username:
            raise ValueError("DEMO_USERNAME must be nonempty and must not contain a colon")
        if self.environment == "production" and len(self.demo_password) < 16:
            raise ValueError("Production requires DEMO_PASSWORD with at least 16 characters")
        if self.max_request_bytes < 1 or self.max_concurrent_uploads < 1:
            raise ValueError("Request size and concurrent upload limits must be positive")
        if self.upload_requests_per_minute < 0:
            raise ValueError("UPLOAD_REQUESTS_PER_MINUTE cannot be negative")
        if self.llm_timeout_seconds < 1:
            raise ValueError("LLM_TIMEOUT_SECONDS must be positive")
        if not 1 <= self.vision_timeout_seconds <= 300:
            raise ValueError("VISION_TIMEOUT_SECONDS must be between 1 and 300")
        if self.environment == "production" and not self.upload_requests_per_minute:
            raise ValueError("Production requires a positive upload rate limit")
