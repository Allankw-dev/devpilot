"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { AssistantAnswer, UserMessage } from "@/components/assistant/message";
import { Composer } from "@/components/assistant/composer";
import { Button } from "@/components/ui/button";
import { ApiError, conversationApi, type AssistantMessage, type ConversationDetail, type Repo } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

const messageOf = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function ConversationView({
  orgId,
  conversationId,
  repos,
  canAsk,
}: {
  orgId: string;
  conversationId: string;
  repos: Map<string, Repo>;
  canAsk: boolean;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = ["org", orgId, "conversation", conversationId];
  const bottom = useRef<HTMLDivElement>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [failedQuestion, setFailedQuestion] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: key,
    queryFn: async () => conversationApi.get(await accessToken(), orgId, conversationId),
  });
  const refreshList = () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "conversations"] });

  const ask = useMutation({
    mutationFn: async (question: string) => conversationApi.ask(await accessToken(), orgId, conversationId, question),
    onMutate: (question) => {
      setPendingQuestion(question);
      setFailedQuestion(null);
    },
    onSuccess: (pair) => {
      queryClient.setQueryData<ConversationDetail>(key, (old) =>
        old ? { ...old, messages: [...old.messages, pair.user, pair.assistant], message_count: old.message_count + 2 } : old,
      );
      void queryClient.invalidateQueries({ queryKey: key });
      void refreshList();
    },
    onError: (_e, question) => setFailedQuestion(question),
    onSettled: () => setPendingQuestion(null),
  });
  const regenerate = useMutation({
    mutationFn: async (messageId: string) => conversationApi.regenerate(await accessToken(), orgId, conversationId, messageId),
    onSuccess: (fresh: AssistantMessage) => {
      queryClient.setQueryData<ConversationDetail>(key, (old) =>
        old ? { ...old, messages: old.messages.map((m) => (m.id === fresh.id ? fresh : m)) } : old,
      );
      void refreshList();
    },
  });
  const remove = useMutation({
    mutationFn: async () => conversationApi.remove(await accessToken(), orgId, conversationId),
    onSuccess: async () => {
      await refreshList();
      router.push("/assistant");
    },
  });

  const messages = detail.data?.messages ?? [];
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages.length, pendingQuestion]);

  if (detail.isPending) return <p role="status" className="text-sm text-muted-foreground">Loading conversation…</p>;
  if (detail.isError || !detail.data) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div>
        <p role="alert" className="text-sm text-danger">
          {notFound ? "This conversation doesn’t exist, or isn’t yours." : "Couldn’t load this conversation."}
        </p>
        {!notFound && (
          <Button size="sm" className="mt-2" onClick={() => detail.refetch()}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const busy = ask.isPending || regenerate.isPending;
  const error = ask.isError ? ask.error : regenerate.isError ? regenerate.error : null;

  return (
    <div className="flex min-h-112 flex-col">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold">{detail.data.title}</h2>
          <p className="text-xs text-muted-foreground">
            {detail.data.repository ? `Asking about ${detail.data.repository}` : "Asking across all indexed repositories"}
          </p>
        </div>
        <Button
          size="sm"
          className="text-danger"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm("Delete this conversation? This can’t be undone.")) remove.mutate();
          }}
        >
          Delete conversation
        </Button>
      </div>

      <div className="flex-1 space-y-4">
        {messages.length === 0 && !pendingQuestion && (
          <p className="text-sm text-muted-foreground">No questions yet. Ask something about the code below.</p>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <UserMessage key={m.id} text={m.content} />
          ) : (
            <AssistantAnswer
              key={m.id}
              message={m}
              repos={repos}
              canRegenerate={canAsk && m.id === lastAssistant?.id && !busy}
              regenerating={regenerate.isPending && regenerate.variables === m.id}
              onRegenerate={() => regenerate.mutate(m.id)}
            />
          ),
        )}
        {pendingQuestion && (
          <>
            <UserMessage text={pendingQuestion} />
            <p role="status" className="text-sm text-muted-foreground">
              Searching the code and writing an answer…
            </p>
          </>
        )}
        <div ref={bottom} />
      </div>

      {error && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-border px-3 py-2 text-sm text-danger">
          <span>{messageOf(error, "Something went wrong.")}</span>
          {failedQuestion && canAsk && (
            <Button size="sm" onClick={() => ask.mutate(failedQuestion)}>
              Try again
            </Button>
          )}
        </div>
      )}

      <div className="mt-4 border-t border-border pt-4">
        {canAsk ? (
          <>
            <Composer pending={busy} placeholder="Ask about this code…" onSend={(q) => ask.mutate(q)} />
            <p className="mt-2 text-xs text-muted-foreground">
              Each question is answered from your code on its own. It does not see your earlier questions or answers.
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Viewers can read conversations but not ask new questions.</p>
        )}
      </div>
    </div>
  );
}
