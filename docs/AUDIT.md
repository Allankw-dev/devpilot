# Audit log

A record of who did what in a workspace. Admins and owners can read it on the **Team** page, under
the members and teams cards. It is for accountability ("who removed Grace?"), not for debugging; for
that, see [`OPERATIONS.md`](OPERATIONS.md).

## What is recorded

| Action | When | `details` |
|---|---|---|
| `org.created` | a workspace is created | `name` |
| `org.renamed` | it is renamed | `from`, `to` |
| `org.deleted` | it is deleted (**log only**, see below) | `name` |
| `member.added` | someone is added | `email`, `role` |
| `member.role_changed` | a role changes | `email`, `from`, `to` |
| `member.removed` | someone is removed or leaves | `email`, `role`, `self` |
| `team.created`, `team.deleted` | a team is created or deleted | `name` |
| `team.member_added`, `team.member_removed` | team membership changes | `team` |
| `github.installation_connected`, `github.installation_disconnected` | a GitHub account is connected or removed | `account` |
| `repository.index_requested` | indexing is started | `repository` |
| `review.requested` | a pull request review is started | `number`, `force` |
| `review.finding_updated` | a finding is marked fixed, dismissed and so on | `status` |
| `ci_analysis.requested` | a failed CI run is analysed | `force` |
| `ai.connection_tested` | an admin runs "Test AI connection" | none |

Each entry also stores who did it, what it was about (`target_type`, `target_id`), when, and the
**request id** of the request that caused it, so it can be matched to the server log.

Only things that actually happened are recorded. A refused request (wrong role, unknown user,
duplicate name) leaves no entry, and neither does a review or analysis that is answered from an
earlier result without doing any work.

Not recorded: asking questions or searching code (the AI usage page covers those), reading anything,
and signing in (that happens at Supabase).

## Guarantees and limits

- **Same transaction.** The entry is saved together with the action, so there is no action without
  an entry and no entry for an action that failed. Entries for jobs are written when the request
  is accepted, not when the background job finishes.
- **Append-only.** No API route edits or deletes an entry; there is a test for that. Someone with
  direct database access can still change anything: this log is not tamper-proof.
- **No sensitive content.** Entries hold short facts such as a role or repository name, never tokens,
  prompts, answers or code. A member's email is stored in the entry when they are added, changed or
  removed, so the entry still makes sense after they leave.
- **Deleting a workspace deletes its entries** (so a deleted workspace leaves no data behind). The
  `org.deleted` event is therefore only written to the application log, as an `app.audit` line with
  the request id, and is gone from the database.
- **If a user is deleted from the database**, their entries stay and show "A removed user".
- **No retention limit yet.** Entries are kept until the workspace is deleted. There is no export.

## Reading it through the API

`GET /api/v1/orgs/{org_id}/audit-log` (admin or owner; anyone else gets 403, and another
organization's id gets 404). Newest first.

| Parameter | Meaning |
|---|---|
| `limit` | 1 to 100, default 50 |
| `before` | the `next_before` of the previous page; `next_before` is `null` on the last page |
| `action` | only entries with exactly this action |

## Also in the application log

Every event is also logged by the `app.audit` logger as JSON with the organization, actor, action and
target ids, plus the request id. Names, emails and other details are left out of the log line.
