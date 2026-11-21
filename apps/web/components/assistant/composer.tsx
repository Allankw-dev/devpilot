"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

export const MIN_QUESTION = 3;
export const MAX_QUESTION = 1000;

/** The question box. Enter sends, Shift+Enter adds a line. */
export function Composer({
  pending,
  disabled,
  placeholder,
  onSend,
}: {
  pending: boolean;
  disabled?: boolean;
  placeholder: string;
  onSend: (question: string) => void;
}) {
  const [text, setText] = useState("");
  const question = text.trim();
  const canSend = question.length >= MIN_QUESTION && !pending && !disabled;
  const send = () => {
    if (!canSend) return;
    onSend(question);
    setText("");
  };

  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <label htmlFor="assistant-question" className="sr-only">
        Question
      </label>
      <textarea
        id="assistant-question"
        value={text}
        rows={2}
        maxLength={MAX_QUESTION}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        className="min-h-[3rem] flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
      />
      <Button type="submit" variant="primary" disabled={!canSend}>
        {pending ? "Thinking…" : "Ask"}
      </Button>
    </form>
  );
}
