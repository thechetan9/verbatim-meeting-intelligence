import type { TrackedActionItem } from "./types";

export interface OwnerGroup {
  owner: string; // "Unassigned" for items without an owner
  items: TrackedActionItem[];
}

export const itemKey = (a: TrackedActionItem) => `${a.meeting_id}::${a.task}`;

/** Group by owner; people with the most open items first, "Unassigned" always last. */
export function groupByOwner(items: TrackedActionItem[], done: Set<string>): OwnerGroup[] {
  const groups = new Map<string, TrackedActionItem[]>();
  for (const a of items) {
    const owner = a.owner ?? "Unassigned";
    groups.set(owner, [...(groups.get(owner) ?? []), a]);
  }
  const open = (g: OwnerGroup) => g.items.filter((a) => !done.has(itemKey(a))).length;
  return [...groups.entries()]
    .map(([owner, list]) => ({ owner, items: list }))
    .sort((a, b) => {
      if (a.owner === "Unassigned") return 1;
      if (b.owner === "Unassigned") return -1;
      return open(b) - open(a) || a.owner.localeCompare(b.owner);
    });
}

// "Done" ticks are a personal to-do view, so they live in the browser (no backend state).
const DONE_KEY = "verbatim.actions.done.v1";
type Store = Pick<Storage, "getItem" | "setItem">;

function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadDone(store: Store | null = browserStore()): Set<string> {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(DONE_KEY) ?? "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

export function saveDone(done: Set<string>, store: Store | null = browserStore()): void {
  try {
    store?.setItem(DONE_KEY, JSON.stringify([...done]));
  } catch {
    /* storage full or disabled: ticks just won't persist */
  }
}
