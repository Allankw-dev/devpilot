# DevPilot AI.

Your AI engineering partner. Open-source AI developer productivity platform: index your repositories,
ask questions about your code with checked citations, review pull requests and understand failed CI runs.

**Status: early development.** GitHub access is read-only, and there is no production deployment guide yet.
See [`ROADMAP.md`](ROADMAP.md) for what is planned and [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md)
for what works today. Project rules are in `CLAUDE.md`; versions are in `docs/VERSIONS.md`.

## Local setup

Prerequisites: Docker, Python 3.12+, Node 22+. The full walkthrough (Supabase, GitHub App, AI key,
what data leaves your machine) is in [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md).

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

Open http://localhost:3001. The page shows API, database and Redis status./
Health endpoint: http://localhost:8001/api/v1/health

## Auth

Sign-in uses Supabase Auth; organizations, teams and roles live in our own Postgres.
Setup steps are in [`docs/AUTH.md`](docs/AUTH.md). After pulling new migrations run
`alembic upgrade head` in `apps\api`.

## GitHub

Repositories, pull requests, issues, commits and CI runs come from a read-only GitHub App.
Setup, including the webhook tunnel for local testing, is in [`docs/GITHUB.md`](docs/GITHUB.md).

## AI

Gemini through a provider abstraction (Anthropic optional). Needs an API key and model names in
`.env`; see [`docs/AI.md`](docs/AI.md). Verify with **Test AI connection** on the Integrations page.

## Background jobs and code search

GitHub syncs and repository indexing run on a Celery worker (Redis is the queue):

```powershell
cd apps/api
celery -A app.jobs.celery_app worker --loglevel=info --pool=solo   # Windows
```

No worker yet? Set `JOB_BACKEND=inline` to run jobs inside the API. See
[`docs/INDEXING.md`](docs/INDEXING.md) for indexing, limits, exclusions and troubleshooting.

## Ask questions about your code

Once a repository is indexed, ask things like "where is authentication implemented?" and get an
answer with citations to exact files and lines. See [`docs/ASK.md`](docs/ASK.md).

## Pull request reviews

Click **Review** on a pull request for an AI review with findings (file, lines, severity, suggested fix).
Nothing is posted to GitHub. See [`docs/REVIEWS.md`](docs/REVIEWS.md).

## CI failure analysis

Click **Analyze** on a failed GitHub Actions run for an AI explanation of what broke and why, with
quotes from the logs. Credential-looking lines never reach the model. Nothing is posted to GitHub or
re-run. See [`docs/CI.md`](docs/CI.md).

## Status and architecture

What works, what doesn't and the latest test results: [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).
How the code is organized: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). What changed and when:
[`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md).

Web tests: `cd apps/web; npm test`.

## AI usage

See where AI requests, tokens and errors go, per feature and model, and how close you are to your
provider's daily limit. See [`docs/USAGE.md`](docs/USAGE.md).

## Ports

DevPilot uses non-default host ports so it doesn't clash with other dev tools
(WSL port forwarding commonly takes 3000, 5432 and 8000):

| Service | Port |
|---|---|
| Web | 3001 |
| API | 8001 |
| Postgres (Docker) | 15433 |
| Redis (Docker) | 6380 |

## Checks

```powershell
cd apps\api; pytest; ruff check .; mypy .; alembic check
cd apps\web; npm run lint; npm run typecheck; npm run build
```

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first, and follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Need help? See [`SUPPORT.md`](SUPPORT.md).

## Security

Report vulnerabilities privately, not as public issues: see [`SECURITY.md`](SECURITY.md).

## License

Apache License 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
