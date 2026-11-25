"use client";

import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Sidebar } from "@/components/shell/sidebar";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { config } from "@/lib/config";
import { titleFor } from "@/lib/nav";
import { useUiStore } from "@/lib/ui-store";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { org } = useWorkspace();
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggleCollapsed = useUiStore((s) => s.toggleSidebar);
  // Remember where the drawer was opened: moving to another page closes it by itself.
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawer = drawerPath === pathname;
  const setDrawer = (open: boolean) => setDrawerPath(open ? pathname : null);
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerPath(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  const title = titleFor(pathname);
  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>

      {/* desktop: a fixed column */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-20 hidden border-r border-border transition-[width] lg:block",
          collapsed ? "w-16" : "w-64",
        )}
      >
        <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      </aside>

      {/* mobile: a drawer */}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/60"
            onClick={() => setDrawer(false)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-border"
          >
            <Sidebar collapsed={false} onNavigate={() => setDrawer(false)} onClose={() => setDrawer(false)} />
          </aside>
        </div>
      )}

      <div className={cn("transition-[padding]", collapsed ? "lg:pl-16" : "lg:pl-64")}>
        <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur-sm">
          <button
            type="button"
            onClick={() => setDrawer(true)}
            aria-label="Open navigation"
            className="rounded-sm p-1.5 hover:bg-muted lg:hidden"
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>
          <nav aria-label="Breadcrumb" className="min-w-0 flex-1 truncate text-sm">
            <span className="text-muted-foreground">{config.productName}</span>
            {org && (
              <>
                <span className="mx-2 text-muted-foreground" aria-hidden>
                  /
                </span>
                <span className="text-muted-foreground">{org.name}</span>
              </>
            )}
            {title && (
              <>
                <span className="mx-2 text-muted-foreground" aria-hidden>
                  /
                </span>
                <span className="font-medium" aria-current="page">
                  {title}
                </span>
              </>
            )}
          </nav>
          <ThemeToggle />
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}
