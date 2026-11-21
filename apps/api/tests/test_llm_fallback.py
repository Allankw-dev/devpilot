import httpx

from app.services.llm.base import GenerationRequest, Message
from app.services.llm.errors import LLMRateLimited
from app.services.llm.fallback import FallbackProvider
from app.services.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from tests.llm_helpers import FakeProvider, reply


def request() -> GenerationRequest:
    return GenerationRequest(messages=[Message(role="user", content="hello")])


def test_fallback_moves_to_groq_after_primary_rate_limit() -> None:
    primary = FakeProvider([LLMRateLimited("limit")])
    primary.name = "gemini"
    primary.model = "gemini-model"
    groq = FakeProvider([reply("from groq")])
    groq.name = "groq"
    groq.model = "groq-model"

    provider = FallbackProvider(primary, [groq])
    result = provider.generate(request(), timeout=10)

    assert result.text == "from groq"
    assert (provider.name, provider.model) == ("groq", "groq-model")


def test_non_retryable_primary_error_does_not_use_fallback() -> None:
    primary = FakeProvider([ValueError("bad request")])
    primary.name = "gemini"
    primary.model = "gemini-model"
    groq = FakeProvider([reply("must not run")])
    groq.name = "groq"
    groq.model = "groq-model"

    provider = FallbackProvider(primary, [groq])
    try:
        provider.generate(request(), timeout=10)
    except ValueError:
        pass
    else:
        raise AssertionError("primary ValueError should be propagated")

    assert groq.requests == []


def test_openai_compatible_provider_parses_generation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openai/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "model": "groq-result-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello"},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        name="groq",
        api_key="key",
        model="groq-model",
        base_url="https://example.com/openai/v1",
        client=client,
    )
    result = provider.generate(request(), timeout=10)

    assert result.text == "hello"
    assert result.model == "groq-result-model"
    assert result.usage.input_tokens == 4
    assert result.usage.output_tokens == 2
