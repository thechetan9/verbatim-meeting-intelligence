"use client";

import { Library, PanelRight, Quote } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ChatPanel } from "@/components/ChatPanel";
import { ContextPanel } from "@/components/ContextPanel";
import { Sidebar } from "@/components/Sidebar";
import { useChat } from "@/hooks/useChat";
import { useMeetings } from "@/hooks/useMeetings";
import { api } from "@/lib/api";
import type { Citation, Focus, Health } from "@/lib/types";

type Drawer = "meetings" | "context" | null;

export default function Home() {
  const { meetings, loading, error, refresh } = useMeetings();
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedScope, setScope] = useState<string[]>([]);
  const [selectedId, setActiveId] = useState<string | null>(null);
  const [tab, setTab] = useState<"insights" | "transcript">("insights");
  const [focus, setFocus] = useState<Focus | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);

  // Derived during render (not synced in an effect): selections stay valid as meetings are
  // added or deleted, and the first meeting is shown when nothing is selected.
  const exists = (id: string) => meetings.some((m) => m.id === id);
  const scope = selectedScope.filter(exists);
  const activeId = selectedId && exists(selectedId) ? selectedId : (meetings[0]?.id ?? null);
  const chat = useChat(scope);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, [meetings.length]);

  const jump = useCallback((meetingId: string, utteranceIdx: number) => {
    setActiveId(meetingId);
    setTab("transcript");
    setFocus({ meetingId, utteranceIdx, nonce: Date.now() });
    // On wide screens the context panel is always visible; only narrow layouts need the drawer.
    const panelVisible = window.matchMedia("(min-width: 1280px)").matches;
    setDrawer(panelVisible ? null : "context");
  }, []);

  const onCite = useCallback((c: Citation) => jump(c.meeting_id, c.utterance_idx), [jump]);

  const llmEnabled = health?.llm_enabled ?? false;
  const chatDisabledReason = disabledReason(llmEnabled, meetings.length);

  const sidebar = (
    <Sidebar
      meetings={meetings}
      loading={loading}
      apiError={error}
      llmEnabled={llmEnabled}
      scope={scope}
      activeId={activeId}
      onToggleScope={(id) => setScope((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))}
      onClearScope={() => setScope([])}
      onOpen={(id) => {
        setActiveId(id);
        setTab("insights");
        setDrawer((d) => (d === "meetings" ? "context" : d));
      }}
      onChanged={refresh}
    />
  );
  const context = (
    <ContextPanel
      meetings={meetings}
      activeId={activeId}
      focus={focus}
      tab={tab}
      onTab={setTab}
      onSelect={setActiveId}
      onJump={jump}
      onClose={drawer === "context" ? () => setDrawer(null) : undefined}
    />
  );

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-panel px-4">
        <button
          className="rounded-lg p-1.5 text-muted hover:bg-panel-2 lg:hidden"
          onClick={() => setDrawer(drawer === "meetings" ? null : "meetings")}
          aria-label="Meetings"
        >
          <Library className="h-5 w-5" />
        </button>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-text">
          <Quote className="h-4 w-4" fill="currentColor" />
        </span>
        <div className="leading-tight">
          <p className="text-[15px] font-semibold tracking-tight">Verbatim</p>
          <p className="hidden text-[11px] text-muted sm:block">Meeting answers, with receipts</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span
            className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium sm:inline-flex ${
              llmEnabled ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn"
            }`}
            title={llmEnabled ? "LLM connected" : "Set GEMINI_API_KEY to enable chat and insights"}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${llmEnabled ? "bg-ok" : "bg-warn"}`} />
            {llmEnabled ? health?.model : "No LLM key: search only"}
          </span>
          <button
            className="rounded-lg p-1.5 text-muted hover:bg-panel-2 xl:hidden"
            onClick={() => setDrawer(drawer === "context" ? null : "context")}
            aria-label="Meeting details"
          >
            <PanelRight className="h-5 w-5" />
          </button>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[280px_1fr] xl:grid-cols-[280px_1fr_400px]">
        <div className="hidden min-h-0 lg:block">{sidebar}</div>
        <ChatPanel
          messages={chat.messages}
          busy={chat.busy}
          disabled={!!chatDisabledReason}
          disabledReason={chatDisabledReason}
          hasMeetings={meetings.length > 0}
          scopeCount={scope.length}
          onSend={chat.send}
          onStop={chat.stop}
          onReset={chat.reset}
          onCite={onCite}
        />
        <div className="hidden min-h-0 xl:block">{context}</div>
      </main>

      {/* Drawers for narrow screens */}
      {drawer && (
        <dialog
          open
          aria-label={drawer === "meetings" ? "Meetings" : "Meeting details"}
          className={`fixed inset-0 z-40 m-0 flex h-full max-h-none w-full max-w-none bg-transparent p-0 ${
            drawer === "context" ? "xl:hidden" : "lg:hidden"
          }`}
        >
          <button className="absolute inset-0 bg-black/30" aria-label="Close" onClick={() => setDrawer(null)} />
          <div className={drawerClass(drawer)}>{drawer === "meetings" ? sidebar : context}</div>
        </dialog>
      )}
    </div>
  );
}

function disabledReason(llmEnabled: boolean, meetingCount: number): string | undefined {
  if (!llmEnabled) return "Chat needs GEMINI_API_KEY on the backend";
  if (meetingCount === 0) return "Add a meeting to start asking questions";
  return undefined;
}

function drawerClass(drawer: Exclude<Drawer, null>): string {
  const side = drawer === "context" ? "ml-auto" : "";
  return `relative h-full w-[88vw] max-w-100 shadow-2xl ${side}`;
}
