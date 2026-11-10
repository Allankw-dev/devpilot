# AI setup

All AI goes through `apps/api/app/services/llm/`. Business code builds a request and calls
`LLMService`; only `providers/` imports a vendor SDK (a test enforces this).

## Turn it on (Gemini)

1. Create an API key in Google AI Studio.
2. Pick a current text model and embedding model from Google's model list
   (https://ai.google.dev/gemini-api/docs/models). Names change often, which is why there is
   no default in code.
3. Put them in the repo-root `.env` and restart the API:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=...
GEMINI_EMBEDDING_MODEL=...
```

4. Open an organization page. As an admin you'll see the AI section; click
   **Test AI connection**. It sends one tiny prompt and shows latency and tokens.

The API key stays on the server. The browser never sees it, and the status endpoint only
reports setting *names* that are missing, never values.

## Using Anthropic instead (optional)

Set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. Anthropic has no
embeddings API, so embeddings stay on Gemini (`GEMINI_API_KEY` + `GEMINI_EMBEDDING_MODEL`).
Using Claude Code to develop this project needs no Anthropic key here.

## What `LLMService` gives every feature

| Need | Call |
|---|---|
| Plain answer | `generate(request, ctx)` |
| JSON validated against a Pydantic model (one repair attempt) | `generate_structured(request, Model, ctx)` |
| Model calls our read-only tools, bounded steps | `run_tools(request, [Tool(...)], ctx)` |
| Embeddings, batched | `embed(texts, "document" \| "query", ctx)` |

Built in: per-call timeout (`LLM_TIMEOUT_SECONDS`), retries with backoff on rate limits,
timeouts and 5xx (`LLM_MAX_ATTEMPTS`), and one `llm_usage` row per operation
(provider, model, tokens, latency, ok/error). Prompts and replies are never stored.

## Rules when writing prompts

- Anything from a repository, PR, issue or CI log goes through `untrusted(label, text)` and the
  system prompt includes `UNTRUSTED_CONTENT_NOTICE`.
- Tool handlers are our code. Model-supplied arguments are untrusted: validate them, keep
  handlers read-only and bounded.
- Nothing the model returns is ever executed or posted to GitHub without a human approving it.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` or `anthropic` |
| `LLM_TIMEOUT_SECONDS` | 60 | per provider call |
| `LLM_MAX_ATTEMPTS` | 3 | calls per operation, retries included |
| `LLM_MAX_OUTPUT_TOKENS` | 4096 | default cap when a caller doesn't set one |
| `EMBEDDING_DIMENSIONS` | 768 | must match the pgvector column (added with indexing) |
| `WEBHOOK_DELIVERY_RETENTION_DAYS` | 7 | how long GitHub delivery ids are remembered |
