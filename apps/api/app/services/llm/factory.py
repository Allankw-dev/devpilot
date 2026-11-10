"""Builds the configured LLMService from settings."""

from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.services.llm.base import LLMProvider
from app.services.llm.errors import LLMNotConfigured
from app.services.llm.service import LLMService
from app.services.llm.usage import DbUsageRecorder


def build_generation_provider(settings: Settings) -> LLMProvider:
    missing = settings.llm_missing_settings()
    if missing:
        raise LLMNotConfigured(missing)
    # Imported here so only the selected provider's SDK is loaded.
    if settings.llm_provider == "anthropic":
        from app.services.llm.providers.anthropic_provider import AnthropicProvider

        assert settings.anthropic_api_key and settings.anthropic_model
        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(), model=settings.anthropic_model
        )
    from app.services.llm.providers.gemini_provider import GeminiProvider

    assert settings.gemini_api_key and settings.gemini_model
    return GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        embedding_model=settings.gemini_embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )


def build_embedding_provider(settings: Settings) -> LLMProvider | None:
    """None when embeddings aren't configured. Generation can still work without them."""
    if settings.embedding_missing_settings():
        return None
    from app.services.llm.providers.gemini_provider import GeminiProvider

    assert settings.gemini_api_key and settings.gemini_embedding_model
    return GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_embedding_model,  # this instance is only used for embed()
        embedding_model=settings.gemini_embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )


def build_llm_service(
    settings: Settings, session_factory: sessionmaker[Session] | None = None
) -> LLMService:
    return LLMService(
        build_generation_provider(settings),
        embedding=build_embedding_provider(settings),
        recorder=DbUsageRecorder(session_factory or get_session_factory()),
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=settings.llm_max_attempts,
        max_output_tokens=settings.llm_max_output_tokens,
    )


@lru_cache
def get_llm_service() -> LLMService:
    """Raises LLMNotConfigured until the provider's settings are filled in."""
    return build_llm_service(get_settings())
