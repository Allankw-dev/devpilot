"""Question answering over retrieved code.

How it stays honest:
- The model sees only numbered sources (pieces of code the search found), never the whole repo.
- It must cite them as [1], [2]... Citations are checked here: a number that doesn't match a real
  source is never presented as one, so the model can't point to a file that wasn't provided.
- All repository text is wrapped as untrusted data (see app.services.llm.prompts).
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.services.indexing.retrieval import Hit
from app.services.llm import (
    UNTRUSTED_CONTENT_NOTICE,
    CallContext,
    GenerationRequest,
    LLMService,
    Message,
    Usage,
    untrusted,
)

MAX_ANSWER_CHARS = 20_000
_CITATION = re.compile(r"\[(\d{1,3})\]")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)  # code like items[1] is not a citation

SYSTEM_PROMPT = (
    "You are DevPilot, a careful assistant that answers questions about a software repository "
    "using ONLY the numbered sources you are given.\n\n"
    "Rules:\n"
    "- Base every statement on the sources. Never invent files, functions or behaviour, and do not "
    "claim to know code you were not shown.\n"
    "- Cite sources inline by number, like [1] or [2][3], directly after the claim they support.\n"
    "- If the sources do not contain enough to answer, say so plainly, describe what is missing in "
    'missing_context, and set confidence to "low". A partial answer with clear limits is better '
    "than a guess.\n"
    "- Name files and functions where that helps. Keep it concise: short paragraphs, bullet lists "
    "where useful, and fenced code blocks only for brief excerpts copied from the sources.\n"
    "- Sources marked documentation (README, docs) show what the documentation CLAIMS, not what "
    "the code does. When a statement rests only on documentation, say so (for example "
    '"according to the README") and do not use high confidence unless source code backs the '
    "main claims.\n"
    "- If a file list is given, it only shows which files exist. It is not their contents, so do "
    "not describe what an unseen file does beyond what its name suggests, and say so if you do.\n"
    '- confidence: "high" if the sources directly answer the question, "medium" if they answer '
    'part of it, "low" if you are mostly inferring or the sources lack what is needed.\n\n'
    + UNTRUSTED_CONTENT_NOTICE
)


class AnswerDraft(BaseModel):
    """What the model must return."""

    answer: str = Field(
        description="The answer in Markdown, with inline citations like [1] to the sources."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="How well the sources support the answer."
    )
    missing_context: str = Field(
        default="",
        description="What the sources lack to answer fully. Empty if nothing is missing.",
    )


@dataclass(frozen=True)
class Source:
    n: int
    hit: Hit


@dataclass(frozen=True)
class Answer:
    text: str
    confidence: str
    missing_context: str
    citations: list[Source]  # only sources the answer actually cites, in order of first use
    sources_considered: int
    model: str
    usage: Usage


def select_sources(hits: list[Hit], max_chars: int) -> list[Source]:
    """Number the hits best-first and stop when the context budget is used up. At least one
    is always kept, so a long best match can't leave the model with nothing."""
    chosen: list[Source] = []
    used = 0
    for hit in hits:
        if chosen and used + len(hit.content) > max_chars:
            break
        chosen.append(Source(len(chosen) + 1, hit))
        used += len(hit.content)
    return chosen


DOC_LANGUAGES = frozenset({"markdown", "text"})


def source_kind(hit: Hit) -> str:
    return "documentation" if hit.language in DOC_LANGUAGES else "code"


def render_user_message(question: str, sources: list[Source], files: list[str]) -> str:
    parts: list[str] = []
    if files:
        parts.append(untrusted("file list", "\n".join(files)))
    for s in sources:
        h = s.hit
        label = (
            f"source {s.n} - {source_kind(h)} - {h.repository} {h.path} "
            f"lines {h.start_line}-{h.end_line}"
        )
        parts.append(untrusted(label, h.content, max_chars=6000))
    return "Sources:\n\n" + "\n\n".join(parts) + f"\n\nQuestion: {question}"


def finalize_citations(answer: str, sources: list[Source]) -> tuple[str, list[Source]]:
    """Check the model's citations and tidy them up.

    - A number that matches no provided source is removed: the model must not be able to point
      at something it wasn't given.
    - Real citations are renumbered 1, 2, 3... in order of first use, so the answer reads
      cleanly whatever rank the search gave each piece of code.
    - Code like `items[1]` (inline or fenced) is left alone and never counts as a citation.
    Returns the rewritten text and the cited sources with their new numbers.
    """
    by_number = {s.n: s for s in sources}
    order: dict[int, int] = {}  # old number -> new number

    def rewrite(segment: str) -> str:
        def swap(match: re.Match[str]) -> str:
            old = int(match.group(2))
            if old not in by_number:
                return ""  # an invented citation
            order.setdefault(old, len(order) + 1)
            return f"{match.group(1)}[{order[old]}]"

        return re.sub(r"( ?)\[(\d{1,3})\]", swap, segment)

    parts = re.split(f"({_CODE.pattern})", answer, flags=re.DOTALL)
    text = "".join(p if i % 2 else rewrite(p) for i, p in enumerate(parts))
    cited = [Source(new, by_number[old].hit) for old, new in order.items()]
    return text, cited


def answer_question(
    llm: LLMService,
    question: str,
    hits: list[Hit],
    files: list[str],
    ctx: CallContext,
    *,
    max_context_chars: int,
    max_output_tokens: int,
) -> Answer:
    sources = select_sources(hits, max_context_chars)
    request = GenerationRequest(
        system=SYSTEM_PROMPT,
        messages=[Message(role="user", content=render_user_message(question, sources, files))],
        max_output_tokens=max_output_tokens,
    )
    result = llm.generate_structured(request, AnswerDraft, ctx)
    draft = result.value
    text, citations = finalize_citations(draft.answer.strip()[:MAX_ANSWER_CHARS], sources)
    return Answer(
        text=text,
        confidence=draft.confidence,
        missing_context=draft.missing_context.strip()[:1000],
        citations=citations,
        sources_considered=len(sources),
        model=result.model,
        usage=result.usage,
    )
