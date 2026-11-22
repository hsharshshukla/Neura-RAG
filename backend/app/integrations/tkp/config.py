from __future__ import annotations

from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TKPSettings(BaseSettings):
    """Private, least-privilege configuration for the staging TKP bridge."""

    model_config = SettingsConfigDict(env_prefix="TKP_", extra="ignore", hide_input_in_errors=True)

    internal_url: AnyHttpUrl
    service_token: SecretStr = Field(min_length=24)
    ingestion_service_token: SecretStr | None = Field(default=None, min_length=24)
    staging_workspace_id: UUID
    staging_workspace_name: str = "TKP staging"

    connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    read_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    write_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    pool_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    total_deadline_seconds: float = Field(default=10.0, gt=0, le=60)
    max_attempts: int = Field(default=2, ge=1, le=4)
    retry_base_seconds: float = Field(default=0.1, ge=0, le=5)
    retry_max_seconds: float = Field(default=1.0, ge=0, le=10)
    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    bulk_max_files: int = Field(default=5, ge=1, le=20)
    bulk_max_file_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    bulk_max_total_bytes: int = Field(default=26 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    bulk_allowed_extensions: tuple[str, ...] = ("pdf", "docx", "txt")

    @field_validator("service_token", "ingestion_service_token")
    @classmethod
    def reject_placeholder_tokens(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        token = value.get_secret_value().strip().lower()
        if len(token) < 24 or token.startswith(("replace-", "change-me", "changeme")):
            raise ValueError("TKP credentials must be provisioned, non-placeholder values")
        return value

    @model_validator(mode="after")
    def private_transport_policy(self) -> TKPSettings:
        url = str(self.internal_url)
        if self.environment in {"staging", "prod"} and not url.startswith("https://"):
            raise ValueError("TKP internal traffic must use HTTPS outside development")
        if self.total_deadline_seconds < self.connect_timeout_seconds:
            raise ValueError("TKP total deadline must cover the connect timeout")
        if self.ingestion_service_token is not None and secrets_equal(
            self.service_token, self.ingestion_service_token
        ):
            raise ValueError("TKP retrieval and ingestion credentials must be different")
        return self


def secrets_equal(left: SecretStr, right: SecretStr) -> bool:
    """Compare credentials without placing either value in validation output."""
    import secrets

    return secrets.compare_digest(left.get_secret_value(), right.get_secret_value())


@lru_cache(maxsize=1)
def get_tkp_settings() -> TKPSettings:
    return TKPSettings()
