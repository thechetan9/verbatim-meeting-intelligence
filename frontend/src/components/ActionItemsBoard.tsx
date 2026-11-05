"use client";

import { CalendarClock, CheckCircle2, Circle, ListTodo } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { SpeakerAvatar, Spinner } from "@/components/ui";
import { groupByOwner, itemKey, loadDone, saveDone } from "@/lib/actions";
import { api } from "@/lib/api";
import { formatDate, formatTs, plural } from "@/lib/format";
import type { Meeting, TrackedActionItem } from "@/lib/types";

interface Props {
  readonly meetings: Meeting[];
  readonly scope: string[];
  readonly onJump: (meetingId: string, idx: number) => void;
}

/** Every action item from every meeting, grouped by person: "who owes what, from where". */
export function ActionItemsBoard({ meetings, scope, onJump }: Props) {
  const [items, setItems] = useState<TrackedActionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(() => loadDone());
  const [showDone, setShowDone] = useState(false);

  // Reload when meetings change (new upload, insights finished) or the scope changes.
  const readyKey = meetings.map((m) => `${m.id}:${m.insights_status}`).join(",");
  const scopeKey = scope.join(",");
  useEffect(() => {
    let cancelled = false;
    api
      .actionItems(scopeKey ? scopeKey.split(",") : [])
      .then((list) => {
        if (cancelled) return;
        setItems(list);
        setError(null);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load"));
    return () => {
      cancelled = true;
    };
  }, [readyKey, scopeKey]);

  useEffect(() => saveDone(done), [done]);

  const groups = useMemo(() => groupByOwner(items ?? [], done), [items, done]);
  const total = items?.length ?? 0;
  const doneCount = (items ?? []).filter((a) => done.has(itemKey(a))).length;

  const toggle = (a: TrackedActionItem) =>
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(itemKey(a))) next.delete(itemKey(a));
      else next.add(itemKey(a));
      return next;
    });

  if (error) return <p className="m-6 rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p>;
  if (items === null) {
    return (
      <div className="flex justify-center py-16 text-muted">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <ListTodo className="h-5 w-5 text-accent" /> Action items
          </h1>
          <p className="mt-1 text-sm text-muted">
            {total === 0
              ? "Action items appear here once insights are extracted."
              : `${plural(total - doneCount, "open item")} across ${plural(new Set(items.map((a) => a.meeting_id)).size, "meeting")}${scope.length ? " (selected meetings)" : ""} · ${doneCount} done`}
          </p>
        </div>
        {doneCount > 0 && (
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} className="accent-accent" />
            Show done
          </label>
        )}
      </div>

      <div className="space-y-4">
        {groups.map((g) => {
          const visible = g.items.filter((a) => showDone || !done.has(itemKey(a)));
          const open = g.items.filter((a) => !done.has(itemKey(a))).length;
          if (visible.length === 0) return null;
          return (
            <section key={g.owner} className="rounded-2xl border border-border bg-panel p-3 shadow-sm">
              <h2 className="mb-2 flex items-center gap-2 px-1 text-sm font-semibold">
                {g.owner === "Unassigned" ? <span className="h-7 w-7 rounded-full bg-panel-2" /> : <SpeakerAvatar name={g.owner} size={28} />}
                {g.owner}
                <span className="font-normal text-faint">· {plural(open, "open item")}</span>
              </h2>
              <ul className="divide-y divide-border">
                {visible.map((a) => {
                  const isDone = done.has(itemKey(a));
                  return (
                    <li key={itemKey(a)} className="flex gap-3 px-1 py-2.5">
                      <button
                        onClick={() => toggle(a)}
                        aria-label={isDone ? "Mark as open" : "Mark as done"}
                        className={`mt-0.5 shrink-0 ${isDone ? "text-ok" : "text-faint hover:text-accent"}`}
                      >
                        {isDone ? <CheckCircle2 className="h-4.5 w-4.5" /> : <Circle className="h-4.5 w-4.5" />}
                      </button>
                      <div className="min-w-0 flex-1">
                        <p className={`text-sm leading-snug ${isDone ? "text-faint line-through" : ""}`}>{a.task}</p>
                        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
                          {a.due && (
                            <span className="inline-flex items-center gap-1 rounded bg-warn-soft px-1.5 py-px text-warn">
                              <CalendarClock className="h-3 w-3" /> Due {a.due}
                            </span>
                          )}
                          <span className="truncate">
                            {a.meeting_title} · {formatDate(a.meeting_date)}
                          </span>
                          {a.evidence.length > 0 && (
                            <button
                              onClick={() => onJump(a.meeting_id, a.evidence[0])}
                              title="Show where it was assigned"
                              className="rounded bg-panel-2 px-1.5 py-px font-mono text-[10px] transition hover:bg-accent-soft hover:text-accent"
                            >
                              {a.start_s === null ? `#${a.evidence[0]}` : formatTs(a.start_s)}
                            </button>
                          )}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
