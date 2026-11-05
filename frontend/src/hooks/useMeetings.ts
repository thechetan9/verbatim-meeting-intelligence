"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";

/** Meeting list that keeps polling while any meeting's insights are still being extracted. */
export function useMeetings() {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState(0); // bumps after every load, so polling re-arms

  // State is only updated in promise callbacks, never synchronously inside an effect.
  const refresh = useCallback(
    () =>
      api
        .listMeetings()
        .then(
          (list) => {
            setMeetings(list);
            setError(null);
          },
          (e: unknown) => setError(e instanceof Error ? e.message : "Could not reach the API"),
        )
        .finally(() => {
          setLoading(false);
          setLoadedAt(Date.now());
        }),
    [],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll every 2 s while insights are pending; retry every 5 s while the API is unreachable.
  const pending = meetings.some((m) => m.insights_status === "pending");
  useEffect(() => {
    if (!loadedAt || (!pending && !error)) return;
    const timer = setTimeout(() => void refresh(), error ? 5000 : 2000);
    return () => clearTimeout(timer);
  }, [loadedAt, pending, error, refresh]);

  return { meetings, loading, error, refresh };
}
