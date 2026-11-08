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
uvicorn app.main:app --reload --port 8000

# Web (new terminal)
cd apps\web
copy ..\..\.env.example .env.local   # keep only the NEXT_PUBLIC_* lines
npm install
npm run dev
```

Open http://localhost:3000. The page shows API, database and Redis status.
Health endpoint: http://localhost:8000/api/v1/health

## Checks

```powershell
cd apps\api; pytest; ruff check .; mypy .
cd apps\web; npm run lint; npm run typecheck; npm run build
```
