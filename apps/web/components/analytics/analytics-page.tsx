"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { UsageDashboard } from "@/components/usage-dashboard";
import { Card, CardHeader } from "@/components/ui/card";
import { aiApi, analyticsApi, ApiError, type Analytics } from "@/lib/api";
import { formatPercent, formatSeconds } from "@/lib/duration";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const RANGES = [7, 14, 30, 90] as const;
const fmt = new Intl.NumberFormat();
const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const TOOLTIP = {
  contentStyle: { background: "hsl(var(--elevated))", border: "1px solid hsl(var(--border))", borderRadius: 6 },
  labelStyle: { color: "hsl(var(--foreground))" },
};
const SEVERITY_COLOR: Record<string, string> = {
  critical: "hsl(var(--danger))",
  high: "hsl(var(--warning))",
  medium: "hsl(var(--primary))",
  low: "hsl(var(--cyan))",
  info: "hsl(var(--muted-foreground))",
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}

function ChartCard({
  title,
  description,
  empty,
  emptyText,
  label,
  children,
}: {
  title: string;
  description: string;
  empty: boolean;
  emptyText: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader title={title} description={description} />
      {empty ? (
        <p className="px-4 py-10 text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <div className="h-64 px-2 py-3" role="img" aria-label={label}>
          <ResponsiveContainer width="100%" height="100%">
            {children as React.ReactElement}
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

export function AnalyticsPage() {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);

  const stats = useQuery({
    queryKey: ["org", orgId, "analytics", days],
    queryFn: async () => analyticsApi.get(await accessToken(), orgId, days),
    enabled: !!org,
  });
  const usage = useQuery({
    queryKey: ["org", orgId, "ai-usage", days],
    queryFn: async () => aiApi.usage(await accessToken(), orgId, days),
    enabled: !!org,
  });

  if (!org) {
    return (
      <>
        <PageHeader title="Analytics" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }

  const a: Analytics | undefined = stats.data;
  const rows = (a?.by_day ?? []).map((d) => ({ ...d, label: d.day.slice(5) }));
  const usageRows = (usage.data?.by_day ?? []).map((d) => ({ ...d, label: d.day.slice(5) }));
  const severityLabel = (a?.findings_by_severity ?? []).map((s) => `${s.severity} ${s.count}`).join(", ");

  return (
    <>
      <PageHeader
        title="Analytics"
        description={`What the AI and CI did in this workspace, last ${days} days.`}
        actions={
          <div className="flex gap-1" role="group" aria-label="Time period">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={days === r}
                onClick={() => setDays(r)}
                className={cn(
                  "rounded-md border border-border px-2.5 py-1.5 text-xs",
                  days === r ? "bg-muted font-medium" : "hover:bg-muted",
                )}
              >
                {r} days
              </button>
            ))}
          </div>
        }
      />

      {stats.isPending && <p role="status" className="text-sm text-muted-foreground">Loading analytics…</p>}
      {stats.isError && (
        <p role="alert" className="text-sm text-danger">
          {stats.error instanceof ApiError ? stats.error.message : "Couldn’t load analytics."}
        </p>
      )}

      {a && (
        <div className="space-y-6">
          <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat
              label="CI success rate"
              value={formatPercent(a.ci_success_rate)}
              hint={`${fmt.format(a.runs_succeeded)} passed, ${fmt.format(a.runs_failed)} failed`}
            />
            <Stat label="AI reviews finished" value={fmt.format(a.reviews_finished)} hint={`avg ${formatSeconds(a.avg_review_seconds)}`} />
            <Stat
              label="CI analyses finished"
              value={fmt.format(a.ci_analyses_finished)}
              hint={`avg ${formatSeconds(a.avg_ci_analysis_seconds)}`}
            />
            <Stat
              label="AI tokens"
              value={usage.data ? fmt.format(usage.data.input_tokens + usage.data.output_tokens) : "…"}
              hint={usage.data ? `${fmt.format(usage.data.provider_calls)} provider calls` : undefined}
            />
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard
              title="AI work finished per day"
              description="Pull request reviews and CI analyses that completed"
              empty={rows.every((r) => r.reviews_finished === 0 && r.ci_analyses_finished === 0)}
              emptyText={`No finished reviews or analyses in the last ${days} days.`}
              label="Stacked bar chart of AI reviews and CI analyses per day"
            >
              <BarChart data={rows}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="label" stroke={AXIS} fontSize={11} />
                <YAxis allowDecimals={false} stroke={AXIS} fontSize={11} width={28} />
                <Tooltip {...TOOLTIP} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="reviews_finished" name="Reviews" stackId="ai" fill="hsl(var(--purple))" />
                <Bar dataKey="ci_analyses_finished" name="CI analyses" stackId="ai" fill="hsl(var(--cyan))" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ChartCard>

            <ChartCard
              title="CI runs per day"
              description="Finished runs by outcome (cancelled and skipped runs are left out)"
              empty={rows.every((r) => r.runs_succeeded === 0 && r.runs_failed === 0)}
              emptyText={`No finished CI runs in the last ${days} days.`}
              label="Stacked bar chart of passed and failed CI runs per day"
            >
              <BarChart data={rows}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="label" stroke={AXIS} fontSize={11} />
                <YAxis allowDecimals={false} stroke={AXIS} fontSize={11} width={28} />
                <Tooltip {...TOOLTIP} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="runs_succeeded" name="Passed" stackId="ci" fill="hsl(var(--success))" />
                <Bar dataKey="runs_failed" name="Failed" stackId="ci" fill="hsl(var(--danger))" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ChartCard>

            <ChartCard
              title="Review findings by severity"
              description="Findings from reviews finished in this period"
              empty={a.findings_by_severity.every((s) => s.count === 0)}
              emptyText={`No review findings in the last ${days} days.`}
              label={`Bar chart of review findings by severity: ${severityLabel}`}
            >
              <BarChart data={a.findings_by_severity} layout="vertical" margin={{ left: 16 }}>
                <CartesianGrid stroke={GRID} horizontal={false} />
                <XAxis type="number" allowDecimals={false} stroke={AXIS} fontSize={11} />
                <YAxis type="category" dataKey="severity" stroke={AXIS} fontSize={11} width={64} />
                <Tooltip {...TOOLTIP} />
                <Bar dataKey="count" name="Findings" radius={[0, 3, 3, 0]}>
                  {a.findings_by_severity.map((s) => (
                    <Cell key={s.severity} fill={SEVERITY_COLOR[s.severity]} />
                  ))}
                </Bar>
              </BarChart>
            </ChartCard>

            <ChartCard
              title="AI tokens per day"
              description="Text sent to and received from the AI provider (output includes thinking)"
              empty={usage.isSuccess && usageRows.every((r) => r.input_tokens === 0 && r.output_tokens === 0)}
              emptyText={`No AI requests in the last ${days} days.`}
              label="Stacked bar chart of input and output tokens per day"
            >
              <BarChart data={usageRows}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="label" stroke={AXIS} fontSize={11} />
                <YAxis stroke={AXIS} fontSize={11} width={40} />
                <Tooltip {...TOOLTIP} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="input_tokens" name="Input" stackId="tokens" fill="hsl(var(--primary))" />
                <Bar dataKey="output_tokens" name="Output" stackId="tokens" fill="hsl(var(--purple))" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ChartCard>
          </div>

          <p className="text-xs text-muted-foreground">
            These are activity counts for this workspace, by UTC day. They are not a measure of developer productivity.
          </p>
        </div>
      )}

      <UsageDashboard orgId={orgId} />
    </>
  );
}
