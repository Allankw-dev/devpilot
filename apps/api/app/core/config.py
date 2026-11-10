import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    product_name: str = "DevPilot AI"
    environment: str = "development"
    log_level: str = "INFO"

    api_v1_prefix: str = "/api/v1"
    # NoDecode: accept plain "a,b" or a JSON list from env instead of forcing JSON
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    database_url: str = "postgresql+psycopg://devpilot:devpilot@localhost:5432/devpilot"
    redis_url: str = "redis://localhost:6379/0"

    # Supabase Auth. SUPABASE_URL is public. Newer projects sign tokens with asymmetric
    # keys (verified via JWKS, no secret needed). The secret is only a legacy HS256 fallback.
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_secret: SecretStr | None = None

    # GitHub App (setup: docs/GITHUB.md). All values come from the GitHub App's settings page.
    github_app_id: str | None = None
    github_app_slug: str | None = None
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None
    github_app_private_key: SecretStr | None = None  # PEM text; "\\n" is accepted for newlines
    github_app_private_key_path: str | None = None  # or a path to the .pem file (easier on Windows)
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    github_api_version: str = "2022-11-28"

    webhook_delivery_retention_days: int = 7  # GitHub only allows redelivery for a few days

    # AI (setup: docs/AI.md). Model names are deliberately required settings with no default:
    # providers retire and rename models, so a name baked into code goes stale silently.
    llm_provider: Literal["gemini", "anthropic"] = "gemini"
    embedding_provider: Literal["gemini"] = "gemini"
    llm_timeout_seconds: float = 60.0  # per provider call
    llm_max_attempts: int = 3  # calls per operation, retries included
    llm_max_output_tokens: int = 4096
    embedding_dimensions: int = 768  # must match the pgvector column added with indexing

    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    gemini_embedding_model: str | None = None

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None

    def github_private_key(self) -> str | None:
        inline = (
            self.github_app_private_key.get_secret_value().strip()
            if self.github_app_private_key
            else ""
        )
        if inline:
            return inline.replace("\\n", "\n")
        path = (self.github_app_private_key_path or "").strip()
        if path:
            return Path(path).read_text(encoding="utf-8")
        return None

    def github_missing_settings(self) -> list[str]:
        """Names (never values) of required GitHub settings that are not set."""

        def blank(value: str | SecretStr | None) -> bool:
            text = value.get_secret_value() if isinstance(value, SecretStr) else (value or "")
            return not text.strip()

        missing = [
            name
            for name, value in (
                ("GITHUB_APP_ID", self.github_app_id),
                ("GITHUB_APP_SLUG", self.github_app_slug),
                ("GITHUB_CLIENT_ID", self.github_client_id),
                ("GITHUB_CLIENT_SECRET", self.github_client_secret),
                ("GITHUB_WEBHOOK_SECRET", self.github_webhook_secret),
            )
            if blank(value)
        ]
        if (
            blank(self.github_app_private_key)
            and not (self.github_app_private_key_path or "").strip()
        ):
            missing.append("GITHUB_APP_PRIVATE_KEY_PATH")
        return missing

    def llm_missing_settings(self) -> list[str]:
        """Names (never values) of settings the selected generation provider still needs."""

        def blank(value: str | SecretStr | None) -> bool:
            text = value.get_secret_value() if isinstance(value, SecretStr) else (value or "")
            return not text.strip()

        if self.llm_provider == "anthropic":
            pairs = (
                ("ANTHROPIC_API_KEY", self.anthropic_api_key),
                ("ANTHROPIC_MODEL", self.anthropic_model),
            )
        else:
            pairs = (("GEMINI_API_KEY", self.gemini_api_key), ("GEMINI_MODEL", self.gemini_model))
        return [name for name, value in pairs if blank(value)]

    def embedding_missing_settings(self) -> list[str]:
        def blank(value: str | SecretStr | None) -> bool:
            text = value.get_secret_value() if isinstance(value, SecretStr) else (value or "")
            return not text.strip()

        return [
            name
            for name, value in (
                ("GEMINI_API_KEY", self.gemini_api_key),
                ("GEMINI_EMBEDDING_MODEL", self.gemini_embedding_model),
            )
            if blank(value)
        ]

    @property
    def supabase_issuer(self) -> str | None:
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else None

    @property
    def supabase_jwks_url(self) -> str | None:
        issuer = self.supabase_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            value = v.strip()
            if value.startswith("["):
                return json.loads(value)
            return [o.strip() for o in value.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
