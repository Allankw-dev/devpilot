"""The optional Anthropic adapter, driven by a fake client (no network, no API key)."""

from types import SimpleNamespace as NS
from typing import Any

import anthropic
import httpx2
import pytest

from app.services.llm import GenerationRequest, Message, ToolCall, ToolSpec
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMBlocked,
    LLMInvalidOutput,
    LLMNotSupported,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from app.services.llm.providers.anthropic_provider import (
    STRUCTURED_TOOL,
    AnthropicProvider,
    _to_messages,
)


class FakeMessages:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def provider(*outcomes: Any) -> tuple[AnthropicProvider, FakeMessages]:
    messages = FakeMessages(*outcomes)
    return AnthropicProvider(api_key="k", model="test-model", client=NS(messages=messages)), messages


def message(blocks: list[Any], stop: str = "end_turn", usage: tuple[int, int] = (11, 6)) -> Any:
    return NS(
        content=blocks,
        stop_reason=stop,
        usage=NS(input_tokens=usage[0], output_tokens=usage[1]),
        model="test-model-2",
    )


def text(t: str) -> Any:
    return NS(type="text", text=t)


def tool_use(name: str, **inputs: Any) -> Any:
    return NS(type="tool_use", id=f"tu_{name}", name=name, input=inputs)


def ask(t: str = "hi", **kw: Any) -> GenerationRequest:
    return GenerationRequest(messages=[Message(role="user", content=t)], **kw)


def test_text_reply_usage_and_request_shape() -> None:
    p, api = provider(message([text("Hello")]))
    result = p.generate(ask(system="be brief", temperature=0.3, max_output_tokens=50), timeout=8)

    assert result.text == "Hello" and result.finish_reason == "stop"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 6)
    sent = api.calls[0]
    assert sent["model"] == "test-model" and sent["max_tokens"] == 50 and sent["timeout"] == 8
    assert sent["system"] == "be brief" and sent["temperature"] == 0.3
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


def test_tools_and_tool_calls() -> None:
    spec = ToolSpec("lookup", "Find it", {"type": "object", "properties": {}})
    p, api = provider(message([text("let me check"), tool_use("lookup", q="auth")], "tool_use"))
    result = p.generate(ask(tools=[spec], tool_choice="required"), timeout=5)

    assert api.calls[0]["tools"] == [
        {"name": "lookup", "description": "Find it", "input_schema": spec.parameters}
    ]
    assert api.calls[0]["tool_choice"] == {"type": "any"}
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == (ToolCall("tu_lookup", "lookup", {"q": "auth"}),)
    assert result.assistant_message.provider_data[1]["type"] == "tool_use"


def test_tools_are_left_out_when_the_caller_turns_them_off() -> None:
    spec = ToolSpec("lookup", "Find it", {"type": "object"})
    p, api = provider(message([text("done")]))
    p.generate(ask(tools=[spec], tool_choice="none"), timeout=5)
    assert "tools" not in api.calls[0]


def test_structured_output_is_a_forced_tool_call() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    p, api = provider(message([tool_use(STRUCTURED_TOOL, a="b")], "tool_use"))
    result = p.generate(ask(response_schema=schema), timeout=5)

    assert api.calls[0]["tool_choice"] == {"type": "tool", "name": STRUCTURED_TOOL}
    assert api.calls[0]["tools"][0]["input_schema"] == schema
    assert result.text == '{"a": "b"}' and result.tool_calls == ()


def test_structured_output_without_the_tool_call_is_invalid() -> None:
    p, _ = provider(message([text("sorry")]))
    with pytest.raises(LLMInvalidOutput):
        p.generate(ask(response_schema={"type": "object"}), timeout=5)


def test_max_tokens_and_refusal() -> None:
    p, _ = provider(message([text("cut")], "max_tokens"))
    assert p.generate(ask(), timeout=5).finish_reason == "length"
    p2, _ = provider(message([], "refusal"))
    with pytest.raises(LLMBlocked):
        p2.generate(ask(), timeout=5)


def test_history_conversion_merges_parallel_tool_results() -> None:
    history = [
        Message(role="user", content="go"),
        Message(role="assistant", tool_calls=(ToolCall("1", "a", {"x": 1}), ToolCall("2", "b", {}))),
        Message(role="tool", content="ra", tool_call_id="1", tool_name="a"),
        Message(role="tool", content="rb", tool_call_id="2", tool_name="b"),
    ]
    out = _to_messages(history)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["1", "2"]
    assert out[1]["content"][0] == {"type": "tool_use", "id": "1", "name": "a", "input": {"x": 1}}


def status_error(cls: type[anthropic.APIStatusError], code: int, headers: dict[str, str] | None = None) -> Exception:
    response = httpx2.Response(code, headers=headers or {}, request=httpx2.Request("POST", "https://x"))
    return cls("secret body sk-ant-123", response=response, body=None)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (status_error(anthropic.RateLimitError, 429, {"retry-after": "5"}), LLMRateLimited),
        (status_error(anthropic.AuthenticationError, 401), LLMAuthError),
        (status_error(anthropic.PermissionDeniedError, 403), LLMAuthError),
        (status_error(anthropic.BadRequestError, 400), LLMBadRequest),
        (status_error(anthropic.InternalServerError, 500), LLMUnavailable),
        (status_error(anthropic.InternalServerError, 529), LLMUnavailable),
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), LLMTimeout),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), LLMUnavailable),
    ],
)
def test_sdk_errors_are_translated(error: Exception, expected: type[Exception]) -> None:
    p, _ = provider(error)
    with pytest.raises(expected) as exc:
        p.generate(ask(), timeout=5)
    assert "sk-ant" not in str(exc.value)


def test_retry_after_header_is_passed_on() -> None:
    p, _ = provider(status_error(anthropic.RateLimitError, 429, {"retry-after": "5"}))
    with pytest.raises(LLMRateLimited) as exc:
        p.generate(ask(), timeout=5)
    assert exc.value.retry_after == 5.0


def test_embeddings_are_not_supported() -> None:
    p, _ = provider()
    with pytest.raises(LLMNotSupported):
        p.embed(["a"], task="query", timeout=5)
