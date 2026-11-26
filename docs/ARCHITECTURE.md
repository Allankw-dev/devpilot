# Architecture

A monorepo with two apps and shared infrastructure.

```
apps/api   FastAPI service, Celery worker, Alembic migrations, tests
apps/web   Next.js 16 (App Router) web app
docs/      guides per feature (this file is the map)
docker-compose.yml   PostgreSQL (pgvector) and Redis for local development
```

## Request flow

Browser (Next.js) signs in with Supabase and calls the API with the user's access token. The API
checks the token, loads the user's organization membership, and every query is scoped to that
organization. Long work (GitHub sync, indexing, reviews, CI analysis) is queued to Celery through
Redis, and the web app polls the job's status.

## API (`apps/api/app`)

| Folder | What lives there |
|---|---|
| `api/v1` | route handlers, thin: validate, authorize, call a service |
| `api/deps.py` | authentication and organization-membership dependencies |
| `core` | settings, roles, security helpers, day grouping, request-id and security-header middleware, JSON logging |
| `db` | SQLAlchemy models and session |
| `services/github` | GitHub App client, sync, webhooks |
| `services/indexing` | file filtering, secret scanning, chunking, embeddings, search |
| `services/llm` | provider interface, Gemini and Anthropic, retries, usage records |
| `services/review`, `services/ci`, `services/ask` | the AI features |
| `jobs` | Celery app, tasks, dispatch (Celery or inline for development) |

The brief suggests a different folder layout (`ai/`, `github/`, ...). We keep this one because it
already groups code by feature and every import and test depends on it.

## Rules that hold across the code

- Every row an organization owns is reached through its GitHub installation, and every route
  checks membership first. Cross-organization access returns 404.
- GitHub is **read-only**. No feature writes to GitHub.
- All AI calls go through `LLMProvider`; model names come from settings, never code.
- Repository content, logs and issue text are **untrusted**: wrapped as data before a prompt, and
  model output is validated (citations, file paths, quoted log lines) before it is stored.
- Credential-looking text is withheld before anything reaches a model, and raw logs are not stored.
- Background jobs are claimed atomically, safe to run twice, and end in a clear status.
- A spent daily AI quota fails fast instead of retrying.
- One middleware (`core/middleware.py`) gives every request an id, adds the security headers, writes the
  access log and turns unexpected errors into a JSON 500 that names only the id. It sits inside CORS so
  browsers can still read errors. Details: `docs/SECURITY.md` and `docs/OPERATIONS.md`.
- AI usage limits are atomic counters in the database (`services/limits.py`): a slot is taken before
  any AI call, in its own short transaction. Sensitive and costly actions call `record_audit`
  (`services/audit.py`) in the same transaction as the action. See `docs/USAGE.md` and `docs/AUDIT.md`.

## Web (`apps/web`)

- `app/(app)/layout.tsx` wraps every signed-in page in the **app shell**: sidebar, top bar, theme
  toggle, workspace switcher. `app/login` and the callbacks sit outside it.
- `components/shell/*` is the shell. `lib/nav.ts` is the only place navigation is defined.
- The selected workspace and sidebar state live in small Zustand stores, remembered in the browser.
  Server data goes through TanStack Query.
- Design tokens are CSS variables in `app/globals.css` (dark by default, `.light` class for the
  light theme) and are mapped to Tailwind colors in the `@theme` block of the same file (Tailwind 4
  has no JavaScript config). `proxy.ts` refreshes the sign-in session on every page request.
- Fonts (Inter, JetBrains Mono) are self-hosted through Fontsource, so no request goes to Google.
- Tests: Vitest and Testing Library in `apps/web/tests`.

## Data

PostgreSQL with pgvector. Migrations in `apps/api/alembic/versions` (one per schema change;
`alembic check` fails CI if models and migrations drift). Usage records hold counts, tokens, model
names and error codes only: never prompts or replies.
