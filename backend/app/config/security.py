from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecuritySettings(BaseSettings):
    """Authentication and browser-security settings with no secret fallbacks."""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_alg: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "neura"
    jwt_audience: str = "neura-web"
    jwt_expires_seconds: int = Field(default=3600, ge=300, le=86_400)

    access_cookie_name: Literal["access_token"] = "access_token"
    csrf_cookie_name: str = "csrf_token"
    cookie_domain: str | None = None
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @field_validator("jwt_secret")
    @classmethod
    def reject_known_development_secrets(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value().strip().lower()
        if (
            len(secret) < 32
            or secret in {"dev", "secret", "supersecretkey", "dev-secret-change-me"}
            or secret.startswith(("replace-", "change-me", "changeme"))
        ):
            raise ValueError("JWT_SECRET must be a unique high-entropy secret")
        return value

    @model_validator(mode="after")
    def secure_cookie_policy(self) -> SecuritySettings:
        if self.app_env in {"staging", "prod"} and not self.cookie_secure:
            raise ValueError("Secure authentication cookies are required outside development")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None cookies must be Secure")
        return self


@lru_cache(maxsize=1)
def get_security_settings() -> SecuritySettings:
    return SecuritySettings()
