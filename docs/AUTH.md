# Auth setup (Supabase)

Supabase handles sign-in (email/password and GitHub). Our API verifies the access token and
keeps organizations, teams and roles in our own Postgres. Menu names below may differ slightly
in the Supabase dashboard.

## 1. Create a project
Create a project at supabase.com (free plan is fine).

## 2. Copy two values (both are public)
Project Settings, API: **Project URL** and the **publishable key** (`sb_publishable_...`).
The legacy `anon` key also works in the same variable. You do **not** need the secret or
`service_role` key. Never put one in this repo or in the web app.

## 3. Fill in the env files
Root `.env`:
```
SUPABASE_URL=https://<project-ref>.supabase.co
```
`apps/web/.env.local`:
```
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```
Restart both servers afterwards. `NEXT_PUBLIC_*` values are read when the web server starts.

## 4. Redirect URLs
Authentication, URL Configuration:
- Site URL: `http://localhost:3001`
- Redirect URLs: add `http://localhost:3001/auth/callback` (add your production URL later)

## 5. Email sign-up
By default Supabase emails a confirmation link. For quick local testing you can turn off
"Confirm email" under Authentication, Providers, Email. Turn it back on before launch.

## 6. GitHub sign-in (optional, identity only)
1. GitHub, Settings, Developer settings, OAuth Apps, New OAuth App.
2. Authorization callback URL: the one Supabase shows under Authentication, Providers, GitHub
   (`https://<project-ref>.supabase.co/auth/v1/callback`).
3. Paste the GitHub client ID and secret into Supabase's GitHub provider and enable it.

This only signs people in. Repository access uses a separate GitHub App, added in a later phase.

## 7. Token verification
New Supabase projects sign tokens with asymmetric keys. The API verifies them against
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`, so nothing else is needed.
If your project still uses the legacy shared secret (HS256), either migrate it to signing
keys (Project Settings, JWT Keys) or set `SUPABASE_JWT_SECRET` as a fallback.

## Check it works
1. `GET /api/v1/me` without a token returns 401. If it returns 503, `SUPABASE_URL` isn't set.
2. Sign up at `/login`, land on `/dashboard`, create an organization. You become its owner.

## Roles
| Role | Can |
|---|---|
| viewer | read the organization, members and teams |
| member | same as viewer (write access arrives with later modules) |
| admin | rename the org, manage teams, add/remove members and viewers |
| owner | everything, including admins, owners and deleting the org |

An organization always keeps at least one owner. Non-members get 404 (not 403) so
organization ids don't leak. Members can only be added if they've signed in once;
email invitations come later.
