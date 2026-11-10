"""Anthropic (optional). Chosen with LLM_PROVIDER=anthropic; needs its own API key.

Anthropic has no embeddings API, so embeddings stay on another provider.
"""

import json
from collections.abc import Sequence
from typing import Any, cast

import anthropic

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
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMBlocked,
    LLMError,
    LLMInvalidOutput,
    LLMNotSupported,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)

STRUCTURED_TOOL = "emit_result"  # structured output is a forced call to this pseudo-tool
_TOOL_CHOICE = {"auto": {"type": "auto"}, "required": {"type": "any"}}


def translate_error(exc: Exception) -> LLMError:
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMTimeout("The request to Anthropic timed out")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMUnavailable("Could not reach Anthropic")
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        if status == 429:
            header = exc.response.headers.get("retry-after", "")
            try:
                wait: float | None = float(header)
            except ValueError:
                wait = None
            return LLMRateLimited("Anthropic rate limit reached", wait)
        if status in (401, 403):
            return LLMAuthError("Anthropic rejected the API key")
        if status in (408, 504):
            return LLMTimeout("Anthropic timed out")
        if status >= 500:  # includes 529 "overloaded"
            return LLMUnavailable(f"Anthropic returned {status}")
        return LLMBadRequest(f"Anthropic rejected the request ({status})")
    return LLMUnavailable("Unexpected error calling Anthropic")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str, client: Any = None) -> None:
        self.model = model
        # max_retries=0: LLMService owns retrying, so attempts aren't multiplied.
        self._client: Any = client or anthropic.Anthropic(api_key=api_key, max_retries=0)

    def generate(self, request: GenerationRequest, *, timeout: float) -> GenerationResult:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens or 4096,
            "messages": _to_messages(request.messages),
            "timeout": timeout,
        }
        if request.system:
            params["system"] = request.system
        if request.temperature is not None:
            params["temperature"] = request.temperature

        structured = request.response_schema is not None
        if structured:
            params["tools"] = [
                {
                    "name": STRUCTURED_TOOL,
                    "description": "Return the final answer in this exact structure.",
                    "input_schema": request.response_schema,
                }
            ]
            params["tool_choice"] = {"type": "tool", "name": STRUCTURED_TOOL}
        elif request.tools and request.tool_choice != "none":
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
            params["tool_choice"] = _TOOL_CHOICE[request.tool_choice]

        try:
            response = self._client.messages.create(**params)
        except Exception as exc:
            raise translate_error(exc) from exc
        return self._parse(response, structured)

    def _parse(self, response: Any, structured: bool) -> GenerationResult:
        blocks: list[Any] = list(response.content or [])
        text = "".join(b.text for b in blocks if b.type == "text")
        calls = tuple(
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in blocks
            if b.type == "tool_use" and b.name != STRUCTURED_TOOL
        )
        if structured:
            emitted = next((b for b in blocks if b.type == "tool_use"), None)
            if emitted is None:
                raise LLMInvalidOutput("The model did not return the requested structure")
            text = json.dumps(dict(emitted.input or {}))

        stop = response.stop_reason
        finish: FinishReason
        if stop == "refusal":
            raise LLMBlocked("Anthropic declined to answer")
        if calls:
            finish = "tool_calls"
        elif stop in ("end_turn", "stop_sequence", "tool_use"):  # tool_use = structured reply
            finish = "stop"
        elif stop == "max_tokens":
            finish = "length"
        else:
            finish = "other"

        usage = Usage(
            input_tokens=int(response.usage.input_tokens or 0),
            output_tokens=int(response.usage.output_tokens or 0),
        )
        native = [_block_to_param(b) for b in blocks]
        return GenerationResult(
            text=text,
            tool_calls=calls,
            usage=usage,
            model=str(getattr(response, "model", None) or self.model),
            finish_reason=finish,
            assistant_message=Message(
                role="assistant", content=text, tool_calls=calls, provider_data=native
            ),
        )

    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult:
        raise LLMNotSupported("Anthropic has no embeddings API; use another embedding provider")


def _block_to_param(block: Any) -> dict[str, Any]:
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)}
    if block.type == "text":
        return {"type": "text", "text": block.text}
    return cast(dict[str, Any], block.model_dump(exclude_none=True))


def _to_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            last = out[-1] if out else None
            if last and last["role"] == "user" and isinstance(last["content"], list) and all(
                b.get("type") == "tool_result" for b in last["content"]
            ):
                last["content"].append(block)  # parallel tool results share one turn
            else:
                out.append({"role": "user", "content": [block]})
        elif m.role == "assistant":
            if isinstance(m.provider_data, list):
                out.append({"role": "assistant", "content": m.provider_data})
            elif m.tool_calls:
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                content.extend(
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                    for c in m.tool_calls
                )
                out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": "assistant", "content": m.content or "(empty)"})
        else:
            out.append({"role": "user", "content": m.content})
    return out
