"""OpenAI-compatible provider adapter for Groq and OpenRouter."""

import json
from collections.abc import Sequence
from typing import Any

import httpx

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
    LLMInvalidOutput,
    LLMNotSupported,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Allankw-dev/devpilot",
            },
            timeout=None,
        )

    def generate(self, request: GenerationRequest, *, timeout: float) -> GenerationResult:
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for message in request.messages:
            if message.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
            elif message.role == "assistant":
                native = message.provider_data if isinstance(message.provider_data, dict) else None
                item: dict[str, Any] = {"role": "assistant", "content": message.content}
                if native:
                    item.update(native)
                elif message.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ]
                messages.append(item)
            else:
                messages.append({"role": "user", "content": message.content})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens or 4096,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "devpilot_result",
                    "schema": request.response_schema,
                    "strict": True,
                },
            }
        elif request.tools and request.tool_choice != "none":
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = request.tool_choice

        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"The request to {self.name} timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Could not reach {self.name}") from exc

        if response.status_code == 429:
            wait = response.headers.get("retry-after")
            try:
                retry_after = float(wait) if wait else None
            except ValueError:
                retry_after = None
            raise LLMRateLimited(f"{self.name} rate limit reached", retry_after)
        if response.status_code in (401, 403):
            raise LLMAuthError(f"{self.name} rejected the API key")
        if response.status_code in (408, 504):
            raise LLMTimeout(f"The request to {self.name} timed out")
        if response.status_code >= 500:
            raise LLMUnavailable(f"{self.name} returned {response.status_code}")
        if response.status_code >= 400:
            raise LLMBadRequest(f"{self.name} rejected the request ({response.status_code})")

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise LLMInvalidOutput(f"{self.name} returned an invalid response") from exc

        text = str(message.get("content") or "")
        calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise LLMBadRequest(f"{self.name} returned invalid tool arguments") from exc
            calls.append(
                ToolCall(
                    id=str(call.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=dict(arguments),
                )
            )

        finish_reason: FinishReason
        reason = str(choice.get("finish_reason") or "")
        if calls:
            finish_reason = "tool_calls"
        elif reason in ("stop", "end_turn"):
            finish_reason = "stop"
        elif reason == "length":
            finish_reason = "length"
        else:
            finish_reason = "other"
        usage = data.get("usage") or {}
        result_usage = Usage(
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
        native = {"tool_calls": message["tool_calls"]} if message.get("tool_calls") else None
        return GenerationResult(
            text=text,
            tool_calls=tuple(calls),
            usage=result_usage,
            model=str(data.get("model") or self.model),
            finish_reason=finish_reason,
            assistant_message=Message(
                role="assistant",
                content=text,
                tool_calls=tuple(calls),
                provider_data=native,
            ),
        )

    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult:
        raise LLMNotSupported(f"{self.name} is generation-only")
