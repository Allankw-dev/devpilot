"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ApiError, membersApi, type Member, type Role } from "@/lib/api";
import { ago } from "@/lib/format";
import { assignableRoles, canManageMember, ROLE_HELP, ROLE_LABEL } from "@/lib/roles";
import { accessToken } from "@/lib/supabase/token";

const field = "rounded-md border border-border bg-background px-2.5 py-1.5 text-sm";
const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function MembersCard({ orgId }: { orgId: string }) {
  const { me, org } = useWorkspace();
  const router = useRouter();
  const queryClient = useQueryClient();
  const actor = org?.role;
  const grantable = assignableRoles(actor);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");

  const members = useQuery({
    queryKey: ["org", orgId, "members"],
    queryFn: async () => membersApi.list(await accessToken(), orgId),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["org", orgId, "members"] });
    void queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams"] });
  };
  const add = useMutation({
    mutationFn: async () => membersApi.add(await accessToken(), orgId, email.trim(), role),
    onSuccess: () => {
      setEmail("");
      refresh();
    },
  });
  const change = useMutation({
    mutationFn: async (v: { member: Member; role: Role }) =>
      membersApi.setRole(await accessToken(), orgId, v.member.user_id, v.role),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: async (member: Member) => membersApi.remove(await accessToken(), orgId, member.user_id),
    onSuccess: async (_d, member) => {
      refresh();
      if (member.user_id === me.user.id) {
        await queryClient.invalidateQueries({ queryKey: ["me"] });
        router.push("/dashboard");
      }
    },
  });

  const error = [add, change, remove].find((m) => m.isError)?.error;
  const rows = members.data ?? [];

  return (
    <Card>
      <CardHeader title="Members" description="People in this workspace and what they can do." />
      {members.isPending && <p role="status" className="px-4 py-4 text-sm text-muted-foreground">Loading members…</p>}
      {members.isError && (
        <p role="alert" className="px-4 py-4 text-sm text-danger">
          Couldn’t load members.{" "}
          <Button size="sm" onClick={() => members.refetch()}>
            Try again
          </Button>
        </p>
      )}

      {rows.length > 0 && (
        <ul className="divide-y divide-border">
          {rows.map((m) => {
            const self = m.user_id === me.user.id;
            const manageable = !self && canManageMember(actor, m.role);
            // you can edit a role you could also grant; keep the current one in the list
            const options = grantable.includes(m.role) ? grantable : [m.role, ...grantable];
            return (
              <li key={m.user_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">
                    {m.display_name || m.email}
                    {self && <Badge className="ml-2">you</Badge>}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {m.display_name ? `${m.email} · ` : ""}joined {ago(m.joined_at)}
                  </p>
                </div>
                {manageable ? (
                  <>
                    <label className="sr-only" htmlFor={`role-${m.user_id}`}>
                      Role of {m.display_name || m.email}
                    </label>
                    <select
                      id={`role-${m.user_id}`}
                      value={m.role}
                      disabled={change.isPending}
                      onChange={(e) => change.mutate({ member: m, role: e.target.value as Role })}
                      className={field}
                    >
                      {options.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABEL[r]}
                        </option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      aria-label={`Remove ${m.display_name || m.email}`}
                      onClick={() => {
                        if (window.confirm(`Remove ${m.display_name || m.email} from this workspace?`)) remove.mutate(m);
                      }}
                      className="text-danger"
                    >
                      Remove
                    </Button>
                  </>
                ) : (
                  <Badge tone={m.role === "owner" ? "primary" : "neutral"}>{ROLE_LABEL[m.role]}</Badge>
                )}
                {self && (
                  <Button
                    size="sm"
                    className="text-danger"
                    onClick={() => {
                      if (window.confirm("Leave this workspace? You will lose access until someone adds you again."))
                        remove.mutate(m);
                    }}
                  >
                    Leave
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {error && (
        <p role="alert" className="border-t border-border px-4 py-3 text-sm text-danger">
          {message(error, "Something went wrong.")}
        </p>
      )}

      {grantable.length > 0 ? (
        <form
          className="border-t border-border px-4 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (email.trim()) add.mutate();
          }}
        >
          <p className="mb-2 text-sm font-medium">Add a member</p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="member-email">
              Email address
            </label>
            <input
              id="member-email"
              type="email"
              required
              placeholder="name@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={`${field} w-64 max-w-full`}
            />
            <label className="sr-only" htmlFor="member-role">
              Role
            </label>
            <select id="member-role" value={role} onChange={(e) => setRole(e.target.value as Role)} className={field}>
              {grantable.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
            <Button type="submit" variant="primary" disabled={add.isPending || !email.trim()}>
              {add.isPending ? "Adding…" : "Add"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {ROLE_HELP[role]} They must have signed in to DevPilot once before you can add them.
          </p>
        </form>
      ) : (
        <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
          Only admins and owners can add or change members.
        </p>
      )}
    </Card>
  );
}
