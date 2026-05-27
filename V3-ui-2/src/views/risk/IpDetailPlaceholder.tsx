import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Tag, Table, Button, Spin } from "antd";
import type { ColumnsType } from "antd/es/table";
import { LearnerInternalTopologyPanel } from "@/components/LearnerInternalTopologyPanel";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import {
  RiskService,
  type IpRiskEventItem,
  type IpSummary,
  type RiskTrafficLogItem,
} from "@/api/services/RiskService";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";
import taskDetailIcon from "@/assets/蒙版组 152.png";

const LIST_PAGE_SIZE = 10;
const LIST_MAX_HEIGHT = "200px";

function buildIpRiskEventColumns(
  currentPage: number,
  onViewRisk: (riskId: number) => void,
): ColumnsType<IpRiskEventItem> {
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
      title: "风险名称",
      dataIndex: "name",
      key: "name",
      width: 180,
      render: (text: string) => (
        <TextWithTooltip text={text || ""} className="font-medium" />
      ),
    },
    {
      title: "触发时间",
      dataIndex: "triggerTime",
      key: "triggerTime",
      width: 170,
    },
    {
      title: "风险说明",
      dataIndex: "description",
      key: "description",
      render: (text: string) => (
        <TextWithTooltip text={text || ""} emptyText="-" className="text-gray-600" />
      ),
    },
    {
      title: "风险特征",
      dataIndex: "features",
      key: "features",
      width: 220,
      render: (text: string) => (
        <TextWithTooltip text={text || ""} emptyText="-" />
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      align: "center",
      render: (_value, record) =>
        record.id > 0 ? (
          <Button type="link" size="small" onClick={() => onViewRisk(record.id)}>
            查看
          </Button>
        ) : (
          <span className="text-[#8c8c8c]">-</span>
        ),
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
  const [riskEvents, setRiskEvents] = useState<IpRiskEventItem[]>([]);
  const [trafficLogs, setTrafficLogs] = useState<RiskTrafficLogItem[]>([]);
  const [riskEventPage, setRiskEventPage] = useState(1);
  const [trafficLogPage, setTrafficLogPage] = useState(1);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    if (!ip) {
      setSummary(null);
      setIpRiskEventTopology(null);
      setRiskEvents([]);
      setTrafficLogs([]);
      setLoadState("done");
      return;
    }

    const requestSeq = ++requestSeqRef.current;
    setLoadState("loading");
    setSummary(null);
    setIpRiskEventTopology(null);
    setRiskEvents([]);
    setTrafficLogs([]);

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

      void Promise.allSettled([
        RiskService.getIpEventsTopology(ip),
        RiskService.getIpEvents(ip),
        RiskService.getIpTrafficLogs(ip),
      ]).then((results) => {
        if (requestSeq !== requestSeqRef.current) return;

        const [topologyResult, eventsResult, logsResult] = results;
        if (topologyResult.status === "fulfilled") {
          setIpRiskEventTopology(topologyResult.value);
        }
        if (eventsResult.status === "fulfilled") {
          setRiskEvents(eventsResult.value);
        }
        if (logsResult.status === "fulfilled") {
          setTrafficLogs(logsResult.value);
        }
      });
    };

    void load();
  }, [ip, run]);

  useEffect(() => {
    setRiskEventPage(1);
    setTrafficLogPage(1);
  }, [ip]);

  const featureTags = summary?.features
    ? summary.features.split("、").map((item) => item.trim()).filter(Boolean)
    : [];

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
              <div className="mt-[10px] flex items-center justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                  <h2 className="m-0 shrink-0 text-lg font-medium text-[#333]">
                    {summary?.ip ?? "IP 详情"}
                  </h2>
                  {summary ? (
                    <Tag color={summary.isInternal ? "blue" : "orange"} className="!m-0">
                      {summary.isInternal ? "内网 IP" : "外网 IP"}
                    </Tag>
                  ) : null}
                  {featureTags.length > 0 ? (
                    <div className="flex flex-wrap items-center gap-[8px]">
                      {featureTags.map((tag) => (
                        <Tag key={tag} className="!m-0">
                          {tag}
                        </Tag>
                      ))}
                    </div>
                  ) : null}
                  {summary?.description ? (
                    <p className="mb-0 mt-0 w-full text-sm leading-[22px] text-[#666]">
                      {summary.description}
                    </p>
                  ) : null}
                </div>
                <div className="flex items-center gap-[12px]">
                  <div className="flex flex-col items-center">
                    <div className="text-sm text-[#8c8c8c]">风险数</div>
                    <div className="w-full text-center text-[28px] font-medium leading-none text-[#333]">
                      {summary?.riskEventCount ?? "-"}
                    </div>
                  </div>

                  {summary?.latestTriggerTime ? (
                    <span className="shrink-0 whitespace-nowrap text-sm text-[#666]">
                      {summary.latestTriggerTime}
                    </span>
                  ) : null}
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
                  onRiskClick={handleViewRisk}
                />
              </div>

              <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
                <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                  与IP关联的风险事件列表（按触发时间从近到远排序）
                </h3>
                <Table<IpRiskEventItem>
                  rowKey="id"
                  size="middle"
                  bordered
                  columns={buildIpRiskEventColumns(riskEventPage, handleViewRisk)}
                  dataSource={riskEvents}
                  pagination={{
                    current: riskEventPage,
                    pageSize: LIST_PAGE_SIZE,
                    total: riskEvents.length,
                    showTotal: (total) => `共 ${total} 条`,
                    onChange: setRiskEventPage,
                  }}
                  scroll={{ x: 1100, y: LIST_MAX_HEIGHT }}
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
