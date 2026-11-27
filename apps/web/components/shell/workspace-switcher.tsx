"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useWorkspace } from "@/components/shell/workspace-provider";
import { authedApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

export function WorkspaceSwitcher({ collapsed }: { collapsed: boolean }) {
  const { orgs, org, select } = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function choose(orgId: string) {
    select(orgId);
    setOpen(false);
    if (pathname.startsWith("/orgs/")) router.push(`/orgs/${orgId}`); // stay on the same kind of page
  }

  const create = useMutation({
    mutationFn: async (orgName: string) => authedApi.createOrg(await accessToken(), orgName),
    onSuccess: async (created) => {
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      choose(created.id);
    },
  });

  const initial = (org?.name ?? "?").slice(0, 1).toUpperCase();
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Workspace: ${org?.name ?? "none"}. Change workspace`}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md border border-border bg-card px-2 py-2 text-left text-sm hover:bg-muted"
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm border border-border-strong bg-elevated text-xs font-semibold text-foreground">
          {initial}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate font-medium">{org?.name ?? "No workspace"}</span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          </>
        )}
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 min-w-56 rounded-md border border-border bg-elevated p-1 shadow-lg">
          <ul role="listbox" aria-label="Workspaces">
            {orgs.map((o) => (
              <li key={o.id} role="option" aria-selected={o.id === org?.id}>
                <button
                  type="button"
                  onClick={() => choose(o.id)}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted"
                >
                  <span className="min-w-0 flex-1 truncate">{o.name}</span>
                  <span className="text-xs capitalize text-muted-foreground">{o.role}</span>
                  {o.id === org?.id && <Check className="h-4 w-4 text-primary" aria-hidden />}
                </button>
              </li>
            ))}
          </ul>
          <form
            className="mt-1 border-t border-border p-1 pt-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim().length >= 2) create.mutate(name.trim());
            }}
          >
            <label htmlFor="new-workspace" className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
              <Plus className="h-3 w-3" aria-hidden /> New workspace
            </label>
            <div className="flex gap-1">
              <input
                id="new-workspace"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                placeholder="Name"
                className="min-w-0 flex-1 rounded-sm border border-border bg-background px-2 py-1 text-sm"
              />
              <button
                type="submit"
                disabled={create.isPending || name.trim().length < 2}
                className={cn(
                  "rounded-sm bg-primary px-2 py-1 text-xs font-medium text-primary-foreground",
                  "disabled:opacity-50",
                )}
              >
                {create.isPending ? "…" : "Create"}
              </button>
            </div>
            {create.isError && (
              <p role="alert" className="mt-1 text-xs text-danger">
                {create.error instanceof Error ? create.error.message : "Could not create it."}
              </p>
            )}
          </form>
        </div>
      )}
    </div>
  );
}
