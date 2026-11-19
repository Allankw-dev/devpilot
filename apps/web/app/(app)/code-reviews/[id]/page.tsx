import { ReviewPage } from "@/components/code-reviews/review-page";

export default async function CodeReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReviewPage prId={id} />;
}
