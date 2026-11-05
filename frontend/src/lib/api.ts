import type { Health, Meeting, MeetingDetail, TrackedActionItem, Utterance } from "./types";
import { readSse, type SseEvent } from "./sse";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  health: () => request<Health>("/api/health"),
  listMeetings: () => request<Meeting[]>("/api/meetings"),
  getMeeting: (id: string) => request<MeetingDetail>(`/api/meetings/${id}`),
  getTranscript: (id: string) =>
    request<{ meeting_id: string; utterances: Utterance[] }>(`/api/meetings/${id}/transcript`),
  deleteMeeting: (id: string) => request<void>(`/api/meetings/${id}`, { method: "DELETE" }),
  regenerateInsights: (id: string) => request<void>(`/api/meetings/${id}/insights`, { method: "POST" }),
  actionItems: (meetingIds: string[] = []) => {
    const qs = meetingIds.map((id) => `meeting_ids=${encodeURIComponent(id)}`).join("&");
    return request<TrackedActionItem[]>(`/api/action-items${qs ? `?${qs}` : ""}`);
  },
  loadSamples: () => request<{ loaded: Meeting[]; skipped: string[] }>("/api/meetings/samples", { method: "POST" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Meeting>("/api/meetings", { method: "POST", body: form });
  },
  async *chat(
    body: { question: string; history: { role: string; content: string }[]; meeting_ids: string[] | null },
    signal?: AbortSignal,
  ): AsyncGenerator<SseEvent> {
    const res = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* ignore */
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : "Request failed");
    }
    yield* readSse(res);
  },
};
