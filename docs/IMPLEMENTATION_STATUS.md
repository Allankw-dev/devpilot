# Implementation status

Checked against the project brief ("Master Development Instruction"). A box is ticked only when
the feature works and has automated tests. Last updated for **Phase 10, milestone B**.

Numbering note: the brief has its own eight phases. This repo's early commits used a different
numbering (Phases 1 to 7). To avoid confusion this file uses the brief's names, and the
development log maps one to the other.

## Test results (last full run)

| Suite | Result |
|---|---|
| API on SQLite | 679 passed, 14 skipped (the skipped ones need PostgreSQL) |
| API on PostgreSQL 16 + pgvector | 691 passed, 2 skipped |
| Web (Vitest) | 83 passed |
| Lint and types | ruff, mypy, ESLint and `tsc` clean |
| End-to-end (Playwright) | **not set up** |
| Load tests | **not run** |

The new web shell was built and unit-tested but has **not yet been checked in a real browser**
(including on a phone-sized screen). Check it by eye before relying on the layout.

## Brief phase 1: foundation and UI: partly done

- [x] Monorepo (`apps/api`, `apps/web`; the brief suggests `backend/` and `frontend/`, we keep ours)
- [x] FastAPI, PostgreSQL, SQLAlchemy 2, Alembic (7 migrations, `alembic check` in CI)
- [x] Supabase authentication, organizations, roles (owner, admin, member, viewer), teams
- [x] Docker Compose for the database and Redis
- [x] Design system: dark-first palette from the brief, light theme, Inter and JetBrains Mono
- [x] App shell: sidebar (collapsible), mobile drawer, top bar with breadcrumbs, theme toggle,
      workspace switcher, usage meter, sign out
- [x] Dashboard with real data (counts, activity chart, AI usage chart, recent lists)
- [x] Routed pages: Dashboard, Repositories (list and detail), Code Reviews (list and detail)
- [ ] Routed pages still to build: assistant, CI/CD, analytics, integrations, team, settings.
      Until then those features live on the **Workspace** page
- [ ] shadcn/ui components beyond Button and Card, Monaco, React Hook Form, Zod, React Flow
- [ ] Playwright end-to-end tests
- [ ] Invitations
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
- [ ] Streaming responses, stop and regenerate
- [ ] Saved conversations and history
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
- [ ] Issue planning, documentation generation, task history

## Brief phase 7: analytics and SaaS: partly done

- [x] AI usage dashboard (calls, tokens, errors, quota status) and usage records
- [ ] Subscriptions, entitlements, billing, audit log, team analytics

## Brief phase 8: production hardening: not started

- [x] CI workflow runs lint, types, tests and build for both apps
- [ ] Sentry, OpenTelemetry, health checks beyond `/health`, production Dockerfiles
- [ ] Load testing, security review, backup and recovery documentation
- [ ] Final production-readiness assessment

## Known issues

- **Dependency vulnerabilities.** `npm audit` reports 13 production findings (1 moderate, 12 high)
  in `apps/web`. They are the same before and after Phase 10. They come from Next 15 (a bundled
  PostCSS) and the Tailwind 3 toolchain (`picomatch`, which has no fix yet). The Next fix is Next
  16.4.6, which also needs the middleware-to-proxy migration and Tailwind 4. Plan this in the
  hardening phase.
- **Dashboard weight.** `/dashboard` loads about 331 kB of JavaScript because of the chart library.
- **Free-tier AI quota.** A free Gemini key allows about 20 requests a day per model; see `docs/USAGE.md`.
- **Nav.** The sidebar lists only pages that work. Features are added to `lib/nav.ts` when they exist.
