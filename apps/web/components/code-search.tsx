"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, codeApi, type Repo } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

const PREVIEW_LINES = 12;

export function CodeSearch({ orgId, repos }: { orgId: string; repos: Repo[] }) {
  const [query, setQuery] = useState("");
  const [repoId, setRepoId] = useState("");
  const indexed = repos.filter((r) => r.index.status === "ready" && r.index.chunks > 0);

  const search = useMutation({
    mutationFn: async () =>
      codeApi.search(await accessToken(), orgId, {
        query: query.trim(),
        ...(repoId ? { repository_id: repoId } : {}),
      }),
  });

  if (indexed.length === 0) return null;
  const byId = new Map(repos.map((r) => [r.id, r]));

  return (
    <section className="mt-10" aria-label="Code search">
      <h2 className="text-lg font-medium">Search code</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Describe what you are looking for, for example “where is login handled”.
      </p>
      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate();
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          maxLength={500}
          placeholder="Search indexed repositories…"
          aria-label="Search query"
          className="min-w-64 flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
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
          disabled={search.isPending || !query.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
        >
          {search.isPending ? "Searching…" : "Search"}
        </button>
      </form>

      {search.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {search.error instanceof ApiError ? search.error.message : "The search failed."}
        </p>
      )}
      {search.isSuccess && search.data.results.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">Nothing found.</p>
      )}
      {search.isSuccess && search.data.results.length > 0 && (
        <ul className="mt-4 space-y-4">
          {search.data.results.map((hit, i) => {
            const repo = byId.get(hit.repository_id);
            const link =
              repo && repo.default_branch
                ? `${repo.html_url}/blob/${encodeURIComponent(repo.default_branch)}/${hit.path}#L${hit.start_line}-L${hit.end_line}`
                : null;
            const lines = hit.content.split("\n");
            const preview = lines.slice(0, PREVIEW_LINES).join("\n");
            return (
              <li key={`${hit.repository_id}-${hit.path}-${hit.start_line}-${i}`} className="rounded-md border border-border">
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-3 py-2 text-sm">
                  <span>
                    <span className="text-muted-foreground">{hit.repository} · </span>
                    {link ? (
                      <a href={link} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                        {hit.path}:{hit.start_line}-{hit.end_line}
                      </a>
                    ) : (
                      <span className="font-medium">
                        {hit.path}:{hit.start_line}-{hit.end_line}
                      </span>
                    )}
                    {hit.symbol && <span className="ml-2 text-xs text-muted-foreground">{hit.symbol}</span>}
                  </span>
                  <span className="text-xs text-muted-foreground">match {Math.round(hit.score * 100)}%</span>
                </div>
                <pre className="overflow-x-auto px-3 py-2 text-xs leading-relaxed">
                  <code>{preview}</code>
                  {lines.length > PREVIEW_LINES && (
                    <span className="text-muted-foreground">{`\n… ${lines.length - PREVIEW_LINES} more lines`}</span>
                  )}
                </pre>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
