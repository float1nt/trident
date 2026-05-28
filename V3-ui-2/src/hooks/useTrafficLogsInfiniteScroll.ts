import { useCallback, useEffect, useRef, useState } from "react";
import type { RiskTrafficLogItem } from "@/api/services/RiskService";
import { normalizeApiList } from "@/utils/normalizeApiList";

export const TRAFFIC_LOG_PAGE_SIZE = 10;
const SCROLL_LOAD_THRESHOLD_PX = 8;

type FetchTrafficLogs = (
  offset: number,
  limit: number,
) => Promise<RiskTrafficLogItem[]>;

export function useTrafficLogsInfiniteScroll(
  enabled: boolean,
  fetchPage: FetchTrafficLogs,
) {
  const [trafficLogs, setTrafficLogs] = useState<RiskTrafficLogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const tableWrapperRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(true);
  const offsetRef = useRef(0);
  const requestSeqRef = useRef(0);
  const fetchPageRef = useRef(fetchPage);

  fetchPageRef.current = fetchPage;

  const loadPage = useCallback(
    async (reset: boolean) => {
      if (!enabled || loadingRef.current) return;
      if (!reset && !hasMoreRef.current) return;

      const requestSeq = ++requestSeqRef.current;
      loadingRef.current = true;
      setLoading(true);

      try {
        const offset = reset ? 0 : offsetRef.current;
        const rawItems = await fetchPageRef.current(offset, TRAFFIC_LOG_PAGE_SIZE);
        const items = normalizeApiList<RiskTrafficLogItem>(rawItems);
        if (requestSeq !== requestSeqRef.current) return;

        setTrafficLogs((prev) => (reset ? items : [...prev, ...items]));
        offsetRef.current = offset + items.length;
        const nextHasMore = items.length >= TRAFFIC_LOG_PAGE_SIZE;
        hasMoreRef.current = nextHasMore;
        setHasMore(nextHasMore);
      } finally {
        if (requestSeq === requestSeqRef.current) {
          loadingRef.current = false;
          setLoading(false);
        }
      }
    },
    [enabled],
  );

  useEffect(() => {
    requestSeqRef.current += 1;
    offsetRef.current = 0;
    hasMoreRef.current = true;
    loadingRef.current = false;
    setTrafficLogs([]);
    setHasMore(true);
    setLoading(false);

    if (!enabled) return;
    void loadPage(true);
  }, [enabled, fetchPage, loadPage]);

  useEffect(() => {
    if (!enabled) return;

    let cleanup: (() => void) | undefined;
    const timer = window.setTimeout(() => {
      const body = tableWrapperRef.current?.querySelector<HTMLDivElement>(
        ".ant-table-body",
      );
      if (!body) return;

      const onScroll = () => {
        const { scrollTop, clientHeight, scrollHeight } = body;
        if (
          scrollTop + clientHeight >=
          scrollHeight - SCROLL_LOAD_THRESHOLD_PX
        ) {
          void loadPage(false);
        }
      };

      body.addEventListener("scroll", onScroll, { passive: true });
      cleanup = () => body.removeEventListener("scroll", onScroll);
    }, 0);

    return () => {
      window.clearTimeout(timer);
      cleanup?.();
    };
  }, [enabled, loadPage, trafficLogs.length]);

  return {
    trafficLogs,
    loading,
    hasMore,
    tableWrapperRef,
  };
}
