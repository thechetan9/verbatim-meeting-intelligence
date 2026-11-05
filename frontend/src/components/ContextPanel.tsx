"use client";

import { CalendarDays, CircleHelp, Clock, Gavel, ListTodo, RefreshCw, Users, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { SpeakerAvatar, Spinner, speakerTextColor } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, formatDuration, formatTs } from "@/lib/format";
import type { Focus, Meeting, MeetingDetail, Utterance } from "@/lib/types";

type Tab = "insights" | "transcript";

interface Props {
  readonly meetings: Meeting[];
  readonly activeId: string | null;
  readonly focus: Focus | null;
  readonly tab: Tab;
  readonly onTab: (t: Tab) => void;
  readonly onSelect: (id: string) => void;
  readonly onJump: (meetingId: string, idx: number) => void;
  readonly onClose?: () => void;
}

export function ContextPanel(p: Props) {
  const meeting = p.meetings.find((m) => m.id === p.activeId) ?? null;
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const [utterances, setUtterances] = useState<Utterance[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load detail + transcript when the meeting changes, and again when its insights finish.
  useEffect(() => {
    if (!p.activeId) return;
    let cancelled = false;
    setError(null);
    Promise.all([api.getMeeting(p.activeId), api.getTranscript(p.activeId)])
      .then(([d, t]) => {
        if (cancelled) return;
        setDetail(d);
        setUtterances(t.utterances);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load"));
    return () => {
      cancelled = true;
    };
  }, [p.activeId, meeting?.insights_status]);

  if (!meeting) {
    return (
      <aside className="flex h-full flex-col items-center justify-center gap-2 border-l border-border bg-panel p-6 text-center">
        <Clock className="h-6 w-6 text-faint" />
        <p className="text-sm font-medium">No meeting selected</p>
        <p className="max-w-[16rem] text-xs text-muted">
          Pick a meeting to see its decisions, action items and full transcript. Clicking a citation opens the exact
          moment here.
        </p>
      </aside>
    );
  }

  const ready = detail?.meeting.id === meeting.id;
  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-panel">
      <header className="border-b border-border p-3">
        <div className="flex items-start gap-2">
          <select
            value={meeting.id}
            onChange={(e) => p.onSelect(e.target.value)}
            aria-label="Meeting"
            className="min-w-0 flex-1 truncate rounded-lg border border-border bg-panel px-2 py-1.5 text-sm font-semibold"
          >
            {p.meetings.map((m) => (
              <option key={m.id} value={m.id}>
                {m.title}
              </option>
            ))}
          </select>
          {p.onClose && (
            <button onClick={p.onClose} className="rounded-lg p-1.5 text-muted hover:bg-panel-2" aria-label="Close panel">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1">
            <CalendarDays className="h-3 w-3" /> {formatDate(meeting.date)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" /> {formatDuration(meeting.duration_s)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Users className="h-3 w-3" /> {meeting.speakers.length} people
          </span>
        </div>
        <div className="mt-2 flex -space-x-1">
          {meeting.speakers.map((s) => (
            <span key={s} className="rounded-full ring-2 ring-panel">
              <SpeakerAvatar name={s} size={26} />
            </span>
          ))}
        </div>
        <div role="tablist" className="mt-3 grid grid-cols-2 rounded-lg bg-panel-2 p-0.5 text-xs font-medium">
          {(["insights", "transcript"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={p.tab === t}
              onClick={() => p.onTab(t)}
              className={`rounded-md py-1.5 capitalize transition ${p.tab === t ? "bg-panel shadow-sm" : "text-muted"}`}
            >
              {t}
            </button>
          ))}
        </div>
      </header>

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        {error && <p className="m-3 rounded-lg bg-danger-soft p-3 text-xs text-danger">{error}</p>}
        {!ready && !error && (
          <div className="flex justify-center py-10 text-muted">
            <Spinner />
          </div>
        )}
        {ready && p.tab === "insights" && (
          <InsightsView meeting={meeting} detail={detail} utterances={utterances ?? []} onJump={p.onJump} />
        )}
        {ready && p.tab === "transcript" && (
          <TranscriptView
            meetingId={meeting.id}
            utterances={utterances ?? []}
            topics={detail?.insights?.topics ?? []}
            focus={p.focus?.meetingId === meeting.id ? p.focus : null}
          />
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------- insights

function InsightsView({
  meeting,
  detail,
  utterances,
  onJump,
}: {
  readonly meeting: Meeting;
  readonly detail: MeetingDetail;
  readonly utterances: Utterance[];
  readonly onJump: (meetingId: string, idx: number) => void;
}) {
  const [retrying, setRetrying] = useState(false);
  const ts = useMemo(() => new Map(utterances.map((u) => [u.idx, formatTs(u.start_s)])), [utterances]);
  const ins = detail.insights;
  const status = meeting.insights_status;

  const Evidence = ({ idx }: { readonly idx: number[] }) => (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {idx.map((i) => (
        <button
          key={i}
          onClick={() => onJump(meeting.id, i)}
          title="Show in transcript"
          className="rounded bg-panel-2 px-1.5 py-px font-mono text-[10px] text-muted transition hover:bg-accent-soft hover:text-accent"
        >
          {ts.get(i) ?? `#${i}`}
        </button>
      ))}
    </span>
  );

  if (status === "pending") {
    return (
      <div className="space-y-3 p-4">
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Extracting decisions and action items…
        </p>
        {[80, 95, 60, 88].map((w) => (
          <div key={w} className="h-3 animate-pulse rounded bg-panel-2" style={{ width: `${w}%` }} />
        ))}
      </div>
    );
  }
  if (status === "skipped" || (status === "failed" && !ins)) {
    return (
      <div className="m-3 rounded-xl bg-panel-2 p-4 text-sm">
        {status === "skipped" ? (
          <p className="text-muted">Insights need an LLM. Set GEMINI_API_KEY on the backend; search still works without it.</p>
        ) : (
          <>
            <p className="font-medium text-danger">Insight extraction failed</p>
            <p className="mt-1 text-xs text-muted">{meeting.insights_error}</p>
            <button
              disabled={retrying}
              onClick={() => {
                setRetrying(true);
                api.regenerateInsights(meeting.id).catch(() => setRetrying(false));
              }}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-panel px-3 py-1.5 text-xs font-medium hover:text-accent"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${retrying ? "animate-spin" : ""}`} /> Retry
            </button>
          </>
        )}
      </div>
    );
  }
  if (!ins) return null;

  return (
    <div className="space-y-5 p-4">
      <section>
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Summary</h3>
        <p className="text-sm leading-relaxed">{ins.summary}</p>
      </section>

      <Section icon={<Gavel className="h-3.5 w-3.5" />} title="Decisions" count={ins.decisions.length}>
        {ins.decisions.map((d) => (
          <li key={d.text} className="rounded-lg border border-border p-2.5 text-sm leading-snug">
            {d.text}
            <span className="mt-1 block text-[11px] text-muted">
              {d.decided_by && <>Decided by {d.decided_by}</>}
              <Evidence idx={d.evidence} />
            </span>
          </li>
        ))}
      </Section>

      <Section icon={<ListTodo className="h-3.5 w-3.5" />} title="Action items" count={ins.action_items.length}>
        {ins.action_items.map((a) => (
          <li key={a.task} className="flex gap-2.5 rounded-lg border border-border p-2.5">
            {a.owner ? <SpeakerAvatar name={a.owner} size={26} /> : <span className="h-[26px] w-[26px] rounded-full bg-panel-2" />}
            <div className="min-w-0 flex-1 text-sm leading-snug">
              {a.task}
              <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-muted">
                <span className="font-medium">{a.owner ?? "Unassigned"}</span>
                {a.due && <span className="rounded bg-warn-soft px-1.5 py-px text-warn">Due {a.due}</span>}
                <Evidence idx={a.evidence} />
              </span>
            </div>
          </li>
        ))}
      </Section>

      <Section icon={<CircleHelp className="h-3.5 w-3.5" />} title="Open questions" count={ins.open_questions.length}>
        {ins.open_questions.map((q) => (
          <li key={q.text} className="rounded-lg bg-panel-2 p-2.5 text-sm leading-snug">
            {q.text}
            <Evidence idx={q.evidence} />
          </li>
        ))}
      </Section>
    </div>
  );
}

function Section({
  icon,
  title,
  count,
  children,
}: {
  readonly icon: React.ReactNode;
  readonly title: string;
  readonly count: number;
  readonly children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        {icon} {title} <span className="text-faint">({count})</span>
      </h3>
      {count === 0 ? <p className="text-xs text-faint">None recorded.</p> : <ul className="space-y-2">{children}</ul>}
    </section>
  );
}

// ---------------------------------------------------------------- transcript

function TranscriptView({
  meetingId,
  utterances,
  topics,
  focus,
}: {
  readonly meetingId: string;
  readonly utterances: Utterance[];
  readonly topics: { title: string; start_idx: number }[];
  readonly focus: Focus | null;
}) {
  const refs = useRef(new Map<number, HTMLLIElement>());
  const [filter, setFilter] = useState("");
  const topicAt = useMemo(() => new Map(topics.map((t) => [t.start_idx, t.title])), [topics]);
  const q = filter.trim().toLowerCase();
  const shown = q
    ? utterances.filter((u) => u.text.toLowerCase().includes(q) || u.speaker.toLowerCase().includes(q))
    : utterances;

  useEffect(() => {
    if (!focus) return;
    setFilter("");
    // Wait a frame so the (unfiltered) list is rendered before scrolling.
    const id = requestAnimationFrame(() =>
      refs.current.get(focus.utteranceIdx)?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
    return () => cancelAnimationFrame(id);
  }, [focus, meetingId]);

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-border bg-panel/95 p-2 backdrop-blur">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter transcript…"
          className="w-full rounded-lg border border-border bg-panel-2 px-2.5 py-1.5 text-xs outline-none focus:border-accent"
        />
      </div>
      <ol className="space-y-0.5 p-2">
        {shown.map((u) => {
          const focused = focus?.utteranceIdx === u.idx;
          const topic = !q && topicAt.get(u.idx);
          return (
            <li
              key={u.idx}
              ref={(el) => {
                if (el) refs.current.set(u.idx, el);
                else refs.current.delete(u.idx);
              }}
            >
              {topic && (
                <p className="mb-1 mt-3 px-2 text-[10.5px] font-semibold uppercase tracking-wide text-accent">{topic}</p>
              )}
              <div
                key={focused ? `f-${focus?.nonce}` : "n"}
                className={`flex gap-2.5 rounded-lg px-2 py-2 ${focused ? "flash ring-1 ring-warn/40" : ""}`}
              >
                <SpeakerAvatar name={u.speaker} size={24} />
                <div className="min-w-0 flex-1">
                  <p className="flex items-baseline gap-2 text-xs">
                    <span className="font-semibold" style={speakerTextColor(u.speaker)}>
                      {u.speaker}
                    </span>
                    <span className="font-mono text-[10.5px] text-faint">{formatTs(u.start_s)}</span>
                  </p>
                  <p className="mt-0.5 text-[13px] leading-relaxed">{u.text}</p>
                </div>
              </div>
            </li>
          );
        })}
        {shown.length === 0 && <p className="p-4 text-center text-xs text-faint">No lines match “{filter}”.</p>}
      </ol>
    </div>
  );
}
