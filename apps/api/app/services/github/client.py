"""Minimal GitHub REST client for a GitHub App.

- Authenticates as the App with a short-lived RS256 JWT, and as an installation with a
  one-hour installation token that is cached in memory only (never stored or logged).
- Retries transient failures, and raises a distinct error when GitHub rate-limits us.
- Tokens never leave the server.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt

from app.core.config import Settings

logger = logging.getLogger(__name__)


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubNotConfigured(GitHubError):
    """Required GitHub App settings are missing."""


class GitHubRateLimited(GitHubError):
    def __init__(self, message: str, reset_at: int | None = None) -> None:
        super().__init__(message, status=429)
        self.reset_at = reset_at


class GitHubClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_attempts: int = 3,
    ) -> None:
        self._s = settings
        self._http = httpx.Client(transport=transport, timeout=15.0)
        self._sleep = sleep
        self._clock = clock
        self._max_attempts = max_attempts
        self._tokens: dict[int, tuple[str, float]] = {}
        self._lock = threading.Lock()

    # ---------- authentication ----------

    def app_jwt(self) -> str:
        app_id = (self._s.github_app_id or "").strip()
        key = self._s.github_private_key()
        if not app_id or not key:
            raise GitHubNotConfigured("GitHub App ID or private key is not configured")
        now = int(self._clock())
        # GitHub allows at most 10 minutes; iat is backdated to tolerate clock drift.
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": app_id}, key, algorithm="RS256"
        )

    def installation_token(self, installation_id: int) -> str:
        with self._lock:
            cached = self._tokens.get(installation_id)
            if cached and cached[1] - 60 > self._clock():
                return cached[0]

        data = self._json(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            bearer=self.app_jwt(),
            expected=(201,),
        )
        token = str(data["token"])
        expires = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
        with self._lock:
            self._tokens[installation_id] = (token, expires.astimezone(UTC).timestamp())
        return token

    def forget_installation(self, installation_id: int) -> None:
        with self._lock:
            self._tokens.pop(installation_id, None)

    # ---------- low-level request ----------

    def _headers(self, bearer: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._s.github_api_version,
            "User-Agent": "devpilot",
        }

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                resp = self._http.request(
                    method, url, headers=headers, params=params, json=json_body
                )
            except httpx.TransportError as exc:
                last = exc
            else:
                if resp.status_code < 500:
                    return resp
                last = GitHubError(f"GitHub returned {resp.status_code}", resp.status_code)
            if attempt < self._max_attempts - 1:
                self._sleep(0.5 * (2**attempt))
        raise GitHubError(f"GitHub is unreachable or failing: {last}") from last

    @staticmethod
    def _check_rate_limit(resp: httpx.Response) -> None:
        if resp.status_code not in (403, 429):
            return
        limited = (
            resp.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in resp.headers
            or "rate limit" in resp.text.lower()
        )
        if limited:
            reset = resp.headers.get("x-ratelimit-reset")
            raise GitHubRateLimited(
                "GitHub rate limit reached", int(reset) if reset and reset.isdigit() else None
            )

    def _json(
        self,
        method: str,
        path: str,
        *,
        bearer: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        resp = self._send(
            method,
            f"{self._s.github_api_url.rstrip('/')}{path}",
            headers=self._headers(bearer),
            params=params,
            json_body=json_body,
        )
        self._check_rate_limit(resp)
        if resp.status_code not in expected:
            raise GitHubError(f"GitHub API {method} {path} failed", resp.status_code)
        return resp.json()

    # ---------- as the App ----------

    def get_installation(self, installation_id: int) -> dict[str, Any]:
        data: dict[str, Any] = self._json(
            "GET", f"/app/installations/{installation_id}", bearer=self.app_jwt()
        )
        return data

    # ---------- as a user (used once, during connect) ----------

    def exchange_code(self, code: str) -> str:
        client_id = (self._s.github_client_id or "").strip()
        secret = (
            self._s.github_client_secret.get_secret_value() if self._s.github_client_secret else ""
        )
        if not client_id or not secret:
            raise GitHubNotConfigured("GitHub client id/secret is not configured")
        resp = self._send(
            "POST",
            f"{self._s.github_web_url.rstrip('/')}/login/oauth/access_token",
            headers={"Accept": "application/json", "User-Agent": "devpilot"},
            json_body={"client_id": client_id, "client_secret": secret, "code": code},
        )
        body = resp.json() if resp.status_code == 200 else {}
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            # GitHub answers 200 with {"error": "bad_verification_code"} for a bad or used code
            raise GitHubError("GitHub rejected the authorization code", 400)
        return token

    def user_installation_ids(self, user_token: str) -> set[int]:
        ids: set[int] = set()
        for page in range(1, 6):
            data = self._json(
                "GET",
                "/user/installations",
                bearer=user_token,
                params={"per_page": 100, "page": page},
            )
            items = data.get("installations", [])
            ids.update(int(i["id"]) for i in items)
            if len(items) < 100:
                break
        return ids

    # ---------- as an installation ----------

    def installation_get(
        self, installation_id: int, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        try:
            return self._json(
                "GET", path, bearer=self.installation_token(installation_id), params=params
            )
        except GitHubError as exc:
            if exc.status != 401:
                raise
        # A cached token can be revoked early (e.g. the app was uninstalled). Mint a fresh one
        # once; if the installation is gone, that request fails with a clear 404.
        self.forget_installation(installation_id)
        return self._json(
            "GET", path, bearer=self.installation_token(installation_id), params=params
        )

    def installation_paginate(
        self,
        installation_id: int,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        per_page: int = 100,
        max_pages: int = 5,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Collect pages. Returns (items, complete). complete is False if max_pages cut it short."""
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            data = self.installation_get(
                installation_id, path, {**(params or {}), "per_page": per_page, "page": page}
            )
            batch = data.get(key, []) if key else data
            items.extend(batch)
            if len(batch) < per_page:
                return items, True
        return items, False
