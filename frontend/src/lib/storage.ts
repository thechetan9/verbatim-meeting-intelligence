import type { ChatMessage } from "./types";

/**
 * Chat history in localStorage so a refresh doesn't lose the conversation.
 * Meetings themselves live in the backend database; the chat is the only client-side state
 * worth keeping (the API is stateless by design). Every access is guarded: storage can be
 * full, disabled (private mode) or contain data from an older version.
 */
const KEY = "verbatim.chat.v1";
const MAX_MESSAGES = 60;

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadChat(store: Store | null = browserStore()): ChatMessage[] {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((m): m is ChatMessage => !!m && typeof m === "object" && "id" in m && "role" in m)
      .map((m) =>
        // A message that was still streaming when the page closed can never finish.
        m.status === "streaming" ? { ...m, status: "error", error: "Interrupted by a page reload." } : m,
      );
  } catch {
    return [];
  }
}

export function saveChat(messages: ChatMessage[], store: Store | null = browserStore()): void {
  try {
    if (messages.length === 0) store?.removeItem(KEY);
    else store?.setItem(KEY, JSON.stringify(messages.slice(-MAX_MESSAGES)));
  } catch {
    /* quota exceeded or storage disabled: the chat still works, it just won't survive a reload */
  }
}
