"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AnswerText } from "@/components/answer-text";
import { ApiError, ciApi, type CiRunRow } from "@/lib/api";
import { analysisToMarkdown, CATEGORY_LABEL } from "@/lib/ci-markdown";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const NO_LINKS = () => null;

export function CiPanel({ orgId, run }: { orgId: string; run: CiRunRow }) {
  const [copied, setCopied] = useState(false);
  const analysis = useQuery({
    queryKey: ["org", orgId, "ci-analysis", run.id],
    queryFn: async () => ciApi.get(await accessToken(), orgId, run.id),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "queued" || status === "running" ? 3000 : false;
    },
  });

  const data = analysis.data;
  if (analysis.isError) {
    return (
      <p role="alert" className="px-4 py-3 text-sm text-danger">
        {analysis.error instanceof ApiError ? analysis.error.message : "Could not load the analysis."}
      </p>
    );
  }
  if (!data) return <p className="px-4 py-3 text-sm text-muted-foreground">No analysis yet.</p>;
  if (data.status === "queued" || data.status === "running") {
    return (
      <p className="px-4 py-3 text-sm text-muted-foreground">
        {data.status === "queued" ? "Queued… waiting for the worker." : "Reading the logs…"}
        {data.error && <span className="block text-xs">{data.error}</span>}
      </p>
    );
  }
  if (data.status === "failed") {
    return (
      <p role="alert" className="px-4 py-3 text-sm text-danger">
        The analysis failed: {data.error ?? "unknown error"}
      </p>
    );
  }

  return (
    <div className="space-y-4 px-4 py-4">
      {data.stale && (
        <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          This run changed after the analysis (it was probably re-run). Analyze it again to read the new logs.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="rounded-sm border border-border px-1.5 py-0.5 text-[0.7rem] font-semibold uppercase">
          {data.category ? CATEGORY_LABEL[data.category] : "Unclear"}
        </span>
        <span className="text-muted-foreground">
          confidence{" "}
          <span className={cn("font-medium", data.confidence === "high" && "text-foreground")}>
            {data.confidence ?? "unknown"}
          </span>
        </span>
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(analysisToMarkdown(run, data));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
          className="ml-auto rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
        >
          {copied ? "Copied" : "Copy as Markdown"}
        </button>
      </div>

      {data.summary && <AnswerText text={data.summary} linkFor={NO_LINKS} />}

      {data.likely_cause && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Likely cause</p>
          <AnswerText text={data.likely_cause} linkFor={NO_LINKS} />
        </div>
      )}
      {data.suggested_fix && (
        <div className="rounded-md bg-muted px-3 py-2">
          <p className="text-xs font-medium text-muted-foreground">Suggested fix</p>
          <AnswerText text={data.suggested_fix} linkFor={NO_LINKS} />
        </div>
      )}

      {data.failed_steps.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Failed steps</p>
          <ul className="mt-1 list-inside list-disc text-sm">
            {data.failed_steps.map((s, i) => (
              <li key={`${s.job}-${s.step ?? ""}-${i}`}>
                {s.job}
                {s.step && <span className="text-muted-foreground">: {s.step}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.evidence.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">From the logs (checked against them)</p>
          <ul className="mt-1 space-y-2">
            {data.evidence.map((e, i) => (
              <li key={`${e.job}-${i}`}>
                <p className="text-xs text-muted-foreground">{e.job}</p>
                <pre className="overflow-x-auto whitespace-pre-wrap wrap-break-word rounded-md border border-border bg-muted px-3 py-2 text-xs">
                  {e.quote}
                </pre>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="border-t border-border pt-3 text-xs text-muted-foreground">
        {data.notes && <span className="block">{data.notes}</span>}
        AI can be wrong: check the log before acting on this. Nothing is posted to GitHub and nothing is re-run.
        {data.model && ` · ${data.model}`}
      </p>
    </div>
  );
}
