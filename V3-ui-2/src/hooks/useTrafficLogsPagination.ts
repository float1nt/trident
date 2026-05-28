import { useCallback, useEffect, useRef, useState } from "react";
import type {
  RiskTrafficLogItem,
  TrafficLogsPageResponse,
} from "@/api/services/RiskService";

type FetchTrafficLogsPage = (
  offset: number,
  limit: number,
) => Promise<TrafficLogsPageResponse>;

export function useTrafficLogsPagination(
  enabled: boolean,
  page: number,
  pageSize: number,
  fetchPage: FetchTrafficLogsPage,
) {
  const [trafficLogs, setTrafficLogs] = useState<RiskTrafficLogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const requestSeqRef = useRef(0);

  const loadPage = useCallback(async () => {
    if (!enabled) return;

    const requestSeq = ++requestSeqRef.current;
    setLoading(true);

    try {
      const offset = (page - 1) * pageSize;
      const result = await fetchPage(offset, pageSize);
      if (requestSeq !== requestSeqRef.current) return;

      setTrafficLogs(result.items);
      setTotal(result.total);
    } finally {
      if (requestSeq === requestSeqRef.current) {
        setLoading(false);
      }
    }
  }, [enabled, fetchPage, page, pageSize]);

  useEffect(() => {
    if (!enabled) {
      setTrafficLogs([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    void loadPage();
  }, [enabled, loadPage]);

  return { trafficLogs, loading, total };
}
