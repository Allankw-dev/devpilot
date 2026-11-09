import { Suspense } from "react";

import { GithubCallback } from "@/components/github-callback";

export default function GithubCallbackPage() {
  return (
    <Suspense fallback={null}>
      <GithubCallback />
    </Suspense>
  );
}
