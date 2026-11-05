// Mirrors the backend's pydantic models (app/domain/models.py, app/api/schemas.py).

export type InsightsStatus = "pending" | "ready" | "failed" | "skipped";

export interface Meeting {
  id: string;
  title: string;
  date: string | null;
  source_filename: string;
  format: string;
  duration_s: number;
  speakers: string[];
  utterance_count: number;
  created_at: string;
  insights_status: InsightsStatus;
  insights_error: string | null;
}

export interface Utterance {
  idx: number;
  speaker: string;
  start_s: number;
  end_s: number | null;
  text: string;
}

export interface Decision {
  text: string;
  decided_by: string | null;
  evidence: number[];
}
export interface ActionItem {
  task: string;
  owner: string | null;
  due: string | null;
  evidence: number[];
}
export interface OpenQuestion {
  text: string;
  evidence: number[];
}
export interface Topic {
  title: string;
  start_idx: number;
}
export interface MeetingInsights {
  summary: string;
  decisions: Decision[];
  action_items: ActionItem[];
  open_questions: OpenQuestion[];
  topics: Topic[];
}

export interface MeetingDetail {
  meeting: Meeting;
  insights: MeetingInsights | null;
}

export interface Health {
  status: "ok";
  llm_enabled: boolean;
  model: string | null;
  meetings: number;
}

export interface Citation {
  key: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string | null;
  utterance_idx: number;
  speaker: string;
  start_s: number;
  timestamp: string;
  text: string;
}

export type Grounding = "grounded" | "no_evidence" | "unsupported";

export interface TraceSpan {
  name: string;
  duration_ms: number;
  [attr: string]: unknown;
}

export interface Trace {
  trace_id: string;
  total_ms: number;
  input_tokens: number;
  output_tokens: number;
  est_cost_usd: number;
  model: string;
  steps: number;
  evidence_shown: number;
  citations: number;
  invalid_citations: string[];
  grounding: Grounding;
  injection_signal: boolean;
  spans: TraceSpan[];
}

export interface AgentStep {
  id: string;
  name: string;
  args: Record<string, unknown>;
  summary?: string;
  duration_ms?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[];
  citations?: Citation[];
  grounding?: Grounding;
  trace?: Trace;
  status?: "streaming" | "done" | "error";
  error?: string;
}

/** Where the transcript panel should scroll to and highlight. */
export interface Focus {
  meetingId: string;
  utteranceIdx: number;
  nonce: number; // forces re-scroll when the same line is clicked twice
}
