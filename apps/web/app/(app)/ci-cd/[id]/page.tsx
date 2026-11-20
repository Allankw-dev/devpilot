import { CiPage } from "@/components/ci-cd/ci-page";

export default async function CiRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CiPage runId={id} />;
}
