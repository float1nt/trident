import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useTrafficLogsInfiniteScroll } from "@/hooks/useTrafficLogsInfiniteScroll";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Tag, Spin } from "antd";
import { LearnerInternalTopologyPanel } from "@/components/LearnerInternalTopologyPanel";
import { TrafficLogsTable } from "@/components/TrafficLogsTable";
import OverflowTooltip from "@/components/OverflowTooltip";
import { RiskService, type IpSummary } from "@/api/services/RiskService";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";
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
  const [ipRiskEventTopology, setIpRiskEventTopology] =
    useState<LearnerNetworkTopologyJson | null>(null);
  const [riskEventsLoading, setRiskEventsLoading] = useState(false);
  const requestSeqRef = useRef(0);

  const trafficLogsEnabled = loadState === "done" && !!summary && !!ip;
  const fetchTrafficLogs = useCallback(
    (offset: number, limit: number) =>
      RiskService.getIpTrafficLogs(ip, limit, offset),
    [ip],
  );
  const {
    trafficLogs,
    loading: trafficLogsLoading,
    hasMore: trafficLogsHasMore,
    tableWrapperRef,
  } = useTrafficLogsInfiniteScroll(trafficLogsEnabled, fetchTrafficLogs);

  useEffect(() => {
    if (!ip) {
      setSummary(null);
      setIpRiskEventTopology(null);
      setRiskEventsLoading(false);
      setLoadState("done");
      return;
    }

    const requestSeq = ++requestSeqRef.current;
    setLoadState("loading");
    setSummary(null);
    setIpRiskEventTopology(null);
    setRiskEventsLoading(false);

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

      setRiskEventsLoading(true);
      void RiskService.getIpEventsTopology(ip)
        .then((topology) => {
          if (requestSeq !== requestSeqRef.current) return;
          setIpRiskEventTopology(topology);
        })
        .finally(() => {
          if (requestSeq !== requestSeqRef.current) return;
          setRiskEventsLoading(false);
        });
    };

    void load();
  }, [ip, run]);

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
                    {/* {featureTags.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-[8px]">
                        {featureTags.map((tag) => (
                          <Tag key={tag} className="!m-0">
                            {tag}
                          </Tag>
                        ))}
                      </div>
                    ) : null} */}
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
                    <div className="w-full text-center text-[28px] font-medium leading-none text-[#333]">
                      {summary?.riskEventCount ?? "-"}
                    </div>
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
              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                  与 IP 关联的风险事件
                </h3>
                <LearnerInternalTopologyPanel
                  data={ipRiskEventTopology}
                  loading={riskEventsLoading}
                  onRiskClick={handleViewRisk}
                />
              </div>

              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                  流量日志
                </h3>
                <TrafficLogsTable
                  trafficLogs={trafficLogs}
                  loading={trafficLogsLoading}
                  hasMore={trafficLogsHasMore}
                  tableWrapperRef={tableWrapperRef}
                />
              </div>
            </div>
          ) : null}
        </div>
      </Spin>
    </div>
  );
}
