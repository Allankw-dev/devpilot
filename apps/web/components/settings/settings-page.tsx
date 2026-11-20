"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ApiError, workspaceApi } from "@/lib/api";
import { ROLE_LABEL, isAdmin } from "@/lib/roles";
import { accessToken } from "@/lib/supabase/token";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const field = "rounded-md border border-border bg-background px-2.5 py-1.5 text-sm";
const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function ProfileCard() {
  const { me } = useWorkspace();
  return (
    <Card>
      <CardHeader title="Profile" description="Who you are signed in as." />
      <dl className="grid gap-x-6 gap-y-3 px-4 py-4 text-sm sm:grid-cols-[8rem_1fr]">
        <dt className="text-muted-foreground">Name</dt>
        <dd>{me.user.display_name || <span className="text-muted-foreground">Not set</span>}</dd>
        <dt className="text-muted-foreground">Email</dt>
        <dd>{me.user.email}</dd>
      </dl>
      <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
        Your name and email come from your sign-in provider, so they can’t be changed here.
      </p>
    </Card>
  );
}

function AppearanceCard() {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => setTheme(readTheme()), []);
  return (
    <Card>
      <CardHeader title="Appearance" description="Remembered in this browser." />
      <div role="radiogroup" aria-label="Theme" className="flex gap-2 px-4 py-4">
        {(["dark", "light"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="radio"
            aria-checked={theme === t}
            onClick={() => {
              applyTheme(t);
              setTheme(t);
            }}
            className={cn(
              "rounded-md border border-border px-4 py-2 text-sm capitalize",
              theme === t ? "bg-muted font-medium" : "hover:bg-muted",
            )}
          >
            {t}
          </button>
        ))}
      </div>
    </Card>
  );
}

function WorkspaceCard() {
  const { org } = useWorkspace();
  const queryClient = useQueryClient();
  const admin = isAdmin(org?.role);
  const [name, setName] = useState(org?.name ?? "");
  useEffect(() => setName(org?.name ?? ""), [org?.name]);

  const rename = useMutation({
    mutationFn: async () => workspaceApi.rename(await accessToken(), org!.id, name.trim()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
  if (!org) return null;

  const changed = name.trim() !== org.name && name.trim().length >= 2;
  return (
    <Card>
      <CardHeader title="Workspace" description="The organization everything here belongs to." />
      <form
        className="space-y-4 px-4 py-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (changed) rename.mutate();
        }}
      >
        <div>
          <label htmlFor="workspace-name" className="mb-1 block text-sm font-medium">
            Name
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id="workspace-name"
              value={name}
              maxLength={80}
              readOnly={!admin}
              onChange={(e) => setName(e.target.value)}
              className={cn(field, "w-72 max-w-full", !admin && "opacity-70")}
            />
            {admin && (
              <Button type="submit" variant="primary" disabled={!changed || rename.isPending}>
                {rename.isPending ? "Saving…" : "Save"}
              </Button>
            )}
            {rename.isSuccess && !changed && (
              <span role="status" className="text-xs text-success">
                Saved
              </span>
            )}
          </div>
          {!admin && <p className="mt-1 text-xs text-muted-foreground">Only admins and owners can rename the workspace.</p>}
          {rename.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {errorText(rename.error, "Could not save the name.")}
            </p>
          )}
        </div>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-muted-foreground">Identifier</dt>
          <dd className="font-mono text-xs">{org.slug}</dd>
          <dt className="text-muted-foreground">Your role</dt>
          <dd>
            <Badge tone={org.role === "owner" ? "primary" : "neutral"}>{ROLE_LABEL[org.role]}</Badge>
          </dd>
        </dl>
      </form>
    </Card>
  );
}

function DangerCard() {
  const { org } = useWorkspace();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState("");
  const remove = useMutation({
    mutationFn: async () => workspaceApi.remove(await accessToken(), org!.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.push("/dashboard");
    },
  });
  if (!org || org.role !== "owner") return null;

  return (
    <Card className="border-danger">
      <CardHeader
        title="Delete this workspace"
        description="Removes its GitHub connections, synced data, reviews, analyses and usage records. This can’t be undone. The GitHub app stays installed on GitHub until you remove it there."
      />
      <form
        className="space-y-3 px-4 py-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (typed === org.name) remove.mutate();
        }}
      >
        <label htmlFor="confirm-delete" className="block text-sm">
          Type <strong>{org.name}</strong> to confirm
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <input
            id="confirm-delete"
            value={typed}
            autoComplete="off"
            onChange={(e) => setTyped(e.target.value)}
            className={cn(field, "w-72 max-w-full")}
          />
          <Button type="submit" className="border-danger text-danger" disabled={typed !== org.name || remove.isPending}>
            {remove.isPending ? "Deleting…" : "Delete workspace"}
          </Button>
        </div>
        {remove.isError && (
          <p role="alert" className="text-sm text-danger">
            {errorText(remove.error, "Could not delete the workspace.")}
          </p>
        )}
      </form>
    </Card>
  );
}

export function SettingsPage() {
  const { org } = useWorkspace();
  return (
    <>
      <PageHeader
        title="Settings"
        description={org ? `Your account and ${org.name}.` : "Your account."}
        actions={
          org && (
            <Link href="/team" className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted">
              Members and teams
            </Link>
          )
        }
      />
      <div className="max-w-3xl space-y-6">
        <ProfileCard />
        <AppearanceCard />
        {org ? (
          <>
            <WorkspaceCard />
            <DangerCard />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Create a workspace on the dashboard to see workspace settings.</p>
        )}
      </div>
    </>
  );
}
