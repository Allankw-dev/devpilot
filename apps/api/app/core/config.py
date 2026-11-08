import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
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
