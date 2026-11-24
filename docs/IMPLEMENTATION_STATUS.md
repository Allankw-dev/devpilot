# Implementation status

Checked against the project brief ("Master Development Instruction"). A box is ticked only when
the feature works and has automated tests. Last updated for **Phase 10, milestone F (navigation finished)** and the open-source readiness step (2026-11-24).

Numbering note: the brief has its own eight phases. This repo's early commits used a different
numbering (Phases 1 to 7). To avoid confusion this file uses the brief's names, and the
development log maps one to the other.

## Test results (last full run)

| Suite | Result |
|---|---|
| API on SQLite | 719 passed, 14 skipped (the skipped ones need PostgreSQL); re-run 2026-11-24 on a fresh clone |
| API on PostgreSQL 16 + pgvector | 723 passed, 2 skipped (earlier run, not repeated on 2026-11-24) |
| Web (Vitest) | 217 passed (re-run 2026-11-24) |
| Lint, types, build | ruff, mypy, ESLint, `tsc` and the production build clean (re-run 2026-11-24) |
| End-to-end (Playwright) | **not set up** |
| Load tests | **not run** |

The new web shell has been opened in a browser (2026-11-22) but **not on a phone-sized screen**, and there
are no end-to-end tests. Check the layout by eye before relying on it.

## Brief phase 1: foundation and UI: partly done

- [x] Monorepo (`apps/api`, `apps/web`; the brief suggests `backend/` and `frontend/`, we keep ours)
- [x] FastAPI, PostgreSQL, SQLAlchemy 2, Alembic (8 migrations, `alembic check` in CI)
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
- [ ] Sentry, OpenTelemetry, health checks beyond `/health`, production Dockerfiles
- [ ] Load testing, security review, backup and recovery documentation
- [ ] Final production-readiness assessment

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

- **Dependency vulnerabilities.** `npm audit --omit=dev` (re-run 2026-11-24 on a fresh install)
  reports 2 production findings in `apps/web` (1 moderate, 1 high), both from a PostCSS copy bundled
  inside Next 15. The advisories concern PostCSS stringifying CSS and reading source maps; the app's
  CSS is its own, so exploitability looks low, but it should still be fixed. The fix is Next 16.4.6,
  a breaking upgrade that also needs the middleware-to-proxy migration and Tailwind 4. An earlier
  count of 13 also listed the Tailwind toolchain (`picomatch`); that no longer appears. Plan the
  upgrade in the hardening phase.
- **Dashboard weight.** `/dashboard` loads about 331 kB of JavaScript because of the chart library.
- **Free-tier AI quota.** A free Gemini key allows about 20 requests a day per model; see `docs/USAGE.md`.
- **Nav.** The sidebar lists only pages that work. Features are added to `lib/nav.ts` when they exist.
