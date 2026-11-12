"""Google Gemini through the official `google-genai` SDK."""

import logging
import math
from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

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
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)

logger = logging.getLogger(__name__)

_BLOCKED = {
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
}
_TASK = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}

# gemini-embedding-2 and newer take no task_type: the task goes into the text instead
# (see https://ai.google.dev/gemini-api/docs/embeddings). The code-retrieval query form fits a
# natural-language question searched against source code.
_PREFIXED = {
    "document": "title: none | text: {text}",
    "query": "task: code retrieval | query: {text}",
}


def _uses_task_type(model: str) -> bool:
    """Only the original embedding models take task_type; newer ones want a text prefix."""
    name = model.removeprefix("models/")
    return "embedding-001" in name or name.startswith("text-embedding")
_MODE = {"auto": "AUTO", "none": "NONE", "required": "ANY"}


def translate_error(exc: Exception) -> LLMError:
    """Map whatever the SDK (or its HTTP layer) raised onto our error types."""
    if isinstance(exc, genai_errors.APIError):
        code = int(exc.code or 0)
        message = str(getattr(exc, "message", "") or "")
        if code == 429:
            return LLMRateLimited("Gemini rate limit reached")
        if code in (401, 403) or (code == 400 and "api key" in message.lower()):
            return LLMAuthError("Gemini rejected the API key or the key can't use this model")
        if code in (408, 504):
            return LLMTimeout("Gemini timed out")
        if code >= 500:
            return LLMUnavailable(f"Gemini returned {code}")
        return LLMBadRequest(f"Gemini rejected the request ({code})")
    names = {c.__name__ for c in type(exc).__mro__}
    if isinstance(exc, TimeoutError) or any("Timeout" in n for n in names):
        return LLMTimeout("The request to Gemini timed out")
    if isinstance(exc, OSError) or any(
        n in names for n in ("ConnectError", "NetworkError", "TransportError", "ConnectionError")
    ):
        return LLMUnavailable("Could not reach Gemini")
    return LLMUnavailable("Unexpected error calling Gemini")


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self._embedding_model = embedding_model
        self._dims = embedding_dimensions
        self._client: Any = client or genai.Client(api_key=api_key)

    # ---------- generation ----------

    def generate(self, request: GenerationRequest, *, timeout: float) -> GenerationResult:
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
            # We run tools ourselves so every call is bounded, recorded and validated.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if request.response_schema is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = request.response_schema
        if request.tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.parameters,
                        )
                        for t in request.tools
                    ]
                )
            ]
            config.tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=_MODE[request.tool_choice]
                )
            )
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=_to_contents(request.messages), config=config
            )
        except Exception as exc:
            raise translate_error(exc) from exc
        return self._parse(response)

    def _parse(self, response: Any) -> GenerationResult:
        candidates = response.candidates or []
        if not candidates or candidates[0].content is None:
            feedback = getattr(response, "prompt_feedback", None)
            reason = getattr(feedback, "block_reason", None)
            if reason:
                raise LLMBlocked("Gemini declined the request")
            raise LLMInvalidOutput("Gemini returned no content")
        candidate = candidates[0]
        parts = candidate.content.parts or []

        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = tuple(
            ToolCall(
                id=p.function_call.id or f"call_{i}",
                name=p.function_call.name or "",
                arguments=dict(p.function_call.args or {}),
            )
            for i, p in enumerate(x for x in parts if x.function_call)
        )

        raw = getattr(candidate.finish_reason, "name", str(candidate.finish_reason or "STOP"))
        finish: FinishReason
        if calls:
            finish = "tool_calls"
        elif raw == "STOP":
            finish = "stop"
        elif raw == "MAX_TOKENS":
            finish = "length"
        elif raw in _BLOCKED:
            finish = "blocked"
        else:
            finish = "other"
        if finish == "blocked" and not text:
            raise LLMBlocked("Gemini declined to answer")

        meta = response.usage_metadata
        usage = Usage()
        if meta:
            usage = Usage(
                input_tokens=int(
                    (meta.prompt_token_count or 0) + (meta.tool_use_prompt_token_count or 0)
                ),
                output_tokens=int(
                    (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
                ),
            )
        return GenerationResult(
            text=text,
            tool_calls=calls,
            usage=usage,
            model=str(response.model_version or self.model),
            finish_reason=finish,
            assistant_message=Message(
                role="assistant", content=text, tool_calls=calls, provider_data=candidate.content
            ),
        )

    # ---------- embeddings ----------

    def embed(
        self, texts: Sequence[str], *, task: EmbeddingTask, timeout: float
    ) -> EmbeddingResult:
        if not self._embedding_model:
            raise LLMBadRequest("No Gemini embedding model is configured")
        legacy = _uses_task_type(self._embedding_model)
        config = types.EmbedContentConfig(
            task_type=_TASK[task] if legacy else None,
            output_dimensionality=self._dims,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )
        # One Content per text. A flat list of strings would be merged into ONE vector by
        # gemini-embedding-2 (it embeds all parts of a single input together).
        contents = [
            types.Content(parts=[types.Part(text=t if legacy else _PREFIXED[task].format(text=t))])
            for t in texts
        ]
        try:
            response = self._client.models.embed_content(
                model=self._embedding_model, contents=contents, config=config
            )
        except Exception as exc:
            raise translate_error(exc) from exc
        vectors = [list(e.values or []) for e in (response.embeddings or [])]
        if self._dims:
            # Gemini only returns unit-length vectors at full size. Shortened ones must be
            # normalised or cosine similarity gets skewed.
            vectors = [_normalise(v) for v in vectors]
        return EmbeddingResult(vectors=vectors, usage=Usage(), model=self._embedding_model)


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def _to_contents(messages: Sequence[Message]) -> list[types.Content]:
    contents: list[types.Content] = []
    for m in messages:
        if m.role == "tool":
            part = types.Part.from_function_response(
                name=m.tool_name or "", response={"result": m.content}
            )
            last = contents[-1] if contents else None
            # Results of parallel tool calls must travel in one turn.
            if last is not None and last.role == "user" and last.parts and all(
                p.function_response for p in last.parts
            ):
                last.parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
        elif m.role == "assistant":
            if isinstance(m.provider_data, types.Content):
                contents.append(m.provider_data)
                continue
            parts: list[types.Part] = []
            if m.content:
                parts.append(types.Part(text=m.content))
            parts.extend(
                types.Part.from_function_call(name=c.name, args=c.arguments) for c in m.tool_calls
            )
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
        else:
            contents.append(types.Content(role="user", parts=[types.Part(text=m.content)]))
    return contents
