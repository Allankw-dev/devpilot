"use client";

import { useState } from "react";

import { AnswerText } from "@/components/answer-text";
import { Button } from "@/components/ui/button";
import type { AssistantMessage, Repo } from "@/lib/api";
import { lineLink } from "@/lib/github-links";
import { cn } from "@/lib/utils";

const CONFIDENCE_STYLE = { high: "text-success", medium: "text-muted-foreground", low: "text-danger" } as const;

export function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap wrap-break-word rounded-lg bg-elevated px-4 py-2 text-sm">{text}</p>
    </div>
  );
}

/** One answer: the text with checked citation links, how sure the model was, and its sources. */
export function AssistantAnswer({
  message,
  repos,
  canRegenerate,
  regenerating,
  onRegenerate,
}: {
  message: AssistantMessage;
  repos: Map<string, Repo>;
  canRegenerate: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const linkFor = (n: number) => {
    const c = message.citations.find((x) => x.n === n);
    return c ? lineLink(repos.get(c.repository_id), c.path, c.start_line, c.end_line) : null;
  };

  return (
    <article className="rounded-lg border border-border bg-card" aria-label="Answer">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground">
        <span>
          Confidence:{" "}
          <span className={cn("font-medium", message.confidence && CONFIDENCE_STYLE[message.confidence])}>
            {message.confidence ?? "unknown"}
          </span>
        </span>
        <span>
          {message.sources_considered !== null && `Based on ${message.sources_considered} pieces of code and docs`}
          {message.model && ` · ${message.model}`}
        </span>
      </div>
      <div className="px-4 py-3">
        {regenerating ? (
          <p role="status" className="text-sm text-muted-foreground">
            Generating this answer again…
          </p>
        ) : (
          <AnswerText text={message.content} linkFor={linkFor} />
        )}
        {message.missing_context && !regenerating && (
          <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
            <span className="font-medium">Not covered by the code found:</span> {message.missing_context}
          </p>
        )}
      </div>
      {message.citations.length > 0 && !regenerating && (
        <div className="border-t border-border px-4 py-3">
          <h3 className="text-xs font-medium text-muted-foreground">Sources</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {message.citations.map((c) => {
              const href = lineLink(repos.get(c.repository_id), c.path, c.start_line, c.end_line);
              const label = `${c.path}:${c.start_line}-${c.end_line}`;
              return (
                <li key={c.n}>
                  <span className="text-muted-foreground">
                    [{c.n}] {c.repository} ·{" "}
                  </span>
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                      {label}
                    </a>
                  ) : (
                    <span className="font-medium">{label}</span>
                  )}
                  {c.symbol && <span className="ml-2 text-xs text-muted-foreground">{c.symbol}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2">
        <p className="text-xs text-muted-foreground">AI can be wrong. Check the cited code before relying on this.</p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={async () => {
              await navigator.clipboard.writeText(message.content);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
          >
            {copied ? "Copied" : "Copy answer"}
          </Button>
          {canRegenerate && (
            <Button size="sm" variant="ghost" disabled={regenerating} onClick={onRegenerate}>
              Generate again
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}
