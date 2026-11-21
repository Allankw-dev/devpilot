"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Composer } from "@/components/assistant/composer";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, conversationApi, type Repo } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

export const EXAMPLES = [
  "Explain the architecture of this repository.",
  "Where is user authentication implemented?",
  "What are the main entry points?",
  "How are errors handled?",
];

export function NewConversation({ orgId, repos, canAsk }: { orgId: string; repos: Repo[]; canAsk: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const indexed = repos.filter((r) => r.index.status === "ready");
  const [repoId, setRepoId] = useState("");
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  // If asking fails after the conversation was created, retry into the same one, not a new one.
  const created = useRef<string | null>(null);

  const start = useMutation({
    mutationFn: async (question: string) => {
      const token = await accessToken();
      if (!created.current) created.current = (await conversationApi.create(token, orgId, repoId || undefined)).id;
      await conversationApi.ask(token, orgId, created.current, question);
      return created.current;
    },
    onMutate: (question) => setLastQuestion(question),
    onSuccess: async (id) => {
      await queryClient.invalidateQueries({ queryKey: ["org", orgId, "conversations"] });
      created.current = null;
      router.push(`/assistant?c=${id}`);
    },
  });

  if (indexed.length === 0) {
    return (
      <Card className="mx-auto max-w-xl p-8 text-center">
        <h2 className="text-lg font-semibold">Index a repository to start asking</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The assistant answers from your code, so a repository has to be indexed first. Secrets and build output are
          skipped.
        </p>
        <Link href="/repositories" className={`${buttonVariants({ variant: "primary" })} mt-5`}>
          Go to repositories
        </Link>
      </Card>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h2 className="text-lg font-semibold">Ask about your code</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Answers cite the files and lines they are based on, and say when the code doesn’t cover the question.
      </p>

      <div className="mt-4">
        <label htmlFor="assistant-repo" className="mb-1 block text-sm font-medium">
          Repository
        </label>
        <select
          id="assistant-repo"
          value={repoId}
          disabled={!!created.current}
          onChange={(e) => setRepoId(e.target.value)}
          className="rounded-md border border-border bg-background px-2.5 py-1.5 text-sm"
        >
          <option value="">All indexed repositories</option>
          {indexed.map((r) => (
            <option key={r.id} value={r.id}>
              {r.full_name}
            </option>
          ))}
        </select>
      </div>

      {canAsk ? (
        <>
          <div className="mt-4 flex flex-wrap gap-2" aria-label="Example questions">
            {EXAMPLES.map((q) => (
              <button
                key={q}
                type="button"
                disabled={start.isPending}
                onClick={() => start.mutate(q)}
                className="rounded-full border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
          <div className="mt-4">
            <Composer pending={start.isPending} placeholder="Ask about this code…" onSend={(q) => start.mutate(q)} />
          </div>
        </>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">Viewers can read conversations but not ask new questions.</p>
      )}

      {start.isError && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 text-sm text-danger">
          <span>{start.error instanceof ApiError ? start.error.message : "Could not get an answer."}</span>
          {lastQuestion && (
            <Button size="sm" onClick={() => start.mutate(lastQuestion)}>
              Try again
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
