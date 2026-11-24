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


@pytest.mark.parametrize("value", ["production", "PRODUCTION", " prod ", "Production"])
def test_production_environment_is_recognised(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", value)
    assert Settings().is_production is True


@pytest.mark.parametrize("value", ["development", "test", "staging", ""])
def test_other_environments_are_not_production(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", value)
    assert Settings().is_production is False
