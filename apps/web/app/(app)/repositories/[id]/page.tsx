import { Suspense } from "react";

import { RepoPage } from "@/components/repositories/repo-page";

export default async function RepositoryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <RepoPage repoId={id} />
    </Suspense>
  );
}
