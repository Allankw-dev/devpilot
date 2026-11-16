import pytest

from app.services.github.client import GitHubClient, GitHubError, GitHubRateLimited
from tests.ci_helpers import REPO
from tests.github_helpers import INSTALLATION_ID, FakeGitHub


def fetch(gh: GitHubClient, job_id: int = 1, max_bytes: int = 1000) -> tuple[str, bool]:
    return gh.installation_job_log(INSTALLATION_ID, REPO, job_id, max_bytes=max_bytes)


def put(fake: FakeGitHub, job_id: int, text: str) -> None:
    fake.data[REPO].setdefault("job_logs", {})[job_id] = text


def test_a_small_log_comes_back_whole(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    put(fake_github, 1, "line one\nline two\n")
    assert fetch(gh_client) == ("line one\nline two\n", False)


def test_only_the_end_of_a_big_log_is_kept_and_a_torn_first_line_is_dropped(
    gh_client: GitHubClient, fake_github: FakeGitHub
) -> None:
    put(fake_github, 1, "".join(f"line {i:04d}\n" for i in range(1000)))  # 10,000 bytes
    text, cut = fetch(gh_client, max_bytes=200)
    assert cut is True and len(text.encode()) <= 200
    assert text.endswith("line 0999\n") and text.startswith("line ")  # starts on a whole line
    assert "line 0000" not in text


def test_the_token_goes_to_github_but_not_to_the_log_host(
    gh_client: GitHubClient, fake_github: FakeGitHub
) -> None:
    put(fake_github, 1, "ok")
    fetch(gh_client)
    assert any("/actions/jobs/1/logs" in c for c in fake_github.calls)
    assert fake_github.log_auth == [None]


def test_an_expired_log_is_a_404(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    with pytest.raises(GitHubError) as err:
        fetch(gh_client, job_id=999)
    assert err.value.status == 404


def test_rate_limiting_is_reported_as_such(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    put(fake_github, 1, "ok")
    fake_github.fail["/logs"] = (403, {"x-ratelimit-remaining": "0"})
    with pytest.raises(GitHubRateLimited):
        fetch(gh_client)


def test_a_runaway_log_is_refused(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    put(fake_github, 1, "x" * 21_000_000)
    with pytest.raises(GitHubError) as err:
        fetch(gh_client, max_bytes=100)
    assert err.value.status == 413
