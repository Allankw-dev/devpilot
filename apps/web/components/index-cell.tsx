"use client";

import type { Repo } from "@/lib/api";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

const WAITING_FOR_WORKER_MS = 90_000;

export function IndexCell({
  repo,
  canIndex,
  busy,
  onStart,
}: {
  repo: Repo;
  canIndex: boolean;
  busy: boolean;
  onStart: () => void;
}) {
  const { index } = repo;
  const active = index.status === "queued" || index.status === "running";
  const waitingTooLong =
    index.status === "queued" &&
    index.queued_at !== null &&
    Date.now() - new Date(index.queued_at).getTime() > WAITING_FOR_WORKER_MS;

  const label = {
    none: "Not indexed",
    queued: "Queued…",
    running: `Indexing… ${index.files} files`,
    ready: `${index.chunks.toLocaleString()} chunks · ${ago(index.indexed_at)}`,
    failed: "Failed",
  }[index.status];

  const action = index.status === "none" ? "Index" : index.status === "failed" ? "Retry" : "Re-index";

  return (
    <div className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          className={cn(
            index.status === "ready" && "text-success",
            index.status === "failed" && "text-danger",
            (index.status === "none" || active) && "text-muted-foreground",
          )}
        >
          {label}
        </span>
        {canIndex && !active && (
          <button
            type="button"
            onClick={onStart}
            disabled={busy || repo.default_branch === null}
            className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
          >
            {action}
          </button>
        )}
      </div>
      {index.error && (
        <p
          className={cn("text-xs", index.status === "failed" ? "text-danger" : "text-muted-foreground")}
          title={index.error}
        >
          {index.error}
        </p>
      )}
      {waitingTooLong && (
        <p className="text-xs text-muted-foreground">
          Still waiting to start. Is the worker running? See docs/INDEXING.md.
        </p>
      )}
      {index.status === "ready" && index.skipped_chunks > 0 && (
        <p
          className="text-xs text-muted-foreground"
          title="Pieces of code that looked like passwords or keys are never stored or sent to the AI."
        >
          {index.skipped_chunks} skipped (looked like secrets)
        </p>
      )}
    </div>
  );
}
