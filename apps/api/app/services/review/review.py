"""The review itself: what the model is asked, and how its findings are checked.

A finding that cites a file or line that is not in the diff is never shown as if it were real:
unknown files are dropped, and line numbers outside the changed code fall back to a file-level
finding. Credentials are found by a scanner (not by the model) and withheld from the model.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.services.llm import (
    UNTRUSTED_CONTENT_NOTICE,
    CallContext,
    GenerationRequest,
    LLMService,
    Message,
    Usage,
    untrusted,
)
from app.services.review.diff import Redaction, Selection

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal[
    "bug", "logic", "security", "performance", "error_handling", "maintainability", "tests"
]
Confidence = Literal["high", "medium", "low"]
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

TITLE_CHARS = 150
TEXT_CHARS = 2500
NOTES_CHARS = 1000

SYSTEM_PROMPT = (
    "You are DevPilot, a senior engineer reviewing a pull request. You are given the diff of the "
    "changed files.\n\n"
    "How to read the diff: each file starts with a line like === path (status, +N -M) ===. Lines "
    'have the NEW file\'s line number on the left, then "+" for an added line or a space for '
    'unchanged context; a removed line has no number and is shown with "-".\n\n'
    "What to do:\n"
    "- Find real problems in the CHANGED code: bugs, wrong logic, security risks, performance "
    "problems, missing error handling, and changes that deserve a test. Prefer a few important "
    "findings over many small ones. Skip pure style preferences.\n"
    "- Every finding must name a file from the diff and give start_line and end_line using the "
    "line numbers shown on the left. Use 0 for both only when a finding is about the whole file.\n"
    "- severity: critical = exploitable security flaw or data loss; high = likely bug or serious "
    "weakness; medium = real but limited; low = minor; info = observation. Be conservative: do "
    "not call something critical unless you are sure.\n"
    "- confidence: high only when the problem is visible in the diff itself; use low when you are "
    "guessing about code you cannot see.\n"
    "- explanation says what is wrong and why it matters, plainly. suggestion says how to fix it "
    "and may include a short code snippet.\n"
    "- Never invent files, lines or behaviour. You cannot run the code or the tests, so do not "
    "claim anything about test results. If code you cannot see decides the question, say so and "
    "lower the confidence.\n"
    "- Lines marked as withheld were removed because they looked like credentials; ignore them.\n"
    "- summary: two to five sentences in plain language saying what the pull request does and "
    "which parts are the riskiest. risk: low, medium or high for the change as a whole.\n"
    "- If you find no problems, return an empty findings list and say what you checked.\n"
    "- not_assessed: anything you could not judge from the diff (leave empty if nothing).\n\n"
    + UNTRUSTED_CONTENT_NOTICE
)


class FindingDraft(BaseModel):
    file: str = Field(description="Path of the changed file, exactly as shown in the diff.")
    start_line: int = Field(description="First line in the NEW file, or 0 for the whole file.")
    end_line: int = Field(description="Last line in the NEW file, or 0 for the whole file.")
    category: Category
    severity: Severity
    confidence: Confidence
    title: str = Field(description="One short line naming the problem.")
    explanation: str
    suggestion: str = ""


class ReviewDraft(BaseModel):
    summary: str
    risk: Literal["low", "medium", "high"]
    findings: list[FindingDraft] = []
    not_assessed: str = ""


@dataclass
class Finding:
    file: str
    start_line: int  # 0 = the whole file
    end_line: int
    category: str
    severity: str
    confidence: str
    title: str
    explanation: str
    suggestion: str
    origin: str  # "ai" or "scan"


@dataclass
class ReviewResult:
    summary: str
    risk: str
    findings: list[Finding]
    notes: str
    model: str
    usage: Usage


# ---------- what the model sees ----------


def coverage_note(sel: Selection) -> str:
    """Plain-language statement of what was and wasn't looked at (also shown to the user)."""
    parts = [f"Reviewed {sel.reviewed} of {sel.total} changed files."]
    labels = {
        "generated_or_binary": "lockfiles, generated or binary",
        "unsupported_type": "unsupported file types",
        "no_diff": "no diff available (binary or too large)",
        "over_file_limit": "over the file limit",
        "over_budget": "over the size budget",
        "deleted": "deleted",
        "secret_file": "credential files (flagged, not read)",
        "odd_path": "unusual paths",
    }
    skipped = [f"{n} {labels.get(k, k)}" for k, n in sorted(sel.skipped.items()) if n]
    if skipped:
        parts.append("Not reviewed: " + ", ".join(skipped) + ".")
    if any(f.truncated for f in sel.files):
        parts.append("Some large diffs were cut short.")
    if sel.incomplete_listing:
        parts.append("GitHub's file list was cut short, so later files are missing.")
    return " ".join(parts)


def render_user_message(
    title: str, body: str, base: str, head: str, repository: str, sel: Selection
) -> str:
    context = f"Repository: {repository}\nTitle: {title}\nBranches: {head} into {base}\n\n"
    context += body.strip() or "(no description)"
    parts = [untrusted("pull request title and description", context, max_chars=6000)]
    for f in sel.files:
        parts.append(untrusted(f"diff {f.path}", f.text, max_chars=60_000))
    if sel.deleted:
        parts.append(untrusted("deleted files", "\n".join(sel.deleted), max_chars=3000))
    return coverage_note(sel) + "\n\n" + "\n\n".join(parts)


# ---------- checking what comes back ----------


def _normalise(path: str, known: set[str]) -> str | None:
    p = path.strip()
    for candidate in (p, p.removeprefix("./"), p.removeprefix("a/"), p.removeprefix("b/")):
        if candidate in known:
            return candidate
    return None


def validate_findings(
    drafts: list[FindingDraft], sel: Selection, max_findings: int
) -> list[Finding]:
    by_path = {f.path: f for f in sel.files}
    known = set(by_path)
    kept: list[Finding] = []
    for d in drafts:
        path = _normalise(d.file, known)
        if path is None:
            continue  # a file that is not in the diff: invented
        start, end = d.start_line, d.end_line
        if start > 0:
            end = max(end, start)
            visible = by_path[path].visible
            inside = sorted(n for n in visible if start <= n <= end)
            if inside:
                start, end = inside[0], inside[-1]  # trimmed to lines that really exist
            else:
                start = end = 0  # the lines aren't in the diff: keep it as a file-level finding
        else:
            start = end = 0
        kept.append(
            Finding(
                file=path,
                start_line=start,
                end_line=end,
                category=d.category,
                severity=d.severity,
                confidence=d.confidence,
                title=" ".join(d.title.split())[:TITLE_CHARS] or "Possible problem",
                explanation=d.explanation.strip()[:TEXT_CHARS],
                suggestion=d.suggestion.strip()[:TEXT_CHARS],
                origin="ai",
            )
        )
    # One finding per place and kind of problem: keep the most severe.
    best: dict[tuple[str, int, str], Finding] = {}
    for f in kept:
        key = (f.file, f.start_line, f.category)
        if key not in best or SEVERITY_RANK[f.severity] < SEVERITY_RANK[best[key].severity]:
            best[key] = f
    return sort_findings(list(best.values()))[:max_findings]


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (
            SEVERITY_RANK[f.severity],
            CONFIDENCE_RANK[f.confidence],
            f.file,
            f.start_line,
        ),
    )


# ---------- findings from the scanner (not the model) ----------


def scanner_findings(redactions: list[Redaction], secret_files: list[str]) -> list[Finding]:
    found: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for r in redactions:
        if (r.path, r.line) in seen:
            continue
        seen.add((r.path, r.line))
        found.append(
            Finding(
                file=r.path,
                start_line=r.line,
                end_line=r.line,
                category="security",
                severity="high",
                confidence="medium",
                title="Possible credential added",
                explanation=(
                    "This line looks like a password, API key or token. It was not sent to the AI. "
                    "Secrets in a repository stay in its history even after they are deleted."
                ),
                suggestion=(
                    "If it is real: revoke and replace it, remove it from the commit history, and "
                    "load it from an environment variable or secret store instead. If it is a "
                    "harmless example, ignore this."
                ),
                origin="scan",
            )
        )
    for path in secret_files:
        found.append(
            Finding(
                file=path,
                start_line=0,
                end_line=0,
                category="security",
                severity="high",
                confidence="medium",
                title="File that usually holds credentials",
                explanation=(
                    f"{path} is the kind of file that normally contains secrets (keys, "
                    "certificates or environment settings). Its contents were not read."
                ),
                suggestion=(
                    "Check that it holds no real credentials, and add it to .gitignore if it "
                    "should not be committed."
                ),
                origin="scan",
            )
        )
    return found


# ---------- the call ----------


def review_diff(
    llm: LLMService,
    *,
    title: str,
    body: str,
    base: str,
    head: str,
    repository: str,
    sel: Selection,
    ctx: CallContext,
    max_output_tokens: int,
    max_findings: int,
) -> ReviewResult:
    """Ask the model to review the selected diff and return checked findings."""
    findings = scanner_findings(sel.redactions, sel.secret_files)
    notes = coverage_note(sel)
    if not sel.files:
        return ReviewResult(
            summary="There was nothing to review: the changes are only generated, binary or "
            "excluded files.",
            risk="low",
            findings=sort_findings(findings),
            notes=notes,
            model="",
            usage=Usage(),
        )
    request = GenerationRequest(
        system=SYSTEM_PROMPT,
        messages=[
            Message(
                role="user",
                content=render_user_message(title, body, base, head, repository, sel),
            )
        ],
        max_output_tokens=max_output_tokens,
    )
    result = llm.generate_structured(request, ReviewDraft, ctx)
    draft = result.value
    ai_findings = validate_findings(draft.findings, sel, max_findings)
    unassessed = re.sub(r"\s+", " ", draft.not_assessed).strip()[:NOTES_CHARS]
    if unassessed:
        notes = f"{notes} Not assessed: {unassessed}"
    risk = draft.risk
    if findings and risk == "low":
        risk = "medium"  # a possible credential means the change is not low risk
    return ReviewResult(
        summary=draft.summary.strip()[:TEXT_CHARS],
        risk=risk,
        findings=sort_findings([*findings, *ai_findings]),
        notes=notes[: NOTES_CHARS + 400],
        model=result.model,
        usage=result.usage,
    )
