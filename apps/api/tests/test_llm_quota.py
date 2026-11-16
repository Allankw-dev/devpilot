import pytest

from app.services.llm.errors import RETRYABLE, LLMError, LLMQuotaExhausted, LLMRateLimited


def test_a_spent_quota_is_not_a_retryable_error() -> None:
    assert not isinstance(LLMQuotaExhausted("x"), RETRYABLE)
    assert not issubclass(LLMQuotaExhausted, LLMRateLimited)
    assert issubclass(LLMQuotaExhausted, LLMError) and LLMQuotaExhausted("x").code == "quota_exhausted"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (83974, "about 23 hours"),
        (5400, "about 2 hours"),
        (3600, "about 60 minutes"),
        (90, "about 2 minutes"),
        (30, "about 1 minute."),
    ],
)
def test_the_reset_time_is_told_in_plain_words(seconds: float, expected: str) -> None:
    assert expected in LLMQuotaExhausted("x", retry_after=seconds).user_message()


@pytest.mark.parametrize("seconds", [None, 0, -5])
def test_an_unknown_reset_time_says_nothing_about_it(seconds: float | None) -> None:
    message = LLMQuotaExhausted("x", retry_after=seconds).user_message()
    assert "reset in" not in message and "daily request quota is used up" in message


def test_the_user_message_never_echoes_the_provider_text() -> None:
    message = LLMQuotaExhausted("project 123 key AIzaSECRET", retry_after=60).user_message()
    assert "AIza" not in message and "123" not in message
