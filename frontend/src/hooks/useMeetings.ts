"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";

/** Meeting list that keeps polling while any meeting's insights are still being extracted. */
export function useMeetings() {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    try {
      const list = await api.listMeetings();
      setMeetings(list);
      setError(null);
      if (list.some((m) => m.insights_status === "pending")) {
        timer.current = setTimeout(refresh, 2000);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the API");
      timer.current = setTimeout(refresh, 5000);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [refresh]);

  return { meetings, loading, error, refresh };
}
