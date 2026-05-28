import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useEventTopologyPagination } from "@/hooks/useEventTopologyPagination";
import { useTrafficLogsPagination } from "@/hooks/useTrafficLogsPagination";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Tag, Spin, Pagination } from "antd";
import { LearnerInternalTopologyPanel } from "@/components/LearnerInternalTopologyPanel";
import { SectionTitle } from "@/components/SectionTitle";
import { TrafficLogsTable } from "@/components/TrafficLogsTable";
import { DetailMetricValue } from "@/components/DetailMetricValue";
import OverflowTooltip from "@/components/OverflowTooltip";
import { RiskService, type IpSummary } from "@/api/services/RiskService";
import {
  createPaginationProps,
  createTablePagination,
  DEFAULT_EVENT_TOPOLOGY_PAGE_SIZE,
  DEFAULT_TABLE_PAGE_SIZE,
  EVENT_TOPOLOGY_PAGE_SIZE_OPTIONS,
} from "@/constants/tablePagination";
import taskDetailIcon from "@/assets/蒙版组 152.png";
/** IP 详情页 */
export default function IpDetailPlaceholder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const ip = searchParams.get("ip")?.trim() ?? "";

  const { loading, run } = useApi({
    successMessage: false,
    initialLoading: true,
  });
  const [summary, setSummary] = useState<IpSummary | null>(null);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "done">("loading");
  const [eventPage, setEventPage] = useState(1);
  const [eventPageSize, setEventPageSize] = useState(
    DEFAULT_EVENT_TOPOLOGY_PAGE_SIZE,
  );
  const [trafficLogPage, setTrafficLogPage] = useState(1);
  const [trafficLogPageSize, setTrafficLogPageSize] = useState(
    DEFAULT_TABLE_PAGE_SIZE,
  );
  const requestSeqRef = useRef(0);

  const fetchIpEventsTopologyPage = useCallback(
    async (offset: number, limit: number) =>
      RiskService.getIpEventsTopology(ip, { limit, offset }),
    [ip],
  );

  const {
    eventTopology: ipRiskEventTopology,
    loading: riskEventsLoading,
    total: ipRiskEventTopologyTotal,
  } = useEventTopologyPagination(
    loadState === "done" && !!summary && !!ip,
    eventPage,
    eventPageSize,
    fetchIpEventsTopologyPage,
  );

  const trafficLogsEnabled = loadState === "done" && !!summary && !!ip;
  const fetchTrafficLogs = useCallback(
    (offset: number, limit: number) =>
      RiskService.getIpTrafficLogs(ip, limit, offset),
    [ip],
  );
  const {
    trafficLogs,
    loading: trafficLogsLoading,
    total: trafficLogsTotal,
  } = useTrafficLogsPagination(
    trafficLogsEnabled,
    trafficLogPage,
    trafficLogPageSize,
    fetchTrafficLogs,
  );

  useEffect(() => {
    if (!ip) {
      setSummary(null);
      setLoadState("done");
      return;
    }

    const requestSeq = ++requestSeqRef.current;
    setLoadState("loading");
    setSummary(null);

    const load = async () => {
      const summaryData = await run(async () => RiskService.getIpSummary(ip));
      if (requestSeq !== requestSeqRef.current) return;

      if (!summaryData) {
        setSummary(null);
        setLoadState("done");
        return;
      }

      setSummary(summaryData);
      setLoadState("done");
    };

    void load();
  }, [ip, run]);

  useEffect(() => {
    setEventPage(1);
    setEventPageSize(DEFAULT_EVENT_TOPOLOGY_PAGE_SIZE);
    setTrafficLogPage(1);
    setTrafficLogPageSize(DEFAULT_TABLE_PAGE_SIZE);
  }, [ip]);

  const handleViewRisk = (riskId: number) => {
    navigate({
      pathname: "/risk/detail",
      search: `?id=${riskId}`,
    });
  };

  const pageLoading = loading || loadState === "loading";

  return (
    <div className="h-[calc(100vh-100px)] w-full rounded-[8px]">
      <Spin spinning={pageLoading}>
        <div className="rounded-[8px] bg-[#f6faff] px-[12px] py-[7px]">
          <div className="flex items-start gap-[12px]">
            <img
              src={taskDetailIcon}
              alt=""
              className="h-[82px] w-[82px] shrink-0 object-contain"
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="mt-[10px] flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="m-0 text-lg font-medium text-[#333]">
                      {summary?.ip ?? "IP 详情"}
                    </h2>
                    {summary ? (
                      <Tag color={summary.isInternal ? "blue" : "orange"} className="!m-0">
                        {summary.isInternal ? "内网 IP" : "外网 IP"}
                      </Tag>
                    ) : null}
                  </div>
                  {(summary?.latestTriggerTime || summary?.description) ? (
                    <div className="flex min-w-0 flex-nowrap items-center gap-1 text-sm leading-[22px] text-[#666]">
                      {summary?.latestTriggerTime ? (
                        <span className="shrink-0 whitespace-nowrap">
                          [{summary.latestTriggerTime}]
                        </span>
                      ) : null}
                      {summary?.description ? (
                        <OverflowTooltip title={summary.description}>
                          <span className="block min-w-0 truncate">
                            {summary.description}
                          </span>
                        </OverflowTooltip>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="flex items-center gap-[12px] mr-[16px]">
                  <div className="flex flex-col items-center">
                    <div className="text-sm text-[#8c8c8c]">风险数</div>
                    {summary ? (
                      <DetailMetricValue count={summary.riskEventCount} />
                    ) : (
                      <div className="w-full text-center text-[28px] font-medium leading-none text-[#333]">
                        -
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="h-[16px] w-full bg-[#fff]" />

        <div className=" w-full rounded-[8px] bg-[#f6faff] p-[12px]">
          {loadState === "done" && !summary ? (
            <p className="text-sm text-[#666]">
              {ip ? `未找到 IP：${ip}` : "未指定 IP"}
            </p>
          ) : summary ? (
            <div className="flex flex-col gap-[12px]">
              <div className="flex flex-col rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <SectionTitle className="mb-[12px] shrink-0">
                  与 IP 关联的风险事件
                </SectionTitle>
                <LearnerInternalTopologyPanel
                  data={ipRiskEventTopology}
                  loading={riskEventsLoading && !ipRiskEventTopology}
                  onRiskClick={handleViewRisk}
                />
                {ipRiskEventTopologyTotal > 0 ? (
                  <div className="flex shrink-0 justify-end pt-3">
                    <Pagination
                      {...createPaginationProps({
                        current: eventPage,
                        pageSize: eventPageSize,
                        total: ipRiskEventTopologyTotal,
                        pageSizeOptions: EVENT_TOPOLOGY_PAGE_SIZE_OPTIONS.map(
                          String,
                        ),
                        onChange: (nextPage, nextPageSize) => {
                          if (nextPageSize !== eventPageSize) {
                            setEventPageSize(nextPageSize);
                            setEventPage(1);
                            return;
                          }
                          setEventPage(nextPage);
                        },
                      })}
                    />
                  </div>
                ) : null}
              </div>

              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <SectionTitle className="mb-[12px]">流量日志</SectionTitle>
                <TrafficLogsTable
                  trafficLogs={trafficLogs}
                  loading={trafficLogsLoading}
                  pagination={createTablePagination({
                    current: trafficLogPage,
                    pageSize: trafficLogPageSize,
                    total: trafficLogsTotal,
                    onChange: (nextPage, nextPageSize) => {
                      setTrafficLogPage(nextPage);
                      setTrafficLogPageSize(nextPageSize);
                    },
                  })}
                />
              </div>
            </div>
          ) : null}
        </div>
      </Spin>
    </div>
  );
}
