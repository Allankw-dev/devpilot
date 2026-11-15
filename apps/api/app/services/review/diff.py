"""Turning GitHub's pull request file list into a reviewable, line-numbered diff.

Why this matters: a finding is only useful if it points at a real changed line. Everything here
keeps exact new-file line numbers, so the model can cite them and the server can verify them.

Also here: choosing which files to spend the review budget on, and keeping credentials out of
what is sent to the AI (such lines are replaced and reported as findings by the scanner instead).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.indexing.filters import FileRules, clean_path
from app.services.indexing.languages import language_of
from app.services.indexing.secretscan import contains_secret

MAX_LINE_CHARS = 400
MAX_DELETED_LISTED = 30
REDACTED = "[line withheld: looks like a credential]"
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# Reviewing a pull request is different from indexing: we want config, workflows and SQL too.
_RULES = FileRules(max_bytes=10**9)

LineKind = Literal["add", "del", "ctx"]


@dataclass
class DiffLine:
    kind: LineKind
    new_no: int | None  # line number in the new version; None for removed lines
    text: str


@dataclass
class Hunk:
    header: str
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    status: str  # added | modified | removed | renamed | ...
    previous_path: str | None
    additions: int
    deletions: int
    hunks: list[Hunk]

    def visible_lines(self) -> set[int]:
        """New-file line numbers the reviewer can see (changed and surrounding context)."""
        return {ln.new_no for h in self.hunks for ln in h.lines if ln.new_no is not None}


def parse_patch(patch: str) -> list[Hunk]:
    """Parse a unified diff body (as GitHub returns per file) into hunks with line numbers."""
    hunks: list[Hunk] = []
    current: Hunk | None = None
    new_no = 0
    lines = patch.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the newline that ends the patch is a terminator, not a blank line
    for raw in lines:
        match = _HUNK.match(raw)
        if match:
            current = Hunk(header=raw[: raw.find("@@", 2) + 2])
            hunks.append(current)
            new_no = int(match.group(2))
            continue
        if current is None or raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        if raw.startswith("+"):
            current.lines.append(DiffLine("add", new_no, raw[1:]))
            new_no += 1
        elif raw.startswith("-"):
            current.lines.append(DiffLine("del", None, raw[1:]))
        else:  # a context line (blank context lines may arrive without their leading space)
            current.lines.append(DiffLine("ctx", new_no, raw[1:] if raw.startswith(" ") else raw))
            new_no += 1
    return [h for h in hunks if h.lines]


# ---------- choosing and rendering files ----------


@dataclass
class RenderedFile:
    path: str
    text: str
    visible: set[int]
    added: set[int]
    truncated: bool = False


@dataclass
class Redaction:
    path: str
    line: int


@dataclass
class Selection:
    files: list[RenderedFile] = field(default_factory=list)
    total: int = 0  # files in the pull request
    skipped: dict[str, int] = field(default_factory=dict)
    redactions: list[Redaction] = field(default_factory=list)
    secret_files: list[str] = field(default_factory=list)  # credential-style files added/changed
    deleted: list[str] = field(default_factory=list)
    incomplete_listing: bool = False  # GitHub's list was cut short

    @property
    def reviewed(self) -> int:
        return len(self.files)

    @property
    def skipped_count(self) -> int:
        return sum(self.skipped.values())


def _priority(path: str) -> int:
    """Lower is reviewed first: source code, then config, tests and docs."""
    lower = path.lower()
    if lower.startswith(".github/workflows/") or lower.endswith(("dockerfile", ".sql")):
        return 0
    language = language_of(path)
    if language in ("markdown", "text"):
        return 4
    if re.search(r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(_test|\.test|\.spec)\.", lower):
        return 2
    if language in ("yaml", "json", "toml", "ini", "xml", "env"):
        return 3
    return 1


def scan_for_credentials(fd: FileDiff) -> list[Redaction]:
    """Added lines that look like credentials. Covers the whole file, whatever the review
    budget lets the AI see."""
    return [
        Redaction(fd.path, ln.new_no)
        for h in fd.hunks
        for ln in h.lines
        if ln.kind == "add" and ln.new_no is not None and contains_secret(ln.text)
    ]


def render_file(fd: FileDiff, budget: int) -> RenderedFile:
    """The diff of one file as numbered text. Lines that look like credentials are withheld.
    Stops adding hunks once `budget` characters are used."""
    header = f"=== {fd.path} ({fd.status}"
    if fd.previous_path:
        header += f" from {fd.previous_path}"
    header += f", +{fd.additions} -{fd.deletions}) ==="
    out = [header]
    used = len(header)
    visible: set[int] = set()
    added: set[int] = set()
    truncated = False
    for hunk in fd.hunks:
        block: list[str] = [hunk.header]
        hunk_visible: list[int] = []
        hunk_added: list[int] = []
        for ln in hunk.lines:
            text = ln.text
            if ln.kind == "add" and contains_secret(text):
                text = REDACTED
            if len(text) > MAX_LINE_CHARS:
                text = text[:MAX_LINE_CHARS] + " …[cut]"
            if ln.kind == "del":
                block.append(f"      - {text}")
            else:
                assert ln.new_no is not None
                marker = "+" if ln.kind == "add" else " "
                block.append(f"{ln.new_no:>5} {marker} {text}")
                hunk_visible.append(ln.new_no)
                if ln.kind == "add":
                    hunk_added.append(ln.new_no)
        size = sum(len(x) + 1 for x in block)
        if used + size > budget and used > len(header):
            truncated = True
            break
        out.extend(block)
        used += size
        visible.update(hunk_visible)
        added.update(hunk_added)
    if truncated:
        out.append("[the rest of this file's diff was left out to stay within the review budget]")
    return RenderedFile(fd.path, "\n".join(out), visible, added, truncated)


def select_files(
    github_files: list[dict[str, Any]],
    *,
    max_files: int,
    max_chars: int,
    complete: bool = True,
) -> Selection:
    """Pick what to review from GitHub's file list, within a file count and character budget."""
    sel = Selection(total=len(github_files), incomplete_listing=not complete)

    def skip(reason: str) -> None:
        sel.skipped[reason] = sel.skipped.get(reason, 0) + 1

    candidates: list[FileDiff] = []
    for item in github_files:
        path = clean_path(str(item.get("filename", "")))
        status = str(item.get("status", "modified"))
        if path is None:
            skip("odd_path")
            continue
        reason = _RULES.skip_reason(path, 1)
        if status == "removed":
            if len(sel.deleted) < MAX_DELETED_LISTED:
                sel.deleted.append(path)
            skip("deleted")
            continue
        if reason == "secret_file":
            sel.secret_files.append(path)  # never read, but worth flagging
            skip("secret_file")
            continue
        if reason in ("excluded", "unsupported"):
            skip("generated_or_binary" if reason == "excluded" else "unsupported_type")
            continue
        patch = item.get("patch")
        if not isinstance(patch, str) or not patch:
            skip("no_diff")  # binary, too large for GitHub to show, or a pure rename
            continue
        hunks = parse_patch(patch)
        if not hunks:
            skip("no_diff")
            continue
        previous = item.get("previous_filename")
        candidates.append(
            FileDiff(
                path=path,
                status=status,
                previous_path=str(previous) if previous else None,
                additions=int(item.get("additions", 0) or 0),
                deletions=int(item.get("deletions", 0) or 0),
                hunks=hunks,
            )
        )

    for fd in candidates:  # every file is scanned, even those the review budget leaves out
        sel.redactions.extend(scan_for_credentials(fd))
    candidates.sort(key=lambda f: (_priority(f.path), -(f.additions + f.deletions), f.path))
    remaining = max_chars
    for fd in candidates:
        if len(sel.files) >= max_files:
            skip("over_file_limit")
            continue
        if remaining < 1500:
            skip("over_budget")
            continue
        rendered = render_file(fd, remaining)
        sel.files.append(rendered)
        remaining -= len(rendered.text)
    return sel
