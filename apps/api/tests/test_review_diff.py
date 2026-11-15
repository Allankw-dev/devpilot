from typing import Any

import pytest

from app.services.review.diff import (
    REDACTED,
    parse_patch,
    select_files,
)
from tests.github_helpers import make_pr_file

PATCH = """@@ -10,6 +10,9 @@ def login(user, password):
     user = find(user)
-    ok = check(user, password)
+    ok = user.password == password
+    if ok:
+        session["user"] = user
     return ok
 
 def logout():"""

SECRET = "AKIAIOSFODNN7EXAMPLE"


def files(*items: dict[str, Any], **kw: Any) -> Any:
    return select_files(list(items), max_files=kw.pop("max_files", 40), max_chars=kw.pop("max_chars", 60_000), **kw)  # noqa: E501


# ---------- reading a patch ----------


def test_new_file_line_numbers_follow_the_hunk_header() -> None:
    (hunk,) = parse_patch(PATCH)
    assert hunk.header == "@@ -10,6 +10,9 @@"
    got = [(ln.kind, ln.new_no, ln.text) for ln in hunk.lines]
    assert got == [
        ("ctx", 10, "    user = find(user)"),
        ("del", None, "    ok = check(user, password)"),
        ("add", 11, "    ok = user.password == password"),
        ("add", 12, "    if ok:"),
        ("add", 13, '        session["user"] = user'),
        ("ctx", 14, "    return ok"),
        ("ctx", 15, ""),  # a blank context line
        ("ctx", 16, "def logout():"),
    ]


def test_several_hunks_each_restart_the_numbering() -> None:
    patch = "@@ -1,2 +1,3 @@\n a\n+b\n c\n@@ -40,2 +41,2 @@ def f():\n-x\n+y\n z"
    first, second = parse_patch(patch)
    assert [ln.new_no for ln in first.lines] == [1, 2, 3]
    assert [(ln.kind, ln.new_no) for ln in second.lines] == [("del", None), ("add", 41), ("ctx", 42)]


def test_single_line_hunk_headers_and_the_no_newline_marker() -> None:
    patch = "@@ -0,0 +1 @@\n+print('hi')\n\\ No newline at end of file"
    (hunk,) = parse_patch(patch)
    assert [(ln.kind, ln.new_no) for ln in hunk.lines] == [("add", 1)]


def test_crlf_patches_and_garbage_are_handled() -> None:
    (hunk,) = parse_patch("@@ -1 +1,2 @@\r\n a\r\n+b\r\n")
    assert [(ln.kind, ln.new_no, ln.text) for ln in hunk.lines] == [
        ("ctx", 1, "a"),
        ("add", 2, "b"),
    ]  # no phantom line 3 from the closing newline
    assert parse_patch("") == []
    assert parse_patch("not a diff at all") == []


def test_visible_lines_are_added_and_context_lines_only() -> None:
    selected = files(make_pr_file("a.py", PATCH))
    (f,) = selected.files
    assert f.visible == {10, 11, 12, 13, 14, 15, 16}
    assert f.added == {11, 12, 13}


# ---------- what the model is shown ----------


def test_rendering_shows_new_line_numbers_markers_and_removed_lines() -> None:
    (f,) = files(make_pr_file("auth.py", PATCH, deletions=1)).files
    lines = f.text.splitlines()
    assert lines[0] == "=== auth.py (modified, +3 -1) ==="
    assert lines[1] == "@@ -10,6 +10,9 @@"
    assert "   11 +     ok = user.password == password" in lines
    assert "   10       user = find(user)" in lines
    assert "      -     ok = check(user, password)" in lines  # removed: no number


def test_renamed_files_say_where_they_came_from() -> None:
    (f,) = files(make_pr_file("new/name.py", PATCH, status="renamed", previous="old/name.py")).files
    assert f.text.startswith("=== new/name.py (renamed from old/name.py,")


def test_very_long_lines_are_cut() -> None:
    patch = "@@ -0,0 +1 @@\n+" + "x" * 5000
    (f,) = files(make_pr_file("min.py", patch)).files
    assert "…[cut]" in f.text and len(f.text) < 1000


# ---------- credentials never reach the model ----------


def test_credential_lines_are_withheld_and_reported_with_their_line_number() -> None:
    patch = f"@@ -1,2 +1,3 @@\n a = 1\n+key = '{SECRET}'\n b = 2"
    sel = files(make_pr_file("settings.py", patch))
    (f,) = sel.files
    assert SECRET not in f.text and REDACTED in f.text
    assert [(r.path, r.line) for r in sel.redactions] == [("settings.py", 2)]


def test_a_credential_that_was_only_removed_is_not_reported() -> None:
    patch = f"@@ -1,2 +1,1 @@\n a = 1\n-key = '{SECRET}'"
    assert files(make_pr_file("settings.py", patch)).redactions == []


def test_scan_covers_files_the_review_budget_leaves_out() -> None:
    big = "@@ -0,0 +1,60 @@\n" + "\n".join(f"+line_number_{i} = {i}  # " + "p" * 40 for i in range(60))
    leaky = f"@@ -0,0 +1 @@\n+token = '{SECRET}'"
    sel = files(
        make_pr_file("a_big.py", big), make_pr_file("z_leaky.py", leaky), max_chars=1700
    )
    assert [f.path for f in sel.files] == ["a_big.py"]  # the second file didn't fit...
    assert sel.skipped == {"over_budget": 1}
    assert [(r.path, r.line) for r in sel.redactions] == [("z_leaky.py", 1)]  # ...but was scanned


def test_only_added_lines_count_as_changed_lines() -> None:
    (f,) = files(make_pr_file("a.py", f"@@ -1,2 +1,2 @@\n+k='{SECRET}'\n ctx='{SECRET}'")).files
    assert f.added == {1}


def test_credential_style_files_are_flagged_never_read() -> None:
    sel = files(
        make_pr_file("config/.env", "@@ -0,0 +1 @@\n+API_KEY=abc", status="added"),
        make_pr_file(".env.example", "@@ -0,0 +1 @@\n+API_KEY=", status="added"),
        make_pr_file("certs/server.pem", "@@ -0,0 +1 @@\n+-----BEGIN", status="added"),
    )
    assert sorted(sel.secret_files) == ["certs/server.pem", "config/.env"]
    assert [f.path for f in sel.files] == [".env.example"]  # the example file is fine
    assert all("API_KEY=abc" not in f.text for f in sel.files)


# ---------- choosing files ----------


def test_generated_binary_and_unsupported_files_are_skipped_with_reasons() -> None:
    sel = files(
        make_pr_file("src/app.py", PATCH),
        make_pr_file("package-lock.json", "@@ -1 +1 @@\n-a\n+b"),
        make_pr_file("dist/bundle.js", "@@ -1 +1 @@\n-a\n+b"),
        make_pr_file("logo.png", None),
        make_pr_file("data.dat", "@@ -1 +1 @@\n-a\n+b"),
        make_pr_file("big.py", None),  # GitHub gives no patch for huge or binary files
        make_pr_file("renamed_only.py", None, status="renamed", previous="old.py"),
    )
    assert [f.path for f in sel.files] == ["src/app.py"]
    assert sel.total == 7 and sel.reviewed == 1
    assert sel.skipped == {"generated_or_binary": 3, "unsupported_type": 1, "no_diff": 2}


def test_deleted_files_are_listed_by_name_not_read() -> None:
    sel = files(make_pr_file("old.py", "@@ -1 +0,0 @@\n-x", status="removed"), make_pr_file("a.py", PATCH))
    assert sel.deleted == ["old.py"] and [f.path for f in sel.files] == ["a.py"]


def test_source_code_is_reviewed_before_tests_config_and_docs() -> None:
    patch = "@@ -0,0 +1 @@\n+x = 1"
    sel = files(
        make_pr_file("README.md", patch),
        make_pr_file("config.yaml", patch),
        make_pr_file("tests/test_a.py", patch),
        make_pr_file("src/main.py", patch),
        make_pr_file(".github/workflows/ci.yml", patch),
    )
    assert [f.path for f in sel.files] == [
        ".github/workflows/ci.yml", "src/main.py", "tests/test_a.py", "config.yaml", "README.md",
    ]  # fmt: skip


def test_bigger_changes_come_first_within_a_group() -> None:
    small = make_pr_file("small.py", "@@ -0,0 +1 @@\n+a")
    large = make_pr_file("large.py", "@@ -0,0 +1,3 @@\n+a\n+b\n+c")
    assert [f.path for f in files(small, large).files] == ["large.py", "small.py"]


def test_the_file_count_limit_is_applied_and_reported() -> None:
    items = [make_pr_file(f"m{i}.py", "@@ -0,0 +1 @@\n+x") for i in range(5)]
    sel = files(*items, max_files=3)
    assert sel.reviewed == 3 and sel.skipped == {"over_file_limit": 2} and sel.total == 5


def test_an_oversized_diff_is_cut_hunk_by_hunk_not_dropped() -> None:
    hunks = "\n".join(f"@@ -{i * 100},1 +{i * 100},2 @@\n ctx\n+added_{i} = '{'x' * 200}'" for i in range(1, 30))
    (f,) = files(make_pr_file("big.py", hunks), max_chars=3000).files
    assert f.truncated and "left out to stay within the review budget" in f.text
    assert 100 < len(f.text) <= 3200
    assert 101 in f.visible and 2901 not in f.visible


@pytest.mark.parametrize("name", ["../evil.py", "/etc/passwd", "a\\b.py", ""])
def test_unusual_paths_are_skipped(name: str) -> None:
    sel = files(make_pr_file(name, PATCH))
    assert sel.files == [] and sel.skipped == {"odd_path": 1}


def test_an_incomplete_listing_is_remembered() -> None:
    assert files(make_pr_file("a.py", PATCH), complete=False).incomplete_listing is True


def test_a_diff_within_budget_is_not_truncated() -> None:
    (f,) = files(make_pr_file("a.py", PATCH)).files
    assert not f.truncated and "left out" not in f.text
