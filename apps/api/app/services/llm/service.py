"""The one entry point business code uses for AI.

Adds what every feature needs on top of a bare provider call: retries with backoff for
transient failures, a timeout per call, JSON output validated against a Pydantic model,
a bounded tool-calling loop, and usage recording. Provider-specific code stays in `providers/`.
"""

import json
import logging
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.llm.base import (
    EmbeddingResult,
    EmbeddingTask,
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from app.services.llm.errors import (
    RETRYABLE,
    LLMError,
    LLMInvalidOutput,
    LLMNotSupported,
    LLMRateLimited,
    LLMToolLoopExceeded,
)
from app.services.llm.usage import CallContext, NullUsageRecorder, UsageEntry, UsageRecorder

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 20.0
MAX_TOOL_RESULT_CHARS = 20_000
EMBED_BATCH_SIZE = 64

ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    """A tool the model may call. The handler is OUR code; the model only supplies arguments.
    Arguments are untrusted input, so handlers must validate them and must only do
    read-only, bounded work."""

    spec: ToolSpec
    handler: ToolHandler


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    usage: Usage
    model: str


@dataclass(frozen=True)
class ToolRunResult:
    result: GenerationResult  # the final answer
    steps: int  # model calls it took
    usage: Usage  # summed over all steps


class _Tally:
    """Counts what one logical operation cost, across retries and follow-up calls."""

    def __init__(self) -> None:
        self.usage = Usage()
        self.calls = 0
        self.model = ""


class LLMService:
    def __init__(
        self,
        generation: LLMProvider,
        *,
        embedding: LLMProvider | None = None,
        recorder: UsageRecorder | None = None,
        timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        max_output_tokens: int = 4096,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._gen = generation
        self._emb = embedding
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()
        self._timeout = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._max_output_tokens = max_output_tokens
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter

    @property
    def provider_name(self) -> str:
        return self._gen.name

    @property
    def embedding_model(self) -> str | None:
        """Name of the model that makes embeddings, or None if embeddings aren't set up."""
        return self._emb.model if self._emb else None

    # ---------- public API ----------

    def generate(self, request: GenerationRequest, ctx: CallContext) -> GenerationResult:
        def run(tally: _Tally) -> GenerationResult:
            return self._call(request, tally)

        return self._operation("generate", self._gen, ctx, run)

    def generate_structured[T: BaseModel](
        self, request: GenerationRequest, schema: type[T], ctx: CallContext
    ) -> StructuredResult[T]:
        """Ask for JSON matching `schema`. A reply that doesn't validate gets one repair
        attempt; after that it is an error, never a half-parsed value."""

        def run(tally: _Tally) -> StructuredResult[T]:
            req = replace(request, response_schema=schema.model_json_schema())
            result = self._call(req, tally)
            try:
                return StructuredResult(_parse(result.text, schema), tally.usage, result.model)
            except _BadOutput as bad:
                if result.finish_reason == "length":
                    raise LLMInvalidOutput(
                        "The reply was cut off before the JSON was complete. "
                        "Raise the output token limit or ask for less."
                    ) from None
                repair = [
                    *request.messages,
                    Message(role="assistant", content=result.text),
                    Message(
                        role="user",
                        content=(
                            "That reply was not valid. Problem: "
                            f"{bad.reason}\nReply again with only JSON that matches the schema."
                        ),
                    ),
                ]
                second = self._call(replace(req, messages=repair), tally)
                try:
                    return StructuredResult(_parse(second.text, schema), tally.usage, second.model)
                except _BadOutput as bad_again:
                    raise LLMInvalidOutput(
                        f"The model did not return valid JSON: {bad_again.reason}"
                    ) from None

        return self._operation("structured", self._gen, ctx, run)

    def run_tools(
        self,
        request: GenerationRequest,
        tools: Sequence[Tool],
        ctx: CallContext,
        *,
        max_steps: int = 6,
    ) -> ToolRunResult:
        """Let the model call our tools until it answers. Bounded by `max_steps`; on the last
        step tools are switched off so it has to answer with what it has."""
        handlers: Mapping[str, ToolHandler] = {t.spec.name: t.handler for t in tools}
        specs = tuple(t.spec for t in tools)

        def run(tally: _Tally) -> ToolRunResult:
            messages = list(request.messages)
            for step in range(1, max_steps + 1):
                last = step == max_steps
                req = replace(
                    request,
                    messages=messages,
                    tools=() if last else specs,
                    tool_choice="auto",
                )
                result = self._call(req, tally)
                if not result.tool_calls:
                    return ToolRunResult(result, step, tally.usage)
                if last:
                    break
                messages.append(result.assistant_message)
                for call in result.tool_calls:
                    messages.append(
                        Message(
                            role="tool",
                            content=_run_tool(handlers, call),
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )
            raise LLMToolLoopExceeded(f"The model was still calling tools after {max_steps} steps")

        return self._operation("tools", self._gen, ctx, run)

    def embed(
        self, texts: Sequence[str], task: EmbeddingTask, ctx: CallContext
    ) -> EmbeddingResult:
        provider = self._emb
        if provider is None:
            raise LLMNotSupported("No embedding provider is configured")

        def run(tally: _Tally) -> EmbeddingResult:
            vectors: list[list[float]] = []
            usage = Usage()
            model = provider.model
            for start in range(0, len(texts), EMBED_BATCH_SIZE):
                batch = texts[start : start + EMBED_BATCH_SIZE]

                def embed_batch(batch: Sequence[str] = batch) -> EmbeddingResult:
                    return provider.embed(batch, task=task, timeout=self._timeout)

                part = self._with_retries(tally, embed_batch)
                if len(part.vectors) != len(batch):
                    raise LLMInvalidOutput("The provider returned the wrong number of embeddings")
                vectors.extend(part.vectors)
                usage += part.usage
                model = part.model
            tally.usage += usage
            tally.model = model
            return EmbeddingResult(vectors, usage, model)

        return self._operation("embed", provider, ctx, run)

    # ---------- internals ----------

    def _call(self, request: GenerationRequest, tally: _Tally) -> GenerationResult:
        if request.max_output_tokens is None:
            request = replace(request, max_output_tokens=self._max_output_tokens)
        req = request
        result = self._with_retries(
            tally, lambda: self._gen.generate(req, timeout=self._timeout)
        )
        tally.usage += result.usage
        tally.model = result.model
        return result

    def _with_retries[R](self, tally: _Tally, call: Callable[[], R]) -> R:
        for attempt in range(self._max_attempts):
            tally.calls += 1
            try:
                return call()
            except RETRYABLE as exc:
                if attempt == self._max_attempts - 1:
                    raise
                delay = self._backoff(attempt, exc)
                logger.warning(
                    "AI call failed (%s), retrying in %.1fs", getattr(exc, "code", "error"), delay
                )
                self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _backoff(self, attempt: int, exc: LLMError) -> float:
        if isinstance(exc, LLMRateLimited) and exc.retry_after is not None:
            return min(MAX_BACKOFF_SECONDS, max(0.0, exc.retry_after))
        base = min(MAX_BACKOFF_SECONDS, float(2**attempt))
        return base + base * 0.25 * self._jitter()

    def _operation[R](
        self, operation: str, provider: LLMProvider, ctx: CallContext, run: Callable[[_Tally], R]
    ) -> R:
        tally = _Tally()
        started = self._clock()
        status, error_code = "ok", None
        try:
            return run(tally)
        except LLMError as exc:
            status, error_code = "error", exc.code
            raise
        except Exception:
            status, error_code = "error", "unexpected"
            raise
        finally:
            self._recorder.record(
                UsageEntry(
                    ctx=ctx,
                    provider=provider.name,
                    model=tally.model or provider.model,
                    operation=operation,
                    status=status,
                    error_code=error_code,
                    input_tokens=tally.usage.input_tokens,
                    output_tokens=tally.usage.output_tokens,
                    calls=max(1, tally.calls),
                    latency_ms=int((self._clock() - started) * 1000),
                )
            )


# ---------- helpers ----------


class _BadOutput(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _strip_fence(text: str) -> str:
    """Some models wrap JSON in a ```json fence even when told not to."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()


def _parse[T: BaseModel](text: str, schema: type[T]) -> T:
    try:
        return schema.model_validate_json(_strip_fence(text))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise _BadOutput(problems[:500]) from None
    except ValueError:
        raise _BadOutput("the reply was not valid JSON") from None


def _run_tool(handlers: Mapping[str, ToolHandler], call: ToolCall) -> str:
    """Run one tool call and return text for the model. Unknown tools and failures are
    reported back to the model as errors; nothing the model names is ever looked up outside
    the tools we registered, and no exception details reach it."""
    handler = handlers.get(call.name)
    if handler is None:
        return json.dumps({"error": f"unknown tool '{call.name[:60]}'"})
    try:
        output = handler(call.arguments)
        text = output if isinstance(output, str) else json.dumps(output, default=str)
    except Exception:
        logger.exception("Tool %s failed", call.name)
        return json.dumps({"error": "the tool failed"})
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n[truncated]"
    return text
