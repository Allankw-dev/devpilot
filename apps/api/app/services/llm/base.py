"""Provider-neutral types and the `LLMProvider` interface.

Only the adapters in `providers/` import a provider SDK. Business code builds a
`GenerationRequest`, calls `LLMService`, and never sees a vendor type.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "tool"]
ToolChoice = Literal["auto", "none", "required"]
FinishReason = Literal["stop", "length", "tool_calls", "blocked", "other"]
EmbeddingTask = Literal["document", "query"]


@dataclass(frozen=True)
class ToolSpec:
    """A function the model may ask us to run. `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]  # chosen by the model: untrusted, validate before use


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()  # assistant turns that call tools
    tool_call_id: str | None = None  # role == "tool": which call this answers
    tool_name: str | None = None
    # The provider's own form of an assistant turn. Echoed back untouched on the next call
    # because some providers require parts of it (e.g. reasoning signatures) to continue.
    provider_data: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0  # includes hidden reasoning tokens, which are billed as output

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens
        )


@dataclass(frozen=True)
class GenerationRequest:
    messages: Sequence[Message]
    system: str | None = None
    tools: Sequence[ToolSpec] = ()
    tool_choice: ToolChoice = "auto"
    max_output_tokens: int | None = None
    temperature: float | None = None  # None = the provider's recommended default
    response_schema: dict[str, Any] | None = None  # JSON Schema: ask for a JSON reply


@dataclass(frozen=True)
class GenerationResult:
    text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    model: str
    finish_reason: FinishReason
    assistant_message: Message  # append this to the history before sending tool results


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    usage: Usage  # providers that don't report embedding tokens give zeros
    model: str


class LLMProvider(ABC):
    """One vendor behind one interface. Adapters raise only `LLMError` subclasses."""

    name: str
    model: str

    @abstractmethod
    def generate(self, request: GenerationRequest, *, timeout: float) -> GenerationResult: ...

    @abstractmethod
    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult: ...
