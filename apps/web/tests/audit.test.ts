import { describe, expect, it } from "vitest";

import type { AuditEntry } from "@/lib/api";
import { actorLabel, describeAudit } from "@/lib/audit";

const entry = (action: string, details: AuditEntry["details"] = null, over: Partial<AuditEntry> = {}): AuditEntry => ({
  id: "e1",
  action,
  actor_id: "u1",
  actor_email: "ada@example.com",
  actor_name: "Ada Lovelace",
  target_type: null,
  target_id: null,
  details,
  request_id: null,
  created_at: "2026-11-25T10:00:00Z",
  ...over,
});

describe("describeAudit", () => {
  it.each([
    ["org.created", { name: "Acme" }, "created the workspace “Acme”"],
    ["org.renamed", { from: "Old", to: "New" }, "renamed the workspace from “Old” to “New”"],
    ["member.added", { email: "g@example.com", role: "member" }, "added g@example.com as member"],
    ["member.role_changed", { email: "g@example.com", from: "member", to: "admin" }, "changed g@example.com from member to admin"],
    ["member.removed", { email: "g@example.com", self: false }, "removed g@example.com"],
    ["member.removed", { email: "g@example.com", self: true }, "left the workspace"],
    ["team.created", { name: "Platform" }, "created the team “Platform”"],
    ["team.member_added", { team: "Platform" }, "added someone to the team “Platform”"],
    ["github.installation_connected", { account: "acme" }, "connected the GitHub account acme"],
    ["repository.index_requested", { repository: "acme/web" }, "started indexing acme/web"],
    ["review.requested", { number: 7, force: false }, "requested a review of pull request #7"],
    ["review.requested", { number: 7, force: true }, "re-ran a review of pull request #7"],
    ["review.finding_updated", { status: "dismissed" }, "marked a review finding as dismissed"],
    ["ci_analysis.requested", { force: false }, "requested a CI failure analysis"],
    ["ai.connection_tested", null, "tested the AI connection"],
  ])("%s → %s", (action, details, expected) => {
    expect(describeAudit(entry(action, details as AuditEntry["details"]))).toBe(expected);
  });

  it("shows an action it doesn't know as its raw code instead of hiding it", () => {
    expect(describeAudit(entry("billing.plan_changed"))).toBe("billing.plan_changed");
  });

  it("copes with missing or oddly typed details", () => {
    expect(describeAudit(entry("member.added", null))).toBe("added ? as ?");
    expect(describeAudit(entry("member.added", { email: { nested: true }, role: null }))).toBe("added ? as ?");
  });
});

describe("actorLabel", () => {
  it("prefers the name, then the email, then says the user is gone", () => {
    expect(actorLabel(entry("x"))).toBe("Ada Lovelace");
    expect(actorLabel(entry("x", null, { actor_name: null }))).toBe("ada@example.com");
    expect(actorLabel(entry("x", null, { actor_name: null, actor_email: null, actor_id: null }))).toBe("A removed user");
  });
});
