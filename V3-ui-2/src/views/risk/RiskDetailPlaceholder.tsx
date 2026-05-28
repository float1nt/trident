import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useSearchParams } from "react-router-dom";
import { Tag, Table, Spin } from "antd";
import type { ColumnsType } from "antd/es/table";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import type { DatasetNetworkTopologyJson } from "@/components/NetworkTopologyPanel";
import {
  RiskService,
  type RiskDetail,
  type RiskIpListItem,
  type RiskTrafficLogItem,
} from "@/api/services/RiskService";
import taskDetailIcon from "@/assets/蒙版组 152.png";

const CHART_HEIGHT = 320;
const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;
const LIST_PAGE_SIZE = 10;
const LIST_MAX_HEIGHT = "200px";
const NEW_LEARNER_PATTERN = /^NEW[_-]?\d+$/i;

const RISK_NAME_FALLBACK: Record<string, string> = {
  BENIGN_NORMAL: "良性流量",
  UNKNOWN_SUSPECTED: "待观察流量",
  DRDOS_REFLECTION_FAMILY: "反射放大攻击族",
  DDOS_VICTIM: "DDoS受害目标",
  DOS_ATTACKER: "DoS攻击源",
  PORT_SCAN: "端口扫描",
  HOST_SCAN: "主机扫描/横向探测",
  SLOW_DOS_SUSPECTED: "慢速DoS嫌疑",
  WEB_DDOS_SUSPECTED: "Web DDoS嫌疑",
  BRUTE_FORCE_SUSPECTED: "暴力破解嫌疑",
};

const RISK_DESC_FALLBACK: Record<string, string> = {
  良性流量: "当前窗口未命中攻击规则，行为接近正常业务流量。",
  待观察流量: "当前窗口暂未形成明确攻击画像，建议结合后续窗口持续观察。",
};

function normalizeRiskName(name?: string): string {
  const raw = (name ?? "").trim();
  if (!raw) return "待观察流量";
  const upper = raw.toUpperCase();
  if (RISK_NAME_FALLBACK[upper]) return RISK_NAME_FALLBACK[upper];
  if (NEW_LEARNER_PATTERN.test(raw)) return "待观察流量";
  return raw;
}

function normalizeRiskDescription(name: string, description?: string): string {
  const text = (description ?? "").trim();
  if (text && !NEW_LEARNER_PATTERN.test(text)) return text;
  return RISK_DESC_FALLBACK[name] ?? "该学习器尚未命中明确攻击规则，建议结合时间窗口继续观察。";
}

function buildRiskIpColumns(currentPage: number): ColumnsType<RiskIpListItem> {
  return [
    {
      title: "序号",
      key: "index",
      width: 72,
      align: "center",
      render: (_value, _record, index) =>
        (currentPage - 1) * LIST_PAGE_SIZE + index + 1,
    },
    {
      title: "IP",
      dataIndex: "ip",
      key: "ip",
    },
    {
      title: "风险触发次数",
      dataIndex: "triggerCount",
      key: "triggerCount",
      width: 540,
      align: "center",
    },
  ];
}

const trafficLogColumns: ColumnsType<RiskTrafficLogItem> = [
  {
    title: "时间",
    dataIndex: "time",
    key: "time",
    width: 180,
  },
  {
    title: "IP",
    dataIndex: "ip",
    key: "ip",
  },
  {
    title: "协议",
    dataIndex: "protocol",
    key: "protocol",
    width: 340,
  },
];

/** 风险详情页 */
export default function RiskDetailPlaceholder() {
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
  const [trafficLogs, setTrafficLogs] = useState<RiskTrafficLogItem[]>([]);
  const [riskIpPage, setRiskIpPage] = useState(1);
  const [trafficLogPage, setTrafficLogPage] = useState(1);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    if (!riskId || Number.isNaN(numericId)) {
      setRisk(null);
      setNetworkTopology(null);
      setRiskIpList([]);
      setTrafficLogs([]);
      setLoadState("done");
      return;
    }

    const requestSeq = ++requestSeqRef.current;
    setLoadState("loading");
    setRisk(null);
    setNetworkTopology(null);
    setRiskIpList([]);
    setTrafficLogs([]);

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
        RiskService.getRiskTrafficLogs(numericId),
      ]).then((results) => {
        if (requestSeq !== requestSeqRef.current) return;

        const [topologyResult, ipsResult, logsResult] = results;
        if (topologyResult.status === "fulfilled") {
          setNetworkTopology(topologyResult.value);
        }
        if (ipsResult.status === "fulfilled") {
          setRiskIpList(ipsResult.value);
        }
        if (logsResult.status === "fulfilled") {
          setTrafficLogs(logsResult.value);
        }
      });
    };

    void load();
  }, [riskId, numericId, run]);

  useEffect(() => {
    setRiskIpPage(1);
    setTrafficLogPage(1);
  }, [riskId]);

  const topologyView = networkTopology?.views.__combined__;
  const pageLoading = loading || loadState === "loading";

  const featureTags = risk?.features
    ? risk.features.split("、").map((item) => item.trim()).filter(Boolean)
    : [];
  const displayName = normalizeRiskName(risk?.name);
  const displayDescription = normalizeRiskDescription(displayName, risk?.description);

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
              <div className="mt-[10px] flex items-center justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                  <h2 className="m-0 shrink-0 text-lg font-medium text-[#333]">
                    {risk ? displayName : "风险详情"}
                  </h2>
                  {featureTags.length > 0 ? (
                    <div className="flex flex-wrap items-center gap-[8px]">
                      {featureTags.map((tag) => (
                        <Tag key={tag} className="!m-0">
                          {tag}
                        </Tag>
                      ))}
                    </div>
                  ) : null}
                  {risk?.triggerTime ? (
                    <span className="shrink-0 whitespace-nowrap text-sm text-[#666]">
                      [{risk.triggerTime}]
                    </span>
                  ) : null}
                  {risk?.description ? (
                    <p className="mb-0 mt-0 text-sm leading-[22px] text-[#666]">
                      {displayDescription}
                    </p>
                  ) : null}
                </div>
                <div className="flex items-center gap-[12px] mr-[16px]">
                  <div className="flex flex-col items-center">
                    <div className="text-sm text-[#8c8c8c]">风险 IP 数</div>
                    <div className="w-full text-center text-[28px] font-medium leading-none text-[#333]">
                      {risk?.riskIpCount ?? 0}
                    </div>
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
              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                  网络拓扑（IP / 端口）
                </h3>
                {topologyView ? (
                  <TopologyChartPane
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

              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                  风险 IP 列表（按每个 IP 的风险触发次数从多到少排序）
                </h3>
                <Table<RiskIpListItem>
                  rowKey="ip"
                  size="middle"
                  bordered
                  columns={buildRiskIpColumns(riskIpPage)}
                  dataSource={riskIpList}
                  pagination={{
                    current: riskIpPage,
                    pageSize: LIST_PAGE_SIZE,
                    total: riskIpList.length,
                    showTotal: (total) => `共 ${total} 条`,
                    onChange: setRiskIpPage,
                  }}
                  scroll={{ y: LIST_MAX_HEIGHT }}
                />
              </div>

              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                  流量日志
                </h3>
                <Table<RiskTrafficLogItem>
                  rowKey="id"
                  size="middle"
                  bordered
                  columns={trafficLogColumns}
                  dataSource={trafficLogs}
                  pagination={{
                    current: trafficLogPage,
                    pageSize: LIST_PAGE_SIZE,
                    total: trafficLogs.length,
                    showTotal: (total) => `共 ${total} 条`,
                    onChange: setTrafficLogPage,
                  }}
                  scroll={{ y: LIST_MAX_HEIGHT }}
                />
              </div>
            </div>
          ) : null}
        </div>
      </Spin>
    </div>
  );
}
