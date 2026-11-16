# CI failure analysis

An AI explanation of why a GitHub Actions run failed: what broke, the most likely cause, what to
try next, and the exact log lines it is based on.

**Nothing is posted to GitHub and nothing is re-run.** DevPilot's GitHub app is read-only. Use
**Copy as Markdown** to paste an analysis into an issue or a chat yourself.

## Try it

1. Sync GitHub (**Sync now**) so your workflow runs appear.
2. On the organization page, open **CI runs** (failed runs are shown first) and click **Analyze**.
3. It goes Queued, then Reading logs, then shows the type of failure, the likely cause, a suggested
   fix, the failed steps, and quotes from the logs.

Members, admins and owners can start an analysis. Viewers can read them. Analyses need the worker
running (`docs/INDEXING.md`), or `JOB_BACKEND=inline`. No new GitHub permission is needed: the app
already has *Actions: read*.

## How an analysis is made

1. DevPilot asks GitHub for the run's jobs and picks the failed ones (up to `CI_MAX_JOBS`).
2. For each, it downloads the **end** of the job log (up to `CI_MAX_LOG_BYTES`), because a job
   almost always fails near its end.
3. The log is cleaned (colour codes, timestamps and blank noise removed) and cut down to the last
   lines plus the lines around error messages, within `CI_MAX_LOG_CHARS` for all jobs together.
4. The model answers from those excerpts. DevPilot checks the answer before storing it (below).

Logs are **not stored**. Only the short quotes that back the answer are kept.

## What is checked

- Every quote the model offers as evidence must appear in the excerpt that was sent. A quote that
  doesn't is **dropped**, and one filed under the wrong job is moved to the job it really came from.
- "High confidence" needs at least one verified quote. Without one it is lowered to medium.
- The category must be one of the known types, otherwise the answer is rejected.
- The analysis says plainly what it read ("Read the logs of 2 of 3 failed jobs. No log for: ...").

## Credentials

- **Credential-looking log lines are never sent to the AI.** They are replaced before the model
  sees the log, and a private key block is replaced from its first line to its last.
  The analysis tells you how many lines were withheld.
- GitHub already masks secrets it knows about; this is a second safety net, not a guarantee.
- The GitHub token is not sent to the host GitHub redirects log downloads to.

## Limits

- It sees log text, not your code or other runs. It can't say a test is flaky from one failure, and
  is told not to.
- Only finished runs that **failed** or **timed out** can be analyzed. Cancelled runs, runs still in
  progress and runs that failed before any job started (for example a mistake in the workflow file)
  have no job log to read.
- GitHub keeps logs for a limited time (90 days by default). Older runs say the log expired.
- Treat the answer as a lead to check, not a verdict. Logs are untrusted text and are wrapped so the
  model reads them as data; that reduces prompt-injection risk but doesn't remove it. The model can
  only produce text: nothing it says is executed or sent anywhere.
- If a run is re-run on GitHub, the analysis is marked "run changed since". Analyze again to read the
  new logs. Analyzing an unchanged run shows the stored result instead of spending tokens again
  (**Re-run** forces it).

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `CI_MAX_JOBS` | 4 | failed jobs whose logs are read per run |
| `CI_MAX_LOG_BYTES` | 1000000 | the end of each job log kept after download |
| `CI_MAX_LOG_CHARS` | 40000 | budget for log text sent to the model, across all jobs |
| `CI_MAX_OUTPUT_TOKENS` | 4096 | analysis size, including the model's hidden reasoning |
| `CI_RATE_LIMIT_PER_MINUTE` | 5 | analyses one person can start a minute |

## Troubleshooting

| You see | Likely cause |
|---|---|
| Stuck on "Queued…" | worker not running, or it can't reach Redis |
| "GitHub denied access to this run" | the app needs *Actions: read*, or the repository is no longer shared with it |
| "No log could be read for this run" | logs expired, were removed, or were empty |
| "GitHub reports no failed jobs" | the run failed before any job started: check the workflow file on GitHub |
| "The AI returned an analysis that could not be used" | the model broke the format: click Retry, or raise `CI_MAX_OUTPUT_TOKENS` |
| "AI isn't set up on the server yet" | fill in `GEMINI_API_KEY` and `GEMINI_MODEL` (`docs/AI.md`) |
| 503 "high demand" from Google | busy: wait and click Retry |
| "The AI provider's daily request quota is used up" | the key's daily limit is spent (the free tier allows very few requests a day). Wait for the reset it names, turn on billing, or switch `GEMINI_MODEL`. DevPilot stops at once instead of retrying all day |
| No CI runs listed | click **Sync now** on the GitHub section |
