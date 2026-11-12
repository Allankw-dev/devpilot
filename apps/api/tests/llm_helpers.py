"""A scripted fake provider so the AI layer can be tested without any network or API key."""

import math
import re
import zlib
from collections.abc import Sequence
from typing import Any

from app.services.llm.base import (
    EmbeddingResult,
    EmbeddingTask,
    FinishReason,
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    Message,
    ToolCall,
    Usage,
)
from app.services.llm.service import LLMService
from app.services.llm.usage import UsageEntry


def reply(
    text: str = "OK",
    *,
    tokens: tuple[int, int] = (10, 5),
    tool_calls: Sequence[ToolCall] = (),
    finish: FinishReason | None = None,
) -> GenerationResult:
    calls = tuple(tool_calls)
    return GenerationResult(
        text=text,
        tool_calls=calls,
        usage=Usage(*tokens),
        model="fake-model-v1",
        finish_reason=finish or ("tool_calls" if calls else "stop"),
        assistant_message=Message(role="assistant", content=text, tool_calls=calls),
    )


class FakeProvider(LLMProvider):
    name = "fake"
    model = "fake-model"

    def __init__(
        self, script: Sequence[GenerationResult | Exception] = (), dims: int = 3
    ) -> None:
        self.script = list(script)
        self.requests: list[GenerationRequest] = []
        self.embed_batches: list[list[str]] = []
        self.dims = dims
        self.embed_error: Exception | None = None
        self.embed_count_off_by: int = 0

    def generate(self, request: GenerationRequest, *, timeout: float) -> GenerationResult:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult:
        if self.embed_error:
            raise self.embed_error
        self.embed_batches.append(list(texts))
        n = len(texts) - self.embed_count_off_by
        return EmbeddingResult(
            vectors=[[1.0] * self.dims for _ in range(n)], usage=Usage(len(texts), 0), model="emb"
        )


class ListRecorder:
    def __init__(self) -> None:
        self.entries: list[UsageEntry] = []

    def record(self, entry: UsageEntry) -> None:
        self.entries.append(entry)


class Harness:
    def __init__(self, provider: FakeProvider, embedding: LLMProvider | None = None) -> None:
        self.provider = provider
        self.recorder = ListRecorder()
        self.sleeps: list[float] = []
        self.service = LLMService(
            provider,
            embedding=embedding,
            recorder=self.recorder,
            max_attempts=3,
            max_output_tokens=777,
            sleep=self.sleeps.append,
            jitter=lambda: 0.0,
        )


def user_request(text: str = "hi", **kw: Any) -> GenerationRequest:
    return GenerationRequest(messages=[Message(role="user", content=text)], **kw)


class FakeEmbedder(FakeProvider):
    """Embeds text as a hashed bag of words, so texts that share words really are closer.
    Deterministic, 768 dimensions (the database column size)."""

    model = "fake-embed-v1"

    def __init__(self, dims: int = 768) -> None:
        super().__init__(dims=dims)
        self.texts: list[str] = []  # everything ever sent for embedding
        self.calls = 0
        self.fail_with: Exception | None = None
        self.fail_after = 0  # calls that succeed before fail_with starts raising
        self.fail_first = 0  # alternatively: the first N calls raise, then it recovers

    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult:
        self.calls += 1
        if self.fail_with is not None and (
            self.calls <= self.fail_first or (not self.fail_first and self.calls > self.fail_after)
        ):
            raise self.fail_with
        self.embed_batches.append(list(texts))
        self.texts.extend(texts)
        return EmbeddingResult(
            vectors=[self.vector(t) for t in texts], usage=Usage(len(texts), 0), model=self.model
        )

    def vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in re.findall(r"[a-z0-9_]+", text.lower()):
            vec[zlib.crc32(token.encode()) % self.dims] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
