# Pull request reviews

An AI review of a pull request: what it changes, how risky it is, and a list of findings (bugs, security
risks, performance problems, missing error handling). Each finding names a file, the lines, a severity, an
explanation, a suggested fix and a confidence.

**Nothing is posted to GitHub.** DevPilot's GitHub app is read-only, and a review needs a person to decide
what to do with it. Use **Copy as Markdown** to paste a review into a GitHub comment yourself.

## Try it

1. Sync GitHub (**Sync now**) so your pull requests appear.
2. On the organization page, open **Pull requests** and click **Review** on one.
3. It goes Queued, then Reviewing, then shows the summary, a risk level and the findings. Click a
   file name to open those exact lines on GitHub.
4. **Dismiss** a finding you don't agree with. It stays hidden for everyone (use **Show dismissed**
   to see it, **Restore** to bring it back).

Members, admins and owners can start a review. Viewers can read reviews and dismissals are not
available to them. Reviews need the worker running (`docs/INDEXING.md`), or `JOB_BACKEND=inline`.

## How a review is made

1. DevPilot fetches the pull request's title, description and changed files from GitHub (needs the
   app's *Pull requests: read* permission, which it already has).
2. It chooses what to review: source code first, then tests, config and docs, within a file and size budget.
   Lockfiles, generated and binary files are skipped. Deleted files are only listed.
3. The diff is shown to the model with the **new file's line numbers**, so it can cite exact lines.
4. DevPilot checks every finding against the real diff (below) before storing it.

## What is checked

- A finding for a file that is not in the diff is **dropped**: the model cannot point at something it was
  not shown.
- A finding whose lines are not in the changed code becomes a **file-level** finding instead of
  pretending to be on a line that doesn't exist. A range that is partly outside is trimmed.
- Duplicates (same place, same kind of problem) collapse to the most severe. At most
  `REVIEW_MAX_FINDINGS` are kept, worst first.
- The review says plainly what it covered ("Reviewed 18 of 52 changed files. Not reviewed: ...").

## Credentials

- **Credential-looking lines are never sent to the AI.** Added lines that look like a key, token or
  password are replaced before the model sees the diff, and DevPilot reports them itself as a
  **security finding** (marked "found by the credential scanner") with the line number.
- Files that usually hold secrets (`.env`, `*.pem`, `id_rsa`, `credentials.json`, ...) are not read at
  all. If a pull request adds or changes one, that is flagged too.
- The scan covers every changed file, even ones the review budget leaves out.
- A pull request with a possible credential is never rated "low risk".

## Limits

- It sees the diff, not the whole codebase. Where code it can't see decides the question, it should say so
  and use low confidence. Treat findings as leads to check, not verdicts.
- It cannot run your code or tests, and says nothing about test results.
- Large pull requests are partly reviewed (see the note under the review). Review big ones in pieces.
- Each review is a single request to the model. Re-running costs tokens again; if the pull request
  hasn't changed since the last review, the stored one is shown instead (use **Re-run** to force it).
- Descriptions and code are treated as untrusted text and wrapped so the model reads them as data. This
  reduces prompt-injection risk but doesn't remove it. The model can only produce text: nothing it says
  is executed or sent anywhere.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `REVIEW_MAX_FILES` | 40 | files whose diffs are sent to the model |
| `REVIEW_MAX_DIFF_CHARS` | 60000 | size budget for those diffs (about 15k tokens) |
| `REVIEW_MAX_OUTPUT_TOKENS` | 8192 | review size, including the model's hidden reasoning |
| `REVIEW_MAX_FINDINGS` | 25 | findings kept per review |
| `REVIEW_RATE_LIMIT_PER_MINUTE` | 5 | reviews one person can start a minute |

## Troubleshooting

| You see | Likely cause |
|---|---|
| Stuck on "Queued…" | worker not running, or it can't reach Redis |
| "GitHub denied access to this pull request" | the app needs *Pull requests: read*, or the repository is no longer shared |
| "cut off before the JSON was complete" | raise `REVIEW_MAX_OUTPUT_TOKENS` |
| "AI isn't set up on the server yet" | fill in `GEMINI_API_KEY` and `GEMINI_MODEL` (`docs/AI.md`) |
| 503 "high demand" from Google | busy: wait and click Retry |
| No pull requests listed | click **Sync now** on the GitHub section |
