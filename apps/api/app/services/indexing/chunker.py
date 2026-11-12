"""Splitting a source file into chunks that make sense on their own.

Python files are split with the real parser (functions, classes, methods). Markdown splits on
headings. Everything else uses a layout heuristic: blocks start at unindented lines after a
blank line, which matches how most languages lay out top-level declarations. Small pieces are
packed together so a repo doesn't turn into thousands of tiny vectors.

Line numbers are 1-based and inclusive, so `lines[start-1:end]` is exactly the chunk's text.
Tree-sitter based splitting for more languages is a possible later upgrade.
"""

import ast
import re
from dataclasses import dataclass

TARGET_CHARS = 1800  # pack small pieces together up to about this size
MAX_CHARS = 4000  # no chunk is bigger than this
OVERLAP_LINES = 3  # when one block must be cut, repeat this many lines at the seam
MAX_CHUNKS_PER_FILE = 300
MAX_LINE_CHARS = MAX_CHARS  # a longer line (minified code, data) is cut

_DECL = re.compile(
    r"""^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?
        (?:(?:public|private|protected|internal|static|final|abstract|sealed|pub)\s+)*
        (?:def|function|class|interface|struct|enum|trait|impl|fn|func|type|module|namespace)
        \s+\*?([A-Za-z_$][\w$.<>]*)""",
    re.VERBOSE,
)
_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?(?:\(|function\b|[A-Za-z_$][\w$]*\s*=>)"
)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_CLOSERS = ("}", ")", "]", "end", "else", "elif", "except", "finally", "catch")


@dataclass(frozen=True)
class Chunk:
    start_line: int
    end_line: int
    symbol: str | None
    text: str


@dataclass
class _Unit:
    start: int
    end: int
    symbol: str | None


# ---------- public ----------


def chunk_file(text: str, language: str | None) -> list[Chunk]:
    lines = [
        ln if len(ln) <= MAX_LINE_CHARS else ln[:MAX_LINE_CHARS] + " …[line truncated]"
        for ln in text.splitlines()
    ]
    if not any(ln.strip() for ln in lines):
        return []

    units: list[_Unit] | None = None
    if language == "python":
        units = _python_units("\n".join(lines), lines)
    elif language == "markdown":
        units = _markdown_units(lines)
    if not units:
        units = _generic_units(lines)

    pieces: list[_Unit] = []
    for unit in units:
        pieces.extend(_split_oversize(unit, lines))
    packed = _pack(pieces, lines)

    chunks = [
        Chunk(u.start, u.end, u.symbol, "\n".join(lines[u.start - 1 : u.end]))
        for u in packed
        if any(ln.strip() for ln in lines[u.start - 1 : u.end])
    ]
    return chunks[:MAX_CHUNKS_PER_FILE]


def embedding_text(path: str, chunk: Chunk) -> str:
    """What gets embedded: the code plus where it lives, which helps retrieval a lot."""
    head = f"File: {path}\n"
    if chunk.symbol:
        head += f"Symbol: {chunk.symbol}\n"
    return head + "\n" + chunk.text


# ---------- helpers ----------


def _chars(lines: list[str], start: int, end: int) -> int:
    return sum(len(ln) + 1 for ln in lines[start - 1 : end])


def _extend_over_comments(start: int, lines: list[str]) -> int:
    """Pull comment lines sitting directly above a declaration into it."""
    while start > 1 and lines[start - 2].lstrip().startswith(("#", "//", "///", "--")):
        start -= 1
    return start


def _pack(units: list[_Unit], lines: list[str]) -> list[_Unit]:
    """Merge neighbours while the result stays small."""
    out: list[_Unit] = []
    names: list[list[str]] = []
    for u in units:
        if out and _chars(lines, out[-1].start, u.end) <= TARGET_CHARS:
            out[-1].end = u.end
            if u.symbol:
                names[-1].append(u.symbol)
        else:
            out.append(_Unit(u.start, u.end, u.symbol))
            names.append([u.symbol] if u.symbol else [])
    for unit, syms in zip(out, names, strict=True):
        unit.symbol = ", ".join(dict.fromkeys(syms))[:200] or None
    return out


def _split_oversize(unit: _Unit, lines: list[str]) -> list[_Unit]:
    """Cut a block bigger than MAX_CHARS into line windows with a little overlap."""
    if _chars(lines, unit.start, unit.end) <= MAX_CHARS:
        return [unit]
    out: list[_Unit] = []
    start, part = unit.start, 1
    while start <= unit.end:
        end, size = start, 0
        while end <= unit.end and size + len(lines[end - 1]) + 1 <= MAX_CHARS:
            size += len(lines[end - 1]) + 1
            end += 1
        end = max(end - 1, start)  # always make progress, even on a very long line
        label = unit.symbol or ""
        out.append(_Unit(start, end, f"{label} (part {part})".strip()))
        if end >= unit.end:
            break
        start = max(end - OVERLAP_LINES + 1, start + 1)
        part += 1
    return out


# ---------- python ----------


def _python_units(source: str, lines: list[str]) -> list[_Unit] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    units = _walk_python(tree.body, "", lines)
    return units or None


def _walk_python(body: list[ast.stmt], prefix: str, lines: list[str]) -> list[_Unit]:
    units: list[_Unit] = []
    for node in body:
        end = node.end_lineno or node.lineno
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            start = _extend_over_comments(first, lines)
            name = f"{prefix}{node.name}"
            if isinstance(node, ast.ClassDef) and _chars(lines, start, end) > MAX_CHARS:
                inner = _walk_python(node.body, f"{name}.", lines)
                if inner and inner[0].start > start:  # class docstring / attributes
                    units.append(_Unit(start, inner[0].start - 1, name))
                units.extend(inner or [_Unit(start, end, name)])
            else:
                units.append(_Unit(start, end, name))
        else:
            start = _extend_over_comments(node.lineno, lines)
            is_main = isinstance(node, ast.If) and "__name__" in ast.dump(node.test)
            units.append(_Unit(start, end, "__main__" if is_main else None))
    return units


# ---------- markdown ----------


def _markdown_units(lines: list[str]) -> list[_Unit]:
    units: list[_Unit] = []
    start, symbol, fenced = 1, None, False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        if match and i > start:
            units.append(_Unit(start, i - 1, symbol))
            start = i
        if match:
            symbol = match.group(2)[:200]
    units.append(_Unit(start, len(lines), symbol))
    return units


# ---------- everything else ----------


def _guess_symbol(line: str) -> str | None:
    match = _DECL.match(line) or _ARROW.match(line)
    return match.group(1)[:200] if match else None


def _generic_units(lines: list[str]) -> list[_Unit]:
    """Blocks start at an unindented line that follows a blank line."""
    units: list[_Unit] = []
    start: int | None = None
    symbol: str | None = None
    for i, line in enumerate(lines, 1):
        blank = not line.strip()
        if start is None:
            if blank:
                continue
            start, symbol = i, _guess_symbol(line)
            continue
        prev_blank = not lines[i - 2].strip()
        top_level = not blank and not line[0].isspace() and not line.startswith(_CLOSERS)
        if prev_blank and top_level:
            end = i - 1
            while end > start and not lines[end - 1].strip():
                end -= 1
            units.append(_Unit(start, end, symbol))
            start, symbol = i, _guess_symbol(line)
        elif symbol is None and not blank:
            symbol = _guess_symbol(line)
    if start is not None:
        end = len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1
        units.append(_Unit(start, end, symbol))
    return units
