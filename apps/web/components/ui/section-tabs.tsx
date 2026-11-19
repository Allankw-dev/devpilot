import Link from "next/link";

import { cn } from "@/lib/utils";

export interface SectionTab {
  id: string;
  label: string;
  count?: number;
}

/** Tabs that are real links (`?tab=id`), so each one can be bookmarked and shared. */
export function SectionTabs({
  tabs,
  active,
  hrefFor,
  label,
}: {
  tabs: SectionTab[];
  active: string;
  hrefFor: (id: string) => string;
  label: string;
}) {
  return (
    <nav aria-label={label} className="mb-5 flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((t) => (
        <Link
          key={t.id}
          href={hrefFor(t.id)}
          aria-current={t.id === active ? "page" : undefined}
          className={cn(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
            t.id === active
              ? "border-primary font-medium text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 text-xs text-muted-foreground">{t.count}</span>}
        </Link>
      ))}
    </nav>
  );
}
