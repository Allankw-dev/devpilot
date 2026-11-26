# Implementation status

Checked against the project brief ("Master Development Instruction"). A box is ticked only when
the feature works and has automated tests. Last updated for **Phase 10, milestone F (navigation finished)**, the open-source readiness step and security foundations milestones A and B (2026-11-26).

Numbering note: the brief has its own eight phases. This repo's early commits used a different
numbering (Phases 1 to 7). To avoid confusion this file uses the brief's names, and the
development log maps one to the other.

## Test results (last full run)

| Suite | Result |
|---|---|
| API on SQLite | 796 passed, 15 skipped (the skipped ones need PostgreSQL); re-run 2026-11-26 |
| API on PostgreSQL 16 + pgvector | 809 passed, 2 skipped (run 2026-11-26 on a local PostgreSQL 16.15 with pgvector 0.6.0; includes the concurrent-limit test); `alembic upgrade head`, `alembic check` and a 0009 downgrade/upgrade round trip pass |
| Web (Vitest) | 253 passed (re-run 2026-11-26) |
| Lint, types, build | ruff, mypy, ESLint 9, `tsc` and the production build (Next 16) clean (re-run 2026-11-26) |
| End-to-end (Playwright) | **not set up** |
| Load tests | **not run** |

The new web shell has been opened in a browser (2026-11-22) but **not on a phone-sized screen**, and there
are no end-to-end tests. Check the layout by eye before relying on it.

## Brief phase 1: foundation and UI: partly done

- [x] Monorepo (`apps/api`, `apps/web`; the brief suggests `backend/` and `frontend/`, we keep ours)
- [x] FastAPI, PostgreSQL, SQLAlchemy 2, Alembic (9 migrations, `alembic check` in CI)
- [x] Supabase authentication, organizations, roles (owner, admin, member, viewer), teams
- [x] Docker Compose for the database and Redis
- [x] Design system: dark-first palette from the brief, light theme, Inter and JetBrains Mono
- [x] App shell: sidebar (collapsible), mobile drawer, top bar with breadcrumbs, theme toggle,
      workspace switcher, usage meter, sign out
- [x] Dashboard with real data (counts, activity chart, AI usage chart, recent lists)
- [x] Routed pages: Dashboard, Repositories, Assistant, Code Search, Code Reviews, CI/CD,
      Analytics, Integrations, Team, Settings
- [ ] Brief pages with no feature behind them yet, so no page: test generator, issues and
      planning, documentation, code health
- [x] The old all-in-one **Workspace** page is retired: its sections live on the pages above, and
      `/orgs/{id}` now redirects to the dashboard
- [ ] Settings sections from the brief that don't exist yet: notifications, security, API keys,
      subscription (no placeholders are shown for them)
- [ ] shadcn/ui components beyond Button and Card, Monaco, React Hook Form, Zod, React Flow
- [ ] Playwright end-to-end tests
- [x] Team page: members, roles (with the same rules the server enforces), teams, leave workspace
- [ ] Invitations: you can only add people who have already signed in once
- [ ] PostgreSQL row-level security (tenant isolation is enforced in code and tested)
- [ ] Docker images for the API and web app
- [x] AI provider fallback (Copilot-written, merged on main): Groq/OpenRouter through an OpenAI-compatible
      provider, used when the main provider's quota is spent

## Brief phase 2: GitHub integration: mostly done (read-only)

- [x] GitHub App install flow, installation tokens, repository list, sync jobs
- [x] Commits, issues, pull requests, workflow runs, pull request diffs
- [x] Webhooks with signature check, idempotent delivery handling
- [x] Disconnect and suspended-installation handling
- [x] Repository pages: searchable, filterable, paged list; detail with overview, commits,
      pull requests and issues
- [ ] Branch listing, file browser and Monaco code viewer (needs live GitHub reads, to be designed)
- [ ] Rate-limit backoff is handled for retries; no dedicated dashboard for it

## Brief phase 3: AI codebase assistant: partly done

- [x] Provider interface, Gemini and Anthropic providers, retries, timeouts, usage records
- [x] Daily-quota detection (fail fast with a clear message)
- [x] Indexing with secret exclusion, chunking, embeddings, pgvector search
- [x] Ask with answers that cite real files, citations checked against retrieved code
- [x] Assistant page: saved private conversations, a repository choice per conversation, example
      questions, sources with line links, copy answer, generate the latest answer again
- [ ] Streaming and a Stop button. Answers are checked against the code only after the full text
      exists, so they are returned whole, not token by token
- [ ] Follow-up questions that use earlier answers: each question is answered from the code on its own
- [ ] Tree-sitter parsing (chunking is line-based)

## Brief phase 4: AI code review: mostly done

- [x] Pull request review with findings: file, lines, severity, confidence, explanation
- [x] Findings checked against the real diff (invented paths and lines are dropped)
- [x] Credential scanner on the diff
- [x] Review pages: pull request list with filters, and a review detail page with findings
- [ ] Changed-files list and diff viewer on the review page
- [ ] Ruff and Semgrep findings feeding the review
- [ ] Publishing comments to GitHub after approval (needs a write permission, a separate decision)

## Brief phase 5: AI test generation: not started

Test generation, sandboxed execution and coverage are all still to do.

## Brief phase 6: developer automation: partly done

- [x] CI failure analysis (logs redacted, evidence quotes verified)
- [x] CI/CD pages: run history with filters, run detail with the AI analysis
- [ ] Issue planning, documentation generation, task history

## Brief phase 7: analytics and SaaS: partly done

- [x] AI usage dashboard (calls, tokens, errors, quota status) and usage records
- [x] Analytics page: AI work and CI outcomes per day, CI success rate, average review and analysis
      times, findings by severity, tokens per day (activity counts, not productivity claims)
- [ ] Subscriptions, entitlements, billing, audit log, team analytics

## Brief phase 8: production hardening: not started

- [x] CI workflow runs lint, types, tests and build for both apps
- [x] Liveness and readiness endpoints (`/health/live`, `/health/ready`)
- [ ] Sentry, OpenTelemetry, production Dockerfiles
- [ ] Load testing, security review, backup and recovery documentation
- [ ] Final production-readiness assessment

## Security and operations foundations (brief sections 6 and 15): started

Milestones A and B, with tests:

- [x] API: security headers, request ids, access log without query strings, JSON 500 without details,
      CORS limited to the methods and headers the web app uses, API docs off in production, HSTS in production
- [x] Web: nosniff, referrer and permissions policies; framing protection and HSTS in production
- [x] Database connection timeout
- [ ] Web Content-Security-Policy **enforced** (it is report-only; needs a look at the browser console first)
- [ ] Checked in a real browser: the CSP console output and the production-mode headers on a deployed site
- [x] Atomic AI usage limits for Ask, reviews and CI analyses (per person per minute), tested with real
      concurrent connections on PostgreSQL; optional daily cap per workspace
- [x] Audit log (member, team, GitHub, indexing, review, CI and AI-connection actions) with an
      admin-only API and a card on the Team page
- [ ] Cancelling running jobs and cancelling queued ones (milestone C)
- [ ] Audit log retention and export; audit entries for the rest of the write routes as they appear
- [ ] Limits for indexing (embedding calls) and a provider-wide concurrency limit
- [ ] PostgreSQL row-level security, statement timeouts, rate limits beyond the AI features (later)
- [ ] Metrics, tracing, queue-depth and worker health, Sentry, dependency scanning in CI

## Open source and community: partly done

- [x] Apache-2.0 `LICENSE` and `NOTICE`
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, `CHANGELOG.md`, `ROADMAP.md`
- [x] Issue forms, pull request template, Dependabot for npm and GitHub Actions
- [x] `docs/SELF_HOSTING.md` (development setup only; the steps were not run end to end on a clean machine)
- [ ] Switch on **private vulnerability reporting** and **Discussions** in the GitHub repository
      settings (`SECURITY.md` and the issue chooser link to them; this cannot be done from the code)
- [ ] Docs the brief names that don't exist yet: `DATABASE.md`, a threat model in `docs/SECURITY.md`,
      `SCALABILITY.md`, `OPERATIONS.md`, `AI_SYSTEM.md`
- [ ] Dependabot for the Python dependencies (they are pinned in `requirements.lock`, which it doesn't read)
- [ ] Plugin SDK, plugin examples, good-first-issue labels, public discussions

## Known issues

- **Dependency vulnerabilities: resolved.** `npm audit` reported 13 production findings (25 in all)
  on Next 15 and the Tailwind 3 toolchain. After moving to Next 16.4.6 and Tailwind 4.3 it reports
  0. Re-run it regularly: `cd apps/web; npm audit`.
- **Dashboard weight.** `/dashboard` loads about 331 kB of JavaScript because of the chart library.
- **Free-tier AI quota.** A free Gemini key allows about 20 requests a day per model; see `docs/USAGE.md`.
- **Nav.** The sidebar lists only pages that work. Features are added to `lib/nav.ts` when they exist.
