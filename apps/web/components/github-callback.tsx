"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { orgApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

// GitHub sends the browser here after the app is installed. The one-time `code` and the
// installation id are handed to our API, which verifies them with GitHub.
export function GithubCallback() {
  const params = useSearchParams();
  const router = useRouter();
  const started = useRef(false); // the code is single-use: never submit it twice
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const code = params.get("code");
    const installationId = Number(params.get("installation_id"));

    if (params.get("setup_action") === "request") {
      setMessage(
        "Your request was sent to the GitHub organization’s owners. Once they approve it, connect again from your organization page.",
      );
      return;
    }
    if (!code || !Number.isInteger(installationId) || installationId <= 0) {
      setFailed(true);
      setMessage("This link is missing information from GitHub. Start again from your organization page.");
      return;
    }

    (async () => {
      try {
        const installation = await orgApi.claim(await accessToken(), {
          code,
          installation_id: installationId,
          state: params.get("state"),
        });
        router.replace(`/orgs/${installation.org_id}`);
      } catch (e) {
        setFailed(true);
        setMessage(e instanceof Error ? e.message : "Could not finish connecting GitHub.");
      }
    })();
  }, [params, router]);

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
