import pytest

from app.core.config import Settings


def test_cors_origins_single_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    assert Settings().cors_origins == ["http://localhost:3000"]


def test_cors_origins_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, https://b.com")
    assert Settings().cors_origins == ["http://a.com", "https://b.com"]


def test_cors_origins_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.com","https://b.com"]')
    assert Settings().cors_origins == ["http://a.com", "https://b.com"]


def test_product_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCT_NAME", "Acme Pilot")
    assert Settings().product_name == "Acme Pilot"
