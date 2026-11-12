import textwrap

from app.services.indexing.chunker import (
    MAX_CHARS,
    MAX_CHUNKS_PER_FILE,
    TARGET_CHARS,
    Chunk,
    chunk_file,
    embedding_text,
)


def lines_of(source: str) -> list[str]:
    return source.splitlines()


def assert_chunks_match_source(source: str, chunks: list[Chunk]) -> None:
    """The contract the UI and later citations rely on: lines[start-1:end] is the chunk text."""
    src = lines_of(source)
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line <= len(src)
        assert c.text == "\n".join(src[c.start_line - 1 : c.end_line])
        assert c.text.strip()


def by_symbol(chunks: list[Chunk], name: str) -> Chunk:
    return next(c for c in chunks if c.symbol and name in c.symbol.split(", "))


def big(name: str, lines: int = 40) -> str:
    body = "\n".join(f"    value_{i} = compute({i})  # padding line {i}" for i in range(lines))
    return f"def {name}(x):\n{body}\n    return x\n"


# ---------- python ----------


def test_python_functions_and_classes_become_separate_chunks_with_exact_lines() -> None:
    source = big("alpha") + "\n\n" + big("beta") + "\n\nclass Gamma:\n" + "\n".join(
        f"    attr_{i} = {i}  # {'x' * 60}" for i in range(40)
    )
    chunks = chunk_file(source, "python")
    assert_chunks_match_source(source, chunks)
    assert [c.symbol for c in chunks] == ["alpha", "beta", "Gamma"]
    assert by_symbol(chunks, "alpha").text.startswith("def alpha(x):")


def test_decorators_and_leading_comments_belong_to_the_function() -> None:
    source = textwrap.dedent(
        '''\
        import os


        # Explains why this exists
        # and how it is used
        @cache
        @route("/x")
        def handler(request):
            """Docs."""
            return os.getcwd()
        '''
    )
    (chunk,) = chunk_file(source, "python")
    assert chunk.text.startswith("import os")  # tiny file: everything packs into one chunk
    big_source = source.replace("import os\n\n\n", "") + "\n" * 2 + big("pad", 70)
    chunks = chunk_file(big_source, "python")
    handler = by_symbol(chunks, "handler")
    assert handler.text.startswith("# Explains why this exists")
    assert "@route" in handler.text and "def handler" in handler.text
    assert_chunks_match_source(big_source, chunks)


def test_small_definitions_are_packed_together_and_named() -> None:
    source = "\n\n".join(f"def tiny_{i}():\n    return {i}" for i in range(5)) + "\n"
    chunks = chunk_file(source, "python")
    assert len(chunks) == 1
    assert chunks[0].symbol == "tiny_0, tiny_1, tiny_2, tiny_3, tiny_4"
    assert_chunks_match_source(source, chunks)


def test_oversized_class_is_split_by_method() -> None:
    methods = "\n".join(
        f"    def method_{i}(self):\n" + "\n".join(f"        step_{j} = {j}  # {'y' * 50}" for j in range(30))
        for i in range(6)
    )
    source = f'class Service:\n    """The service."""\n\n{methods}\n'
    chunks = chunk_file(source, "python")
    assert_chunks_match_source(source, chunks)
    symbols = {s for c in chunks for s in (c.symbol or "").split(", ")}
    assert {"Service", "Service.method_0", "Service.method_5"} <= symbols
    assert all(len(c.text) <= MAX_CHARS for c in chunks)


def test_main_guard_is_labelled() -> None:
    source = "def run():\n    pass\n\n\nif __name__ == '__main__':\n    run()\n"
    (chunk,) = chunk_file(source, "python")
    assert chunk.symbol == "run, __main__"


def test_python_with_a_syntax_error_still_gets_chunked() -> None:
    source = "def broken(:\n    pass\n\n\ndef fine():\n    return 1\n"
    chunks = chunk_file(source, "python")
    assert chunks and "def fine" in "".join(c.text for c in chunks)
    assert_chunks_match_source(source, chunks)


def test_a_python_file_of_only_comments_falls_back() -> None:
    source = "# just a note\n# nothing else\n"
    chunks = chunk_file(source, "python")
    assert [c.text for c in chunks] == ["# just a note\n# nothing else"]


# ---------- markdown ----------


def test_markdown_splits_on_headings_but_not_inside_code_fences() -> None:
    filler = "Some explanatory text. " * 40
    source = (
        f"# Title\n\n{filler}\n\n## Install\n\n{filler}\n\n"
        "```bash\n# this is a comment, not a heading\nnpm install\n```\n\n"
        f"## Usage\n\n{filler}\n"
    )
    chunks = chunk_file(source, "markdown")
    assert_chunks_match_source(source, chunks)
    assert [c.symbol for c in chunks] == ["Title", "Install", "Usage"]
    assert "# this is a comment" in by_symbol(chunks, "Install").text


# ---------- other languages ----------


def test_typescript_top_level_declarations_are_found() -> None:
    body = "\n".join(f"  const v{i} = compute({i}); // {'z' * 60}" for i in range(30))
    source = (
        f"export function first(a: number) {{\n{body}\n}}\n\n"
        f"export const second = async (b: string) => {{\n{body}\n}};\n\n"
        f"export class Third {{\n{body}\n}}\n"
    )
    chunks = chunk_file(source, "typescript")
    assert_chunks_match_source(source, chunks)
    assert [c.symbol for c in chunks] == ["first", "second", "Third"]
    assert chunks[0].text.rstrip().endswith("}")  # closing brace stays with its function


def test_closing_brace_after_a_blank_line_does_not_start_a_new_chunk() -> None:
    source = "function a() {\n  x();\n\n}\n\nfunction b() {\n  y();\n}\n"
    chunks = chunk_file(source, "javascript")
    assert_chunks_match_source(source, chunks)
    assert chunks[0].text.count("}") >= 2


def test_yaml_and_unknown_languages_use_the_generic_splitter() -> None:
    source = "services:\n  web:\n    image: x\n\nvolumes:\n  data: {}\n"
    chunks = chunk_file(source, "yaml")
    assert_chunks_match_source(source, chunks)
    assert chunk_file(source, None)[0].text.startswith("services:")


# ---------- size and safety limits ----------


def test_one_giant_block_is_cut_with_overlap_and_never_exceeds_the_limit() -> None:
    source = "\n".join(f"line {i} " + "q" * 60 for i in range(400))  # one block, no blank lines
    chunks = chunk_file(source, None)
    assert_chunks_match_source(source, chunks)
    assert len(chunks) > 3
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.start_line <= a.end_line  # overlap, so nothing falls into a gap
        assert b.start_line > a.start_line  # and the loop always moves forward
    assert chunks[-1].end_line == 400


def test_a_single_enormous_line_is_truncated_not_stored_whole() -> None:
    source = "var a = '" + "x" * 50_000 + "';\nvar b = 1;\n"
    chunks = chunk_file(source, "javascript")
    assert chunks and all(len(c.text) <= MAX_CHARS + 50 for c in chunks)
    assert "line truncated" in chunks[0].text


def test_chunk_count_per_file_is_capped() -> None:
    source = "\n\n".join(big(f"fn_{i}", 60) for i in range(MAX_CHUNKS_PER_FILE + 50))
    assert len(chunk_file(source, "python")) == MAX_CHUNKS_PER_FILE


def test_blank_and_whitespace_files_produce_nothing() -> None:
    assert chunk_file("", "python") == []
    assert chunk_file("\n\n   \n\t\n", None) == []


def test_crlf_files_are_handled() -> None:
    source = "def a():\r\n    return 1\r\n\r\n\r\ndef b():\r\n    return 2\r\n"
    chunks = chunk_file(source, "python")
    assert chunks and "\r" not in chunks[0].text


def test_typical_chunk_size_stays_near_target() -> None:
    source = "\n\n".join(big(f"f{i}", 8) for i in range(30))
    chunks = chunk_file(source, "python")
    assert len(chunks) > 1
    assert all(len(c.text) <= TARGET_CHARS + 600 for c in chunks)


def test_embedding_text_carries_path_and_symbol() -> None:
    text = embedding_text("src/app.py", Chunk(1, 2, "login", "def login(): ..."))
    assert text.startswith("File: src/app.py\nSymbol: login\n")
    assert text.endswith("def login(): ...")
    assert "Symbol:" not in embedding_text("a.py", Chunk(1, 1, None, "x = 1"))
