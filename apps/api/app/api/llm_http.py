"""One place that turns AI errors into HTTP responses, so no route leaks provider details."""

from fastapi import HTTPException, status

from app.services.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMNotConfigured,
    LLMRateLimited,
    LLMTimeout,
)


def llm_http_error(exc: LLMError) -> HTTPException:
    if isinstance(exc, LLMNotConfigured):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    if isinstance(exc, LLMAuthError):
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The AI provider rejected the API key, or the key can't use the configured model.",
        )
    if isinstance(exc, LLMRateLimited):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "The AI provider is rate limiting us"
        )
    if isinstance(exc, LLMTimeout):
        return HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The AI provider timed out")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"The AI provider call failed ({exc.code})")
