"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { aiApi, ApiError, type AiUsageDetail } from "@/lib/api";
import { errorLabel, featureLabel } from "@/lib/ai-labels";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const fmt = new Intl.NumberFormat();
const RANGES = [7, 14, 30] as const;

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function DayBars({ data }: { data: AiUsageDetail }) {
  const peak = Math.max(1, ...data.by_day.map((d) => d.provider_calls));
  return (
    <div>
      <div
        className="flex h-24 items-end gap-1"
        role="img"
        aria-label={`Provider calls per day, busiest day ${fmt.format(peak)}`}
      >
        {data.by_day.map((d) => (
          <div
            key={d.day}
            title={`${d.day}: ${fmt.format(d.provider_calls)} calls, ${fmt.format(d.errors)} failed operations, ${fmt.format(d.input_tokens + d.output_tokens)} tokens`}
            className={cn(
              "min-h-[2px] flex-1 rounded-t",
              d.provider_calls === 0 ? "bg-muted" : d.errors > 0 ? "bg-danger" : "bg-primary",
            )}
            style={{ height: `${Math.max(2, (d.provider_calls / peak) * 100)}%` }}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{data.by_day[0]?.day}</span>
        <span>today (UTC)</span>
      </div>
    </div>
  );
}

export function UsageDashboard({ orgId }: { orgId: string }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(14);
  const usage = useQuery({
    queryKey: ["org", orgId, "ai-usage", days],
    queryFn: async () => aiApi.usage(await accessToken(), orgId, days),
  });
  const data = usage.data;

  const quotaRecent = data?.quota_hit_at
    ? Date.now() - new Date(data.quota_hit_at).getTime() < 24 * 3600 * 1000
    : false;
  const limit = data?.daily_limit ?? null;
  const used24 = data?.calls_last_24h ?? 0;
  const pct = limit ? Math.min(100, Math.round((used24 / limit) * 100)) : 0;

  return (
    <section className="mt-10" aria-label="AI usage">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium">AI usage</h2>
        <div className="flex gap-1 text-xs">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setDays(r)}
              className={cn(
                "rounded-md border border-border px-2 py-1",
                days === r ? "bg-muted font-medium" : "hover:bg-muted",
              )}
            >
              {r} days
            </button>
          ))}
        </div>
      </div>

      {usage.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {usage.error instanceof ApiError ? usage.error.message : "Couldn’t load AI usage."}
        </p>
      )}

      {data && quotaRecent && (
        <p role="alert" className="mt-3 rounded-md border border-border bg-muted px-4 py-3 text-sm">
          <span className="font-medium text-danger">Daily quota used up</span> (last seen{" "}
          {ago(data.quota_hit_at)}). The AI provider refuses requests until its quota resets: wait,
          turn on billing with the provider, or switch the model. See docs/USAGE.md.
        </p>
      )}

      {data && data.operations === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          No AI requests in the last {data.days} days.
        </p>
      )}

      {data && data.operations > 0 && (
        <div className="mt-4 space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Operations" value={fmt.format(data.operations)} />
            <Stat
              label="Provider calls"
              value={fmt.format(data.provider_calls)}
              hint="what the provider counts, retries included"
            />
            <Stat label="Failed operations" value={fmt.format(data.errors)} />
            <Stat
              label="Avg response"
              value={data.avg_latency_ms === null ? "n/a" : `${fmt.format(data.avg_latency_ms)} ms`}
              hint="successful ones only"
            />
            <Stat label="Input tokens" value={fmt.format(data.input_tokens)} />
            <Stat label="Output tokens" value={fmt.format(data.output_tokens)} hint="includes thinking" />
          </div>

          <div className="rounded-md border border-border px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">Last 24 hours</span>
              <span className="text-muted-foreground">
                {fmt.format(used24)} provider calls
                {limit ? ` of ${fmt.format(limit)} allowed` : ""}
              </span>
            </div>
            {limit ? (
              <div
                className="mt-2 h-2 overflow-hidden rounded bg-muted"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={limit}
                aria-valuenow={Math.min(used24, limit)}
                aria-label="Provider calls in the last 24 hours against the daily limit"
              >
                <div
                  className={cn("h-full", pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-foreground" : "bg-primary")}
                  style={{ width: `${pct}%` }}
                />
              </div>
            ) : (
              <p className="mt-1 text-xs text-muted-foreground">
                Set AI_DAILY_REQUEST_LIMIT on the server to see your limit here.
              </p>
            )}
          </div>

          <div>
            <p className="mb-2 text-sm font-medium">Provider calls per day</p>
            <DayBars data={data} />
            <p className="mt-1 text-xs text-muted-foreground">Red days had failed operations.</p>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="overflow-x-auto">
              <p className="mb-2 text-sm font-medium">By feature</p>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-3 font-normal">Feature</th>
                    <th className="py-1 pr-3 text-right font-normal">Calls</th>
                    <th className="py-1 pr-3 text-right font-normal">Failed</th>
                    <th className="py-1 text-right font-normal">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_feature.map((f) => (
                    <tr key={f.feature} className="border-t border-border">
                      <td className="py-1.5 pr-3">{featureLabel(f.feature)}</td>
                      <td className="py-1.5 pr-3 text-right">{fmt.format(f.provider_calls)}</td>
                      <td className="py-1.5 pr-3 text-right">{fmt.format(f.errors)}</td>
                      <td className="py-1.5 text-right">{fmt.format(f.input_tokens + f.output_tokens)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="overflow-x-auto">
              <p className="mb-2 text-sm font-medium">By model</p>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-3 font-normal">Model</th>
                    <th className="py-1 pr-3 text-right font-normal">Calls</th>
                    <th className="py-1 pr-3 text-right font-normal">Failed</th>
                    <th className="py-1 text-right font-normal">Last 24 h</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_model.map((m) => (
                    <tr key={m.model} className="border-t border-border">
                      <td className="py-1.5 pr-3">
                        <code>{m.model}</code>
                      </td>
                      <td className="py-1.5 pr-3 text-right">{fmt.format(m.provider_calls)}</td>
                      <td className="py-1.5 pr-3 text-right">{fmt.format(m.errors)}</td>
                      <td className="py-1.5 text-right">{fmt.format(m.calls_last_24h)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {data.errors_by_code.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium">What went wrong</p>
              <ul className="space-y-1 text-sm">
                {data.errors_by_code.map((e) => (
                  <li key={e.code} className="flex justify-between gap-3 border-t border-border py-1.5">
                    <span>{errorLabel(e.code)}</span>
                    <span className="text-muted-foreground">{fmt.format(e.count)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Counts only requests made through DevPilot, by UTC day. Your provider counts per project
            and per model, and may reset its day at a different time, so treat the limit bar as a
            guide.
          </p>
        </div>
      )}
    </section>
  );
}
