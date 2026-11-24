# Security

What DevPilot does today to protect itself and its users, how to check it, and what it does not do
yet. How to report a vulnerability is in the repository's [`SECURITY.md`](../SECURITY.md).

**The threat model is not written yet** (see [`ROADMAP.md`](../ROADMAP.md)). This file lists
controls that exist and have tests; it is not a claim that the system is secure.

## The API's HTTP layer

Implemented in `apps/api/app/core/middleware.py` and tested in `tests/test_http_hardening.py`.

| Header or behavior | Value | Why |
|---|---|---|
| `X-Request-ID` | on every response | see [`OPERATIONS.md`](OPERATIONS.md); a caller's own id is kept only if it is 8 to 64 characters of letters, digits, `.`, `_` or `-` |
| `X-Content-Type-Options` | `nosniff` | browsers must not guess a type for API responses |
| `X-Frame-Options` and `Content-Security-Policy` | `DENY`; `default-src 'none'; frame-ancestors 'none'` | the API returns only JSON, so nothing it sends should load or be framed |
| `Referrer-Policy` | `no-referrer` | |
| `Cache-Control` | `no-store` (an endpoint may set its own) | responses hold private organization data |
| `Strict-Transport-Security` | `max-age=31536000`, only when `ENVIRONMENT=production` | HTTPS isn't available on localhost |

Also:

- **API docs.** `/docs`, `/redoc` and `/openapi.json` are switched off when `ENVIRONMENT=production`.
  In development they work and are exempt from the strict policy, because they load scripts from a CDN.
- **CORS.** Only origins in `CORS_ORIGINS` are allowed, with the methods `GET POST PUT PATCH DELETE
  OPTIONS` and the request headers `Authorization`, `Content-Type` and `X-Request-ID`. A preflight
  asking for anything else gets a 400. `X-Request-ID` is exposed so the browser can read it.
- **Unexpected errors.** The caller gets a JSON 500 naming only the request id. The traceback goes to
  the log. CORS and security headers are still present, so the web app can show the message.
- **Access log.** One line per request: method, path, status and time. Never the query string,
  headers or body, because those can hold tokens. Client IP addresses are not logged either.
- **Database connections** give up after 5 seconds (`DB_CONNECT_TIMEOUT_SECONDS`), so a database
  that is down fails fast.

Controls that already existed (organization scoping, token verification, webhook signatures,
untrusted-input handling, secret scanning, answer checking) are listed in the root `SECURITY.md`.

## The web app's headers

Defined in `apps/web/lib/security-headers.mjs`, applied by `next.config.mjs`, tested in
`tests/security-headers.test.ts`.

| Header | Development | Production |
|---|---|---|
| `X-Content-Type-Options: nosniff` | yes | yes |
| `Referrer-Policy: strict-origin-when-cross-origin` | yes | yes |
| `Permissions-Policy` (camera, microphone, geolocation, payment off) | yes | yes |
| `X-Frame-Options: DENY` | **no** | yes |
| `Strict-Transport-Security` | **no** | yes |
| `Content-Security-Policy-Report-Only` | yes | yes, plus `frame-ancestors 'none'` |

Framing protection is production-only because VS Code's built-in browser shows the page inside a
frame, and HSTS because localhost has no HTTPS.

### The Content-Security-Policy is report-only

It does **not block anything yet**. The browser only lists what it would have blocked in the developer
console (messages starting "Content-Security-Policy-Report-Only"). It was not checked in a real
browser when it was written, so enforcing it blind could have blanked the app.

The policy allows scripts and styles from the app itself plus **inline** scripts, because Next.js
needs them unless every request carries a nonce. Even enforced, it therefore limits where data and
resources can go, but it is only a partial defence against injected scripts. A nonce-based policy is
a later, separate piece of work.

To check it: open the app in a browser, open the console, click through every page (sign in, GitHub
connect, Assistant, Reviews, CI), and look for report-only messages. A clean console means the policy
can be switched on by renaming the header in `securityHeaders()` to `Content-Security-Policy`.

## How to check the headers yourself

With the API running on port 8001 (`curl.exe` is built into Windows):

```powershell
curl.exe -i http://localhost:8001/api/v1/health/live
curl.exe -i -H "X-Request-ID: my-test-0001" http://localhost:8001/api/v1/health/live
curl.exe -I http://localhost:3001/login
```

The first shows the security headers and a generated `x-request-id`; the second shows your own id
echoed back; the third shows the web app's headers (no `X-Frame-Options` in development).

## Known limitations

- The web CSP is report-only and allows inline scripts (above).
- There are no rate limits outside the AI features, and DevPilot does not limit sign-in attempts
  (sign-in happens at Supabase).
- Organization isolation is enforced in application code only; there is no PostgreSQL row-level security.
- There is no audit log yet.
- Only a connection timeout exists on the database; there is no statement timeout.
- Uvicorn's own start-up and error lines are not JSON (the app's lines are).
- Dependency scanning does not run in CI yet; Dependabot covers npm and GitHub Actions only.
- Two `npm audit` findings remain in the PostCSS copy bundled with Next 15
  (see [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)).
