"""Provider-neutral AI errors. Provider adapters translate their SDK's exceptions into these,
so nothing above them depends on which provider is configured."""


class LLMError(Exception):
    code = "llm_error"


class LLMNotConfigured(LLMError):
    code = "not_configured"

    def __init__(self, missing: list[str]) -> None:
        super().__init__("AI is not configured. Missing: " + ", ".join(missing))
        self.missing = missing


class LLMNotSupported(LLMError):
    """The configured provider can't do this (e.g. embeddings on a chat-only provider)."""

    code = "not_supported"


class LLMAuthError(LLMError):
    """The provider rejected our API key or the key lacks access to the model."""

    code = "auth"


class LLMBadRequest(LLMError):
    code = "bad_request"


class LLMRateLimited(LLMError):
    code = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMQuotaExhausted(LLMError):
    """A usage quota is used up (typically the free tier's daily request limit). Unlike a short
    rate limit, trying again in a few seconds or minutes cannot help, so nothing retries it."""

    code = "quota_exhausted"

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after  # seconds until the provider says it resets, if known

    def user_message(self) -> str:
        """Safe to show to people: our own words, nothing from the provider's reply."""
        text = (
            "The AI provider's daily request quota is used up. Free tiers allow very few "
            "requests a day. Try again later, turn on billing with the provider, or switch "
            "GEMINI_MODEL to another model."
        )
        seconds = self.retry_after
        if seconds is not None and seconds > 0:
            if seconds >= 5400:
                text += f" It should reset in about {round(seconds / 3600)} hours."
            else:
                minutes = max(1, round(seconds / 60))
                unit = "minute" if minutes == 1 else "minutes"
                text += f" It should reset in about {minutes} {unit}."
        return text


class LLMTimeout(LLMError):
    code = "timeout"


class LLMUnavailable(LLMError):
    """Provider 5xx or network failure."""

    code = "unavailable"


class LLMBlocked(LLMError):
    """The provider declined to answer (safety filter, refusal)."""

    code = "blocked"


class LLMInvalidOutput(LLMError):
    """The model's reply could not be turned into what we asked for."""

    code = "invalid_output"


class LLMToolLoopExceeded(LLMError):
    code = "tool_loop"


# Worth trying again; everything else would fail the same way.
RETRYABLE: tuple[type[LLMError], ...] = (LLMRateLimited, LLMTimeout, LLMUnavailable)
