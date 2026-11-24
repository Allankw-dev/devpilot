# Self-hosting

You can run DevPilot on your own machine without paying DevPilot anything. You do need three outside
accounts, all with free tiers: a **Supabase** project (sign-in), a **GitHub App** (repository
access) and an **AI provider key** (Gemini by default).

> **Status: development setup only.** The steps below run the app locally with `uvicorn` and
> `npm run dev`. There are no production Docker images for the API or web app yet, and a production
> deployment (HTTPS, process supervision, backups) is not documented or tested. Don't expose an
> instance to the internet until you have read [`SECURITY.md`](../SECURITY.md) and the known issues in
> [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md). Docker Compose here starts PostgreSQL and
> Redis only.

## What you need

| Tool | Version |
|---|---|
| Docker (with Compose) | any recent version |
| Python | 3.12 or newer |
| Node.js | 22 or newer |
| Git | any |

Commands are for Windows PowerShell. On macOS or Linux, replace `copy` with `cp` and
`.venv\Scripts\Activate.ps1` with `source .venv/bin/activate`.

## 1. Get the code and the services

```powershell
git clone https://github.com/Allankw-dev/devpilot.git
cd devpilot
copy .env.example .env
docker compose up -d
```

Docker Compose starts PostgreSQL (with pgvector) and Redis on non-default host ports so they don't
clash with other tools:

| Service | Host port |
|---|---|
| Web | 3001 |
| API | 8001 |
| PostgreSQL | 15433 |
| Redis | 6380 |

Check both are healthy: `docker compose ps` should show `healthy` for `db` and `redis`.

## 2. Fill in `.env`

Edit the `.env` file in the repository root. Nothing in it has a working default for the three outside
services, and the file is ignored by Git, so never commit it.

| Setting | Where to get it | Guide |
|---|---|---|
| `SUPABASE_URL` | your Supabase project | [`AUTH.md`](AUTH.md) |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_APP_PRIVATE_KEY_PATH` | your GitHub App | [`GITHUB.md`](GITHUB.md) |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL` | Google AI Studio | [`AI.md`](AI.md) |

Model names have no default on purpose: providers rename and retire models, so pick current ones
from your provider's model list. Keep the GitHub App's `.pem` file **outside** the repository.

Then create the web app's file `apps\web\.env.local` with only the `NEXT_PUBLIC_*` lines from
`.env.example` filled in:

```powershell
copy .env.example apps\web\.env.local
```

Delete every line that doesn't start with `NEXT_PUBLIC_` from that copy: those other values are
server secrets and must not sit in a web app folder.

## 3. Start the API and the worker

```powershell
cd apps\api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

In a second terminal, start the background worker (it runs GitHub syncs, indexing, reviews and CI
analyses). On Windows the `solo` pool is required:

```powershell
cd apps\api
.venv\Scripts\Activate.ps1
celery -A app.jobs.celery_app worker --loglevel=info --pool=solo
```

No worker? Set `JOB_BACKEND=inline` in `.env` and restart the API. Jobs then run inside the API
process, which is simpler but loses a running job if the API restarts.

## 4. Start the web app

```powershell
cd apps\web
npm install
npm run dev
```

Open <http://localhost:3001>.

## 5. Check that it works

1. <http://localhost:8001/api/v1/health> shows the API, database and Redis as `ok`.
2. Sign up at `/login`, land on the dashboard and create an organization. You become its owner.
3. On **Integrations**, click **Connect GitHub**, choose repositories, and wait for the first sync.
4. On **Integrations**, click **Test AI connection** (admins only). It sends one tiny prompt.
5. On **Repositories**, index one, then ask a question on **Assistant**.

## What leaves your machine

DevPilot never sends code anywhere you didn't configure.

- **GitHub:** the app talks to GitHub's API with your GitHub App (read-only). GitHub tokens stay on the server.
- **Your AI provider** (Gemini unless you change `LLM_PROVIDER`): receives pieces of your code to
  embed when you index, and the question plus retrieved code when you ask, review or analyze. Chunks
  and diff lines that look like credentials are withheld first, but this is a safety net, not a
  guarantee. If code must not leave your network, don't connect that repository.
- **Supabase:** handles sign-in (email, and GitHub identity if you enable it). It does not receive code.
- Usage records store counts, token numbers, model names and error codes. Never prompts or replies.

## Updating

```powershell
git pull
cd apps\api
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
alembic upgrade head
cd ..\web
npm install
```

Restart the API, the worker and the web app. Read the newest entries of
[`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) first for anything you need to do by hand.

## Troubleshooting

| You see | Likely cause |
|---|---|
| API can't connect to the database | `docker compose ps`; the database is on port **15433**, so make sure `DATABASE_URL` in `.env` says 15433 |
| 503 "Authentication is not configured" | `SUPABASE_URL` is empty; set it and restart the API |
| Sign-in page loads but nothing works | `apps\web\.env.local` is missing, or was changed after `npm run dev` started: restart it |
| Sync or indexing stuck on "Queued…" | the worker isn't running or can't reach Redis |
| 503 "job queue is not reachable" | Redis is down: `docker compose up -d` |
| AI features fail with a quota message | free tiers allow few requests per day (Gemini's free tier is about 20 per model); wait, or use a paid key |
| "Missing settings: ..." | fill in `.env`, then restart the API **and** the worker |
| Port already in use | something else holds 3001, 8001, 15433 or 6380; stop it or change the port in `docker-compose.yml`, `.env` and the commands |

More detail per feature: [`INDEXING.md`](INDEXING.md), [`ASK.md`](ASK.md), [`REVIEWS.md`](REVIEWS.md),
[`CI.md`](CI.md), [`USAGE.md`](USAGE.md).
