"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { orgApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";
import { useWorkspaceStore } from "@/lib/workspace";

// GitHub sends the browser here after the app is installed. The one-time `code` and the
// installation id are handed to our API, which verifies them with GitHub.
export function GithubCallback() {
  const params = useSearchParams();
  const router = useRouter();
  const started = useRef(false); // the code is single-use: never submit it twice
  const [error, setError] = useState<string | null>(null);

  const code = params.get("code");
  const state = params.get("state");
  const installationId = Number(params.get("installation_id"));
  const isRequest = params.get("setup_action") === "request";
  const invalid = !isRequest && (!code || !Number.isInteger(installationId) || installationId <= 0);

  useEffect(() => {
    if (started.current || isRequest || invalid) return;
    started.current = true;
    (async () => {
      try {
        const installation = await orgApi.claim(await accessToken(), {
          code: code as string,
          installation_id: installationId,
          state,
        });
        useWorkspaceStore.getState().select(installation.org_id); // show the workspace you just connected
        router.replace("/integrations");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not finish connecting GitHub.");
      }
    })();
  }, [code, state, installationId, isRequest, invalid, router]);

  const message = isRequest
    ? "Your request was sent to the GitHub organization’s owners. Once they approve it, connect again from the Integrations page."
    : invalid
      ? "This link is missing information from GitHub. Start again from the Integrations page."
      : error;
  const failed = !isRequest && message !== null;

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold tracking-tight">Connecting GitHub</h1>
      {message ? (
        <>
          <p role={failed ? "alert" : "status"} className={failed ? "mt-4 text-danger" : "mt-4 text-muted-foreground"}>
            {message}
          </p>
          <Link href="/dashboard" className="mt-6 inline-block text-sm text-primary underline underline-offset-2">
            Back to organizations
          </Link>
        </>
      ) : (
        <p className="mt-4 text-muted-foreground">Finishing up…</p>
      )}
    </main>
  );
}
