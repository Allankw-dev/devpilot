# DevPilot AI

AI developer productivity platform. See `CLAUDE.md` for project rules and `docs/VERSIONS.md` for versions.

## Local setup

Prerequisites: Docker, Python 3.12+, Node 22+.

```powershell
copy .env.example .env
docker compose up -d

# API
cd apps\api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8001

# Web (new terminal)
cd apps\web
copy ..\..\.env.example .env.local   # keep only the NEXT_PUBLIC_* lines
npm install
npm run dev
```

Open http://localhost:3001. The page shows API, database and Redis status.
Health endpoint: http://localhost:8001/api/v1/health

## Auth

Sign-in uses Supabase Auth; organizations, teams and roles live in our own Postgres.
Setup steps are in [`docs/AUTH.md`](docs/AUTH.md). After pulling new migrations run
`alembic upgrade head` in `apps\api`.

## Ports

DevPilot uses non-default host ports so it doesn't clash with other dev tools
(WSL port forwarding commonly takes 3000, 5432 and 8000):

| Service | Port |
|---|---|
| Web | 3001 |
| API | 8001 |
| Postgres (Docker) | 5433 |
| Redis (Docker) | 6380 |

## Checks

```powershell
cd apps\api; pytest; ruff check .; mypy .; alembic check
cd apps\web; npm run lint; npm run typecheck; npm run build
```
