"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type ServiceStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

function Row({ label, status }: { label: string; status: ServiceStatus }) {
  const ok = status === "ok";
  return (
    <li className="flex items-center justify-between py-3">
      <span>{label}</span>
      <span className={cn("font-medium", ok ? "text-success" : "text-danger")}>
        {ok ? "Connected" : "Unreachable"}
      </span>
    </li>
  );
}

export function SystemStatus() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
  });

  if (isPending) return <p className="text-muted-foreground">Checking services…</p>;

  if (isError || !data) {
    return (
      <div role="alert" className="space-y-3">
        <p className="text-danger">Can’t reach the API. Start it with the steps in the README.</p>
        <button
          onClick={() => refetch()}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border border-y border-border">
      <Row label="API" status="ok" />
      <Row label="Database" status={data.database} />
      <Row label="Redis" status={data.redis} />
    </ul>
  );
}
