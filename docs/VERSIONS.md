# Versions

Resolved and verified on 2026-11-08. Exact API pins live in `apps/api/requirements.lock`,
web pins in `apps/web/package-lock.json`. Bump deliberately, then re-run CI.

## Runtime
| Tool | Version |
|---|---|
| Python | 3.12 |
| Node.js | 22 LTS |
| PostgreSQL | 16 (`pgvector/pgvector:pg16`) |
| Redis | 7 |

## API (apps/api)
| Package | Version |
|---|---|
| fastapi | 0.162.2 |
| uvicorn | 0.54.0 |
| pydantic / pydantic-settings | 2.14.3 / 2.16.2 |
| SQLAlchemy | 2.0.57 |
| alembic | 1.20.1 |
| psycopg | 3.3.8 |
| redis (client) | 6.4.0 |
| pgvector (client) | 0.5.1 |
| PyJWT / cryptography | 2.15.1 / 50.0.2 |
| httpx (GitHub client) | 0.28.1 |
| google-genai (Gemini) | 3.0.0 |
| anthropic (optional provider) | 2.7.0 |
| httpx2 (dev: starlette TestClient) | 2.16.0 |
| celery[redis] | 5.7.0 |
| celery-types (dev, type stubs) | 0.26.0 |
| ruff / mypy / pytest | 0.17.4 / 1.20.2 / 8.4.2 |

## Web (apps/web)
| Package | Version |
|---|---|
| next | 15.5.x |
| react / react-dom | 19.x |
| tailwindcss | 3.4.x |
| typescript | 5.9.x |
| @tanstack/react-query | 5.x |
| zustand | 5.x |
| @supabase/supabase-js / @supabase/ssr | 2.119.0 / 0.12.7 |
| eslint | 8.57 |

Tailwind is on v3 because shadcn/ui's config and plugins are most stable there.
Celery runs the worker; pgvector stores the 768-dimension code embeddings (HNSW, cosine).

Model names are never pinned in code (see `docs/AI.md`). `google-genai` and `anthropic` pull in
`httpx2`, which makes `starlette.testclient` use it instead of `httpx`, so the tests import
`httpx2` types for TestClient responses.

GitHub REST API version is pinned to `2022-11-28` (setting `GITHUB_API_VERSION`).
GitHub released `2026-03-10` with breaking changes; upgrade deliberately, not by accident.
Sync runs as a FastAPI background task for now. Celery arrives with the indexing phase.
