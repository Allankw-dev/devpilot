"""A fake GitHub (REST + OAuth) served through httpx.MockTransport, plus data builders."""

import io
import json
import re
import tarfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import jwt
from fastapi.testclient import TestClient
from httpx import Response

CLIENT_ID = "Iv1.test"
CLIENT_SECRET = "client-secret"
WEBHOOK_SECRET = "whsec-test"
INSTALLATION_ID = 777


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- builders ----------


def make_tarball(
    files: dict[str, str | bytes],
    *,
    prefix: str = "octo-org-repo-abc1234",
    extra: Callable[[tarfile.TarFile], None] | None = None,
) -> bytes:
    """A .tar.gz shaped like GitHub's repository snapshots: everything under one top folder."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        top = tarfile.TarInfo(prefix)
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if extra:
            extra(tar)
    return buf.getvalue()



def make_repo(
    gid: int,
    full_name: str,
    *,
    default_branch: str = "main",
    private: bool = False,
    pushed: str = "2026-11-01T10:00:00Z",
    language: str | None = "Python",
) -> dict[str, Any]:
    owner, name = full_name.split("/")
    return {
        "id": gid,
        "name": name,
        "full_name": full_name,
        "private": private,
        "archived": False,
        "owner": {"login": owner},
        "default_branch": default_branch,
        "description": f"{name} repo",
        "html_url": f"https://github.com/{full_name}",
        "language": language,
        "pushed_at": pushed,
    }


def make_pr(
    number: int,
    state: str = "open",
    *,
    title: str | None = None,
    merged: bool = False,
    draft: bool = False,
    user: str = "octo",
) -> dict[str, Any]:
    return {
        "number": number,
        "id": 9000 + number,
        "title": title or f"PR {number}",
        "state": state,
        "draft": draft,
        "merged_at": "2026-11-02T00:00:00Z" if merged else None,
        "user": {"login": user},
        "html_url": f"https://github.com/x/y/pull/{number}",
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T00:00:00Z",
        "closed_at": None if state == "open" else "2026-11-02T00:00:00Z",
    }


def make_issue(
    number: int, state: str = "open", *, title: str | None = None, pull_request: bool = False
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "number": number,
        "id": 8000 + number,
        "title": title or f"Issue {number}",
        "state": state,
        "user": {"login": "octo"},
        "html_url": f"https://github.com/x/y/issues/{number}",
        "comments": 2,
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T00:00:00Z",
        "closed_at": None if state == "open" else "2026-11-02T00:00:00Z",
    }
    if pull_request:
        issue["pull_request"] = {"url": "https://api.github.com/..."}
    return issue


def make_commit(
    sha: str,
    message: str = "Fix bug\n\nlong body",
    login: str | None = "octo",
    date: str = "2026-11-03T12:00:00Z",
) -> dict[str, Any]:
    return {
        "sha": sha,
        "html_url": f"https://github.com/x/y/commit/{sha}",
        "author": {"login": login} if login else None,
        "commit": {"message": message, "author": {"name": "Octo Cat", "date": date}},
    }


def make_run(
    run_id: int,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    branch: str = "main",
    created: str = "2026-11-03T12:00:00Z",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "CI",
        "event": "push",
        "status": status,
        "conclusion": conclusion,
        "head_branch": branch,
        "head_sha": "a" * 40,
        "run_number": run_id,
        "html_url": f"https://github.com/x/y/actions/runs/{run_id}",
        "created_at": created,
        "updated_at": created,
    }


# ---------- the fake server ----------


class FakeGitHub:
    def __init__(self, public_key: Any, app_id: str = "12345") -> None:
        self.public_key = public_key
        self.app_id = app_id
        self.installations: dict[int, dict[str, Any]] = {}
        self.codes: dict[str, set[int]] = {}
        self.user_tokens: dict[str, set[int]] = {}
        self.repos: dict[int, list[dict[str, Any]]] = {}
        self.data: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.token_requests = 0
        self.fail: dict[str, tuple[int, dict[str, str]]] = {}
        self.codeload_auth: list[str | None] = []  # Authorization header seen by the download host

    # -- setup helpers --
    def add_installation(
        self,
        iid: int = INSTALLATION_ID,
        login: str = "octo-org",
        account_type: str = "Organization",
    ) -> None:
        self.installations[iid] = {
            "id": iid,
            "account": {"id": 55, "login": login, "type": account_type},
            "repository_selection": "selected",
            "suspended_at": None,
        }
        self.repos.setdefault(iid, [])

    def add_repo(self, iid: int, repo: dict[str, Any], **data: Any) -> None:
        self.repos[iid].append(repo)
        self.data[repo["full_name"]] = {
            "pulls_open": [],
            "pulls_closed": [],
            "issues_open": [],
            "issues_closed": [],
            "commits": [],
            "runs": [],
            **data,
        }

    def _archive(self, full: str) -> bytes:
        d = self.data[full]
        if "archive" in d:  # tests can hand over any bytes, e.g. a hostile archive
            return bytes(d["archive"])
        head = str(d.get("head_sha", "a" * 40))
        return make_tarball(d.get("files", {}), prefix=f"{full.replace('/', '-')}-{head[:7]}")

    # -- the handler --
    def handler(self, request: httpx.Request) -> Response:
        path, method = request.url.path, request.method
        self.calls.append(f"{method} {path}")
        if request.url.host == "codeload.github.com":  # where tarball redirects end up
            self.codeload_auth.append(request.headers.get("authorization"))
            owner_repo = "/".join(path.strip("/").split("/")[:2])
            # A real stream, like a network response, so the client's streaming path is exercised.
            return Response(
                200,
                stream=httpx.ByteStream(self._archive(owner_repo)),
                headers={"content-type": "application/x-gzip"},
            )
        for needle, (status, headers) in self.fail.items():
            if needle in path:
                return Response(status, headers=headers, json={"message": "failure injected"})

        q = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        auth = request.headers.get("authorization", "").removeprefix("Bearer ")

        def page(items: list[Any]) -> list[Any]:
            p, pp = int(q.get("page", 1)), int(q.get("per_page", 30))
            return items[(p - 1) * pp : p * pp]

        if path == "/login/oauth/access_token" and method == "POST":
            body = json.loads(request.content)
            code = body.get("code")
            if (
                body.get("client_id") != CLIENT_ID
                or body.get("client_secret") != CLIENT_SECRET
                or code not in self.codes
            ):
                return Response(200, json={"error": "bad_verification_code"})
            self.user_tokens[f"ghu_{code}"] = self.codes.pop(code)  # codes are single use
            return Response(200, json={"access_token": f"ghu_{code}", "token_type": "bearer"})

        if path == "/user/installations":
            ids = self.user_tokens.get(auth)
            if ids is None:
                return Response(401, json={"message": "Bad credentials"})
            items = [{"id": i} for i in sorted(ids)]
            return Response(200, json={"total_count": len(items), "installations": page(items)})

        m = re.fullmatch(r"/app/installations/(\d+)(/access_tokens)?", path)
        if m:
            try:
                claims = jwt.decode(
                    auth,
                    self.public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False, "verify_iat": False, "verify_exp": False},
                )
                assert claims["iss"] == self.app_id
            except Exception:
                return Response(401, json={"message": "bad app jwt"})
            iid = int(m.group(1))
            if iid not in self.installations:
                return Response(404, json={"message": "Not Found"})
            if m.group(2):
                self.token_requests += 1
                return Response(
                    201,
                    json={
                        "token": f"ghs_{iid}_{self.token_requests}",
                        "expires_at": iso(datetime.now(UTC) + timedelta(hours=1)),
                    },
                )
            return Response(200, json=self.installations[iid])

        tm = re.fullmatch(r"ghs_(\d+)_\d+", auth)
        if not tm:
            return Response(401, json={"message": "Bad credentials"})
        iid = int(tm.group(1))
        if iid not in self.installations:  # uninstalled: GitHub revokes its tokens
            return Response(401, json={"message": "Bad credentials"})

        if path == "/installation/repositories":
            repos = self.repos.get(iid, [])
            return Response(200, json={"total_count": len(repos), "repositories": page(repos)})

        cm = re.fullmatch(r"/repos/([^/]+/[^/]+)/commits/([^/]+)", path)
        if cm:
            full = cm.group(1)
            if full not in {r["full_name"] for r in self.repos.get(iid, [])}:
                return Response(404, json={"message": "Not Found"})
            if self.data[full].get("empty"):
                return Response(409, json={"message": "Git Repository is empty."})
            return Response(200, json={"sha": self.data[full].get("head_sha", "a" * 40)})

        am = re.fullmatch(r"/repos/([^/]+/[^/]+)/tarball/([^/]+)", path)
        if am:
            full, ref = am.groups()
            if full not in {r["full_name"] for r in self.repos.get(iid, [])}:
                return Response(404, json={"message": "Not Found"})
            return Response(
                302, headers={"location": f"https://codeload.github.com/{full}/legacy.tar.gz/{ref}"}
            )

        rm = re.fullmatch(r"/repos/([^/]+/[^/]+)/(pulls|issues|commits|actions/runs)", path)
        if rm:
            full, kind = rm.groups()
            if full not in {r["full_name"] for r in self.repos.get(iid, [])}:
                return Response(404, json={"message": "Not Found"})
            d = self.data[full]
            state = q.get("state", "open")
            if kind == "pulls":
                return Response(200, json=page(d[f"pulls_{state}"]))
            if kind == "issues":
                if d.get("issues_disabled"):  # GitHub answers 410 Gone, e.g. on forks
                    return Response(410, json={"message": "Issues are disabled for this repo"})
                return Response(200, json=page(d[f"issues_{state}"]))
            if kind == "commits":
                if d.get("empty"):
                    return Response(409, json={"message": "Git Repository is empty."})
                return Response(200, json=page(d["commits"]))
            return Response(
                200, json={"total_count": len(d["runs"]), "workflow_runs": page(d["runs"])}
            )

        return Response(404, json={"message": f"unhandled {path}"})


def standard_world(fake: FakeGitHub) -> None:
    """One installation with two repos: 'api' (healthy) and 'web' (failing CI)."""
    fake.add_installation()
    fake.add_repo(
        INSTALLATION_ID,
        make_repo(101, "octo-org/api"),
        pulls_open=[make_pr(1), make_pr(2, draft=True)],
        pulls_closed=[make_pr(3, "closed", merged=True)],
        issues_open=[make_issue(10), make_issue(1, pull_request=True)],  # PRs also show up here
        issues_closed=[make_issue(11, "closed")],
        commits=[make_commit("a" * 40, "Add login"), make_commit("b" * 40, "Fix typo", login=None)],
        runs=[make_run(1, conclusion="success")],
    )
    fake.add_repo(
        INSTALLATION_ID,
        make_repo(102, "octo-org/web", language="TypeScript"),
        commits=[make_commit("c" * 40, "Update deps", date="2026-11-04T08:00:00Z")],
        runs=[make_run(2, conclusion="failure")],
    )


# ---------- HTTP-level helpers ----------


def start_connect(client: TestClient, headers: dict[str, str], org_id: str) -> str:
    res = client.post(f"/api/v1/orgs/{org_id}/github/install-url", headers=headers)
    assert res.status_code == 200, res.text
    return str(parse_qs(urlparse(res.json()["url"]).query)["state"][0])


def connect(
    client: TestClient,
    fake: FakeGitHub,
    headers: dict[str, str],
    org_id: str,
    *,
    code: str = "good-code",
    installation_id: int = INSTALLATION_ID,
    with_state: bool = True,
    accessible: set[int] | None = None,
) -> httpx2.Response:
    state = start_connect(client, headers, org_id)
    fake.codes[code] = {installation_id} if accessible is None else accessible
    body: dict[str, Any] = {"code": code, "installation_id": installation_id}
    if with_state:
        body["state"] = state
    res: httpx2.Response = client.post("/api/v1/github/installations/claim", json=body, headers=headers)
    return res


def post_hook(
    client: TestClient,
    event: str,
    payload: dict[str, Any],
    *,
    delivery: str | None = None,
    secret: str = WEBHOOK_SECRET,
    signature: str | None = None,
    raw: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    import hashlib
    import hmac
    import uuid

    body = raw if raw is not None else json.dumps(payload).encode()
    sig = signature or "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    h = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery or str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    h.update(headers or {})
    res: httpx2.Response = client.post("/api/v1/webhooks/github", content=body, headers=h)
    return res


Handler = Callable[[httpx.Request], Response]
