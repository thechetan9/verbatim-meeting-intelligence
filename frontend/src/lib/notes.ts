import { formatDuration, formatTs } from "./format";
import type { Meeting, MeetingInsights, Utterance } from "./types";

/** Meeting notes as Markdown: paste into email, Slack, Confluence or a ticket. */
export function meetingNotesMarkdown(meeting: Meeting, insights: MeetingInsights, utterances: Utterance[]): string {
  const at = new Map(utterances.map((u) => [u.idx, formatTs(u.start_s)]));
  const when = (idx: number[]) => {
    const stamps = idx.map((i) => at.get(i)).filter(Boolean);
    return stamps.length ? ` _(${stamps.join(", ")})_` : "";
  };

  const lines = [
    `# ${meeting.title}`,
    "",
    [meeting.date, formatDuration(meeting.duration_s), `Participants: ${meeting.speakers.join(", ")}`]
      .filter(Boolean)
      .join(" · "),
    "",
    "## Summary",
    "",
    insights.summary,
    "",
    "## Decisions",
    "",
    ...(insights.decisions.length
      ? insights.decisions.map((d) => `- ${d.text}${d.decided_by ? ` (decided by ${d.decided_by})` : ""}${when(d.evidence)}`)
      : ["- None recorded"]),
    "",
    "## Action items",
    "",
    ...(insights.action_items.length
      ? insights.action_items.map(
          (a) => `- [ ] ${a.task}: **${a.owner ?? "Unassigned"}**${a.due ? `, due ${a.due}` : ""}${when(a.evidence)}`,
        )
      : ["- None recorded"]),
    "",
    "## Open questions",
    "",
    ...(insights.open_questions.length
      ? insights.open_questions.map((q) => `- ${q.text}${when(q.evidence)}`)
      : ["- None recorded"]),
    "",
    "_Timestamps point to the moment in the meeting recording/transcript._",
    "",
  ];
  return lines.join("\n");
}

export function notesFilename(meeting: Meeting): string {
  const slug = meeting.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
  return `${meeting.date ? `${meeting.date}_` : ""}${slug || "meeting"}-notes.md`;
}
