const GROUPED = /\[((?:S\d+\s*,\s*)+S\d+)\]/g;
const SINGLE = /\[(S\d+)\](?!\()/g;

/**
 * Turn citation keys into markdown links that the renderer swaps for citation chips:
 *   "Added two sites [S3][S4]." -> "Added two sites [S3](#cite-S3)[S4](#cite-S4)."
 * Grouped keys "[S1, S2]" are split first. Keys followed by "(" are left alone
 * (already links). Hash URLs survive react-markdown's URL sanitiser.
 */
export function linkCitations(text: string): string {
  return text
    .replace(GROUPED, (_, keys: string) =>
      keys
        .split(",")
        .map((k) => `[${k.trim()}]`)
        .join(""),
    )
    .replace(SINGLE, (_, key: string) => `[${key}](#cite-${key})`);
}

export function citationKeyFromHref(href: string | undefined): string | null {
  const m = href?.match(/^#cite-(S\d+)$/);
  return m ? m[1] : null;
}

/** While streaming, hide a half-typed trailing key like "[S1" so it doesn't flicker. */
export function trimPartialCitation(text: string): string {
  return text.replace(/\[S?\d*$/, "");
}
