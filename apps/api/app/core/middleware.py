"""Request ids, security headers, access logging and a last-resort error response.

Written as plain ASGI middleware (not `BaseHTTPMiddleware`) so streaming responses keep working.

- Every response carries `X-Request-ID`. A caller may supply one; it is only kept if it is short and
  made of letters, digits, `.`, `_` and `-`. Anything else is replaced, so a caller can't put odd
  characters into our logs.
- Every response gets the security headers below. An endpoint that sets its own `Cache-Control`
  keeps it.
- One access-log line per request: method, path, status and time. Never the query string, headers or
  body, because those can hold tokens.
- An unexpected exception becomes a JSON 500 that names the request id and nothing else. The
  traceback goes to the log, not to the caller.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import REQUEST_ID

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_SUFFIXES = ("/health", "/health/live", "/health/ready")  # probes run every few seconds


def is_docs_path(path: str) -> bool:
    """The interactive API docs load scripts from a CDN, so the strict API policy can't apply."""
    return path in ("/docs", "/redoc") or path.startswith(("/docs/", "/redoc/"))


def security_headers(path: str, *, hsts: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",  # responses hold private organization data
    }
    if not is_docs_path(path):
        # The API only returns JSON, so nothing it sends should ever load or be framed.
        headers["X-Frame-Options"] = "DENY"
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers


def _incoming_request_id(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            candidate = bytes(value).decode("latin-1")
            if _SAFE_REQUEST_ID.fullmatch(candidate):
                return str(candidate)
            break
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        token = REQUEST_ID.set(request_id)
        path: str = scope["path"]
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for name, value in security_headers(path, hsts=self.hsts).items():
                    headers.setdefault(name, value)
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_headers)
            except Exception:
                logger.exception("Unhandled error while handling a request")
                if response_started:  # too late to send an error page; let the server close it
                    raise
                response = JSONResponse(
                    {
                        "detail": f"Internal server error (request id: {request_id})",
                        "request_id": request_id,
                    },
                    status_code=500,
                )
                await response(scope, receive, send_with_headers)
        finally:
            quiet = path.endswith(_QUIET_SUFFIXES)
            logger.log(
                logging.DEBUG if quiet else logging.INFO,
                "request",
                extra={
                    "http": {
                        "method": scope["method"],
                        "path": path,
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            REQUEST_ID.reset(token)
