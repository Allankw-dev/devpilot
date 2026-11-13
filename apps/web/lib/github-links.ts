import type { Repo } from "@/lib/api";

/** Link to the exact lines of a file on GitHub, or null if the repository's branch is unknown. */
export function lineLink(
  repo: Pick<Repo, "html_url" | "default_branch"> | undefined,
  path: string,
  startLine: number,
  endLine: number,
): string | null {
  if (!repo || !repo.default_branch) return null;
  const encodedPath = path.split("/").map(encodeURIComponent).join("/");
  return `${repo.html_url}/blob/${encodeURIComponent(repo.default_branch)}/${encodedPath}#L${startLine}-L${endLine}`;
}
