# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub:
<https://github.com/Allankw-dev/devpilot/security/advisories/new>

Include what you found, how to reproduce it, and what an attacker could do with it. Do not include
real credentials or other people's data; use test accounts and test repositories.

DevPilot is a small project maintained by one person. I aim to acknowledge a report within 7 days.
Fixing it may take longer, and I will tell you where it stands. Please give me a reasonable chance to
fix the problem before you publish details.

## Supported versions

DevPilot has no tagged releases yet. Only the latest commit on `main` is supported.

## What is in scope

- Access to another organization's data (tenant isolation).
- Authentication or authorization bypass in the API.
- GitHub App tokens, AI provider keys or other credentials reaching the browser, logs or the database
  in plain form.
- Forged GitHub webhooks being accepted.
- Repository content, pull request text or CI logs making the app run code, post to GitHub, or leak
  credentials to an AI model.
- Cross-site scripting through model output or repository content.

Out of scope: problems that need a malicious local machine, findings in third-party services
(Supabase, GitHub, your AI provider), and denial of service by sending huge volumes of traffic.

## What the code does today

These rules are in `CLAUDE.md`, and each has automated tests:

- Every query for organization data is scoped to the caller's organization; other organizations get a 404.
- Supabase tokens are verified against an allow-list of algorithms.
- GitHub webhooks are rejected unless the signature over the raw body is valid, and redelivered
  events are recognised.
- The GitHub App is read-only. Nothing is posted to GitHub or re-run.
- Repository code, diffs and CI logs are wrapped as untrusted text before they reach a model.
  Credential-looking lines and chunks are withheld from models and from the index.
- The API sends security headers on every response, tags each request with an id, never logs query
  strings or bodies, and hides its API docs in production.
- Member, team, GitHub-connection and AI-work actions are written to an audit log that admins can read.
  Per-person and per-workspace AI limits are taken atomically, so concurrent requests can't exceed them.
- Model answers are checked server-side (citations, file paths, quoted log lines) before they are
  stored or shown, and are rendered as plain text, never as HTML.

## Known limitations

Be aware of these before you expose an instance to the internet. The current list is in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md); at the time of writing it includes:

- No PostgreSQL row-level security (isolation is enforced in application code).
- The audit log can be changed by anyone with database access, has no retention setting and no export.
- The web app's Content-Security-Policy is report-only (not enforced) and allows inline scripts;
  details in [`docs/SECURITY.md`](docs/SECURITY.md).
- Credentials: GitHub installation tokens are cached in memory only, and provider keys come from
  environment settings, so the database holds no tokens or keys today. There is no encrypted store for
  per-organization keys because no feature needs one yet.
- No production Docker images and no documented production deployment.
- No sandbox: DevPilot never executes repository code today, and features that would need to are
  not built.
