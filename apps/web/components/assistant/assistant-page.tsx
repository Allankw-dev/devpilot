"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { ConversationView } from "@/components/assistant/conversation-view";
import { NewConversation } from "@/components/assistant/new-conversation";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { conversationApi, orgApi } from "@/lib/api";
import { ago } from "@/lib/format";
import { canWrite } from "@/lib/labels";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

export function AssistantPage() {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const activeId = useSearchParams().get("c");
  const canAsk = canWrite(org?.role);

  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
    enabled: !!org,
  });
  const conversations = useQuery({
    queryKey: ["org", orgId, "conversations"],
    queryFn: async () => conversationApi.list(await accessToken(), orgId),
    enabled: !!org,
  });
  const repoMap = useMemo(() => new Map((repos.data ?? []).map((r) => [r.id, r])), [repos.data]);

  if (!org) {
    return (
      <>
        <PageHeader title="Assistant" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Assistant"
        description="Ask questions about your indexed code. Your conversations are private to you."
      />
      <div className="grid gap-6 md:grid-cols-[16rem_minmax(0,1fr)]">
        <aside aria-label="Conversations">
          <Link href="/assistant" className={cn(buttonVariants({ variant: "primary", size: "sm" }), "mb-3 w-full")}>
            New conversation
          </Link>
          <Card>
            {conversations.isPending && <p role="status" className="px-3 py-3 text-sm text-muted-foreground">Loading…</p>}
            {conversations.isError && (
              <p role="alert" className="px-3 py-3 text-sm text-danger">
                Couldn’t load conversations.
              </p>
            )}
            {conversations.isSuccess && conversations.data.length === 0 && (
              <p className="px-3 py-3 text-sm text-muted-foreground">No conversations yet.</p>
            )}
            <ul className="divide-y divide-border">
              {(conversations.data ?? []).map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/assistant?c=${c.id}`}
                    aria-current={c.id === activeId ? "page" : undefined}
                    className={cn("block px-3 py-2.5 text-sm hover:bg-muted", c.id === activeId && "bg-muted")}
                  >
                    <span className="line-clamp-2 font-medium">{c.title}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {c.repository ?? "All repositories"} · {ago(c.updated_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </aside>

        <section aria-label="Conversation" className="min-w-0">
          {repos.isPending ? (
            <p role="status" className="text-sm text-muted-foreground">Loading…</p>
          ) : activeId ? (
            <ConversationView key={activeId} orgId={orgId} conversationId={activeId} repos={repoMap} canAsk={canAsk} />
          ) : (
            <NewConversation orgId={orgId} repos={repos.data ?? []} canAsk={canAsk} />
          )}
        </section>
      </div>
    </>
  );
}
