"""The Gemini adapter, driven with real google-genai types and a fake client (no network)."""

import math
from typing import Any

import httpx
import httpx2
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.services.llm import GenerationRequest, Message, ToolCall, ToolSpec
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMBlocked,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from app.services.llm.providers.gemini_provider import GeminiProvider, _to_contents


class FakeModels:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def _next(self, kwargs: dict[str, Any]) -> Any:
        self.calls.append(kwargs)
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def generate_content(self, **kwargs: Any) -> Any:
        return self._next(kwargs)

    def embed_content(self, **kwargs: Any) -> Any:
        return self._next(kwargs)


class FakeClient:
    def __init__(self, *outcomes: Any) -> None:
        self.models = FakeModels(*outcomes)


def provider(*outcomes: Any, **kw: Any) -> tuple[GeminiProvider, FakeModels]:
    client = FakeClient(*outcomes)
    return GeminiProvider(api_key="k", model="test-model", client=client, **kw), client.models


def response(
    parts: list[types.Part],
    *,
    finish: str = "STOP",
    usage: tuple[int, int, int] = (10, 5, 0),
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
                finish_reason=types.FinishReason(finish),
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=usage[0],
            candidates_token_count=usage[1],
            thoughts_token_count=usage[2],
        ),
        model_version="test-model-001",
    )


def ask(text: str = "hi", **kw: Any) -> GenerationRequest:
    return GenerationRequest(messages=[Message(role="user", content=text)], **kw)


# ---------- generation ----------


def test_text_reply_and_token_usage_including_hidden_reasoning() -> None:
    p, models = provider(response([types.Part(text="Hello")], usage=(12, 5, 30)))
    result = p.generate(ask(max_output_tokens=100, temperature=0.2), timeout=9)

    assert result.text == "Hello" and result.finish_reason == "stop"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 35)  # 5 + 30 thinking
    assert result.model == "test-model-001"
    call = models.calls[0]
    assert call["model"] == "test-model"
    cfg = call["config"]
    assert cfg.max_output_tokens == 100 and cfg.temperature == 0.2
    assert cfg.http_options.timeout == 9000  # the SDK takes milliseconds
    assert cfg.automatic_function_calling.disable is True


def test_reasoning_text_is_not_returned_as_the_answer() -> None:
    parts = [types.Part(text="thinking...", thought=True), types.Part(text="Answer")]
    p, _ = provider(response(parts))
    assert p.generate(ask(), timeout=5).text == "Answer"


def test_system_prompt_and_temperature_default() -> None:
    p, models = provider(response([types.Part(text="x")]))
    p.generate(ask(system="be brief"), timeout=5)
    cfg = models.calls[0]["config"]
    assert cfg.system_instruction == "be brief" and cfg.temperature is None


def test_structured_output_sends_the_json_schema() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    p, models = provider(response([types.Part(text='{"a": "b"}')]))
    p.generate(ask(response_schema=schema), timeout=5)
    cfg = models.calls[0]["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == schema


def test_tool_declarations_and_choice_are_sent() -> None:
    spec = ToolSpec("lookup", "Find it", {"type": "object", "properties": {}})
    p, models = provider(response([types.Part(text="x")]))
    p.generate(ask(tools=[spec], tool_choice="required"), timeout=5)
    cfg = models.calls[0]["config"]
    decl = cfg.tools[0].function_declarations[0]
    assert (decl.name, decl.description) == ("lookup", "Find it")
    assert decl.parameters_json_schema == spec.parameters
    assert cfg.tool_config.function_calling_config.mode.value == "ANY"


def test_tool_calls_are_parsed_and_the_native_turn_is_kept_for_the_next_call() -> None:
    part = types.Part(function_call=types.FunctionCall(name="lookup", args={"q": "auth"}))
    p, _ = provider(response([part]))
    result = p.generate(ask(), timeout=5)

    assert result.finish_reason == "tool_calls"
    (call,) = result.tool_calls
    assert (call.name, call.arguments) == ("lookup", {"q": "auth"}) and call.id
    # Echoed back as-is, so reasoning signatures survive between turns.
    assert _to_contents([result.assistant_message])[0] is result.assistant_message.provider_data


def test_tool_results_of_parallel_calls_share_one_turn() -> None:
    msgs = [
        Message(role="user", content="go"),
        Message(role="assistant", tool_calls=(ToolCall("1", "a", {}), ToolCall("2", "b", {}))),
        Message(role="tool", content="ra", tool_call_id="1", tool_name="a"),
        Message(role="tool", content="rb", tool_call_id="2", tool_name="b"),
    ]
    contents = _to_contents(msgs)
    assert [c.role for c in contents] == ["user", "model", "user"]
    responses = contents[2].parts or []
    assert [r.function_response.name for r in responses if r.function_response] == ["a", "b"]


def test_length_finish_reason() -> None:
    p, _ = provider(response([types.Part(text='{"a":')], finish="MAX_TOKENS"))
    assert p.generate(ask(), timeout=5).finish_reason == "length"


def test_blocked_answer_raises() -> None:
    empty = types.GenerateContentResponse(
        candidates=[types.Candidate(content=None, finish_reason=types.FinishReason("SAFETY"))]
    )
    p, _ = provider(empty)
    with pytest.raises(LLMInvalidOutput):  # no content at all
        p.generate(ask(), timeout=5)

    refused = response([], finish="SAFETY")
    p2, _ = provider(refused)
    with pytest.raises(LLMBlocked):
        p2.generate(ask(), timeout=5)


def test_prompt_blocked_before_generation() -> None:
    blocked = types.GenerateContentResponse(
        candidates=[],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(
            block_reason=types.BlockedReason("SAFETY")
        ),
    )
    p, _ = provider(blocked)
    with pytest.raises(LLMBlocked):
        p.generate(ask(), timeout=5)


# ---------- errors become provider-neutral errors ----------


def api_error(cls: type[genai_errors.APIError], code: int, message: str = "x") -> Exception:
    return cls(code, {"error": {"code": code, "message": message, "status": "S"}})


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (api_error(genai_errors.ClientError, 429), LLMRateLimited),
        (api_error(genai_errors.ClientError, 401), LLMAuthError),
        (api_error(genai_errors.ClientError, 403), LLMAuthError),
        (api_error(genai_errors.ClientError, 400, "API key not valid. Please pass a valid key"), LLMAuthError),
        (api_error(genai_errors.ClientError, 400, "bad schema"), LLMBadRequest),
        (api_error(genai_errors.ClientError, 404, "model not found"), LLMBadRequest),
        (api_error(genai_errors.ServerError, 503), LLMUnavailable),
        (api_error(genai_errors.ServerError, 504), LLMTimeout),
        (httpx.ReadTimeout("slow"), LLMTimeout),
        (httpx.ConnectError("down"), LLMUnavailable),
        (httpx2.ReadTimeout("slow"), LLMTimeout),  # the SDK may use either HTTP library
        (httpx2.ConnectError("down"), LLMUnavailable),
        (TimeoutError(), LLMTimeout),
        (RuntimeError("weird"), LLMUnavailable),
    ],
)
def test_sdk_errors_are_translated(error: Exception, expected: type[Exception]) -> None:
    p, _ = provider(error)
    with pytest.raises(expected):
        p.generate(ask(), timeout=5)


def test_error_messages_never_echo_the_provider_body() -> None:
    err = api_error(genai_errors.ClientError, 400, "key AIzaSyDEADBEEF is wrong for project 123")
    p, _ = provider(err)
    with pytest.raises(LLMBadRequest) as exc:
        p.generate(ask(), timeout=5)
    assert "AIza" not in str(exc.value)


# ---------- embeddings ----------


def embedding_response(*vectors: list[float]) -> types.EmbedContentResponse:
    return types.EmbedContentResponse(
        embeddings=[types.ContentEmbedding(values=v) for v in vectors]
    )


def test_embeddings_use_the_right_task_and_are_normalised_when_shortened() -> None:
    p, models = provider(
        embedding_response([3.0, 4.0], [0.0, 2.0]), embedding_model="emb-model", embedding_dimensions=2
    )
    out = p.embed(["a", "b"], task="query", timeout=5)

    cfg = models.calls[0]["config"]
    assert models.calls[0]["model"] == "emb-model"
    assert cfg.task_type == "RETRIEVAL_QUERY" and cfg.output_dimensionality == 2
    assert out.vectors[0] == pytest.approx([0.6, 0.8])
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0) for v in out.vectors)


def test_document_embeddings_use_the_document_task() -> None:
    p, models = provider(embedding_response([1.0]), embedding_model="emb", embedding_dimensions=1)
    p.embed(["a"], task="document", timeout=5)
    assert models.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"


def test_embedding_without_a_model_is_a_configuration_error() -> None:
    p, _ = provider()
    with pytest.raises(LLMBadRequest):
        p.embed(["a"], task="query", timeout=5)


def test_embedding_errors_are_translated() -> None:
    p, _ = provider(api_error(genai_errors.ClientError, 429), embedding_model="emb")
    with pytest.raises(LLMRateLimited):
        p.embed(["a"], task="query", timeout=5)
