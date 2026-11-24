# Roadmap

This is the plan, not a promise. Order can change. What exists today, with test results, is in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Where it stands

Working today: repository indexing and code search, asking questions about code with checked
citations, AI pull request reviews, AI analysis of failed CI runs, usage and analytics pages, teams
and roles. GitHub access is read-only.

## Now: project foundations

- Open-source files and a self-hosting guide (done in this release).
- Security basics: HTTP security headers, request IDs, separate liveness and readiness endpoints,
  an audit log, atomic AI usage limits, cancelling running jobs.
- PostgreSQL row-level security as a second layer behind the existing organization checks.
- Dockerfiles for the API and web app, and a documented production deployment.

## Next: more of the product

- Issue and task planning (read-only: produces a plan, changes nothing).
- Test generation, starting with previews you read before anything runs.
- Documentation generation with preview and approval.
- Streaming answers with a Stop button, and follow-up questions that use earlier answers.
- File browser and code viewer; diff viewer on review pages.

## Later: needs design first

- A sandbox for running generated tests. It needs a written threat model before any code.
- Coordinated agents with explicit per-agent permissions, cost ceilings and human approval for every
  write to a repository.
- Automations: triggers, conditions, approval steps and run history.
- Plugin SDK with a manifest, permissions and out-of-process execution.
- Billing and plan limits, GitLab and Bitbucket adapters.
- Observability (metrics, tracing), load tests with published results, backup and restore tests.

## Not planned

- Merging pull requests or pushing code automatically.
- Sending private code to an AI provider you did not configure.
