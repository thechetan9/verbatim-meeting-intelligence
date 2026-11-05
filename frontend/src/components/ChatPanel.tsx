"use client";

import { ArrowUp, MessagesSquare, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { AssistantMessage } from "@/components/AssistantMessage";
import { Kbd } from "@/components/ui";
import type { ChatMessage, Citation } from "@/lib/types";

const SUGGESTIONS = [
  "Which new trial sites are we adding, and why did that change?",
  "What action items does Priya Nair own across all meetings?",
  "Why did we choose AWS SNS over Twilio for reminders?",
  "What guardrails were agreed for the AI drafting pilot?",
];

interface Props {
  readonly messages: ChatMessage[];
  readonly busy: boolean;
  readonly disabled: boolean;
  readonly disabledReason?: string;
  readonly hasMeetings: boolean;
  readonly scopeCount: number;
  readonly onSend: (q: string) => void;
  readonly onStop: () => void;
  readonly onReset: () => void;
  readonly onCite: (c: Citation) => void;
}

export function ChatPanel(p: Props) {
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const last = p.messages.at(-1);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [p.messages.length, last?.content, last?.steps?.length]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [draft]);

  const submit = (q: string) => {
    if (!q.trim() || p.busy || p.disabled) return;
    p.onSend(q);
    setDraft("");
  };

  const placeholder = p.scopeCount
    ? `Ask about the ${p.scopeCount} selected meeting${p.scopeCount > 1 ? "s" : ""}…`
    : "Ask about decisions, action items, who said what…";

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {p.messages.length === 0 ? (
            <EmptyState hasMeetings={p.hasMeetings} disabled={p.disabled} onPick={submit} />
          ) : (
            <div className="space-y-6">
              {p.messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-[15px] text-accent-text">
                      {m.content}
                    </p>
                  </div>
                ) : (
                  <div key={m.id} data-testid="assistant-message" className="rounded-2xl border border-border bg-panel p-4 shadow-sm">
                    <AssistantMessage message={m} onCite={p.onCite} />
                  </div>
                ),
              )}
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>

      <div className="border-t border-border bg-bg/80 px-4 pb-4 pt-3 backdrop-blur">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(draft);
          }}
          className="mx-auto max-w-3xl"
        >
          <div className="flex items-end gap-2 rounded-2xl border border-border bg-panel p-2 shadow-sm focus-within:border-accent">
            <textarea
              ref={box}
              rows={1}
              value={draft}
              maxLength={2000}
              disabled={p.disabled}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit(draft);
                }
              }}
              placeholder={p.disabled ? p.disabledReason : placeholder}
              aria-label="Your question"
              className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-faint disabled:cursor-not-allowed"
            />
            {p.busy ? (
              <button
                type="button"
                onClick={p.onStop}
                aria-label="Stop"
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-text text-bg"
              >
                <Square className="h-3.5 w-3.5" fill="currentColor" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim() || p.disabled}
                aria-label="Send"
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-accent-text transition disabled:opacity-40"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </div>
          <div className="mt-1.5 flex items-center justify-between px-1 text-[11px] text-faint">
            <span className="hidden sm:inline">
              <Kbd>Enter</Kbd> to send · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> new line · answers cite the exact moment
            </span>
            {p.messages.length > 0 && (
              <button
                type="button"
                onClick={p.onReset}
                className="inline-flex items-center gap-1 hover:text-muted"
              >
                <RotateCcw className="h-3 w-3" /> New chat
              </button>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}

function EmptyState({
  hasMeetings,
  disabled,
  onPick,
}: {
  readonly hasMeetings: boolean;
  readonly disabled: boolean;
  readonly onPick: (q: string) => void;
}) {
  return (
    <div className="flex flex-col items-center pt-[8vh] text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        <MessagesSquare className="h-6 w-6" />
      </span>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Ask your meetings anything</h1>
      <p className="mt-2 max-w-md text-sm text-muted">
        Decisions, action items, who said what, and how things changed from one meeting to the next. Every answer
        links to the exact moment in the transcript.
      </p>
      {hasMeetings ? (
        <div className="mt-8 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              disabled={disabled}
              onClick={() => onPick(s)}
              className="rounded-xl border border-border bg-panel p-3 text-left text-sm text-muted transition hover:border-accent hover:text-text disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      ) : (
        <p className="mt-8 rounded-xl bg-panel-2 px-4 py-3 text-sm text-muted">
          Start by uploading a transcript or loading the sample meetings from the left panel.
        </p>
      )}
    </div>
  );
}
