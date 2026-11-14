"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { AnswerText } from "@/components/answer-text";
import { ApiError, codeApi, type Repo } from "@/lib/api";
import { lineLink } from "@/lib/github-links";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "Give me a technical overview of this codebase",
  "Where is authentication implemented?",
  "How does the API work?",
  "Which external services or dependencies does it use?",
];

const CONFIDENCE_STYLE = {
  high: "text-success",
  medium: "text-muted-foreground",
  low: "text-danger",
} as const;

export function AskPanel({ orgId, repos }: { orgId: string; repos: Repo[] }) {
  const [question, setQuestion] = useState("");
  const [repoId, setRepoId] = useState("");
  const indexed = repos.filter((r) => r.index.status === "ready" && r.index.chunks > 0);

  const ask = useMutation({
    mutationFn: async () =>
      codeApi.ask(await accessToken(), orgId, {
        question: question.trim(),
        ...(repoId ? { repository_id: repoId } : {}),
      }),
  });

  if (indexed.length === 0) return null;
  const byId = new Map(repos.map((r) => [r.id, r]));
  const result = ask.data;
  const citation = (n: number) => result?.citations.find((c) => c.n === n);
  const linkFor = (n: number) => {
    const c = citation(n);
    return c ? lineLink(byId.get(c.repository_id), c.path, c.start_line, c.end_line) : null;
  };
  const canSubmit = question.trim().length >= 3 && !ask.isPending;

  return (
    <section className="mt-10" aria-label="Ask about your code">
      <h2 className="text-lg font-medium">Ask about your code</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Answers come from the indexed code and cite the files and lines they used.
      </p>

      <form
        className="mt-3 space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) ask.mutate();
        }}
      >
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && canSubmit) ask.mutate();
          }}
          maxLength={1000}
          rows={2}
          placeholder="Ask a question about the code…  (Ctrl+Enter to send)"
          aria-label="Question"
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={repoId}
            onChange={(e) => setRepoId(e.target.value)}
            aria-label="Repository"
            className="rounded-md border border-border bg-background px-2 py-2 text-sm"
          >
            <option value="">All indexed repositories</option>
            {indexed.map((r) => (
              <option key={r.id} value={r.id}>
                {r.full_name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
          >
            {ask.isPending ? "Thinking…" : "Ask"}
          </button>
        </div>
        {repoId === "" && indexed.length > 1 && (
          <p className="text-xs text-muted-foreground">
            Tip: choose one repository for questions like “overview of this program”. Otherwise
            the answer can mix several projects.
          </p>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuestion(example)}
              className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted"
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {ask.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {ask.error instanceof ApiError ? ask.error.message : "The question could not be answered."}
        </p>
      )}

      {result && (
        <div className="mt-4 rounded-md border border-border">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground">
            <span>
              Confidence:{" "}
              <span className={cn("font-medium", CONFIDENCE_STYLE[result.confidence])}>
                {result.confidence}
              </span>
            </span>
            <span>
              Based on {result.sources_considered} pieces of code and docs · {result.model}
            </span>
          </div>
          <div className="px-4 py-3">
            <AnswerText text={result.answer} linkFor={linkFor} />
            {result.missing_context && (
              <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                <span className="font-medium">Not covered by the code found:</span>{" "}
                {result.missing_context}
              </p>
            )}
          </div>
          {result.citations.length > 0 && (
            <div className="border-t border-border px-4 py-3">
              <h3 className="text-xs font-medium text-muted-foreground">Sources</h3>
              <ul className="mt-2 space-y-1 text-sm">
                {result.citations.map((c) => {
                  const href = lineLink(byId.get(c.repository_id), c.path, c.start_line, c.end_line);
                  const label = `${c.path}:${c.start_line}-${c.end_line}`;
                  return (
                    <li key={c.n}>
                      <span className="text-muted-foreground">[{c.n}] {c.repository} · </span>
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
          <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
            AI can be wrong. Check the cited code before relying on an answer.
          </p>
        </div>
      )}
    </section>
  );
}
