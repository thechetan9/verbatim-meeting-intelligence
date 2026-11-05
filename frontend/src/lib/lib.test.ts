import { describe, expect, it } from "vitest";

import { citationKeyFromHref, linkCitations, trimPartialCitation } from "./citations";
import { formatTs, initials, speakerHue } from "./format";
import { SseParser } from "./sse";

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
