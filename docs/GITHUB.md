# GitHub setup

DevPilot reads your repositories through a **GitHub App** with read-only permissions.
You register the app once on your own GitHub account. Tokens and the private key stay on
the server and never reach the browser. Menu names may differ slightly on GitHub.

## 1. Create the app
GitHub, Settings, Developer settings, GitHub Apps, **New GitHub App**.

| Field | Value |
|---|---|
| GitHub App name | anything unique, e.g. `devpilot-yourname` |
| Homepage URL | `http://localhost:3001` |
| Callback URL | `http://localhost:3001/github/callback` |
| Request user authorization (OAuth) during installation | **tick this** (it is what stops people claiming installations they don't own) |
| Setup URL | leave empty (GitHub disables it when the box above is ticked) |
| Webhook, Active | ticked |
| Webhook URL | your smee.io channel URL (step 3) |
| Webhook secret | a long random string. Save it, it goes in `.env` too |

**Repository permissions** (all *Read-only*): Actions, Contents, Issues, Pull requests.
Metadata is added automatically. No account or organization permissions.

**Subscribe to events:** Issues, Pull request, Push, Workflow run, Repository.
Installation events are sent automatically.

**Where can this app be installed:** "Only on this account" is fine while developing.

Click **Create GitHub App**.

## 2. Collect the values
On the app's settings page:
- **App ID** (a number)
- **Client ID** (`Iv1...` or `Iv23...`), then **Generate a new client secret** and copy it straight away
- **Public link** ends in the **slug**: `https://github.com/apps/<slug>`
- **Generate a private key** downloads a `.pem` file. Move it **outside the repo**, for example
  `C:\Users\Admin\secrets\devpilot-github.pem`. The repo's `.gitignore` also blocks `*.pem`.

Put them in the root `.env` (no quotes, no spaces around `=`):
```
GITHUB_APP_ID=123456
GITHUB_APP_SLUG=devpilot-yourname
GITHUB_CLIENT_ID=Iv23...
GITHUB_CLIENT_SECRET=...
GITHUB_WEBHOOK_SECRET=the-same-random-string-as-step-1
GITHUB_APP_PRIVATE_KEY_PATH=C:\Users\Admin\secrets\devpilot-github.pem
```
Restart the API afterwards. It doesn't reload `.env` by itself.

## 3. Webhooks on localhost
GitHub can't reach `localhost`, so use a free relay:
1. Go to https://smee.io and click **Start a new channel**. Copy the channel URL into the app's
   *Webhook URL* field.
2. Run the forwarder in its own terminal:
```
npx smee-client --url https://smee.io/YOUR-CHANNEL --target http://localhost:8001/api/v1/webhooks/github
```
Without it everything still works, but the data only refreshes when you press **Sync now**.
Anyone who knows a smee URL can read what passes through it, so use it for development only.

## 4. Connect
1. Restart the API, sign in, and open your organization.
2. Click **Connect GitHub**, choose the account, and pick the repositories to share.
3. You land back on the organization page. The first sync starts by itself and the numbers
   fill in within a minute.

## What it does and doesn't do
- Read-only: DevPilot can't push, merge, comment or edit anything.
- Stores titles, states, authors, dates, commit headlines and CI results. It does **not** store
  issue or PR bodies or file contents. AI features fetch what they need at the time.
- Webhooks are accepted only with a valid signature. Redelivered ones are ignored.
- **Disconnect** removes our copy of the data. To revoke access completely, also uninstall the
  app in GitHub, Settings, Applications.
- Any admin of an organization can connect GitHub. Everyone in the organization can see the
  synced repositories, including private ones.

## Troubleshooting
- **"Missing: GITHUB_..." on the org page:** that variable is empty or the API wasn't restarted.
- **GitHub says the callback URL doesn't match:** it must be exactly
  `http://localhost:3001/github/callback`.
- **"GitHub did not accept the authorization":** the one-time code was used or expired.
  Click Connect GitHub again.
- **Webhooks don't arrive:** on the app's *Advanced* tab, *Recent Deliveries* shows each attempt
  and its response. `401` means the secret in `.env` differs from the app's.
- **Sync says "rate limit reached":** GitHub allows a few thousand calls an hour per installation.
  Wait for the time shown, then press Sync now.
- **App permissions changed later:** the account owner has to approve the new permissions on GitHub.

## Production
Create a second GitHub App for production with the real URLs, never reuse the dev app's
secrets, and keep the private key in the host's secret store, not in the repo.
