import { CircleAlert, CircleCheck, CircleDashed, CircleMinus, LoaderCircle } from "lucide-react";

import { initials, speakerHue } from "@/lib/format";
import type { InsightsStatus } from "@/lib/types";

export function SpeakerAvatar({ name, size = 28 }: { name: string; size?: number }) {
  const hue = speakerHue(name);
  return (
    <span
      title={name}
      aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold uppercase"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        background: `hsl(${hue} 70% 50% / 0.16)`,
        color: `hsl(${hue} 65% 42%)`,
      }}
    >
      {initials(name)}
    </span>
  );
}

export function speakerTextColor(name: string) {
  return { color: `hsl(${speakerHue(name)} 60% 45%)` };
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <LoaderCircle className={`${className} animate-spin`} aria-label="Loading" />;
}

const STATUS: Record<InsightsStatus, { label: string; cls: string; icon: React.ReactNode }> = {
  pending: { label: "Analysing", cls: "text-accent", icon: <Spinner className="h-3 w-3" /> },
  ready: { label: "Insights ready", cls: "text-ok", icon: <CircleCheck className="h-3 w-3" /> },
  failed: { label: "Insights failed", cls: "text-danger", icon: <CircleAlert className="h-3 w-3" /> },
  skipped: { label: "Search only", cls: "text-faint", icon: <CircleMinus className="h-3 w-3" /> },
};

export function InsightsBadge({ status }: { status: InsightsStatus }) {
  const s = STATUS[status] ?? { label: status, cls: "text-faint", icon: <CircleDashed className="h-3 w-3" /> };
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${s.cls}`}>
      {s.icon}
      {s.label}
    </span>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-panel-2 px-1 py-px font-mono text-[10px] text-muted">
      {children}
    </kbd>
  );
}
