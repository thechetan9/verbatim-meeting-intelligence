"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { loadChat, saveChat } from "@/lib/storage";
import type { AgentStep, ChatMessage, Citation, Grounding, Trace } from "@/lib/types";

let counter = 0;
const newId = () => `msg_${Date.now()}_${counter++}`;

/** Chat state + streaming. The server is stateless: we send recent history with each question. */
export function useChat(scope: string[]) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadChat());
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);

  // Persist finished conversations (not every streamed token) so a refresh keeps the chat.
  useEffect(() => {
    if (!busy) saveChat(messages);
  }, [messages, busy]);

  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || busy) return;
      const history = messages
        .filter((m) => m.status !== "error" && m.content)
        .map((m) => ({ role: m.role, content: m.content }));
      const user: ChatMessage = { id: newId(), role: "user", content: q };
      const assistantId = newId();
      setMessages((prev) => [
        ...prev,
        user,
        { id: assistantId, role: "assistant", content: "", steps: [], status: "streaming" },
      ]);
      setBusy(true);
      const controller = new AbortController();
      abort.current = controller;

      try {
        const stream = api.chat(
          { question: q, history, meeting_ids: scope.length ? scope : null },
          controller.signal,
        );
        for await (const { event, data } of stream) {
          const d = data as Record<string, unknown>;
          switch (event) {
            case "tool_call":
              patch(assistantId, (m) => ({
                ...m,
                steps: [...(m.steps ?? []), { id: String(d.id), name: String(d.name), args: d.args as AgentStep["args"] }],
              }));
              break;
            case "tool_result":
              patch(assistantId, (m) => ({
                ...m,
                steps: (m.steps ?? []).map((s) =>
                  s.id === d.id && !s.summary
                    ? { ...s, summary: String(d.summary), duration_ms: Number(d.duration_ms) }
                    : s,
                ),
              }));
              break;
            case "delta":
              patch(assistantId, (m) => ({ ...m, content: m.content + String(d.text) }));
              break;
            case "reset":
              patch(assistantId, (m) => ({ ...m, content: "" }));
              break;
            case "citations":
              patch(assistantId, (m) => ({ ...m, citations: d.items as Citation[] }));
              break;
            case "done":
              patch(assistantId, (m) => ({
                ...m,
                content: String(d.answer ?? m.content),
                grounding: d.grounding as Grounding,
                trace: d.trace as Trace,
                status: "done",
              }));
              setBusy(false); // the answer is complete; suggestions may still arrive after it
              break;
            case "suggestions":
              patch(assistantId, (m) => ({ ...m, suggestions: d.questions as string[] }));
              break;
            case "error":
              patch(assistantId, (m) => ({ ...m, status: "error", error: String(d.message) }));
              break;
          }
        }
        // Stream ended without "done" (e.g. connection dropped): don't leave a spinner forever.
        patch(assistantId, (m) =>
          m.status === "streaming" ? { ...m, status: "error", error: "The answer was interrupted." } : m,
        );
      } catch (e) {
        const aborted = e instanceof DOMException && e.name === "AbortError";
        patch(assistantId, (m) => ({
          ...m,
          status: aborted ? "done" : "error",
          error: aborted ? undefined : e instanceof ApiError ? e.message : "Could not reach the API.",
          content: aborted ? m.content || "_Stopped._" : m.content,
        }));
      } finally {
        setBusy(false);
        abort.current = null;
      }
    },
    [busy, messages, scope],
  );

  const stop = useCallback(() => abort.current?.abort(), []);
  const reset = useCallback(() => {
    abort.current?.abort();
    setMessages([]);
  }, []);

  return { messages, busy, send, stop, reset };
}
