import { redirect } from "next/navigation";

// The old all-in-one workspace page is gone: its sections now have their own pages. Old
// bookmarks and links land on the dashboard.
export default function OldWorkspacePage() {
  redirect("/dashboard");
}
