## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] The change is small and stays inside one phase or feature
- [ ] New behaviour has tests (including a test for the failure case)
- [ ] API: `ruff check .`, `mypy .` and `pytest` pass
- [ ] Web: `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` pass
- [ ] Schema change: new Alembic migration, and `alembic check` passes
- [ ] No secrets, tokens or real repository content in code, tests, logs or screenshots
- [ ] Anything from a repository, pull request or CI log is treated as untrusted (wrapped with `untrusted()`, never executed)
- [ ] No write to GitHub was added (or it needs explicit approval and is described below)
- [ ] Docs updated (`docs/`, and `docs/IMPLEMENTATION_STATUS.md` if a feature changed)

## How I tested it

<!-- Commands you ran and what you saw. Say what you did NOT test. -->
