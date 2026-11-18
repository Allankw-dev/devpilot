import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import type { Me, OrgWithRole } from "@/lib/api";

export function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

export const ORG: OrgWithRole = {
  id: "org-1",
  name: "Acme",
  slug: "acme",
  created_at: "2026-01-01T00:00:00Z",
  role: "owner",
};

export const ME: Me = {
  user: { id: "u1", email: "ada@example.com", display_name: "Ada Lovelace" },
  organizations: [ORG],
};
