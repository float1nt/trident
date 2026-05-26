import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Tag, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import {
  getMockRiskById,
  getMockRiskIpList,
  getMockRiskNetworkTopology,
  getMockRiskTrafficLogs,
  type RiskIpListItem,
  type RiskTrafficLogItem,
} from "@/mock/riskTasks";
import taskDetailIcon from "@/assets/蒙版组 152.png";

const CHART_HEIGHT = 320;
const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;
const LIST_PAGE_SIZE = 10;
const LIST_MAX_HEIGHT = '200px';

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

/** 风险详情页（布局对齐 V3-ui-2 IP 视角详情页） */
export default function RiskDetailPlaceholder() {
  const [searchParams] = useSearchParams();
  const riskId = searchParams.get("id");
  const risk = riskId ? getMockRiskById(Number(riskId)) : undefined;
  const [riskIpPage, setRiskIpPage] = useState(1);
  const [trafficLogPage, setTrafficLogPage] = useState(1);

  const networkTopology = useMemo(
    () => (riskId ? getMockRiskNetworkTopology(Number(riskId)) : null),
    [riskId],
  );
  const topologyView = networkTopology?.views.__combined__;

  const riskIpList = useMemo(
    () => (riskId ? getMockRiskIpList(Number(riskId)) : []),
    [riskId],
  );
  const trafficLogs = useMemo(
    () => (riskId ? getMockRiskTrafficLogs(Number(riskId)) : []),
    [riskId],
  );

  useEffect(() => {
    setRiskIpPage(1);
    setTrafficLogPage(1);
  }, [riskId]);

  const featureTags = risk?.features
    ? risk.features.split("、").map((item) => item.trim()).filter(Boolean)
    : [];

  return (
    <div className="h-[calc(100vh-100px)] w-full rounded-[8px]">
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
                  {risk?.name ?? "风险详情"}
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
                {risk?.description ? (
                  <p className="mb-0 mt-0 text-sm leading-[22px] text-[#666]">
                    {risk.description}
                  </p>
                ) : null}
              </div>
              <div className="flex items-center gap-[12px]">
                <div className="flex flex-col items-center">
                  <div className="text-sm text-[#8c8c8c]">风险 IP 数</div>
                  <div className="w-full text-center text-[28px] font-medium leading-none text-[#333]">
                    99
                  </div>
                </div>

                {risk?.triggerTime ? (
                  <span className="shrink-0 whitespace-nowrap text-sm text-[#666]">
                    {risk.triggerTime}
                  </span>
                ) : null}
              </div>

            </div>
          </div>
        </div>
      </div>

      <div className="h-[16px] w-full bg-[#fff]" />

      <div className=" w-full rounded-[8px] bg-[#f6faff] p-[12px]">
        {!risk ? (
          <p className="text-sm text-[#666]">
            {riskId ? `未找到风险 ID：${riskId}` : "未指定风险 ID"}
          </p>
        ) : (
          <div className="flex flex-col gap-[12px]">
            <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                网络拓扑（IP / 端口）
              </h3>
              {topologyView ? (
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  <TopologyChartPane
                    title="IP（主机）"
                    graph={topologyView.host}
                    viewIsBenign={topologyView.is_benign}
                    repulsion={TOPOLOGY_REPULSION}
                    minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                    chartHeight={CHART_HEIGHT}
                  />
                  <TopologyChartPane
                    title="IP:端口（服务）"
                    graph={topologyView.endpoint}
                    viewIsBenign={topologyView.is_benign}
                    repulsion={TOPOLOGY_REPULSION}
                    minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                    chartHeight={CHART_HEIGHT}
                  />
                </div>
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
        )}
      </div>
    </div>
  );
}
