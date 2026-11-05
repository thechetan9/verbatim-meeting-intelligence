"use client";

import {
  Activity,
  ChevronDown,
  CircleAlert,
  CornerDownRight,
  FileSearch,
  ListChecks,
  SearchX,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import { SpeakerAvatar, Spinner } from "@/components/ui";
import { citationKeyFromHref, linkCitations, trimPartialCitation } from "@/lib/citations";
import type { AgentStep, ChatMessage, Citation, Grounding, Trace } from "@/lib/types";

interface Props {
  readonly message: ChatMessage;
  readonly onCite: (c: Citation) => void;
  /** Only the latest answer shows follow-up suggestions, to keep the thread calm. */
  readonly onAsk?: (question: string) => void;
}

export function AssistantMessage({ message, onCite, onAsk }: Props) {
  const citations = useMemo(() => message.citations ?? [], [message.citations]);
  const byKey = useMemo(() => new Map(citations.map((c, i) => [c.key, { c, n: i + 1 }])), [citations]);
  const streaming = message.status === "streaming";
  const text = linkCitations(streaming ? trimPartialCitation(message.content) : message.content);

  return (
    <div className="space-y-3">
      {(message.steps?.length ?? 0) > 0 && <AgentSteps steps={message.steps!} streaming={streaming} />}

      {message.content ? (
        <div className="prose-answer text-[15px]">
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                const key = citationKeyFromHref(href);
                if (!key) {
                  return (
                    <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">
                      {children}
                    </a>
                  );
                }
                const hit = byKey.get(key);
                return <CitationChip citeKey={key} n={hit?.n} citation={hit?.c} onCite={onCite} />;
              },
            }}
          >
            {text}
          </ReactMarkdown>
          {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-accent align-middle" />}
        </div>
      ) : (
        streaming && (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Spinner /> {message.steps?.length ? "Reading the evidence…" : "Thinking…"}
          </p>
        )
      )}

      {message.status === "error" && (
        <p className="flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
          <CircleAlert className="h-4 w-4" /> {message.error}
        </p>
      )}

      {message.status === "done" && (
        <>
          {citations.length > 0 && <Sources citations={citations} onCite={onCite} />}
          <div className="flex flex-wrap items-center gap-2">
            {message.grounding && <GroundingBadge grounding={message.grounding} count={citations.length} />}
            {message.trace && <TraceToggle trace={message.trace} />}
          </div>
          {onAsk && (message.suggestions?.length ?? 0) > 0 && (
            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              {message.suggestions!.map((q) => (
                <button
                  key={q}
                  onClick={() => onAsk(q)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-panel-2/60 px-3 py-1 text-xs text-muted transition hover:border-accent hover:text-accent"
                >
                  <CornerDownRight className="h-3 w-3" />
                  {q}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CitationChip({
  citeKey,
  n,
  citation,
  onCite,
}: {
  citeKey: string;
  n?: number;
  citation?: Citation;
  onCite: (c: Citation) => void;
}) {
  if (!citation) {
    // Still streaming (citations arrive at the end) or an invalid key that the guardrail removed.
    return <span className="mx-0.5 align-super text-[10px] text-faint">[{citeKey}]</span>;
  }
  return (
    <span className="group relative inline-block align-baseline">
      <button
        type="button"
        onClick={() => onCite(citation)}
        className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full bg-accent-soft px-1 text-[10.5px] font-semibold text-accent transition hover:bg-accent hover:text-accent-text"
        aria-label={`Source ${n}: ${citation.speaker} at ${citation.timestamp}`}
      >
        {n}
      </button>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-30 mb-2 w-72 -translate-x-1/2 rounded-xl border border-border bg-panel p-3 text-left text-xs opacity-0 shadow-xl transition group-hover:visible group-hover:opacity-100"
      >
        <span className="mb-1.5 flex items-center gap-2">
          <SpeakerAvatar name={citation.speaker} size={20} />
          <span className="font-semibold">{citation.speaker}</span>
          <span className="font-mono text-faint">{citation.timestamp}</span>
        </span>
        <span className="block leading-relaxed text-muted">“{truncate(citation.text, 220)}”</span>
        <span className="mt-1.5 block truncate text-[10.5px] text-faint">{citation.meeting_title}</span>
      </span>
    </span>
  );
}

function Sources({ citations, onCite }: { citations: Citation[]; onCite: (c: Citation) => void }) {
  const [open, setOpen] = useState(citations.length <= 3);
  return (
    <div className="rounded-xl border border-border bg-panel-2/60">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted"
      >
        <FileSearch className="h-3.5 w-3.5" />
        {citations.length} source{citations.length > 1 ? "s" : ""} from{" "}
        {new Set(citations.map((c) => c.meeting_id)).size} meeting
        {new Set(citations.map((c) => c.meeting_id)).size > 1 ? "s" : ""}
        <ChevronDown className={`ml-auto h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ol className="space-y-1 px-2 pb-2">
          {citations.map((c, i) => (
            <li key={c.key}>
              <button
                onClick={() => onCite(c)}
                className="flex w-full gap-2.5 rounded-lg px-2 py-1.5 text-left transition hover:bg-panel"
              >
                <span className="mt-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-accent-soft text-[10.5px] font-semibold text-accent">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-xs">
                    <span className="font-semibold">{c.speaker}</span>
                    <span className="font-mono text-faint">{c.timestamp}</span>
                    <span className="truncate text-faint">· {c.meeting_title}</span>
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted">“{truncate(c.text, 160)}”</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const GROUNDING: Record<Grounding, { label: (n: number) => string; cls: string; icon: React.ReactNode; tip: string }> = {
  grounded: {
    label: (n) => `Grounded in ${n} source${n > 1 ? "s" : ""}`,
    cls: "bg-ok-soft text-ok",
    icon: <ShieldCheck className="h-3.5 w-3.5" />,
    tip: "Every citation was checked against the transcript lines the assistant was shown.",
  },
  no_evidence: {
    label: () => "Not covered in these meetings",
    cls: "bg-panel-2 text-muted",
    icon: <SearchX className="h-3.5 w-3.5" />,
    tip: "The assistant searched the transcripts and found nothing that answers this.",
  },
  unsupported: {
    label: () => "Unverified — no citations",
    cls: "bg-warn-soft text-warn",
    icon: <TriangleAlert className="h-3.5 w-3.5" />,
    tip: "This answer has no valid citations. Treat it with caution.",
  },
};

function GroundingBadge({ grounding, count }: { grounding: Grounding; count: number }) {
  const g = GROUNDING[grounding];
  return (
    <span title={g.tip} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${g.cls}`}>
      {g.icon}
      {g.label(count)}
    </span>
  );
}

function stepLabel(step: AgentStep): { icon: React.ReactNode; text: string } {
  if (step.name === "search_transcripts") {
    const extra = [step.args.speaker && `speaker: ${step.args.speaker}`].filter(Boolean).join(", ");
    return {
      icon: <FileSearch className="h-3.5 w-3.5" />,
      text: `Searched transcripts for “${String(step.args.query ?? "")}”${extra ? ` (${extra})` : ""}`,
    };
  }
  if (step.name === "get_meeting_insights") {
    return {
      icon: <ListChecks className="h-3.5 w-3.5" />,
      text: step.args.owner ? `Looked up action items for ${String(step.args.owner)}` : "Read decisions & action items",
    };
  }
  return { icon: <Activity className="h-3.5 w-3.5" />, text: step.name };
}

function AgentSteps({ steps, streaming }: { steps: AgentStep[]; streaming: boolean }) {
  return (
    <ol className="space-y-1 border-l-2 border-border pl-3">
      {steps.map((s) => {
        const { icon, text } = stepLabel(s);
        return (
          <li key={s.id + text} className="flex items-center gap-2 text-xs text-muted">
            <span className="text-faint">{icon}</span>
            <span className="min-w-0 truncate">{text}</span>
            {s.summary ? (
              <span className="shrink-0 text-faint">
                · {s.summary} · {Math.round(s.duration_ms ?? 0)} ms
              </span>
            ) : (
              streaming && <Spinner className="h-3 w-3 shrink-0" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function TraceToggle({ trace }: { trace: Trace }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="w-full sm:w-auto">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] text-faint hover:bg-panel-2 hover:text-muted"
      >
        <Activity className="h-3.5 w-3.5" />
        {(trace.total_ms / 1000).toFixed(1)}s · {(trace.input_tokens + trace.output_tokens).toLocaleString()} tokens · $
        {trace.est_cost_usd.toFixed(4)}
        <ChevronDown className={`h-3 w-3 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 rounded-xl border border-border bg-panel-2/60 p-3 font-mono text-[11px] text-muted">
          <p className="mb-2">
            trace {trace.trace_id} · model {trace.model} · {trace.steps} step{trace.steps > 1 ? "s" : ""} ·{" "}
            {trace.evidence_shown} lines shown · {trace.citations} cited
            {trace.invalid_citations.length > 0 && ` · removed invalid: ${trace.invalid_citations.join(", ")}`}
            {trace.injection_signal && " · ⚠ injection pattern detected"}
          </p>
          <table className="w-full">
            <tbody>
              {trace.spans.map((s, i) => (
                <tr key={i} className="align-top">
                  <td className="py-0.5 pr-3 text-text">{s.name}</td>
                  <td className="py-0.5 pr-3 text-right tabular-nums">{Math.round(s.duration_ms)} ms</td>
                  <td className="py-0.5 text-faint">{spanDetail(s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function spanDetail(s: Trace["spans"][number]): string {
  if (s.name === "llm.generate") {
    const calls = (s.tool_calls as string[] | undefined) ?? [];
    return `in ${s.input_tokens} / out ${s.output_tokens} tok${calls.length ? ` → ${calls.join(", ")}` : " → answer"}`;
  }
  if (s.name === "tool.search_transcripts") return `“${s.query}” → ${s.hits} chunks (hybrid BM25+dense, RRF)`;
  if (s.name === "tool.get_meeting_insights") return `${(s.meeting_ids as string[] | undefined)?.length ?? 0} meetings`;
  return "";
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
