"""Request ids, security headers, access logging, error responses, CORS and production mode."""

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logging import JsonFormatter
from app.core.middleware import RequestContextMiddleware
from app.core.request_context import REQUEST_ID, get_request_id
from app.main import app, create_app


def make_app(*, hsts: bool = False) -> FastAPI:
    """A tiny app with the middleware and a few endpoints that behave in the ways we care about."""
    small = FastAPI(docs_url="/docs")
    small.add_middleware(RequestContextMiddleware, hsts=hsts)

    @small.get("/ok")
    def ok() -> dict[str, str | None]:
        return {"request_id": get_request_id()}

    @small.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @small.get("/cached")
    def cached() -> Response:
        return Response("x", headers={"Cache-Control": "public, max-age=60"})

    @small.get("/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(iter([b"one,", b"two"]), media_type="text/plain")

    @small.get("/api/v1/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    return small


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_app())


# ---------- request ids ----------


def test_every_response_has_a_request_id_the_handler_can_see(client: TestClient) -> None:
    res = client.get("/ok")
    request_id = res.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert res.json()["request_id"] == request_id  # context reaches the threadpool handler


def test_each_request_gets_its_own_id(client: TestClient) -> None:
    first = client.get("/ok").headers["X-Request-ID"]
    second = client.get("/ok").headers["X-Request-ID"]
    assert first != second


def test_a_valid_incoming_request_id_is_kept(client: TestClient) -> None:
    res = client.get("/ok", headers={"X-Request-ID": "web-1234.abcd_EF"})
    assert res.headers["X-Request-ID"] == "web-1234.abcd_EF"
    assert res.json()["request_id"] == "web-1234.abcd_EF"


@pytest.mark.parametrize(
    "bad",
    ["short", "a" * 65, "has spaces in it", "<script>alert(1)</script>", "semi;colon,comma"],
)
def test_an_unsafe_incoming_request_id_is_replaced(client: TestClient, bad: str) -> None:
    res = client.get("/ok", headers={"X-Request-ID": bad})
    assert res.headers["X-Request-ID"] != bad
    assert len(res.headers["X-Request-ID"]) == 32


def test_request_id_is_cleared_after_the_request(client: TestClient) -> None:
    client.get("/ok")
    assert REQUEST_ID.get() is None


# ---------- security headers ----------


def test_security_headers_are_on_every_response(client: TestClient) -> None:
    res = client.get("/ok")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert res.headers["Cache-Control"] == "no-store"
    assert res.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "Strict-Transport-Security" not in res.headers  # only when hsts is on


def test_headers_are_added_to_404s_too(client: TestClient) -> None:
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Request-ID"]


def test_an_endpoint_can_keep_its_own_cache_control(client: TestClient) -> None:
    assert client.get("/cached").headers["Cache-Control"] == "public, max-age=60"


def test_hsts_only_when_enabled() -> None:
    res = TestClient(make_app(hsts=True)).get("/ok")
    assert res.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_docs_pages_keep_nosniff_but_not_the_strict_policy(client: TestClient) -> None:
    res = client.get("/docs")
    assert res.status_code == 200
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" not in res.headers
    assert "X-Frame-Options" not in res.headers


def test_streaming_responses_still_work(client: TestClient) -> None:
    res = client.get("/stream")
    assert res.text == "one,two"
    assert res.headers["X-Request-ID"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"


# ---------- unexpected errors ----------


def test_an_unexpected_error_is_a_json_500_without_details(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        res = client.get("/boom")
    request_id = res.headers["X-Request-ID"]
    assert res.status_code == 500
    assert res.json() == {
        "detail": f"Internal server error (request id: {request_id})",
        "request_id": request_id,
    }
    assert "secret internal detail" not in res.text
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    # the cause is in the log, tied to the same id
    errors = [r for r in caplog.records if r.exc_info]
    assert errors and "secret internal detail" in str(errors[0].exc_info)
    access = [r for r in caplog.records if getattr(r, "http", None)]
    assert access[-1].http["status"] == 500  # type: ignore[attr-defined]


# ---------- access log ----------


def test_access_log_has_method_path_status_and_time_but_no_query(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/ok?token=hunter2&password=letmein", headers={"Authorization": "Bearer abc"})
    records = [r for r in caplog.records if getattr(r, "http", None)]
    assert len(records) == 1
    http = records[0].http  # type: ignore[attr-defined]
    assert http["method"] == "GET"
    assert http["path"] == "/ok"
    assert http["status"] == 200
    assert http["duration_ms"] >= 0
    everything = json.dumps(http) + records[0].getMessage()
    assert "hunter2" not in everything and "letmein" not in everything and "abc" not in everything


def test_health_probes_are_not_logged_at_info(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/api/v1/health/live")
    assert [r for r in caplog.records if getattr(r, "http", None)] == []


def test_json_formatter_includes_the_request_id_and_http_fields() -> None:
    record = logging.LogRecord("app.request", logging.INFO, __file__, 1, "request", None, None)
    record.http = {"status": 200}
    token = REQUEST_ID.set("req-12345678")
    try:
        out = json.loads(JsonFormatter().format(record))
    finally:
        REQUEST_ID.reset(token)
    assert out["request_id"] == "req-12345678"
    assert out["http"] == {"status": 200}
    assert out["message"] == "request"


def test_json_formatter_leaves_out_the_request_id_outside_a_request() -> None:
    record = logging.LogRecord("worker", logging.INFO, __file__, 1, "job done", None, None)
    out = json.loads(JsonFormatter().format(record))
    assert "request_id" not in out


# ---------- the real app ----------


def test_real_app_endpoints_carry_the_headers() -> None:
    client = TestClient(app)
    live = client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.headers["X-Request-ID"]
    assert live.headers["Content-Security-Policy"].startswith("default-src 'none'")
    unauthorized = client.get("/api/v1/me")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["X-Content-Type-Options"] == "nosniff"
    assert unauthorized.headers["X-Request-ID"]


def test_real_app_docs_work_in_development() -> None:
    client = TestClient(app)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


# ---------- CORS ----------


def _origin() -> str:
    return get_settings().cors_origins[0]


def test_cors_exposes_the_request_id_to_the_browser() -> None:
    res = TestClient(app).get("/api/v1/health/live", headers={"Origin": _origin()})
    assert res.headers["Access-Control-Allow-Origin"] == _origin()
    assert "X-Request-ID" in res.headers["Access-Control-Expose-Headers"]


def test_cors_preflight_allows_the_headers_the_web_app_sends() -> None:
    res = TestClient(app).options(
        "/api/v1/me",
        headers={
            "Origin": _origin(),
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert res.status_code == 200


def test_cors_preflight_refuses_unexpected_headers_and_methods() -> None:
    client = TestClient(app)
    odd_header = client.options(
        "/api/v1/me",
        headers={
            "Origin": _origin(),
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-custom-thing",
        },
    )
    assert odd_header.status_code == 400
    odd_method = client.options(
        "/api/v1/me", headers={"Origin": _origin(), "Access-Control-Request-Method": "TRACE"}
    )
    assert odd_method.status_code == 400


def test_cors_refuses_an_unlisted_origin() -> None:
    res = TestClient(app).get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in res.headers


# ---------- production mode ----------


@pytest.fixture
def production_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level  # create_app resets logging
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        yield create_app()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        root.handlers, root.level = saved_handlers, saved_level


def test_production_hides_the_api_docs_and_turns_on_hsts(production_app: FastAPI) -> None:
    client = TestClient(production_app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    live = client.get("/api/v1/health/live")
    assert live.headers["Strict-Transport-Security"] == "max-age=31536000"
