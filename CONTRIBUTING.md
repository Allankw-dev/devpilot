# Contributing to DevPilot AI

Thanks for helping. DevPilot is early and small, so a short conversation before a big change saves
everyone time: open an issue first for anything larger than a bug fix.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Contributions are
licensed under the [Apache License 2.0](LICENSE). Security problems go through
[`SECURITY.md`](SECURITY.md), never a public issue.

## Set up

Prerequisites: Docker, Python 3.12+, Node 22+. The full walkthrough, including the Supabase project,
the GitHub App and an AI key, is in [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md). The short version:

```powershell
copy .env.example .env
docker compose up -d

cd apps\api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

```powershell
cd apps\web
copy ..\..\.env.example .env.local   # keep only the NEXT_PUBLIC_* lines
npm install
npm run dev
```

The API tests run on SQLite with no setup. A few tests need PostgreSQL with pgvector and are skipped
unless you set `TEST_DATABASE_URL` (see `.github/workflows/ci.yml` for how CI does it).

## Before you open a pull request

Run the same checks CI runs:

```powershell
cd apps\api; ruff check .; mypy .; pytest; alembic check
cd apps\web; npm run lint; npm run typecheck; npm test; npm run build
```

`alembic check` needs the database from `docker compose up -d` and fails if your models and
migrations disagree.

## Rules that matter here

The full list is in [`CLAUDE.md`](CLAUDE.md). The ones reviewers check first:

- **Small phases.** One feature per pull request. Don't build outside the current phase.
- **Tests with every feature**, including the failure case. Say in the pull request what you did not test.
- **Tenant isolation.** Every read of organization data is scoped to the caller's organization, and
  other organizations get a 404. Add a cross-organization test.
- **Untrusted input.** Repository code, pull request text, issues and CI logs are untrusted. Wrap them
  with `untrusted()` before a prompt, never execute them, and check model output (citations, paths,
  quotes) on the server.
- **Read-only GitHub.** Nothing writes to GitHub on a model's say-so. A future write action needs
  explicit user approval and its own design discussion.
- **No secrets, no hardcoded model names or URLs.** Settings come from `.env` through pydantic-settings.
  Never commit `.env`, keys or real repository content.
- **No fake data.** Dashboards show database records. If a feature is not built, there is no button for it.
- **Migrations.** Every schema change is an Alembic migration. Jobs must be safe to run twice.
- **Pin dependencies** and record them in `docs/VERSIONS.md`.
- **Docs.** Update the relevant file in `docs/`, and `docs/IMPLEMENTATION_STATUS.md` if a feature
  changes. Only tick a box there when the feature works and has tests.

## Pull requests

1. Fork, create a branch from `main`, make your change.
2. Fill in the pull request template honestly. A failing check you could not fix is fine to report;
   a hidden one is not.
3. CI must be green. Expect review comments; I review in my spare time.

## Good first contributions

- Documentation fixes and clearer setup steps.
- Tests for an uncovered edge case.
- Items marked unchecked under "Known issues" or a phase in
  [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) that are small, such as an empty-state wording fix.

The plugin system in the roadmap does not exist yet, so please don't open plugin pull requests.
