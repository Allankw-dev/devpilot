"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useWorkspace } from "@/components/shell/workspace-provider";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ApiError, membersApi, teamsApi, type Team } from "@/lib/api";
import { isAdmin } from "@/lib/roles";
import { accessToken } from "@/lib/supabase/token";

const field = "rounded-md border border-border bg-background px-2.5 py-1.5 text-sm";
const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function TeamMembers({ orgId, team, admin }: { orgId: string; team: Team; admin: boolean }) {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState("");

  const members = useQuery({
    queryKey: ["org", orgId, "team", team.id, "members"],
    queryFn: async () => teamsApi.members(await accessToken(), orgId, team.id),
  });
  const orgMembers = useQuery({
    queryKey: ["org", orgId, "members"],
    queryFn: async () => membersApi.list(await accessToken(), orgId),
    enabled: admin,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["org", orgId, "team", team.id, "members"] });
    void queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams"] });
  };
  const add = useMutation({
    mutationFn: async () => teamsApi.addMember(await accessToken(), orgId, team.id, userId),
    onSuccess: () => {
      setUserId("");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) => teamsApi.removeMember(await accessToken(), orgId, team.id, id),
    onSuccess: refresh,
  });

  const rows = members.data ?? [];
  const onTeam = new Set(rows.map((m) => m.user_id));
  const candidates = (orgMembers.data ?? []).filter((m) => !onTeam.has(m.user_id));
  const error = [add, remove].find((m) => m.isError)?.error;

  return (
    <div className="border-t border-border bg-background/40 px-4 py-3">
      {members.isPending && <p role="status" className="text-sm text-muted-foreground">Loading…</p>}
      {members.isError && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load this team’s members.
        </p>
      )}
      {members.isSuccess && rows.length === 0 && <p className="text-sm text-muted-foreground">No one on this team yet.</p>}
      <ul className="space-y-1">
        {rows.map((m) => (
          <li key={m.user_id} className="flex items-center justify-between gap-3 text-sm">
            <span className="truncate">
              {m.display_name || m.email}
              {m.display_name && <span className="ml-2 text-xs text-muted-foreground">{m.email}</span>}
            </span>
            {admin && (
              <Button size="sm" variant="ghost" aria-label={`Remove ${m.display_name || m.email} from ${team.name}`} onClick={() => remove.mutate(m.user_id)}>
                Remove
              </Button>
            )}
          </li>
        ))}
      </ul>
      {admin && (
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (userId) add.mutate();
          }}
        >
          <label className="sr-only" htmlFor={`add-to-${team.id}`}>
            Add a member to {team.name}
          </label>
          <select id={`add-to-${team.id}`} value={userId} onChange={(e) => setUserId(e.target.value)} className={field}>
            <option value="">Choose a member…</option>
            {candidates.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name || m.email}
              </option>
            ))}
          </select>
          <Button type="submit" size="sm" variant="primary" disabled={!userId || add.isPending}>
            Add to team
          </Button>
        </form>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {message(error, "Something went wrong.")}
        </p>
      )}
    </div>
  );
}

export function TeamsCard({ orgId }: { orgId: string }) {
  const { org } = useWorkspace();
  const admin = isAdmin(org?.role);
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const teams = useQuery({
    queryKey: ["org", orgId, "teams"],
    queryFn: async () => teamsApi.list(await accessToken(), orgId),
  });
  const create = useMutation({
    mutationFn: async () => teamsApi.create(await accessToken(), orgId, name.trim()),
    onSuccess: () => {
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams"] });
    },
  });
  const remove = useMutation({
    mutationFn: async (team: Team) => teamsApi.remove(await accessToken(), orgId, team.id),
    onSuccess: (_d, team) => {
      if (open === team.id) setOpen(null);
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams"] });
    },
  });

  const rows = teams.data ?? [];
  const error = [create, remove].find((m) => m.isError)?.error;

  return (
    <Card>
      <CardHeader title="Teams" description="Groups of members, for example “Backend” or “Reviewers”." />
      {teams.isPending && <p role="status" className="px-4 py-4 text-sm text-muted-foreground">Loading teams…</p>}
      {teams.isError && (
        <p role="alert" className="px-4 py-4 text-sm text-danger">
          Couldn’t load teams.{" "}
          <Button size="sm" onClick={() => teams.refetch()}>
            Try again
          </Button>
        </p>
      )}
      {teams.isSuccess && rows.length === 0 && (
        <p className="px-4 py-4 text-sm text-muted-foreground">
          No teams yet.{admin ? " Create one below." : " An admin can create teams."}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="divide-y divide-border">
          {rows.map((t) => (
            <li key={t.id}>
              <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <button
                  type="button"
                  aria-expanded={open === t.id}
                  onClick={() => setOpen(open === t.id ? null : t.id)}
                  className="min-w-0 flex-1 text-left font-medium hover:underline"
                >
                  {t.name}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {t.member_count} {t.member_count === 1 ? "member" : "members"}
                  </span>
                </button>
                {admin && (
                  <Button
                    size="sm"
                    className="text-danger"
                    aria-label={`Delete team ${t.name}`}
                    onClick={() => {
                      if (window.confirm(`Delete the team “${t.name}”? Its members stay in the workspace.`)) remove.mutate(t);
                    }}
                  >
                    Delete
                  </Button>
                )}
              </div>
              {open === t.id && <TeamMembers orgId={orgId} team={t} admin={admin} />}
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p role="alert" className="border-t border-border px-4 py-3 text-sm text-danger">
          {message(error, "Something went wrong.")}
        </p>
      )}

      {admin && (
        <form
          className="border-t border-border px-4 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim().length >= 2) create.mutate();
          }}
        >
          <p className="mb-2 text-sm font-medium">Create a team</p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="team-name">
              Team name
            </label>
            <input
              id="team-name"
              value={name}
              maxLength={80}
              placeholder="Team name"
              onChange={(e) => setName(e.target.value)}
              className={`${field} w-64 max-w-full`}
            />
            <Button type="submit" variant="primary" disabled={create.isPending || name.trim().length < 2}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}
