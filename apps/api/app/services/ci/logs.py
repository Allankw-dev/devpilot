"""Turning a raw CI job log into a short, safe excerpt for the model.

A log is untrusted text and can hold secrets, so before anything is sent to the AI:
- escape codes, timestamps and noise are removed,
- any line that looks like a credential is replaced (and a private key block is replaced whole),
- what remains is cut down to the parts that matter: the end of the log (where jobs fail) and
  the lines around error messages, within a character budget.
"""

import re
from dataclasses import dataclass

from app.services.indexing.secretscan import contains_secret

WITHHELD = "[line withheld: looked like a credential]"
OMITTED = "[... {n} lines omitted ...]"

MAX_LINE_CHARS = 400
TAIL_LINES = 40
LINES_BEFORE = 8
LINES_AFTER = 4

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
_PRIVATE_KEY_START = re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")
_PRIVATE_KEY_END = re.compile(r"-----END (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")
_ANCHOR = re.compile(
    r"##\[error\]|\berror\b|\bfailed\b|\bfailure\b|\bfatal\b|traceback|exception|"
    r"assertion|exit code|npm err!|\bpanic\b|cannot find|not found|timed out|segmentation",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LogExcerpt:
    text: str
    withheld_lines: int  # lines replaced because they looked like credentials
    truncated: bool  # the log was cut off before it reached us, or parts were left out
    lines_total: int


def clean_lines(raw: str) -> list[str]:
    """Plain lines: no escape codes, timestamps or blank noise; `##[group]` becomes a heading."""
    out: list[str] = []
    for line in raw.lstrip("\ufeff").splitlines():
        line = _ANSI.sub("", line).rstrip()
        line = _TIMESTAMP.sub("", line)
        if line.startswith("##[endgroup]") or not line.strip():
            continue
        if line.startswith("##[group]"):
            line = "== " + line.removeprefix("##[group]").strip() + " =="
        elif line.startswith("##[error]"):
            line = "ERROR: " + line.removeprefix("##[error]").strip()
        elif line.startswith("##[warning]"):
            line = "WARNING: " + line.removeprefix("##[warning]").strip()
        out.append(line[:MAX_LINE_CHARS])
    return out


def withhold_secrets(lines: list[str]) -> tuple[list[str], int]:
    """Replace credential-looking lines. A private key block is replaced from its first line
    to its last, because the key body itself looks like harmless text."""
    safe: list[str] = []
    count = 0
    in_key = False
    for line in lines:
        if in_key:
            count += 1
            safe.append(WITHHELD)
            if _PRIVATE_KEY_END.search(line):
                in_key = False
            continue
        if _PRIVATE_KEY_START.search(line):
            count += 1
            safe.append(WITHHELD)
            in_key = not _PRIVATE_KEY_END.search(line)
            continue
        if contains_secret(line):
            count += 1
            safe.append(WITHHELD)
            continue
        safe.append(line)
    return safe, count


def _around(anchor: int) -> list[int]:
    """The error line, then its neighbours nearest first (the lines before it explain it)."""
    order = [anchor]
    for step in range(1, max(LINES_BEFORE, LINES_AFTER) + 1):
        if step <= LINES_BEFORE:
            order.append(anchor - step)
        if step <= LINES_AFTER:
            order.append(anchor + step)
    return order


def build_excerpt(raw: str, *, max_chars: int, cut_before: bool = False) -> LogExcerpt:
    """The part of a log worth reading, within `max_chars`. `cut_before` says the download
    already dropped the start of the log."""
    lines, withheld = withhold_secrets(clean_lines(raw))
    n = len(lines)
    if n == 0:
        return LogExcerpt("", withheld, cut_before, 0)

    keep: set[int] = set()
    used = 0

    def add(i: int) -> bool:
        nonlocal used
        if i < 0 or i >= n or i in keep:
            return True
        cost = len(lines[i]) + 1
        if used + cost > max_chars:
            return False
        keep.add(i)
        used += cost
        return True

    for i in range(n - 1, max(n - TAIL_LINES, 0) - 1, -1):  # the end of the log first
        if not add(i):
            break
    anchors = [i for i, line in enumerate(lines) if _ANCHOR.search(line)]
    out_of_room = False
    for a in reversed(anchors):  # then around errors, latest first, the error line itself first
        for i in _around(a):
            if not add(i):
                out_of_room = True
                break
        if out_of_room:
            break

    parts: list[str] = []
    previous = -1
    for i in sorted(keep):
        if previous != -1 and i != previous + 1:
            parts.append(OMITTED.format(n=i - previous - 1))
        elif previous == -1 and i > 0:
            parts.append(OMITTED.format(n=i))
        parts.append(lines[i])
        previous = i
    return LogExcerpt(
        text="\n".join(parts),
        withheld_lines=withheld,
        truncated=cut_before or len(keep) < n,
        lines_total=n,
    )
