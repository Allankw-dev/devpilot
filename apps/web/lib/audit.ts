import type { AuditEntry } from "@/lib/api";

const text = (value: unknown): string => (typeof value === "string" || typeof value === "number" ? String(value) : "?");
const quoted = (value: unknown): string => `“${text(value)}”`;

/** Who did it, as a name a person would recognise. */
export function actorLabel(entry: AuditEntry): string {
  return entry.actor_name || entry.actor_email || "A removed user";
}

/**
 * What happened, as a short phrase that follows the actor's name ("Ada " + this). Everything here is
 * rendered as plain text by React, so names typed by users can't inject markup.
 * An action this app doesn't know yet is shown as its raw code rather than hidden.
 */
export function describeAudit(entry: AuditEntry): string {
  const d = entry.details ?? {};
  switch (entry.action) {
    case "org.created":
      return `created the workspace ${quoted(d.name)}`;
    case "org.renamed":
      return `renamed the workspace from ${quoted(d.from)} to ${quoted(d.to)}`;
    case "org.deleted":
      return "deleted the workspace";
    case "member.added":
      return `added ${text(d.email)} as ${text(d.role)}`;
    case "member.role_changed":
      return `changed ${text(d.email)} from ${text(d.from)} to ${text(d.to)}`;
    case "member.removed":
      return d.self === true ? "left the workspace" : `removed ${text(d.email)}`;
    case "team.created":
      return `created the team ${quoted(d.name)}`;
    case "team.deleted":
      return `deleted the team ${quoted(d.name)}`;
    case "team.member_added":
      return `added someone to the team ${quoted(d.team)}`;
    case "team.member_removed":
      return `removed someone from the team ${quoted(d.team)}`;
    case "github.installation_connected":
      return `connected the GitHub account ${text(d.account)}`;
    case "github.installation_disconnected":
      return `disconnected the GitHub account ${text(d.account)}`;
    case "repository.index_requested":
      return `started indexing ${text(d.repository)}`;
    case "review.requested":
      return `${d.force === true ? "re-ran" : "requested"} a review of pull request #${text(d.number)}`;
    case "review.finding_updated":
      return `marked a review finding as ${text(d.status)}`;
    case "ci_analysis.requested":
      return d.force === true ? "re-ran a CI failure analysis" : "requested a CI failure analysis";
    case "ai.connection_tested":
      return "tested the AI connection";
    default:
      return entry.action;
  }
}
