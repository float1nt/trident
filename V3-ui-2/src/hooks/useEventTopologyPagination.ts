import { useCallback, useEffect, useRef, useState } from "react";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";

type FetchEventTopologyPage = (
  offset: number,
  limit: number,
) => Promise<LearnerNetworkTopologyJson>;

export function useEventTopologyPagination(
  enabled: boolean,
  page: number,
  pageSize: number,
  fetchPage: FetchEventTopologyPage,
) {
  const [eventTopology, setEventTopology] =
    useState<LearnerNetworkTopologyJson | null>(null);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [riskEventTotal, setRiskEventTotal] = useState(0);
  const requestSeqRef = useRef(0);

  const loadPage = useCallback(async () => {
    if (!enabled) return;

    const requestSeq = ++requestSeqRef.current;
    setLoading(true);

    try {
      const offset = (page - 1) * pageSize;
      const result = await fetchPage(offset, pageSize);
      if (requestSeq !== requestSeqRef.current) return;

      const resolvedTotal = result.total ?? result.learners.length;
      const resolvedRiskEventTotal = result.risk_event_total ?? 0;
      setEventTopology({
        ...result,
        total: resolvedTotal,
        risk_event_total: resolvedRiskEventTotal,
      });
      setTotal(resolvedTotal);
      setRiskEventTotal(resolvedRiskEventTotal);
    } finally {
      if (requestSeq !== requestSeqRef.current) return;
      setLoading(false);
    }
  }, [enabled, fetchPage, page, pageSize]);

  useEffect(() => {
    if (!enabled) {
      setEventTopology(null);
      setTotal(0);
      setRiskEventTotal(0);
      setLoading(false);
      return;
    }
    void loadPage();
  }, [enabled, loadPage]);

  return {
    eventTopology,
    loading,
    total,
    eventTopologyTotal: eventTopology?.total ?? total,
    eventTopologyRiskEventTotal:
      eventTopology?.risk_event_total ?? riskEventTotal,
  };
}
