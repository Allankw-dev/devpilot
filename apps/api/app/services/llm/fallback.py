"""Provider fallback for generation calls."""

from collections.abc import Sequence

from app.services.llm.base import (
    EmbeddingResult,
    EmbeddingTask,
    GenerationRequest,
    GenerationResult,
    LLMProvider,
)
from app.services.llm.errors import RETRYABLE, LLMNotSupported, LLMQuotaExhausted


class FallbackProvider(LLMProvider):
    name: str
    model: str

    def __init__(self, primary: LLMProvider, fallbacks: Sequence[LLMProvider]) -> None:
        self.primary = primary
        self.fallbacks = tuple(fallbacks)
        self.name = primary.name
        self.model = primary.model

    def generate(self, request: GenerationRequest, *, timeout: float) -> GenerationResult:
        providers: list[LLMProvider] = []
        for provider in (self.primary, *self.fallbacks):
            if all(
                provider.name != existing.name or provider.model != existing.model
                for existing in providers
            ):
                providers.append(provider)
        last_error: Exception | None = None
        for provider in providers:
            try:
                result = provider.generate(request, timeout=timeout)
                self.name = provider.name
                self.model = provider.model
                return result
            except (LLMQuotaExhausted,) + RETRYABLE as exc:
                last_error = exc
        raise last_error or AssertionError("no providers configured")

    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult:
        raise LLMNotSupported("Generation fallback provider cannot create embeddings")
