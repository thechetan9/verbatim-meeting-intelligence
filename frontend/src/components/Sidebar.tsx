"use client";

import { FileText, Sparkles, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { InsightsBadge, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, formatDuration, plural } from "@/lib/format";
import type { Meeting } from "@/lib/types";

const ACCEPT = ".txt,.vtt,.srt,.md,.mp3,.wav,.m4a,.aac,.ogg,.flac,.webm";
const AUDIO = /\.(mp3|wav|m4a|aac|ogg|flac|webm)$/i;

interface Props {
  meetings: Meeting[];
  loading: boolean;
  apiError: string | null;
  llmEnabled: boolean;
  scope: string[];
  activeId: string | null;
  onToggleScope: (id: string) => void;
  onClearScope: () => void;
  onOpen: (id: string) => void;
  onChanged: () => Promise<void> | void;
}

export function Sidebar(p: Readonly<Props>) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await p.onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (list.length === 0) return;
    const label = list.some((f) => AUDIO.test(f.name)) ? "Transcribing audio…" : "Uploading…";
    void run(label, async () => {
      const uploaded = await Promise.all(list.map((f) => api.upload(f)));
      p.onOpen(uploaded[uploaded.length - 1].id);
    });
  }

  const loadSamples = () => void run("Loading samples…", api.loadSamples);
  const remove = (m: Meeting) => {
    if (confirm(`Delete "${m.title}"?`)) void run("Deleting…", () => api.deleteMeeting(m.id));
  };

  let list: React.ReactNode;
  if (p.loading) {
    list = (
      <div className="flex justify-center py-8 text-muted">
        <Spinner />
      </div>
    );
  } else if (p.meetings.length === 0) {
    list = <EmptyMeetings disabled={!!busy} onLoadSamples={loadSamples} />;
  } else {
    list = (
      <ul className="space-y-1.5">
        {p.meetings.map((m) => (
          <MeetingRow
            key={m.id}
            meeting={m}
            active={p.activeId === m.id}
            inScope={p.scope.includes(m.id)}
            onToggleScope={() => p.onToggleScope(m.id)}
            onOpen={() => p.onOpen(m.id)}
            onDelete={() => remove(m)}
          />
        ))}
      </ul>
    );
  }

  const n = p.scope.length;
  const scopeNote = n
    ? `Questions are limited to ${plural(n, "selected meeting")}.`
    : "Questions search across all meetings. Tick meetings to narrow the scope.";

  return (
    <aside className="flex h-full min-h-0 flex-col gap-3 border-r border-border bg-panel p-3">
      <section
        aria-label="Upload transcripts"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          uploadFiles(e.dataTransfer.files);
        }}
        className={`rounded-xl border border-dashed p-3 text-center transition ${
          dragging ? "border-accent bg-accent-soft" : "border-border"
        }`}
      >
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) uploadFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          disabled={!!busy}
          onClick={() => input.current?.click()}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-text transition hover:opacity-90 disabled:opacity-60"
        >
          {busy ? <Spinner /> : <Upload className="h-4 w-4" />}
          {busy ?? "Upload transcript"}
        </button>
        <p className="mt-2 text-[11px] leading-snug text-faint">
          Drop .txt / .vtt / .srt with speakers &amp; timestamps
          {p.llmEnabled ? ", or an audio file to transcribe" : ""}
        </p>
      </section>

      {error && (
        <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}
      {p.apiError && (
        <p role="alert" className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
          API unreachable: {p.apiError}. Is the backend running on port 8000?
        </p>
      )}

      <div className="flex items-center justify-between px-1 pt-1">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
          Meetings {p.meetings.length > 0 && <span className="text-faint">({p.meetings.length})</span>}
        </h2>
        {n > 0 && (
          <button onClick={p.onClearScope} className="text-[11px] text-accent hover:underline">
            Clear selection
          </button>
        )}
      </div>

      <div className="scrollbar-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1">{list}</div>

      <p className="px-1 text-[11px] leading-snug text-faint">{scopeNote}</p>
    </aside>
  );
}

function EmptyMeetings({ disabled, onLoadSamples }: Readonly<{ disabled: boolean; onLoadSamples: () => void }>) {
  return (
    <div className="rounded-xl bg-panel-2 p-4 text-center">
      <p className="text-sm font-medium">No meetings yet</p>
      <p className="mt-1 text-xs text-muted">
        Upload a transcript, or load four sample meetings from a fictional clinical-trial team.
      </p>
      <button
        onClick={onLoadSamples}
        disabled={disabled}
        className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-panel px-3 py-1.5 text-xs font-medium hover:border-accent hover:text-accent disabled:opacity-60"
      >
        <Sparkles className="h-3.5 w-3.5" /> Load sample meetings
      </button>
    </div>
  );
}

function MeetingRow({
  meeting: m,
  active,
  inScope,
  onToggleScope,
  onOpen,
  onDelete,
}: Readonly<{
  meeting: Meeting;
  active: boolean;
  inScope: boolean;
  onToggleScope: () => void;
  onOpen: () => void;
  onDelete: () => void;
}>) {
  return (
    <li>
      <div
        className={`group relative flex gap-2.5 rounded-xl border p-2.5 transition ${
          active ? "border-accent bg-accent-soft/60" : "border-transparent hover:bg-panel-2"
        }`}
      >
        <input
          type="checkbox"
          checked={inScope}
          onChange={onToggleScope}
          aria-label={`Limit chat to ${m.title}`}
          title="Limit questions to selected meetings"
          className="mt-1 h-3.5 w-3.5 shrink-0 accent-accent"
        />
        <button onClick={onOpen} title={m.title} className="min-w-0 flex-1 pr-5 text-left">
          <span className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5 shrink-0 text-faint" />
            <span className="truncate text-sm font-medium">{m.title}</span>
          </span>
          <span className="mt-0.5 block text-[11px] text-muted">
            {formatDate(m.date)} · {formatDuration(m.duration_s)} · {m.speakers.length} people
          </span>
          <span className="mt-1 block">
            <InsightsBadge status={m.insights_status} />
          </span>
        </button>
        <button
          onClick={onDelete}
          className="absolute right-2 top-2 rounded p-1 text-faint opacity-0 transition hover:bg-danger-soft hover:text-danger group-hover:opacity-100 focus:opacity-100"
          aria-label={`Delete ${m.title}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </li>
  );
}
