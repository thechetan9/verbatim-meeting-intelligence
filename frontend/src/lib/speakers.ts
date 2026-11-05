import type { ActionItem, Utterance } from "./types";

export interface SpeakerStat {
  name: string;
  turns: number;
  words: number;
  share: number; // fraction of all words spoken in the meeting, 0..1
}

/** Who spoke how much. Word count is a steadier proxy for talk time than timestamps. */
export function speakerStats(utterances: Utterance[]): SpeakerStat[] {
  const byName = new Map<string, { turns: number; words: number }>();
  let total = 0;
  for (const u of utterances) {
    const words = u.text.split(/\s+/).filter(Boolean).length;
    const s = byName.get(u.speaker) ?? { turns: 0, words: 0 };
    s.turns += 1;
    s.words += words;
    byName.set(u.speaker, s);
    total += words;
  }
  return [...byName.entries()]
    .map(([name, s]) => ({ name, ...s, share: total ? s.words / total : 0 }))
    .sort((a, b) => b.words - a.words);
}

/** Action items owned by a person. Owners are names as the model wrote them, so match loosely. */
export function actionsFor(name: string, items: ActionItem[]): ActionItem[] {
  const target = normaliseName(name);
  return items.filter((a) => {
    if (!a.owner) return false;
    const owner = normaliseName(a.owner);
    return owner === target || target.includes(owner) || owner.includes(target);
  });
}

function normaliseName(name: string): string {
  return name
    .toLowerCase()
    .replace(/^(dr|mr|ms|mrs|prof)\.?\s+/, "")
    .trim();
}
