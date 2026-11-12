"""What a job needs to run. A worker has no web request, so it builds these for itself."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.services.github.client import GitHubClient
from app.services.llm import LLMService
from app.services.llm.factory import get_llm_service


@dataclass
class JobResources:
    factory: sessionmaker[Session]
    github: GitHubClient
    get_llm: Callable[[], LLMService]
    settings: Settings


@lru_cache
def _default() -> JobResources:
    settings = get_settings()
    return JobResources(get_session_factory(), GitHubClient(settings), get_llm_service, settings)


_override: JobResources | None = None


def resources() -> JobResources:
    return _override or _default()


def set_resources(value: JobResources | None) -> None:
    """For tests: run tasks against fakes."""
    global _override
    _override = value
