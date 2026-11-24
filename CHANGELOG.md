# Changelog

All notable changes are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There are no tagged releases yet, so
everything sits under Unreleased. Day-by-day detail and test numbers are in
[`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md).

## [Unreleased]

### Added

- Open-source project files: Apache-2.0 license, contributing guide, code of conduct, security
  policy, support guide, roadmap, issue and pull request templates, Dependabot for npm and GitHub Actions.
- Self-hosting guide (`docs/SELF_HOSTING.md`).
- Foundation: FastAPI API, Next.js web app, PostgreSQL with pgvector, Redis, Celery worker, Docker Compose
  for the database and Redis, CI workflow running lint, types, tests and build.
- Sign-in with Supabase Auth; organizations, teams and roles (owner, admin, member, viewer).
- Read-only GitHub App integration: repositories, commits, issues, pull requests, workflow runs,
  webhooks with signature checks and duplicate-delivery handling.
- AI provider layer: Gemini and Anthropic, plus optional Groq and OpenRouter fallbacks; retries,
  daily-quota detection, usage records.
- Repository indexing with secret exclusion, chunking, embeddings and pgvector search.
- Ask questions about your code, with citations checked against the retrieved code; saved private
  conversations.
- AI pull request reviews with findings checked against the real diff.
- AI analysis of failed GitHub Actions runs, with credentials redacted and quoted log lines verified.
- AI usage dashboard and analytics page.
- Web app shell with dark and light themes and pages for Dashboard, Repositories, Assistant, Code
  Search, Code Reviews, CI/CD, Analytics, Integrations, Team and Settings.

### Fixed

- CI analysis now says when a job never started instead of reporting an expired log.
- Sidebar keeps its page links visible on short windows.
- Port numbers in the README and `.env.example` now match `docker-compose.yml`.
