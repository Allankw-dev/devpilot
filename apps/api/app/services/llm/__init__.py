"""AI layer: provider-neutral types, one service, adapters in `providers/`."""

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
from app.services.llm.errors import LLMError, LLMNotConfigured
from app.services.llm.prompts import UNTRUSTED_CONTENT_NOTICE, untrusted
from app.services.llm.service import LLMService, StructuredResult, Tool, ToolRunResult
from app.services.llm.usage import CallContext

__all__ = [
    "UNTRUSTED_CONTENT_NOTICE",
    "CallContext",
    "EmbeddingResult",
    "EmbeddingTask",
    "GenerationRequest",
    "GenerationResult",
    "LLMError",
    "LLMNotConfigured",
    "LLMProvider",
    "LLMService",
    "Message",
    "StructuredResult",
    "Tool",
    "ToolCall",
    "ToolRunResult",
    "ToolSpec",
    "Usage",
    "untrusted",
]
