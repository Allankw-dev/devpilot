"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AnswerText } from "@/components/answer-text";
import { ApiError, reviewApi, type Finding, type PullRequestRow, type Severity } from "@/lib/api";
import { findingLink, reviewToMarkdown } from "@/lib/review-markdown";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "border-danger bg-danger text-primary-foreground",
  high: "border-danger text-danger",
  medium: "border-border text-foreground",
  low: "border-border text-muted-foreground",
  info: "border-border text-muted-foreground",
};

const RISK_STYLE = { low: "text-success", medium: "text-foreground", high: "text-danger" } as const;
const NO_LINKS = () => null;

function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={cn("rounded-sm border px-1.5 py-0.5 text-[0.7rem] font-semibold uppercase", SEVERITY_STYLE[severity])}>
      {severity}
    </span>
  );
}

function FindingCard({
  finding,
  link,
  canEdit,
  busy,
  onToggle,
}: {
  finding: Finding;
  link: string;
  canEdit: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  const where =
    finding.start_line > 0
      ? `${finding.file}:${finding.start_line}${finding.end_line > finding.start_line ? `-${finding.end_line}` : ""}`
      : finding.file;
  const dismissed = finding.status === "dismissed";
  return (
    <li className={cn("rounded-md border border-border", dismissed && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-sm">
        <SeverityBadge severity={finding.severity} />
        <span className="font-medium">{finding.title}</span>
        <span className="ml-auto text-xs text-muted-foreground">
          {finding.category.replace("_", " ")} · confidence {finding.confidence}
          {finding.origin === "scan" && " · found by the credential scanner"}
        </span>
      </div>
      <div className="space-y-2 px-3 py-2">
        <a
          href={link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-muted-foreground hover:underline"
        >
          {where}
        </a>
        <AnswerText text={finding.explanation} linkFor={NO_LINKS} />
        {finding.suggestion && (
          <div className="rounded-md bg-muted px-3 py-2">
            <p className="text-xs font-medium text-muted-foreground">Suggestion</p>
            <AnswerText text={finding.suggestion} linkFor={NO_LINKS} />
          </div>
        )}
        {canEdit && (
          <button
            type="button"
            onClick={onToggle}
            disabled={busy}
            className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
          >
            {dismissed ? "Restore" : "Dismiss"}
          </button>
        )}
      </div>
    </li>
  );
}

export function ReviewPanel({
  orgId,
  row,
  canEdit,
}: {
  orgId: string;
  row: PullRequestRow;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [showDismissed, setShowDismissed] = useState(false);
  const [copied, setCopied] = useState(false);
  const key = ["org", orgId, "review", row.id];

  const review = useQuery({
    queryKey: key,
    queryFn: async () => reviewApi.get(await accessToken(), orgId, row.id),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "queued" || status === "running" ? 3000 : false;
    },
  });
  const toggle = useMutation({
    mutationFn: async (f: Finding) =>
      reviewApi.setFinding(await accessToken(), orgId, f.id, f.status === "open" ? "dismissed" : "open"),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: key });
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "pull-requests"] });
    },
  });

  const data = review.data;
  if (review.isError) {
    return (
      <p role="alert" className="px-4 py-3 text-sm text-danger">
        {review.error instanceof ApiError ? review.error.message : "Could not load the review."}
      </p>
    );
  }
  if (!data) return <p className="px-4 py-3 text-sm text-muted-foreground">No review yet.</p>;
  if (data.status === "queued" || data.status === "running") {
    return (
      <p className="px-4 py-3 text-sm text-muted-foreground">
        {data.status === "queued" ? "Queued… waiting for the worker." : "Reviewing the changes…"}
        {data.error && <span className="block text-xs">{data.error}</span>}
      </p>
    );
  }
  if (data.status === "failed") {
    return (
      <p role="alert" className="px-4 py-3 text-sm text-danger">
        The review failed: {data.error ?? "unknown error"}
      </p>
    );
  }

  const open = data.findings.filter((f) => f.status === "open");
  const dismissed = data.findings.filter((f) => f.status === "dismissed");
  const shown = showDismissed ? data.findings : open;

  return (
    <div className="space-y-4 px-4 py-4">
      {data.stale && (
        <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          This pull request changed after the review. Review it again to include the new changes.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>
          Risk:{" "}
          <span className={cn("font-semibold", data.risk && RISK_STYLE[data.risk])}>{data.risk ?? "unknown"}</span>
        </span>
        <span className="text-muted-foreground">
          {open.length} open {open.length === 1 ? "finding" : "findings"}
        </span>
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(reviewToMarkdown(row, data));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
          className="ml-auto rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
        >
          {copied ? "Copied" : "Copy as Markdown"}
        </button>
      </div>

      {data.summary && <AnswerText text={data.summary} linkFor={NO_LINKS} />}

      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {open.length === 0 && dismissed.length === 0
            ? "No problems found in the code that was reviewed."
            : "No open findings."}
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((f) => (
            <FindingCard
              key={f.id}
              finding={f}
              link={findingLink(row, data, f.file, f.start_line, f.end_line)}
              canEdit={canEdit}
              busy={toggle.isPending && toggle.variables?.id === f.id}
              onToggle={() => toggle.mutate(f)}
            />
          ))}
        </ul>
      )}
      {dismissed.length > 0 && (
        <button
          type="button"
          onClick={() => setShowDismissed((v) => !v)}
          className="text-xs text-muted-foreground hover:underline"
        >
          {showDismissed ? "Hide dismissed" : `Show ${dismissed.length} dismissed`}
        </button>
      )}
      {toggle.isError && (
        <p role="alert" className="text-xs text-danger">
          Could not update the finding.
        </p>
      )}

      <p className="border-t border-border pt-3 text-xs text-muted-foreground">
        {data.notes} {data.model && `· ${data.model}`} · {data.input_tokens + data.output_tokens} tokens ·
        Not posted to GitHub: copy it if you want to share it. AI can be wrong, so check each finding.
      </p>
    </div>
  );
}
