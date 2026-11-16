import time

from app.services.ci.logs import WITHHELD, build_excerpt, clean_lines, withhold_secrets

SECRET = "AKIAIOSFODNN7EXAMPLE"


def test_clean_lines_strips_timestamps_escape_codes_and_noise() -> None:
    raw = "\n".join(
        [
            "\ufeff2026-11-16T09:00:00.1234567Z ##[group]Run tests",
            "2026-11-16T09:00:01.0000000Z \x1b[31mFAILED\x1b[0m test_a",
            "",
            "2026-11-16T09:00:02.0000000Z ##[endgroup]",
            "2026-11-16T09:00:03.0000000Z ##[error]Process completed with exit code 1.",
            "2026-11-16T09:00:04.0000000Z ##[warning]Node 18 is deprecated",
        ]
    )
    assert clean_lines(raw) == [
        "== Run tests ==",
        "FAILED test_a",
        "ERROR: Process completed with exit code 1.",
        "WARNING: Node 18 is deprecated",
    ]


def test_very_long_lines_are_clipped() -> None:
    (line,) = clean_lines("x" * 5000)
    assert len(line) == 400


def test_credential_looking_lines_are_withheld_and_counted() -> None:
    safe, count = withhold_secrets(["fine", f"key = {SECRET}", "also fine"])
    assert safe == ["fine", WITHHELD, "also fine"] and count == 1


def test_a_whole_private_key_block_is_withheld_not_just_its_first_line() -> None:
    lines = [
        "before",
        "-----BEGIN RSA PRIVATE KEY-----",
        "MIIEowIBAAKCAQEAtotallyharmlookingbase64text",
        "morebase64lookingtext==",
        "-----END RSA PRIVATE KEY-----",
        "after",
    ]
    safe, count = withhold_secrets(lines)
    assert safe == ["before", WITHHELD, WITHHELD, WITHHELD, WITHHELD, "after"] and count == 4
    assert "base64" not in "\n".join(safe)


def test_a_single_line_private_key_marker_does_not_swallow_the_rest() -> None:
    safe, count = withhold_secrets(
        ["-----BEGIN PRIVATE KEY----- abc -----END PRIVATE KEY-----", "next line"]
    )
    assert safe == [WITHHELD, "next line"] and count == 1


def test_a_short_log_is_kept_whole() -> None:
    ex = build_excerpt("one\ntwo\nthree", max_chars=1000)
    assert ex.text == "one\ntwo\nthree" and not ex.truncated and ex.lines_total == 3


def test_an_empty_log_gives_an_empty_excerpt() -> None:
    ex = build_excerpt("\n\n  \n", max_chars=1000)
    assert ex.text == "" and ex.lines_total == 0


def test_a_long_log_keeps_the_end_and_the_lines_around_an_early_error() -> None:
    lines = [f"step output {i}" for i in range(500)]
    lines[100] = "ERROR: could not resolve dependency left-pad"
    ex = build_excerpt("\n".join(lines), max_chars=3000)
    assert "could not resolve dependency left-pad" in ex.text  # the anchor window
    assert "step output 99" in ex.text and "step output 101" in ex.text
    assert "step output 499" in ex.text  # the tail
    assert "step output 300" not in ex.text  # the boring middle is gone
    assert "lines omitted" in ex.text and ex.truncated
    assert len(ex.text) <= 3000 + 200  # budget plus the omission markers


def test_when_room_is_tight_the_latest_errors_win() -> None:
    lines = [f"noise {i}" for i in range(300)]
    lines[20] = "ERROR: early problem"
    lines[250] = "ERROR: late problem"
    ex = build_excerpt("\n".join(lines), max_chars=520)
    assert "late problem" in ex.text and "early problem" not in ex.text


def test_the_budget_is_respected_even_for_huge_logs_and_it_is_fast() -> None:
    raw = "\n".join(f"line {i} error somewhere" for i in range(60_000))
    started = time.monotonic()
    ex = build_excerpt(raw, max_chars=5000)
    assert time.monotonic() - started < 5
    assert len(ex.text) <= 5000 + 100 * 40 and ex.truncated


def test_withheld_lines_are_reported_and_never_reach_the_excerpt() -> None:
    ex = build_excerpt(f"start\npassword = '{'x' * 24}'\nERROR: boom\nend", max_chars=1000)
    assert ex.withheld_lines == 1 and "xxxx" not in ex.text and WITHHELD in ex.text


def test_a_log_cut_before_it_reached_us_is_marked_truncated() -> None:
    assert build_excerpt("a\nb", max_chars=1000, cut_before=True).truncated
