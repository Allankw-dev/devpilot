# Development log

Newest first. Each entry says what changed, what was run, and what is still open. Test numbers are
from runs that were actually executed.

## Phase 10, milestone A: app shell and design system

- New design tokens (dark-first palette from the brief, light theme), self-hosted Inter and
  JetBrains Mono, Tailwind color and font mapping.
- App shell for all signed-in pages: collapsible sidebar, mobile drawer with Escape and backdrop
  close, breadcrumb top bar, theme toggle (no flash on load), workspace switcher with in-place
  workspace creation, AI usage meter, help link, sign out. A skip-to-content link is included.
- Primary buttons use dark text on the brand blue: white on `#3B82F6` is 3.7:1, below the 4.5:1
  that accessibility guidelines ask for.
- New dashboard (`/dashboard`) from `GET /orgs/{id}/dashboard`: counts, commits and pull requests
  per day, AI calls per day, recent pull requests, reviews, failed runs and issues. A GitHub
  not-connected state and a no-workspace state replace the numbers: no placeholder statistics.
- The old organization page moved into the shell unchanged (it is the **Workspace** page for now).
- Added Vitest with 33 tests for the shell, dashboard, theme and workspace logic. CI runs them.
- Verified: ruff, mypy, ESLint, `tsc`, production build; API 670 passed on SQLite and 682 on
  PostgreSQL; web 33 passed. **Not** verified: a real browser, a phone-sized screen, end-to-end flows.
- Found: `npm audit` shows 13 production findings that exist before and after this change
  (see `IMPLEMENTATION_STATUS.md`).
- Open: split the Workspace page into the routed pages from the brief (milestones B and C),
  Playwright tests, Next 16 upgrade.

## AI usage dashboard

`GET /orgs/{id}/ai/usage`: calls (retries included), tokens, errors, per feature and model,
a rolling 24-hour count against an optional `AI_DAILY_REQUEST_LIMIT`, and a banner when the
provider says the daily quota is used up. No migration. See `docs/USAGE.md`.

## Daily-quota handling

A 429 that names a per-day quota (or a zero allowance) is now `LLMQuotaExhausted`, never retried.
Reviews, CI analyses and indexing fail at once with a plain message; Ask and the connection test
return 429 with the same text. Found when a free Gemini key (20 requests a day) ran out.

## CI failure analysis

Reads the end of each failed job's log, withholds credential-looking lines, asks the model why it
failed, and keeps only quotes that really appear in what was sent. Migration `0007`. See
`docs/CI.md`.

## Earlier work (this repo's original numbering)

1. Foundation: monorepo, FastAPI, Postgres, Alembic, Docker Compose.
2. Supabase auth, organizations, roles, teams.
3. GitHub App: install flow, sync, webhooks.
4. AI provider layer (Gemini, Anthropic), usage records.
5. Indexing and code search (pgvector).
6. Ask with checked citations.
7. AI pull request reviewer.
