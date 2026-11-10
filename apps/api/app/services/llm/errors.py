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
