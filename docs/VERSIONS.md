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
| eslint | 8.57 |

Tailwind is on v3 because shadcn/ui's config and plugins are most stable there.
Celery, Gemini SDK, auth and pgvector columns arrive in later phases.
