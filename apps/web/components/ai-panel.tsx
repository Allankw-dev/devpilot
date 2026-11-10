"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { aiApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

export function AiPanel({ orgId, isAdmin }: { orgId: string; isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["org", orgId, "ai"],
    queryFn: async () => aiApi.status(await accessToken(), orgId),
  });
  const test = useMutation({
    mutationFn: async () => aiApi.test(await accessToken(), orgId),
    // the test is recorded as usage, so refresh the numbers (also after a failed test)
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "ai"] }),
  });

  const ai = status.data;
  const fmt = new Intl.NumberFormat();

  return (
    <section className="mt-10" aria-label="AI">
      <h2 className="text-lg font-medium">AI</h2>

      {status.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          Couldn’t load AI status.
        </p>
      )}

      {ai && !ai.configured && (
        <div className="mt-3 space-y-1 text-sm">
          <p className="text-muted-foreground">AI isn’t set up on the server yet.</p>
          {isAdmin && ai.missing.length > 0 && (
            <p className="text-muted-foreground">
              Missing settings: <code className="text-foreground">{ai.missing.join(", ")}</code>.
              See docs/AI.md.
            </p>
          )}
        </div>
      )}

      {ai && ai.configured && (
        <>
          <p className="mt-3 text-sm text-muted-foreground">
            Using <span className="capitalize text-foreground">{ai.provider}</span>
            {ai.model && (
              <>
                {" "}
                · <code className="text-foreground">{ai.model}</code>
              </>
            )}
            {!ai.embeddings_configured && " · code search embeddings not configured yet"}
          </p>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label={`Requests (${ai.usage.days} days)`} value={fmt.format(ai.usage.requests)} />
            <Stat label="Failed" value={fmt.format(ai.usage.errors)} />
            <Stat label="Input tokens" value={fmt.format(ai.usage.input_tokens)} />
            <Stat label="Output tokens" value={fmt.format(ai.usage.output_tokens)} />
          </div>

          {isAdmin && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => test.mutate()}
                disabled={test.isPending}
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
              >
                {test.isPending ? "Testing…" : "Test AI connection"}
              </button>
              {test.isSuccess && (
                <p role="status" className="text-sm text-success">
                  Works: replied in {fmt.format(test.data.latency_ms)} ms (
                  {fmt.format(test.data.input_tokens + test.data.output_tokens)} tokens).
                </p>
              )}
              {test.isError && (
                <p role="alert" className="text-sm text-danger">
                  {test.error instanceof Error ? test.error.message : "The test failed."}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
