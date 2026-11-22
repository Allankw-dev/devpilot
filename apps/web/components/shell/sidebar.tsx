"use client";

import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, LogOut, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { UsageMeter } from "@/components/shell/usage-meter";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { config } from "@/lib/config";
import { NAV_ITEMS } from "@/lib/nav";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

export function Sidebar({
  collapsed,
  onToggleCollapsed,
  onNavigate,
  onClose,
}: {
  collapsed: boolean;
  onToggleCollapsed?: () => void; // desktop only
  onNavigate?: () => void;
  onClose?: () => void; // mobile drawer only
}) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { me, org } = useWorkspace();

  async function signOut() {
    await createClient().auth.signOut();
    queryClient.clear();
    router.push("/login");
    router.refresh();
  }

  const name = me.user.display_name || me.user.email;
  return (
    <div className="flex h-full flex-col bg-sidebar">
      <div className={cn("flex h-14 items-center gap-2 border-b border-border px-3", collapsed && "justify-center")}>
        <span
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary font-mono text-sm font-bold text-primary-foreground"
        >
          D
        </span>
        {!collapsed && <span className="flex-1 truncate text-sm font-semibold">{config.productName}</span>}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="rounded p-1 hover:bg-muted"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        )}
      </div>

      <div className="px-3 pt-3">
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>

      <nav aria-label="Main" className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              title={collapsed ? item.label : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm",
                collapsed && "justify-center",
                active ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              {collapsed ? <span className="sr-only">{item.label}</span> : <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-3 border-t border-border p-3">
        {!collapsed && org && <UsageMeter orgId={org.id} />}
        <a
          href={config.docsUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={collapsed ? "Help and documentation" : undefined}
          className={cn(
            "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
            collapsed && "justify-center",
          )}
        >
          <BookOpen className="h-4 w-4 shrink-0" aria-hidden />
          {collapsed ? <span className="sr-only">Help and documentation</span> : <span>Help and documentation</span>}
        </a>
        <div className={cn("flex items-center gap-2", collapsed && "flex-col")}>
          <span
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-elevated text-xs font-semibold"
          >
            {name.slice(0, 1).toUpperCase()}
          </span>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm">{name}</p>
              {org && <p className="truncate text-xs capitalize text-muted-foreground">{org.role}</p>}
            </div>
          )}
          <button
            type="button"
            onClick={signOut}
            aria-label="Sign out"
            title="Sign out"
            className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
        </div>
        {onToggleCollapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-pressed={collapsed}
            className="hidden w-full items-center justify-center rounded-md py-1.5 text-muted-foreground hover:bg-muted hover:text-foreground lg:flex"
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" aria-hidden /> : <PanelLeftClose className="h-4 w-4" aria-hidden />}
          </button>
        )}
      </div>
    </div>
  );
}
