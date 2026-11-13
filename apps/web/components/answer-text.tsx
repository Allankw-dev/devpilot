import type { ReactNode } from "react";

/**
 * Renders a model's Markdown-ish answer as plain React nodes. It never produces HTML from the
 * text, so nothing the model (or the code it read) says can inject markup or scripts. Only
 * citation numbers that match a real source become links.
 */
export function AnswerText({
  text,
  linkFor,
}: {
  text: string;
  linkFor: (n: number) => string | null;
}) {
  return <div className="space-y-3 text-sm leading-relaxed">{blocks(text, linkFor)}</div>;
}

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[\d{1,3}\])/g;
const LIST_ITEM = /^\s*(?:[-*]|\d+[.)])\s+(.*)$/;

function inline(text: string, linkFor: (n: number) => string | null, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={k} className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={k}>{part.slice(2, -2)}</strong>;
    }
    const cite = /^\[(\d{1,3})\]$/.exec(part);
    if (cite) {
      const href = linkFor(Number(cite[1]));
      return href ? (
        <a
          key={k}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="align-super text-[0.7em] font-medium text-primary hover:underline"
        >
          [{cite[1]}]
        </a>
      ) : (
        <span key={k}>{part}</span>
      );
    }
    return <span key={k}>{part}</span>;
  });
}

function blocks(text: string, linkFor: (n: number) => string | null): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i += 1; // the closing fence (or the end of the text)
      out.push(
        <pre key={`b${out.length}`} className="overflow-x-auto rounded-md border border-border bg-muted px-3 py-2 text-xs">
          <code>{code.join("\n")}</code>
        </pre>,
      );
    } else if (LIST_ITEM.test(line)) {
      const items: string[] = [];
      while (i < lines.length && LIST_ITEM.test(lines[i])) items.push(LIST_ITEM.exec(lines[i++])![1]);
      out.push(
        <ul key={`b${out.length}`} className="list-disc space-y-1 pl-5">
          {items.map((item, n) => (
            <li key={n}>{inline(item, linkFor, `b${out.length}-${n}`)}</li>
          ))}
        </ul>,
      );
    } else if (!line.trim()) {
      i += 1;
    } else {
      const para: string[] = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !lines[i].trim().startsWith("```") &&
        !LIST_ITEM.test(lines[i])
      ) {
        para.push(lines[i++]);
      }
      const heading = /^#{1,4}\s+(.*)$/.exec(para[0]);
      const content = heading ? [heading[1], ...para.slice(1)].join(" ") : para.join(" ");
      out.push(
        <p key={`b${out.length}`} className={heading ? "font-semibold" : undefined}>
          {inline(content, linkFor, `b${out.length}`)}
        </p>,
      );
    }
  }
  return out;
}
