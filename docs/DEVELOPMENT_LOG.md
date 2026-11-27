# Development log

Newest first. Each entry says what changed, what was run, and what is still open. Test numbers are
from runs that were actually executed.

## Design pass 1 (2026-11-26)

- Reviewed the Next 16 / Tailwind 4 upgrade commit: logic changes read correctly; fixed what it broke
  (it overwrote earlier doc updates, left `components.json` pointing at a deleted Tailwind config, and
  left outdated `npm audit` notes). Added a second lockfile, `apps/api/uv.lock`, that disagrees with
  `requirements.lock` (SQLAlchemy 2.0.58 against 2.0.57); not removed, flagged.
- Found: the code has no gradients at all; purple appeared only on the workspace badge and three chart
  series. The "AI dashboard" feel came from the palette (navy with blue, purple and cyan accents).
- Figma file created with variables (Color dark, Color Light, spacing and radius), IBM Plex text styles,
  components and three screens (`docs/DESIGN.md` has the status). The Figma MCP call limit on the
  Starter plan was reached before the remaining screens could be drawn.
- Code: new tokens in `globals.css`, IBM Plex through Fontsource (replacing Inter and JetBrains Mono),
  `--purple` and `--cyan` removed, charts use ink and grays, workspace badge is neutral.
- Verified: ESLint, `tsc`, 253 tests, production build and `npm audit` (0 findings) pass.
- **Not** verified: how it looks in a browser (none available where this was built), contrast in the
  real UI, the light theme. Decisions to check by eye: `text-primary` links are now near-white and rely
  on underline on hover; the focus ring is the primary color.

## Security foundations, milestone B (2026-11-26)

- **Found by reading the code:** the Ask limit counted `llm_usage` rows, which are written *after* the
  model answers, so a burst of parallel questions all passed the check. The review and CI limits counted
  queued rows with a read-then-insert, which is also racy. No per-organization cap existed.
- **Atomic limits.** New table `rate_counters` and `services/limits.py`: one `INSERT ... ON CONFLICT DO
  UPDATE ... WHERE count < limit RETURNING` takes a slot, in its own short transaction (so the row lock
  isn't held during a slow AI call). Replaces `api/ratelimit.py`, `_check_rate` (CI) and
  `_check_review_rate`. Fixed windows, documented. New optional `AI_ORG_DAILY_REQUEST_LIMIT`.
  Behavior change: a request answered from a cached review or analysis now uses a slot.
- **Audit log.** New table `audit_logs`, `services/audit.py` and `GET /orgs/{id}/audit-log` (admin/owner,
  newest first, keyset paging, optional action filter). Recorded in the same transaction as the action;
  only for actions that actually happen. `org.deleted` is log-only because the rows cascade away with the
  organization. Each entry stores the request id. Team page card shows it, with "Load older entries".
- Migration 0009 (hand-written like the others) creates both tables.
- Verified: ruff and mypy clean; API 796 passed, 15 skipped (SQLite); **809 passed, 2 skipped on
  PostgreSQL 16 with pgvector** (first time the PostgreSQL suite was run in this review); `alembic
  upgrade head`, `alembic check` and a downgrade/upgrade of 0009 pass; web lint, `tsc`, 253 tests and the
  production build pass. The limiter's concurrency test (60 callers, 16 threads, limit 5) gives exactly 5
  slots, and fails against a deliberately naive read-then-write version.
- **Not** verified: the new card in a browser; behavior under real multi-server load; clock skew between
  servers; the Docker Compose setup.
- Open: milestone C (cancel running and queued jobs); audit retention and export; limits for indexing.

## Security foundations, milestone A (2026-11-24)

- API: new `core/middleware.py` (pure ASGI, so streaming still works) gives each request an id,
  adds security headers, writes one access-log line and turns unexpected errors into a JSON 500 that
  names only the request id. `core/logging.py` now adds `request_id` and the access fields to the JSON
  log. New `/health/live` and `/health/ready`; `/health` unchanged for the web status panel.
- Decisions: the middleware sits inside CORS so error responses still carry CORS headers; a caller's
  `X-Request-ID` is kept only if it is 8 to 64 characters of `A-Za-z0-9._-`; the access log never holds
  the query string, headers, body or client IP; API docs are off and HSTS is on when
  `ENVIRONMENT=production`; CORS methods and headers narrowed to what `lib/api.ts` sends; DB connect
  timeout 5 s; a failed health probe is one warning line, with the traceback only at DEBUG (probes run
  every few seconds, so tracebacks would flood the log during an outage).
- Web: `lib/security-headers.mjs` sets nosniff, referrer and permissions policies everywhere;
  `X-Frame-Options` and HSTS only in production, because VS Code's built-in browser shows the dev page
  in a frame. The CSP is **report-only** because it could not be tested in a real browser here, and it
  allows inline scripts because Next.js needs them without a nonce.
- Verified: ruff and mypy clean; API 760 passed, 14 skipped (SQLite); web lint, `tsc`, 225 tests and
  the production build pass. Headers confirmed with `curl` against a real `uvicorn`, `next start`
  (production) and `next dev`. Deliberately breaking the middleware (no id sanitising, logging the
  query string, leaking the exception text) made the new tests fail.
- **Not** verified: the PostgreSQL suite, `alembic check`, Docker Compose, any browser (so the CSP
  console output is unseen), a real database or Redis outage against `/health/ready`.
- Open: look at the browser console, then enforce the CSP; then milestone B (audit log, atomic AI usage
  limits, job cancellation).

## Open-source readiness (2026-11-24)

- Added `LICENSE` (Apache-2.0) and `NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor
  Covenant 2.1), `SECURITY.md`, `SUPPORT.md`, `CHANGELOG.md`, `ROADMAP.md`, issue forms, a pull
  request template and Dependabot (npm and GitHub Actions). New guide: `docs/SELF_HOSTING.md`.
- Found by reading the repo against the full project brief, and fixed: the README and `.env.example`
  said PostgreSQL is on host port 5433 while `docker-compose.yml` uses 15433; a stray `/` and a
  trailing period in the README; the empty "echo Hello" `.vscode/tasks.json` template was removed.
- Found and recorded, not changed: `npm audit` now reports 2 findings, not 13 (see Known issues in
  `IMPLEMENTATION_STATUS.md`); a stored-credentials gap suspected during the review does not exist, because
  the app keeps no tokens or keys in the database (GitHub installation tokens are cached in memory).
- Verified on a fresh clone: ruff and mypy clean; API 719 passed, 14 skipped (SQLite); web lint,
  `tsc`, 217 tests and the production build pass. **Not** run: the PostgreSQL suite, `alembic check`,
  Docker Compose, anything in a browser. This change is documentation and templates only.
- Open: switch on private vulnerability reporting and Discussions in the repository settings; then the
  security basics listed under "Now" in `ROADMAP.md`.

## Web stack upgrade: Next 16, Tailwind 4, ESLint 9 (2026-11-22)

- **Why:** `npm audit` reported 13 production vulnerabilities (12 high), all from Next 15 and the
  Tailwind 3 toolchain. It now reports **0** (production and dev).
- **What changed:** Next 15.5 to 16.4.6 (`middleware.ts` became `proxy.ts`); Tailwind 3.4 to 4.3
  using Tailwind's own upgrade tool (the JavaScript config became an `@theme` block in
  `app/globals.css`; `autoprefixer` and the unused `tailwindcss-animate` were removed;
  `tailwind-merge` 2 to 3); ESLint 8 to 9 with a flat config (`next lint` no longer exists).
  npm warns that ESLint 9 "is no longer supported"; ESLint 10 exists but the plugins inside
  `eslint-config-next` 16.4 don't declare support for it yet (npm reports invalid peers), so 9.x stays
  until they do.
- **Lint findings fixed instead of switched off:** the newer React rules flagged state set inside
  effects, `Date.now()` and a ref read while rendering. The theme is now an external store
  (`useTheme`), "now" comes from `useNow`, the mobile drawer closes by comparing the page it was
  opened on, filters reset the page in the same handler, and the GitHub callback works out what the
  link says while rendering. Behavior and tests are unchanged.
- **Look:** the upgrade tool renamed a few utilities to keep the same size (`rounded` to
  `rounded-sm`, `break-words` to `wrap-break-word`). Borders with no color now use the theme's
  border color instead of a light gray.
- **Verified:** ESLint, `tsc`, 217 web tests and the production build pass; `next start` serves
  `/login` with its stylesheet, and signed-out requests to `/dashboard` redirect to `/login`; the
  generated CSS contains the theme colors and the utilities the app uses. **Not** verified: how it
  looks in a real browser or on a phone, so look through every page once.
- **Your Copilot work:** the AI provider fallback (Groq/OpenRouter via an OpenAI-compatible
  provider, used when the main provider's quota is spent) is on `main` (it was committed together
  with the CI fix). Synced into the build sandbox; with it the API suite passes (719 on SQLite).

## Fixes after first real use (2026-11-22)

- **CI analysis, jobs that never started.** A real failed run (a fresh one, with both jobs failed
  and no steps) was reported as "log expired or removed", which was wrong: logs last about 90 days
  and this run was minutes old. A failed job with no recorded steps is now reported as "the job
  never started, so it has no log", and the failure message tells you to open the run on GitHub to
  see why (for example a runner or billing problem). A job that did run but whose log is gone is
  still called expired. Three new tests; 711 API tests on SQLite plus these still pass.
- **Sidebar on short windows.** In a small browser panel only five page links were visible. On
  windows under 760 px tall the Help link is hidden and the bottom block is tighter, so the page
  links keep their room (the usage meter stays).
- Seen in the screenshot and not a bug: the usage meter showing 36 / 20 means 36 AI calls in 24
  hours against a 20-call free-tier limit, which is also why AI features were failing.

## Phase 10, milestone F: navigation finished, Workspace page retired

- **Code Search** (`/search`) is its own page. The AI usage detail (calls, quota status, features,
  models) moved to the bottom of **Analytics**, and the server status list moved to
  **Integrations**. After the GitHub connection flow you now land on Integrations with that
  workspace selected.
- The old Workspace page and its four sections (Ask, pull requests, CI runs, the org view) are
  deleted. `/orgs/{id}` redirects to the dashboard so old bookmarks still work. Every "Connect
  GitHub", "View all" and "Open workspace" link now points at the page that really has that content;
  the dashboard's issues card no longer has a "View all", because there is no all-issues page.
- Navigation no longer has a disabled item state: with the Workspace page gone, every page is
  always reachable.
- Docs that said "open the organization page" now name the right page.
- Verified: web 217 passed; ESLint, `tsc` and the production build clean. API unchanged
  (711 passed on SQLite, 723 on PostgreSQL at the last full run). **Not** verified: a real browser
  or phone screen.
- Open: streaming and Stop in the Assistant, follow-ups that use earlier answers, Playwright tests
  (browsers can't be downloaded in the build sandbox, so they need running on your machine),
  Next 16 upgrade for the audit findings, then the features still missing from the brief.

## Phase 10, milestone E: the Assistant

- **Assistant** (`/assistant`): a list of your conversations, a new-conversation screen (choose
  one indexed repository or all, or click an example question) and a conversation view with the
  answer, confidence, sources linked to the exact lines on GitHub, copy, and "Generate again" for
  the latest answer. Viewers can read but not ask.
- **Private by design:** a conversation is visible only to the person who started it. Other
  members, admins included, get a 404. Deleting a conversation deletes its messages.
- **Saved only on success:** a question and its answer are stored together, so a failed attempt
  leaves no half-finished thread and costs no stored data. Retrying reuses the same conversation.
- **Limits, stated in the page:** each question is answered from the code on its own (it doesn't
  see earlier answers); answers arrive whole rather than streamed, because citations are checked
  against the code after the full text exists; one conversation holds at most 100 messages.
- API: `/orgs/{id}/conversations` (list, create, read, delete), `.../messages` (ask) and
  `.../messages/{id}/regenerate`. The Ask logic moved into one shared function, `run_ask`, used by
  both `/ask` and conversations (the 25 existing Ask tests pass unchanged). Migration `0008`
  (`conversations`, `conversation_messages`), verified on PostgreSQL: upgrade, `alembic check`,
  downgrade, upgrade.
- Verified: API 711 passed on SQLite, 723 on PostgreSQL; web 203 passed; ruff, mypy, ESLint, `tsc`
  and the production build clean. **Not** verified: a real browser, phone screen, or a real
  Gemini answer through the new page.
- Open: streaming and Stop, follow-ups that use earlier answers, moving code search to its own
  page and retiring the Workspace page, Playwright tests.

## Phase 10, milestone D: Team and Settings pages

- **Team** (`/team`): members with roles, add a member by email, change roles, remove, leave the
  workspace; teams with their members. The role choices shown follow the server's rules (owners
  grant anything, admins only member or viewer and can't touch other admins; the server still
  enforces them and its messages are shown, for example the last-owner rule).
- **Settings** (`/settings`): read-only profile (name and email come from the sign-in provider),
  theme choice, workspace rename (admins), and an owner-only delete that needs the workspace name
  typed in.
- No backend changes: the endpoints already existed.
- Not built, so not shown: notifications, security, API keys, subscription, invitations.
- Verified: web 163 passed; ESLint, `tsc` and the production build clean. API unchanged
  (690 passed on SQLite, 702 on PostgreSQL at the last full run). **Not** verified: a real
  browser or phone screen.
- Open: the assistant page (Ask with streaming, saved conversations, code search), retiring
  duplicated sections on the Workspace page, Playwright tests, invitations.

## Phase 10, milestone C: CI/CD, Analytics and Integrations pages

- **CI/CD** (`/ci-cd`, `/ci-cd/[id]`): workflow runs with failed/all, repository and
  workflow-or-branch search, "load more"; a run page with the AI analysis. Starting an analysis
  is a deliberate click by a member or above.
- **Analytics** (`/analytics`): CI success rate, reviews and CI analyses finished, average review
  and analysis times, findings by severity, AI work and CI runs per day, tokens per day. "n/a" is
  shown when there is nothing to measure. Cancelled and skipped runs are left out of the success
  rate. The page says these are activity counts, not productivity.
- **Integrations** (`/integrations`): GitHub connection (connect, sync, disconnect), the AI
  provider panel and a note on GitHub Actions. Secret values are never shown; missing settings
  are listed by name only. The GitHub section was extracted from the Workspace page into a
  shared component.
- API: `GET /orgs/{id}/analytics`, `GET /orgs/{id}/ci-runs/{run}`; the CI runs list gained
  `repo_id`, `q` and `offset`. No migration.
- Verified: API 690 passed on SQLite, 702 on PostgreSQL; web 128 passed; ruff, mypy, ESLint, `tsc`
  and the production build clean. **Not** verified: a real browser or phone screen, end-to-end flows.
- Open: team and settings pages, the assistant page (Ask with streaming, saved conversations),
  retiring the duplicated sections on the Workspace page, then Playwright tests.

## Phase 10, milestone B: Repositories and Code Reviews pages

- **Repositories** (`/repositories`): search by name or description, language and CI filters, an
  archived toggle, 10 per page. Rows link to the repository page.
- **Repository page** (`/repositories/[id]`): overview facts and code-index control, commits,
  pull requests (with review actions) and issues. Tabs are links (`?tab=`), so they can be shared.
- **Code reviews** (`/code-reviews`, `/code-reviews/[id]`): pull requests with review status,
  repository filter, title search, "load more", and a detail page showing the findings.
- API: `GET /orgs/{id}/repos/{repo}/commits`, `GET /orgs/{id}/issues`,
  `GET /orgs/{id}/pull-requests/{pr}`; pull request list gained `repo_id`, `q` and `offset`;
  repository list gained `owner` and `description`. Search treats `%` and `_` literally.
  No migration.
- Starting a review or indexing is always a deliberate click by a member or above (it costs AI
  tokens); viewers see results only.
- Renamed `vitest.config.ts` to `.mts` to silence a Vite loader warning.
- Verified: API 679 passed on SQLite, 691 on PostgreSQL; web 83 passed; ruff, mypy, ESLint, `tsc`
  and the production build clean. **Not** verified: a real browser or phone screen, end-to-end flows.
- Open: file browser with Monaco (needs live GitHub reads and secret filtering for display),
  branches, review diff viewer, then CI/CD, analytics, integrations, team and settings pages.

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
