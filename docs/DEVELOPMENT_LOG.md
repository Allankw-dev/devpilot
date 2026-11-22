# Development log

Newest first. Each entry says what changed, what was run, and what is still open. Test numbers are
from runs that were actually executed.

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
