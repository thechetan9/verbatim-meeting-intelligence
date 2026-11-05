import { describe, expect, it } from "vitest";

import { groupByOwner, itemKey, loadDone, saveDone } from "./actions";
import { citationKeyFromHref, linkCitations, trimPartialCitation } from "./citations";
import { formatTs, initials, speakerHue } from "./format";
import { actionsFor, speakerStats } from "./speakers";
import { meetingNotesMarkdown, notesFilename } from "./notes";
import { SseParser } from "./sse";
import { loadChat, saveChat } from "./storage";

describe("SseParser", () => {
  it("parses events split across arbitrary chunk boundaries", () => {
    const p = new SseParser();
    const wire = 'event: delta\ndata: {"text":"Hel"}\n\nevent: delta\ndata: {"text":"lo"}\n\nevent: done\ndata: {}\n\n';
    const events = [...wire].flatMap((ch) => p.push(ch)); // one character at a time
    expect(events.map((e) => e.event)).toEqual(["delta", "delta", "done"]);
    expect(events[0].data).toEqual({ text: "Hel" });
  });

  it("ignores comments and keeps non-JSON data as text", () => {
    const p = new SseParser();
    expect(p.push(": keep-alive\n\nevent: x\ndata: plain\n\n")).toEqual([{ event: "x", data: "plain" }]);
  });
});

describe("citations", () => {
  it("turns keys into hash links, including grouped keys", () => {
    expect(linkCitations("Two sites [S3]. Budget [S1, S2].")).toBe(
      "Two sites [S3](#cite-S3). Budget [S1](#cite-S1)[S2](#cite-S2).",
    );
  });
  it("is idempotent for already-linked keys", () => {
    const once = linkCitations("x [S1]");
    expect(linkCitations(once)).toBe(once);
  });
  it("extracts keys from hrefs", () => {
    expect(citationKeyFromHref("#cite-S12")).toBe("S12");
    expect(citationKeyFromHref("https://example.com")).toBeNull();
  });
  it("hides a half-streamed key", () => {
    expect(trimPartialCitation("We agreed [S")).toBe("We agreed ");
    expect(trimPartialCitation("We agreed [S1]")).toBe("We agreed [S1]");
  });
});

describe("format", () => {
  it("formats timestamps", () => {
    expect(formatTs(83)).toBe("01:23");
    expect(formatTs(3723)).toBe("01:02:03");
  });
  it("gives stable speaker colours and initials", () => {
    expect(speakerHue("Priya Nair")).toBe(speakerHue("Priya Nair"));
    expect(initials("Dr. Anita Rao")).toBe("AR");
  });
});

describe("speakers", () => {
  const utts = [
    { idx: 0, speaker: "Dr. Anita Rao", start_s: 0, end_s: 5, text: "one two three four" },
    { idx: 1, speaker: "Marcus Lee", start_s: 5, end_s: 9, text: "five six" },
    { idx: 2, speaker: "Dr. Anita Rao", start_s: 9, end_s: 12, text: "seven eight" },
  ];
  it("computes turns and share of words, busiest speaker first", () => {
    const stats = speakerStats(utts);
    expect(stats.map((s) => [s.name, s.turns, s.words])).toEqual([
      ["Dr. Anita Rao", 2, 6],
      ["Marcus Lee", 1, 2],
    ]);
    expect(stats[0].share).toBeCloseTo(0.75);
  });
  it("matches action-item owners loosely (titles, first names)", () => {
    const items = [
      { task: "a", owner: "Anita Rao", due: null, evidence: [0] },
      { task: "b", owner: "Marcus", due: null, evidence: [1] },
      { task: "c", owner: null, due: null, evidence: [2] },
    ];
    expect(actionsFor("Dr. Anita Rao", items).map((a) => a.task)).toEqual(["a"]);
    expect(actionsFor("Marcus Lee", items).map((a) => a.task)).toEqual(["b"]);
  });
});

describe("chat storage", () => {
  function memoryStore() {
    const data = new Map<string, string>();
    return {
      getItem: (k: string) => data.get(k) ?? null,
      setItem: (k: string, v: string) => void data.set(k, v),
      removeItem: (k: string) => void data.delete(k),
    };
  }
  it("round-trips messages and marks interrupted streams", () => {
    const store = memoryStore();
    saveChat(
      [
        { id: "1", role: "user", content: "q" },
        { id: "2", role: "assistant", content: "half", status: "streaming" },
      ],
      store,
    );
    const loaded = loadChat(store);
    expect(loaded).toHaveLength(2);
    expect(loaded[1].status).toBe("error");
  });
  it("survives corrupt or missing storage", () => {
    const store = memoryStore();
    store.setItem("verbatim.chat.v1", "{not json");
    expect(loadChat(store)).toEqual([]);
    expect(loadChat(null)).toEqual([]);
    expect(() => saveChat([{ id: "1", role: "user", content: "q" }], null)).not.toThrow();
  });
});

describe("meeting notes export", () => {
  const meeting = {
    id: "m1", title: "Sprint 14 Planning", date: "2026-10-13", source_filename: "x.vtt", format: "vtt",
    duration_s: 450, speakers: ["Sofia Alvarez", "Daniel Kim"], utterance_count: 2,
    created_at: "", insights_status: "ready" as const, insights_error: null,
  };
  const insights = {
    summary: "Chose SNS.",
    decisions: [{ text: "Use AWS SNS", decided_by: "Sofia Alvarez", evidence: [1] }],
    action_items: [{ task: "Build SNS service", owner: "Daniel Kim", due: "October 24", evidence: [1] }],
    open_questions: [],
    topics: [],
  };
  const utts = [{ idx: 1, speaker: "Sofia Alvarez", start_s: 129, end_s: 140, text: "SNS it is." }];
  it("renders decisions, checkbox action items and timestamps", () => {
    const md = meetingNotesMarkdown(meeting, insights, utts);
    expect(md).toContain("# Sprint 14 Planning");
    expect(md).toContain("- Use AWS SNS (decided by Sofia Alvarez) _(02:09)_");
    expect(md).toContain("- [ ] Build SNS service: **Daniel Kim**, due October 24 _(02:09)_");
    expect(md).toContain("## Open questions\n\n- None recorded");
  });
  it("builds a safe filename", () => {
    expect(notesFilename({ ...meeting, title: "Adherence App — Sprint 14 / Planning!" })).toBe(
      "2026-10-13_adherence-app-sprint-14-planning-notes.md",
    );
  });
});

describe("action items", () => {
  const item = (owner: string | null, task: string, meeting_id = "m1") => ({
    meeting_id, meeting_title: "T", meeting_date: null, owner, task, due: null, evidence: [0], start_s: 0,
  });
  it("groups by owner, most open items first, unassigned last", () => {
    const items = [item("Bob", "a"), item(null, "b"), item("Alice", "c"), item("Alice", "d")];
    const groups = groupByOwner(items, new Set());
    expect(groups.map((g) => g.owner)).toEqual(["Alice", "Bob", "Unassigned"]);
    const doneAlice = new Set([itemKey(items[2]), itemKey(items[3])]);
    expect(groupByOwner(items, doneAlice).map((g) => g.owner)).toEqual(["Bob", "Alice", "Unassigned"]);
  });
  it("persists done ticks and survives bad storage", () => {
    const data = new Map<string, string>();
    const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
    saveDone(new Set(["m1::a"]), store);
    expect([...loadDone(store)]).toEqual(["m1::a"]);
    data.set("verbatim.actions.done.v1", "oops");
    expect(loadDone(store).size).toBe(0);
  });
});
