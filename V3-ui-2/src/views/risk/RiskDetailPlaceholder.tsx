import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Tag } from "antd";
import EChartsRingChart from "@/components/EChartsRingChart";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import { buildDistributionRingOption } from "@/mock/overviewDistribution";
import {
  getMockProtocolDistribution,
  getMockRiskById,
  getMockRiskNetworkTopology,
} from "@/mock/riskTasks";
import taskDetailIcon from "@/assets/蒙版组 152.png";

const CHART_HEIGHT = 320;
const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;

const PROTOCOL_COLORS = [
  "#4368f0",
  "#52c41a",
  "#fa8c16",
  "#722ed1",
  "#1777ff",
  "#faad14",
  "#ff4d4f",
  "#8c8c8c",
];

/** 风险详情页（布局对齐 V3-ui-2 IP 视角详情页） */
export default function RiskDetailPlaceholder() {
  const [searchParams] = useSearchParams();
  const riskId = searchParams.get("id");
  const risk = riskId ? getMockRiskById(Number(riskId)) : undefined;

  const networkTopology = useMemo(
    () => (riskId ? getMockRiskNetworkTopology(Number(riskId)) : null),
    [riskId],
  );
  const topologyView = networkTopology?.views.__combined__;

  const protocolChartOption = useMemo(() => {
    if (!riskId) return buildDistributionRingOption([]);
    const distribution = getMockProtocolDistribution(Number(riskId));
    return buildDistributionRingOption(
      distribution.map((item, index) => ({
        name: item.name,
        value: item.value,
        color: PROTOCOL_COLORS[index % PROTOCOL_COLORS.length],
      })),
    );
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
                    compact
                  />
                  <TopologyChartPane
                    title="IP:端口（服务）"
                    graph={topologyView.endpoint}
                    viewIsBenign={topologyView.is_benign}
                    repulsion={TOPOLOGY_REPULSION}
                    minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                    chartHeight={CHART_HEIGHT}
                    compact
                  />
                </div>
              ) : (
                <p className="text-sm text-[#8c8c8c]">暂无拓扑数据</p>
              )}
            </div>

            <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <h3 className="mb-[12px] text-[14px] font-medium text-[#333]">
                协议分布占比
              </h3>
              <EChartsRingChart option={protocolChartOption} height={CHART_HEIGHT} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
