import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useTrafficLogsPagination } from "@/hooks/useTrafficLogsPagination";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Table, Spin } from "antd";
import type { ColumnsType } from "antd/es/table";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import type { DatasetNetworkTopologyJson } from "@/components/NetworkTopologyPanel";
import { SectionTitle } from "@/components/SectionTitle";
import { TrafficLogsTable } from "@/components/TrafficLogsTable";
import { DetailMetricValue } from "@/components/DetailMetricValue";
import OverflowTooltip from "@/components/OverflowTooltip";
import {
  RiskService,
  type RiskDetail,
  type RiskIpListItem,
} from "@/api/services/RiskService";
import {
  createTablePagination,
  DEFAULT_TABLE_PAGE_SIZE,
} from "@/constants/tablePagination";
import { normalizeApiList } from "@/utils/normalizeApiList";
import taskDetailIcon from "@/assets/蒙版组 152.png";

const CHART_HEIGHT = 320;
const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;
const LIST_MAX_HEIGHT = "300px";

function buildRiskIpColumns(
  currentPage: number,
  pageSize: number,
  onIpClick: (ip: string) => void,
): ColumnsType<RiskIpListItem> {
  return [
    {
      title: "序号",
      key: "index",
      width: 72,
      render: (_value, _record, index) =>
        (currentPage - 1) * pageSize + index + 1,
    },
    {
      title: "IP",
      dataIndex: "ip",
      key: "ip",
      render: (ip: string) => (
        <Button className="!h-auto !p-0" variant="link" color="primary" onClick={() => onIpClick(ip)}>
          {ip}
        </Button>
      ),
    },
    {
      title: "风险触发次数",
      dataIndex: "triggerCount",
      key: "triggerCount",
      width: 120,
    },
  ];
}

/** 风险详情页 */
export default function RiskDetailPlaceholder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const riskId = searchParams.get("id");
  const numericId = riskId ? Number(riskId) : NaN;

  const { loading, run } = useApi({
    successMessage: false,
    initialLoading: true,
  });
  const [risk, setRisk] = useState<RiskDetail | null>(null);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "done">("loading");
  const [networkTopology, setNetworkTopology] =
    useState<DatasetNetworkTopologyJson | null>(null);
  const [riskIpList, setRiskIpList] = useState<RiskIpListItem[]>([]);
  const [riskIpPage, setRiskIpPage] = useState(1);
  const [riskIpPageSize, setRiskIpPageSize] = useState(DEFAULT_TABLE_PAGE_SIZE);
  const [trafficLogPage, setTrafficLogPage] = useState(1);
  const [trafficLogPageSize, setTrafficLogPageSize] = useState(
    DEFAULT_TABLE_PAGE_SIZE,
  );
  const requestSeqRef = useRef(0);

  const trafficLogsEnabled =
    loadState === "done" && !!risk && !Number.isNaN(numericId);
  const fetchTrafficLogs = useCallback(
    (offset: number, limit: number) =>
      RiskService.getRiskTrafficLogs(numericId, limit, offset),
    [numericId],
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
    if (!riskId || Number.isNaN(numericId)) {
      setRisk(null);
      setNetworkTopology(null);
      setRiskIpList([]);
      setLoadState("done");
      return;
    }

    const requestSeq = ++requestSeqRef.current;
    setLoadState("loading");
    setRisk(null);
    setNetworkTopology(null);
    setRiskIpList([]);

    const load = async () => {
      const detail = await run(async () => RiskService.getRiskById(numericId));
      if (requestSeq !== requestSeqRef.current) return;

      if (!detail) {
        setRisk(null);
        setLoadState("done");
        return;
      }

      setRisk(detail);
      setLoadState("done");

      void Promise.allSettled([
        RiskService.getRiskNetworkTopology(numericId),
        RiskService.getRiskIps(numericId),
      ]).then((results) => {
        if (requestSeq !== requestSeqRef.current) return;

        const [topologyResult, ipsResult] = results;
        if (topologyResult.status === "fulfilled") {
          setNetworkTopology(topologyResult.value);
        }
        if (ipsResult.status === "fulfilled") {
          setRiskIpList(normalizeApiList<RiskIpListItem>(ipsResult.value));
        }
      });
    };

    void load();
  }, [riskId, numericId, run]);

  useEffect(() => {
    setRiskIpPage(1);
    setRiskIpPageSize(DEFAULT_TABLE_PAGE_SIZE);
    setTrafficLogPage(1);
    setTrafficLogPageSize(DEFAULT_TABLE_PAGE_SIZE);
  }, [riskId]);

  const topologyView = networkTopology?.views.__combined__;
  const pageLoading = loading || loadState === "loading";

  const handleIpDetail = useCallback(
    (ip: string) => {
      navigate({
        pathname: "/risk/ip-detail",
        search: `?ip=${encodeURIComponent(ip)}`,
      });
    },
    [navigate],
  );

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
                  <h2 className="m-0 text-lg font-medium text-[#333]">
                    {risk?.name ?? "风险详情"}
                  </h2>
                  {(risk?.triggerTime || risk?.description) ? (
                    <div className="flex min-w-0 flex-nowrap items-center gap-1 text-sm leading-[22px] text-[#666]">
                      {risk?.triggerTime ? (
                        <span className="shrink-0 whitespace-nowrap">
                          [{risk.triggerTime}]
                        </span>
                      ) : null}
                      {risk?.description ? (
                        <OverflowTooltip title={risk.description}>
                          <span className="block min-w-0 truncate">
                            {risk.description}
                          </span>
                        </OverflowTooltip>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="mr-[16px] flex items-center gap-[24px]">
                  <div className="flex flex-col items-center">
                    <div className="text-sm text-[#8c8c8c]">风险 IP 数</div>
                    <DetailMetricValue count={risk?.riskIpCount ?? 0} />
                  </div>
                  <div className="flex flex-col items-center">
                    <div className="text-sm text-[#8c8c8c]">风险端口数</div>
                    <DetailMetricValue count={risk?.riskPortCount ?? 0} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="h-[16px] w-full bg-[#fff]" />

        <div className=" w-full rounded-[8px] bg-[#f6faff] p-[12px]">
          {loadState === "done" && !risk ? (
            <p className="text-sm text-[#666]">
              {riskId ? `未找到风险 ID：${riskId}` : "未指定风险 ID"}
            </p>
          ) : risk ? (
            <div className="flex flex-col gap-[12px]">
              <div className="flex min-w-0 gap-[12px]">
                <div className="min-w-0 flex-[2] rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                  {topologyView ? (
                    <TopologyChartPane
                      title="流量拓扑图"
                      hostGraph={topologyView.host}
                      endpointGraph={topologyView.endpoint}
                      viewIsBenign={topologyView.is_benign}
                      repulsion={TOPOLOGY_REPULSION}
                      minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                      chartHeight={CHART_HEIGHT}
                    />
                  ) : (
                    <p className="text-sm text-[#8c8c8c]">暂无拓扑数据</p>
                  )}
                </div>

                <div className="flex min-w-0 flex-[1] flex-col rounded-[8px] border border-[#e8eaed] bg-[#fff] px-[16px] pt-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                  <SectionTitle className="mb-[12px] shrink-0">
                    风险 IP 列表
                    {/* （按每个 IP 的风险触发次数从多到少排序） */}
                  </SectionTitle>
                  <Table<RiskIpListItem>
                    className="min-w-0"
                    rowKey="ip"
                    size="middle"
                    bordered
                    columns={buildRiskIpColumns(
                      riskIpPage,
                      riskIpPageSize,
                      handleIpDetail,
                    )}
                    dataSource={riskIpList}
                    pagination={createTablePagination({
                      current: riskIpPage,
                      pageSize: riskIpPageSize,
                      total: riskIpList.length,
                      onChange: (nextPage, nextPageSize) => {
                        setRiskIpPage(nextPage);
                        setRiskIpPageSize(nextPageSize);
                      },
                    })}
                    scroll={{ y: LIST_MAX_HEIGHT }}
                  />
                </div>
              </div>

              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] px-[16px] pt-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
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
