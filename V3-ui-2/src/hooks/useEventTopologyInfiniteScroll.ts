import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { EVENT_TOPOLOGY_PAGE_SIZE } from "@/api/services/RiskService";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";

const SCROLL_LOAD_THRESHOLD_PX = 48;

type FetchEventTopologyPage = (
  offset: number,
  limit: number,
) => Promise<LearnerNetworkTopologyJson>;

function mergeEventTopology(
  prev: LearnerNetworkTopologyJson | null,
  next: LearnerNetworkTopologyJson,
  reset: boolean,
): LearnerNetworkTopologyJson {
  if (reset || !prev) {
    return {
      ...next,
      total: next.total ?? next.learners.length,
    };
  }

  const mergedViews = { ...prev.views, ...next.views };
  const mergedLearners = [
    ...prev.learners,
    ...next.learners.filter((name) => !prev.views[name]),
  ];

  return {
    version: next.version ?? prev.version,
    total: next.total ?? prev.total,
    learners: mergedLearners,
    default_learner: prev.default_learner || next.default_learner,
    views: mergedViews,
  };
}

export function useEventTopologyInfiniteScroll(
  enabled: boolean,
  scrollContainerRef: RefObject<HTMLDivElement | null>,
  fetchPage: FetchEventTopologyPage,
) {
  const [eventTopology, setEventTopology] =
    useState<LearnerNetworkTopologyJson | null>(null);
  const [initialLoading, setInitialLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
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
      if (reset) {
        setInitialLoading(true);
      } else {
        setLoadingMore(true);
      }

      try {
        const offset = reset ? 0 : offsetRef.current;
        const page = await fetchPageRef.current(offset, EVENT_TOPOLOGY_PAGE_SIZE);
        if (requestSeq !== requestSeqRef.current) return;

        setEventTopology((prev) => mergeEventTopology(prev, page, reset));
        const loadedCount = page.learners.length;
        offsetRef.current = offset + loadedCount;
        const total = page.total;
        const nextHasMore =
          loadedCount >= EVENT_TOPOLOGY_PAGE_SIZE &&
          (typeof total === "number"
            ? offsetRef.current < total
            : loadedCount > 0);
        hasMoreRef.current = nextHasMore;
        setHasMore(nextHasMore);
      } finally {
        if (requestSeq === requestSeqRef.current) {
          loadingRef.current = false;
          setInitialLoading(false);
          setLoadingMore(false);
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
    setEventTopology(null);
    setHasMore(true);
    setInitialLoading(false);
    setLoadingMore(false);

    if (!enabled) return;
    void loadPage(true);
  }, [enabled, fetchPage, loadPage]);

  const tryLoadNearBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container || !enabled || loadingRef.current || !hasMoreRef.current) {
      return;
    }
    const { scrollTop, clientHeight, scrollHeight } = container;
    if (
      scrollTop + clientHeight >=
      scrollHeight - SCROLL_LOAD_THRESHOLD_PX
    ) {
      void loadPage(false);
    }
  }, [enabled, loadPage, scrollContainerRef]);

  useEffect(() => {
    if (!enabled) return;

    let cleanup: (() => void) | undefined;
    let cancelled = false;

    const attach = () => {
      const container = scrollContainerRef.current;
      if (!container) return false;

      const onScroll = () => {
        tryLoadNearBottom();
      };

      container.addEventListener("scroll", onScroll, { passive: true });
      tryLoadNearBottom();
      cleanup = () => container.removeEventListener("scroll", onScroll);
      return true;
    };

    const timer = window.setTimeout(() => {
      if (cancelled) return;
      if (!attach()) {
        requestAnimationFrame(() => {
          if (!cancelled) attach();
        });
      }
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      cleanup?.();
    };
  }, [
    enabled,
    tryLoadNearBottom,
    scrollContainerRef,
    eventTopology?.learners.length,
  ]);

  return {
    eventTopology,
    initialLoading,
    loadingMore,
    hasMore,
    eventTopologyTotal: eventTopology?.total ?? 0,
  };
}
