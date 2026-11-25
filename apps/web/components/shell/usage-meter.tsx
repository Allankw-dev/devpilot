"use client";

import { useQuery } from "@tanstack/react-query";

import { aiApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

/** AI provider calls in the last 24 hours: a real number from the usage records. */
export function UsageMeter({ orgId }: { orgId: string }) {
  const usage = useQuery({
    queryKey: ["org", orgId, "ai-usage", 7],
    queryFn: async () => aiApi.usage(await accessToken(), orgId, 7),
    staleTime: 60_000,
  });
  if (usage.isPending) return <p className="px-1 text-xs text-muted-foreground">Loading usage…</p>;
  if (usage.isError) return <p className="px-1 text-xs text-muted-foreground">Usage unavailable</p>;

  const used = usage.data.calls_last_24h;
  const limit = usage.data.daily_limit;
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="px-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">AI calls, 24 h</span>
        <span>{limit ? `${used} / ${limit}` : used}</span>
      </div>
      {limit ? (
        <div
          className="mt-1 h-1.5 overflow-hidden rounded-sm bg-muted"
          role="progressbar"
          aria-label="AI calls in the last 24 hours against your daily limit"
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={Math.min(used, limit)}
        >
          <div className={cn("h-full", pct >= 100 ? "bg-danger" : "bg-primary")} style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}
