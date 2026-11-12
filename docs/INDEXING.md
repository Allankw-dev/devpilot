# Code indexing and search

Indexing turns a repository into searchable pieces so features like "where is auth handled?"
can find the right code without sending whole repositories to an AI model.

## Try it

1. Make sure AI is set up (`docs/AI.md`), including `GEMINI_EMBEDDING_MODEL`.
2. Start the **worker** (below), or set `JOB_BACKEND=inline` to run jobs inside the API instead.
3. Open an organization page. In the repository table click **Index** next to a repository.
4. When it says "N chunks", use **Search code** under the table.

Members, admins and owners can index and search. Viewers can see index status only.

## The worker

Indexing and GitHub syncs run as background jobs on a Celery worker, using Redis as the queue
(`docker compose up -d` starts Redis). Run it in its own terminal, from `apps/api` with the
virtual environment active:

```powershell
# Windows (the default process pool does not work on Windows, so use solo)
celery -A app.jobs.celery_app worker --loglevel=info --pool=solo
```

```bash
# Linux / macOS
celery -A app.jobs.celery_app worker --loglevel=info --concurrency=4
```

Restart the worker after changing code or `.env`. If jobs sit in "Queued" the worker is not
running or cannot reach Redis.

**No worker?** Set `JOB_BACKEND=inline` in `.env`. Jobs then run inside the API process right after
the response. That is fine for trying things out, but a job is lost if the API restarts and a
long index occupies a server thread. Use the worker for anything real.

## What happens during an index run

1. The job is claimed atomically, so a duplicate or stale delivery does nothing.
2. The repository snapshot (default branch tip) is downloaded as one archive and read in memory.
   It is never written to disk and nothing in it is executed.
3. Files are filtered (below), split into chunks, and each chunk is embedded.
4. Progress is saved in batches. If the run is interrupted (rate limit, crash, timeout) the next run
   continues where it stopped.
5. Re-indexing is cheap: each file's content hash is remembered and unchanged files are skipped.
   Only changed files cost embedding tokens. Files removed from the repository are removed from the index.

Failures that may pass (AI rate limit, GitHub outage) are retried automatically with growing delays,
up to 6 times. Failures that will not pass (wrong API key, no access) stop with a message in the table.

## What is stored

Chunk text, its file path and line range, a symbol name where one was found, and its embedding vector.
This is repository content. It is removed when the repository or the GitHub connection is removed, and
it is only ever returned to members of the organization that owns the repository.

## What is left out

Never indexed:
- dependencies and build output: `node_modules`, `vendor`, `dist`, `build`, `target`, `.venv`, `.next`, ...
- lockfiles, minified files, source maps, images, fonts, archives, binaries, notebooks
- files that usually hold credentials: `.env` (but `.env.example` is fine), `*.pem`, `*.key`,
  `id_rsa*`, `*.tfstate`, `*.tfvars`, `credentials.json`, `.npmrc`, ...
- files over `INDEX_MAX_FILE_BYTES`, empty files, binary or non-UTF-8 files, unknown file types

Dropped before embedding: any chunk that looks like a credential (private key blocks, AWS, GitHub,
Google, Anthropic, Slack and Stripe keys, `password = "..."` style assignments). The table shows how many.
This is a safety net, not a guarantee: still keep real secrets out of repositories.

Add your own exclusions with `INDEX_EXCLUDE` (comma separated):

```
INDEX_EXCLUDE=docs/generated,*.snap,legacy
```

A bare name (`legacy`) excludes any folder or file with that name. `docs/generated` excludes that folder.
`*.snap` is a pattern on the file name or path.

## Limits (cost and memory protection)

| Setting | Default | If exceeded |
|---|---|---|
| `INDEX_MAX_FILES` | 3000 | the run fails and says so |
| `INDEX_MAX_CHUNKS` | 20000 | the run fails before paying for the rest |
| `INDEX_MAX_FILE_BYTES` | 200000 | that file is skipped |
| `INDEX_MAX_ARCHIVE_MB` | 150 | download stops, run fails (unpacked size is capped at 6x this) |
| `INDEX_MAX_RUNTIME_SECONDS` | 1800 | the run pauses and continues automatically |

For a too-big repository, add exclusions rather than raising limits.

## How code is split

Python is split with the real parser into functions, classes and methods (decorators and leading
comments stay with their function). Markdown splits on headings. Other languages use a layout heuristic
that starts a new piece at an unindented line after a blank line. Small neighbours are packed together
and large pieces are cut with a little overlap. Line numbers are exact, so results can link to
`path#L10-L42`. Parser-based splitting for more languages (tree-sitter) is a possible upgrade.

## Which embedding model

`gemini-embedding-001` and `gemini-embedding-2` both work, but they are called differently and
DevPilot handles that for you:

- Every chunk is sent as its own input. (`gemini-embedding-2` merges everything in one input into a
  single vector, so a batch sent as one list gets one vector back: that gives the error
  "asked for N embeddings but received 1".)
- `gemini-embedding-001` is told the task with `task_type`. `gemini-embedding-2` takes no `task_type`;
  the task goes into the text (`title: none | text: ...` for code, `task: code retrieval | query: ...`
  for questions).

## Changing the embedding model

Vectors from different models can not be compared. If you change `GEMINI_EMBEDDING_MODEL`, click
**Re-index** on each repository: everything is re-embedded automatically when the model differs.

The database column is 768 dimensions and `EMBEDDING_DIMENSIONS` must stay 768. Using a model or
size that does not fit needs a new migration and re-indexing every repository.

## Troubleshooting

| You see | Likely cause |
|---|---|
| Stuck on "Queued…" | worker not running, or it cannot reach Redis |
| "Missing settings: GEMINI_API_KEY, ..." | fill in `.env`, restart the API and the worker |
| "rejected the API key" | wrong key, or the key cannot use that embedding model |
| "wrong vector size" | the embedding model does not return 768 dimensions |
| "GitHub denied access" | the GitHub App needs Contents: read, or the repo is no longer shared with it |
| "more than N indexable files" | add `INDEX_EXCLUDE` entries |
| 503 "job queue is not reachable" | Redis is down: `docker compose up -d` |
