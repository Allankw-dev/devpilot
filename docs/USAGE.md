# AI usage

The **AI usage** section at the bottom of the **Analytics** page shows where your AI requests, tokens and errors
went, so you can see why you're hitting limits before you hit them. Everyone in the organization
can see it. Nothing about prompts or replies is stored or shown: only counts, token numbers,
model names and error types.

## What you see

| Item | Meaning |
|---|---|
| **Operations** | things DevPilot asked the AI to do (a review, an analysis, a question) |
| **Provider calls** | requests actually sent to the provider, **retries included**. This is the number your quota counts |
| **Failed operations** | operations that ended in an error |
| **Avg response** | average time of the successful ones |
| **Input / output tokens** | text sent and received. Output includes the model's hidden thinking |
| **Last 24 hours** | provider calls in the last 24 hours, against your daily limit if you set one |
| **Provider calls per day** | bars per UTC day; a red bar had failures |
| **By feature** | Ask, code search, indexing, pull request review, CI analysis, connection test |
| **By model** | calls per model. Provider daily limits are usually **per model** |
| **What went wrong** | error types: daily quota used up, rate limited, provider unavailable, timeout, API key rejected, and so on |

When the provider says a daily quota is used up, a banner appears for 24 hours with when it was last
seen. DevPilot stops retrying at that point (`docs/AI.md`), so one bad day doesn't burn requests.

## Show your limit

DevPilot can't read your quota from the provider, so you tell it. In `apps/api/.env`:

```
AI_DAILY_REQUEST_LIMIT=20
```

Use the number from your provider's rate-limits page (the Google AI Studio free tier is small). The
**Last 24 hours** bar then fills up and turns red at the limit. Leave it unset to hide the bar.
Restart the API after changing it.

## Limits DevPilot enforces itself

These stop one person, or one workspace, from using up your AI allowance. They are separate from
the provider's own limits and from the **Last 24 hours** bar above.

| Limit | Setting | Default |
|---|---|---|
| Questions per person per minute | `ASK_RATE_LIMIT_PER_MINUTE` | 10 |
| Reviews started per person per minute | `REVIEW_RATE_LIMIT_PER_MINUTE` | 5 |
| CI analyses started per person per minute | `CI_RATE_LIMIT_PER_MINUTE` | 5 |
| Ask, review and CI requests per **workspace** per UTC day | `AI_ORG_DAILY_REQUEST_LIMIT` | 0 (no cap) |

How they behave:

- **A slot is taken before any AI work starts**, with one atomic database statement. Fifty requests
  arriving at the same moment get exactly as many slots as are left, and no more. (Before, the
  count only grew after the AI had answered, so a burst all got through.) A test with real
  concurrent connections on PostgreSQL checks this.
- **Every attempt that gets past permission checks counts**, even if the answer then comes from an
  earlier review, or the AI call later fails. A blocked request costs nothing.
- **Windows are fixed, not sliding:** "this minute" and "this UTC day". Right at a boundary someone can
  use up to twice the limit across two windows.
- **The workspace cap counts requests, not provider calls.** One review can make several model
  calls, and indexing (which embeds code) isn't counted at all.
- **They work across several API servers**, because the counters live in the database, as long as the
  servers' clocks agree to within a few seconds.
- A blocked request gets a 429 with a message, and nothing is queued.

## Why the numbers may differ from your provider's

- DevPilot counts **only requests it sent**. If the same API key is used by other apps, the provider
  counts those too.
- Days here are **UTC**. A provider may reset its day at another time (some use midnight Pacific),
  so the 24-hour bar is a guide, not the exact quota state.
- **Retries count.** One slow review that retries three times is three provider calls. That is
  usually why a small quota runs out faster than the operation count suggests.

## Tips for a small quota

- Look at **By feature**: reviews and indexing use the most calls.
- Don't click Analyze or Review repeatedly while a request is queued.
- Check **By model**: a different model has its own daily allowance.
- Turn on billing with your provider for real use.
