import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from app.services.llm import CallContext, ToolCall, ToolSpec, Usage
from app.services.llm.errors import (
    LLMAuthError,
    LLMInvalidOutput,
    LLMNotSupported,
    LLMRateLimited,
    LLMTimeout,
    LLMToolLoopExceeded,
    LLMUnavailable,
)
from app.services.llm.service import EMBED_BATCH_SIZE, Tool
from tests.llm_helpers import FakeProvider, Harness, reply, user_request

CTX = CallContext(feature="unit_test", org_id=uuid.uuid4())


class Verdict(BaseModel):
    severity: str
    confidence: float


# ---------- plain generation, retries, usage ----------


def test_generate_returns_result_and_records_usage() -> None:
    h = Harness(FakeProvider([reply("hello", tokens=(12, 7))]))
    result = h.service.generate(user_request(), CTX)

    assert result.text == "hello"
    (entry,) = h.recorder.entries
    assert (entry.status, entry.operation, entry.calls) == ("ok", "generate", 1)
    assert (entry.input_tokens, entry.output_tokens) == (12, 7)
    assert entry.ctx == CTX and entry.model == "fake-model-v1"


def test_default_output_limit_comes_from_service_config_not_the_caller() -> None:
    h = Harness(FakeProvider([reply()]))
    h.service.generate(user_request(), CTX)
    assert h.provider.requests[0].max_output_tokens == 777


def test_transient_failures_are_retried_with_backoff() -> None:
    h = Harness(FakeProvider([LLMUnavailable("boom"), LLMTimeout("slow"), reply("ok")]))
    assert h.service.generate(user_request(), CTX).text == "ok"
    assert h.sleeps == [1.0, 2.0]
    assert h.recorder.entries[0].calls == 3 and h.recorder.entries[0].status == "ok"


def test_rate_limit_waits_as_long_as_the_provider_asks() -> None:
    h = Harness(FakeProvider([LLMRateLimited("slow down", retry_after=7), reply()]))
    h.service.generate(user_request(), CTX)
    assert h.sleeps == [7.0]


def test_rate_limit_wait_is_capped() -> None:
    h = Harness(FakeProvider([LLMRateLimited("slow down", retry_after=9999), reply()]))
    h.service.generate(user_request(), CTX)
    assert h.sleeps == [20.0]


def test_gives_up_after_max_attempts_and_records_the_failure() -> None:
    h = Harness(FakeProvider([LLMUnavailable("1"), LLMUnavailable("2"), LLMUnavailable("3")]))
    with pytest.raises(LLMUnavailable):
        h.service.generate(user_request(), CTX)
    (entry,) = h.recorder.entries
    assert (entry.status, entry.error_code, entry.calls) == ("error", "unavailable", 3)


def test_errors_that_cannot_succeed_are_not_retried() -> None:
    h = Harness(FakeProvider([LLMAuthError("bad key"), reply()]))
    with pytest.raises(LLMAuthError):
        h.service.generate(user_request(), CTX)
    assert len(h.provider.requests) == 1 and h.sleeps == []
    assert h.recorder.entries[0].error_code == "auth"


def test_unexpected_exceptions_are_recorded_and_propagate() -> None:
    h = Harness(FakeProvider([RuntimeError("bug")]))
    with pytest.raises(RuntimeError):
        h.service.generate(user_request(), CTX)
    assert h.recorder.entries[0].error_code == "unexpected"


# ---------- structured output ----------


def test_structured_output_is_validated_into_the_model() -> None:
    h = Harness(FakeProvider([reply('{"severity": "high", "confidence": 0.9}')]))
    out = h.service.generate_structured(user_request(), Verdict, CTX)

    assert out.value == Verdict(severity="high", confidence=0.9)
    sent = h.provider.requests[0].response_schema
    assert sent is not None and "severity" in sent["properties"]
    assert h.recorder.entries[0].operation == "structured"


def test_structured_output_tolerates_a_code_fence() -> None:
    fenced = '```json\n{"severity": "low", "confidence": 0.1}\n```'
    h = Harness(FakeProvider([reply(fenced)]))
    assert h.service.generate_structured(user_request(), Verdict, CTX).value.severity == "low"


def test_structured_output_gets_one_repair_attempt_and_usage_is_summed() -> None:
    h = Harness(
        FakeProvider(
            [
                reply('{"severity": "high"}', tokens=(10, 5)),  # confidence missing
                reply('{"severity": "high", "confidence": 0.5}', tokens=(20, 8)),
            ]
        )
    )
    out = h.service.generate_structured(user_request(), Verdict, CTX)

    assert out.value.confidence == 0.5
    repair_prompt = h.provider.requests[1].messages[-1].content
    assert "confidence" in repair_prompt  # tells the model what was wrong
    assert out.usage == Usage(30, 13)
    assert h.recorder.entries[0].calls == 2


def test_structured_output_fails_cleanly_when_still_invalid() -> None:
    h = Harness(FakeProvider([reply("nope"), reply("still nope")]))
    with pytest.raises(LLMInvalidOutput):
        h.service.generate_structured(user_request(), Verdict, CTX)
    assert h.recorder.entries[0].error_code == "invalid_output"


def test_truncated_json_is_reported_not_repaired() -> None:
    h = Harness(FakeProvider([reply('{"severity": "hi', finish="length"), reply()]))
    with pytest.raises(LLMInvalidOutput, match="cut off"):
        h.service.generate_structured(user_request(), Verdict, CTX)
    assert len(h.provider.requests) == 1


# ---------- tool calling ----------

LOOKUP = ToolSpec(
    "lookup", "Find a thing", {"type": "object", "properties": {"q": {"type": "string"}}}
)


def call(name: str = "lookup", **args: Any) -> ToolCall:
    return ToolCall(id=f"id-{name}", name=name, arguments=args)


def test_tool_loop_runs_our_handler_and_feeds_the_result_back() -> None:
    seen: list[dict[str, Any]] = []

    def handler(args: dict[str, Any]) -> Any:
        seen.append(args)
        return {"found": args["q"].upper()}

    h = Harness(
        FakeProvider([reply("", tool_calls=[call(q="auth")], tokens=(5, 1)), reply("Done.")])
    )
    out = h.service.run_tools(user_request(), [Tool(LOOKUP, handler)], CTX)

    assert out.result.text == "Done." and out.steps == 2
    assert seen == [{"q": "auth"}]
    tool_msg = h.provider.requests[1].messages[-1]
    assert tool_msg.role == "tool" and '"AUTH"' in tool_msg.content
    assert (tool_msg.tool_call_id, tool_msg.tool_name) == ("id-lookup", "lookup")
    assert out.usage == Usage(15, 6)
    assert h.recorder.entries[0].operation == "tools"


def test_unknown_tool_names_are_never_executed() -> None:
    h = Harness(FakeProvider([reply("", tool_calls=[call("rm_rf", path="/")]), reply("ok")]))
    h.service.run_tools(user_request(), [Tool(LOOKUP, lambda a: "x")], CTX)
    assert "unknown tool" in h.provider.requests[1].messages[-1].content


def test_failing_tool_reports_a_generic_error_without_details() -> None:
    def boom(args: dict[str, Any]) -> Any:
        raise RuntimeError("secret internal detail /srv/app.py")

    h = Harness(FakeProvider([reply("", tool_calls=[call(q="x")]), reply("ok")]))
    h.service.run_tools(user_request(), [Tool(LOOKUP, boom)], CTX)
    content = h.provider.requests[1].messages[-1].content
    assert "the tool failed" in content and "secret" not in content


def test_huge_tool_output_is_truncated() -> None:
    h = Harness(FakeProvider([reply("", tool_calls=[call(q="x")]), reply("ok")]))
    h.service.run_tools(user_request(), [Tool(LOOKUP, lambda a: "x" * 100_000)], CTX)
    assert len(h.provider.requests[1].messages[-1].content) < 21_000


def test_tools_are_switched_off_on_the_last_step() -> None:
    h = Harness(
        FakeProvider([reply("", tool_calls=[call(q="a")]), reply("final answer")])
    )
    out = h.service.run_tools(user_request(), [Tool(LOOKUP, lambda a: "r")], CTX, max_steps=2)
    assert out.result.text == "final answer"
    assert h.provider.requests[0].tools and not h.provider.requests[1].tools


def test_tool_loop_is_bounded_even_if_the_model_keeps_asking() -> None:
    script = [reply("", tool_calls=[call(q=str(i))]) for i in range(3)]
    h = Harness(FakeProvider(script))
    with pytest.raises(LLMToolLoopExceeded):
        h.service.run_tools(user_request(), [Tool(LOOKUP, lambda a: "r")], CTX, max_steps=3)
    assert len(h.provider.requests) == 3
    assert h.recorder.entries[0].error_code == "tool_loop"


# ---------- embeddings ----------


def test_embeddings_are_batched_and_ordered() -> None:
    emb = FakeProvider()
    h = Harness(FakeProvider(), embedding=emb)
    texts = [f"chunk {i}" for i in range(EMBED_BATCH_SIZE + 5)]
    out = h.service.embed(texts, "document", CTX)

    assert [len(b) for b in emb.embed_batches] == [EMBED_BATCH_SIZE, 5]
    assert len(out.vectors) == len(texts)
    assert out.usage.input_tokens == len(texts)
    assert h.recorder.entries[0].operation == "embed"


def test_embedding_count_mismatch_is_an_error() -> None:
    emb = FakeProvider()
    emb.embed_count_off_by = 1
    h = Harness(FakeProvider(), embedding=emb)
    with pytest.raises(LLMInvalidOutput):
        h.service.embed(["a", "b"], "query", CTX)


def test_embeddings_retry_transient_failures() -> None:
    emb = FakeProvider()
    emb.embed_error = LLMUnavailable("down")
    h = Harness(FakeProvider(), embedding=emb)
    with pytest.raises(LLMUnavailable):
        h.service.embed(["a"], "query", CTX)
    assert h.recorder.entries[0].calls == 3


def test_embed_without_an_embedding_provider() -> None:
    h = Harness(FakeProvider())
    with pytest.raises(LLMNotSupported):
        h.service.embed(["a"], "query", CTX)
