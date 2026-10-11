from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Enterprise AI Knowledge Assistant"
    app_env: str = "development"
    app_debug: bool = False
    frontend_base_url: str = "http://127.0.0.1:5173"

    database_url: str = (
        "sqlite+aiosqlite:///./knowledge_assistant.db"
    )

    documents_storage_directory: Path = Path(
        "storage/documents"
    )
    document_max_upload_bytes: int = Field(
        default=25 * 1024 * 1024,
        gt=0,
    )
    document_upload_chunk_bytes: int = Field(
        default=1024 * 1024,
        gt=0,
    )
    document_max_pdf_pages: int = Field(default=500, gt=0)
    document_max_extracted_text_characters: int = Field(
        default=5_000_000,
        gt=0,
    )
    document_max_docx_uncompressed_bytes: int = Field(
        default=100 * 1024 * 1024,
        gt=0,
    )
    document_max_docx_archive_entries: int = Field(
        default=2_048,
        gt=0,
    )
    document_max_docx_compression_ratio: int = Field(
        default=100,
        gt=0,
    )

    chroma_storage_directory: Path = Path(
        "storage/chroma"
    )

    mail_outbox_directory: Path = Path(
        "storage/mail_outbox"
    )

    cors_origins: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174,"
        "http://localhost:5175,"
        "http://127.0.0.1:5175"
    )

    jwt_secret_key: str = Field(min_length=32)

    jwt_algorithm: str = "HS256"

    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    account_action_token_expire_minutes: int = 30

    access_cookie_name: str = "knowledge_ai_access"
    refresh_cookie_name: str = "knowledge_ai_refresh"
    auth_cookie_domain: str | None = None
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "auto"

    login_max_failed_attempts: int = 5
    login_lock_minutes: int = 15
    auth_rate_limit_requests: int = Field(default=20, gt=0)
    auth_rate_limit_window_seconds: int = Field(default=60, gt=0)
    auth_rate_limit_max_keys: int = Field(default=10_000, gt=0)
    trusted_proxy_cidrs: str = ""

    mail_delivery_mode: str = "outbox"
    mail_from_address: str = "no-reply@knowledge-ai.local"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: str) -> str:
        for entry in value.split(","):
            candidate = entry.strip()
            if candidate:
                ip_network(candidate, strict=False)
        return value

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        secret = self.jwt_secret_key.strip()
        normalized_secret = secret.casefold()
        if len(secret) < 32 or normalized_secret.startswith(
            ("change-this-", "replace-with-")
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be a unique value of at least 32 "
                "characters and cannot use a documented placeholder."
            )
        if self.app_env.strip().casefold() == "production" and self.app_debug:
            raise ValueError("APP_DEBUG must be false in production.")
        self.jwt_secret_key = secret
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def trusted_proxy_networks(
        self,
    ) -> tuple[IPv4Network | IPv6Network, ...]:
        return tuple(
            ip_network(entry.strip(), strict=False)
            for entry in self.trusted_proxy_cidrs.split(",")
            if entry.strip()
        )

    @property
    def effective_cookie_secure(self) -> bool:
        return self.auth_cookie_secure or self.app_env.lower() == "production"

    @property
    def effective_cookie_samesite(self) -> str:
        value = self.auth_cookie_samesite.lower().strip()
        if value == "auto":
            return "none" if self.effective_cookie_secure else "lax"
        if value not in {"lax", "strict", "none"}:
            return "none" if self.effective_cookie_secure else "lax"
        if value == "none" and not self.effective_cookie_secure:
            return "lax"
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
