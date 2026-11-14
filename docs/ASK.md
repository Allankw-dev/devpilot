# Asking questions about your code

Ask in plain language and get an answer that cites the files and lines it used.

## Try it

1. Index at least one repository (`docs/INDEXING.md`).
2. On the organization page, open **Ask about your code**, type a question (or click an example),
   optionally choose one repository, and press **Ask** (or Ctrl+Enter).
3. Click a `[1]` marker or an entry under **Sources** to open those exact lines on GitHub.

Members, admins and owners can ask. Viewers cannot, because every question costs tokens.

Good questions: "Where is authentication implemented?", "How does the API handle errors?",
"Which external services does this use?", "Give me a technical overview". Choosing one repository
works better for overview questions, because DevPilot then also gives the model the repository's file list.

## How an answer is made

1. Your question is embedded and the closest pieces of code are found (the same search as **Search
   code**), only within your organization. Identical copies are collapsed.
2. Those pieces, up to `ASK_TOP_K` and `ASK_MAX_CONTEXT_CHARS`, are numbered and given to the
   configured model (`GEMINI_MODEL`). The model never sees the whole repository.
   No single file supplies more than `ASK_MAX_CHUNKS_PER_FILE` of them (default 3), so a long README
   can't crowd out the actual code.
3. The model must answer only from those sources and cite them as `[1]`, `[2]`. Sources are labelled
   **code** or **documentation**, and the model is told that documentation shows what the docs
   *claim*, not what the code does. An answer that rests only on a README should say so and should not
   claim high confidence.
4. DevPilot checks the citations. A number that doesn't match a real source is removed, so the model
   can't point at something it wasn't given. Real citations are renumbered 1, 2, 3... in order of first
   use, so the answer reads cleanly.

The answer also carries a **confidence** (high / medium / low) and, when the code found doesn't cover
the question, a note saying what is missing. **Low confidence or a "not covered" note usually means the
relevant code wasn't retrieved**: try a more specific question, choose the repository, or re-index.

## Limits you should know about

- It answers from the best-matching pieces of code, not from reading everything. Questions about
  the whole repository ("find all bugs", "list unused code", "find duplicates") are only as good as
  the pieces retrieved. Treat those answers as leads, not audits.
- Overview questions lean on READMEs because they summarise well. If the answer says "according to the
  README", it is repeating documentation, not verified code. Ask about specific behaviour ("how does
  deposit validate the amount?") to make it read the code.
- It sees only indexed files. Excluded files, secrets and files over the size limit are invisible.
- Each question is separate: there is no conversation memory yet.
- Answers are not saved. Reloading the page clears them.
- AI can be wrong. The answer shows its sources so you can check them.

## Safety

- Code, comments and file names are untrusted text. They are wrapped so the model treats them as
  data, but this reduces the risk and does not remove it. The model can only produce text: nothing it
  says is executed or sent to GitHub.
- The answer is displayed as plain text. Model output can never inject HTML, scripts or links;
  only validated citation numbers become links.
- Search and answers are limited to your organization.
- One person can ask `ASK_RATE_LIMIT_PER_MINUTE` questions a minute (default 10).

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `ASK_TOP_K` | 12 | pieces of code given to the model |
| `ASK_MAX_CHUNKS_PER_FILE` | 3 | most pieces taken from any one file |
| `ASK_MAX_CONTEXT_CHARS` | 28000 | budget for those pieces (about 7k tokens) |
| `ASK_MAX_OUTPUT_TOKENS` | 8192 | answer size, including the model's hidden reasoning |
| `ASK_RATE_LIMIT_PER_MINUTE` | 10 | per person |

## Troubleshooting

| You see | Likely cause |
|---|---|
| "Nothing is indexed to answer from" | no repository has finished indexing |
| "The AI provider rejected the API key" or `bad_request` | check `GEMINI_MODEL` is a chat model (`docs/AI.md`) |
| "cut off before the JSON was complete" | raise `ASK_MAX_OUTPUT_TOKENS` |
| "The AI provider is rate limiting us" / 503 "high demand" | Google is busy: wait and retry |
| A confident-sounding but wrong answer | check the cited lines; re-index if the code changed |
