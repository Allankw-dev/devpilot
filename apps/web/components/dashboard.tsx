"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, authedApi } from "@/lib/api";
import { config } from "@/lib/config";
import { createClient } from "@/lib/supabase/client";
import { accessToken } from "@/lib/supabase/token";

export function Dashboard() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => authedApi.me(await accessToken()),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 1,
  });

  const createOrg = useMutation({
    mutationFn: async (orgName: string) => authedApi.createOrg(await accessToken(), orgName),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  async function signOut() {
    await createClient().auth.signOut();
    queryClient.clear();
    router.push("/login");
    router.refresh();
  }

  if (me.isError && me.error instanceof ApiError && me.error.status === 401) {
    router.push("/login");
    return null;
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">{config.productName}</h1>
        <div className="flex items-center gap-4 text-sm">
          {me.data && <span className="text-muted-foreground">{me.data.user.email}</span>}
          <button onClick={signOut} className="rounded-md border border-border px-3 py-1.5 hover:bg-muted">
            Sign out
          </button>
        </div>
      </header>

      <section className="mt-10">
        <h2 className="text-lg font-medium">Organizations</h2>

        {me.isPending && <p className="mt-4 text-muted-foreground">Loading…</p>}

        {me.isError && (
          <p role="alert" className="mt-4 text-danger">
            {me.error instanceof Error ? me.error.message : "Couldn’t load your account."}
          </p>
        )}

        {me.data && me.data.organizations.length === 0 && (
          <p className="mt-4 text-muted-foreground">
            You’re not in any organization yet. Create one to get started.
          </p>
        )}

        {me.data && me.data.organizations.length > 0 && (
          <ul className="mt-4 divide-y divide-border border-y border-border">
            {me.data.organizations.map((org) => (
              <li key={org.id} className="flex items-center justify-between py-3">
                <Link href={`/orgs/${org.id}`} className="font-medium hover:underline">
                  {org.name}
                </Link>
                <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs capitalize text-muted-foreground">
                  {org.role}
                </span>
              </li>
            ))}
          </ul>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim().length >= 2) createOrg.mutate(name.trim());
          }}
          className="mt-6 flex gap-2"
        >
          <label htmlFor="org-name" className="sr-only">
            Organization name
          </label>
          <input
            id="org-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New organization name"
            maxLength={80}
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground"
          />
          <button
            type="submit"
            disabled={createOrg.isPending || name.trim().length < 2}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {createOrg.isPending ? "Creating…" : "Create"}
          </button>
        </form>
        {createOrg.isError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {createOrg.error instanceof Error ? createOrg.error.message : "Could not create it."}
          </p>
        )}
      </section>
    </main>
  );
}
