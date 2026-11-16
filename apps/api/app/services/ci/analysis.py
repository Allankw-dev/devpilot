"""The analysis itself: what the model is asked, and how its answer is checked.

The model only ever sees log excerpts (with credential-looking lines already withheld). Every
quote it offers as evidence is checked against the excerpt that was actually sent: a quote that
isn't there is dropped, and a "high confidence" answer with no verified quote is lowered.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import CI_CATEGORIES
from app.services.ci.logs import LogExcerpt
from app.services.llm import (
    UNTRUSTED_CONTENT_NOTICE,
    CallContext,
    GenerationRequest,
    LLMService,
    Message,
    Usage,
    untrusted,
)

Category = Literal[
    "test_failure",
    "build_error",
    "lint_or_types",
    "dependency",
    "configuration",
    "infrastructure",
    "flaky_or_timeout",
    "unknown",
]
Confidence = Literal["high", "medium", "low"]

TEXT_CHARS = 2500
NOTES_CHARS = 1400
QUOTE_MIN = 6
QUOTE_MAX = 300
MAX_EVIDENCE = 5

assert set(CI_CATEGORIES) == set(Category.__args__)  # type: ignore[attr-defined]

SYSTEM_PROMPT = (
    "You are DevPilot, a senior engineer working out why a CI run failed. You are given the "
    "failed jobs of one GitHub Actions run, each with the names of its failed steps and an "
    "excerpt of its log. Long logs are cut: [... N lines omitted ...] marks a gap, and lines "
    "marked as withheld were removed because they looked like credentials.\n\n"
    "What to do:\n"
    "- Say what failed and the most likely cause, using only what the logs show. Name the "
    "failing test, command, file or package when the log does.\n"
    "- category: test_failure (a test assertion or test runner failure), build_error (compile, "
    "bundle or packaging error), lint_or_types (linter, formatter or type checker), dependency "
    "(install or version resolution problems), configuration (workflow, environment variable "
    "or setup mistakes), infrastructure (runner, network, registry or service outages), "
    "flaky_or_timeout (timeouts or intermittent failures), unknown (the logs don't say).\n"
    "- Only use flaky_or_timeout or infrastructure when the log shows signs of it (a timeout, a "
    "connection error, a rate limit, a runner shutdown). You cannot see other runs, so never "
    "claim a test is flaky from one failure.\n"
    "- evidence: up to five short quotes (one line each) copied EXACTLY from the logs, with the "
    "name of the job they came from. Never invent or reword a quote.\n"
    "- suggested_fix: concrete next steps, with a short code or command snippet if it helps. If "
    "the cause is unclear, say what to check first instead of guessing.\n"
    "- confidence: high only when the log states the cause directly; low when you are guessing "
    "from partial logs.\n"
    "- You cannot run anything or see the repository's code. Do not claim to know what the "
    "source files contain.\n"
    "- not_assessed: anything you could not judge (leave empty if nothing).\n\n"
    + UNTRUSTED_CONTENT_NOTICE
)


class EvidenceDraft(BaseModel):
    job: str = Field(description="Name of the job the quote came from.")
    quote: str = Field(description="One line copied exactly from that job's log.")


class CiDraft(BaseModel):
    summary: str = Field(description="One to three sentences: what failed and why.")
    category: Category
    likely_cause: str
    suggested_fix: str = ""
    confidence: Confidence
    evidence: list[EvidenceDraft] = []
    not_assessed: str = ""


@dataclass
class JobInput:
    """One failed job as it goes to the model."""

    name: str
    conclusion: str
    failed_steps: list[str]
    excerpt: LogExcerpt | None  # None: no log could be read
    problem: str | None = None  # why there is no log


@dataclass
class CiResult:
    summary: str
    category: str
    confidence: str
    likely_cause: str
    suggested_fix: str
    evidence: list[dict[str, str]]
    notes: str
    model: str
    usage: Usage
    dropped_quotes: int = 0


# ---------- what the model sees ----------


def coverage_note(jobs: list[JobInput], jobs_total: int, listing_complete: bool = True) -> str:
    read = [j for j in jobs if j.excerpt is not None]
    parts = [f"Read the logs of {len(read)} of {jobs_total} failed jobs."]
    unread = [j for j in jobs if j.excerpt is None]
    if unread:
        parts.append(
            "No log for: "
            + ", ".join(f"{j.name} ({j.problem or 'unavailable'})" for j in unread)
            + "."
        )
    over = jobs_total - len(jobs)
    if over > 0:
        parts.append(f"{over} more failed {'job' if over == 1 else 'jobs'} over the limit.")
    cut = [j.name for j in read if j.excerpt and j.excerpt.truncated]
    if cut:
        parts.append("Long logs were shortened: " + ", ".join(cut) + ".")
    withheld = sum(j.excerpt.withheld_lines for j in read if j.excerpt)
    if withheld:
        parts.append(
            f"{withheld} {'line' if withheld == 1 else 'lines'} that looked like credentials "
            "were withheld from the AI."
        )
    if not listing_complete:
        parts.append("GitHub's job list was cut short.")
    return " ".join(parts)


def render_user_message(
    repository: str, workflow: str, branch: str, event: str, jobs: list[JobInput], note: str
) -> str:
    header = (
        f"Repository: {repository}\nWorkflow: {workflow}\nBranch: {branch}\nTriggered by: {event}"
    )
    parts = [untrusted("run details", header, max_chars=2000)]
    for j in jobs:
        if j.excerpt is None:
            continue
        steps = ", ".join(j.failed_steps) or "unknown"
        text = f"Job: {j.name}\nResult: {j.conclusion}\nFailed steps: {steps}\n\n{j.excerpt.text}"
        parts.append(untrusted(f"log of job {j.name}", text, max_chars=60_000))
    return note + "\n\n" + "\n\n".join(parts)


# ---------- checking what comes back ----------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verify_evidence(
    drafts: list[EvidenceDraft], jobs: list[JobInput]
) -> tuple[list[dict[str, str]], int]:
    """Keep only quotes that really appear in a log excerpt that was sent. Returns the kept
    quotes (labelled with the job they were really found in) and how many were dropped."""
    haystacks = {j.name: _norm(j.excerpt.text) for j in jobs if j.excerpt is not None}
    lowered = {name.lower(): name for name in haystacks}
    kept: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for d in drafts:
        quote = _norm(d.quote)
        if not (QUOTE_MIN <= len(quote) <= QUOTE_MAX):
            dropped += 1
            continue
        claimed = lowered.get(_norm(d.job).lower())
        found = claimed if claimed and quote in haystacks[claimed] else None
        if found is None:  # right quote, wrong job label: find where it really is
            found = next((name for name, text in haystacks.items() if quote in text), None)
        if found is None or (found, quote) in seen:
            dropped += 1
            continue
        seen.add((found, quote))
        kept.append({"job": found, "quote": quote})
        if len(kept) == MAX_EVIDENCE:
            break
    return kept, dropped


# ---------- the call ----------


def analyze_failure(
    llm: LLMService,
    *,
    repository: str,
    workflow: str,
    branch: str,
    event: str,
    jobs: list[JobInput],
    jobs_total: int,
    listing_complete: bool,
    ctx: CallContext,
    max_output_tokens: int,
) -> CiResult:
    """Ask the model why the run failed and return a checked answer. At least one job must
    have a log excerpt."""
    note = coverage_note(jobs, jobs_total, listing_complete)
    request = GenerationRequest(
        system=SYSTEM_PROMPT,
        messages=[
            Message(
                role="user",
                content=render_user_message(repository, workflow, branch, event, jobs, note),
            )
        ],
        max_output_tokens=max_output_tokens,
    )
    result = llm.generate_structured(request, CiDraft, ctx)
    draft = result.value
    evidence, dropped = verify_evidence(draft.evidence, jobs)
    confidence = draft.confidence
    if confidence == "high" and not evidence:
        confidence = "medium"  # "the log says so" needs a quote that really is in the log
    unassessed = _norm(draft.not_assessed)[:NOTES_CHARS]
    if unassessed:
        note = f"{note} Not assessed: {unassessed}"
    return CiResult(
        summary=draft.summary.strip()[:TEXT_CHARS],
        category=draft.category,
        confidence=confidence,
        likely_cause=draft.likely_cause.strip()[:TEXT_CHARS],
        suggested_fix=draft.suggested_fix.strip()[:TEXT_CHARS],
        evidence=evidence,
        notes=note[:1500],
        model=result.model,
        usage=result.usage,
        dropped_quotes=dropped,
    )
