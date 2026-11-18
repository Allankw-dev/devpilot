import { AppShell } from "@/components/shell/app-shell";
import { WorkspaceProvider } from "@/components/shell/workspace-provider";

// Every signed-in page lives in this group and gets the sidebar and top bar.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <AppShell>{children}</AppShell>
    </WorkspaceProvider>
  );
}
