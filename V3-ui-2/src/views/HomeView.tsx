import { useMemo } from "react";
import DataFlowMetricsSection from "@/components/DataFlowMetricsSection";
import EChartsRingChart from "@/components/EChartsRingChart";
import {
  MOCK_PROTOCOL_DISTRIBUTION,
  MOCK_TRAFFIC_DISTRIBUTION,
  buildDistributionRingOption,
} from "@/mock/overviewDistribution";

const CHART_HEIGHT = 280;

/** 总览：数据流动看板 — 当前仅实现核心指标区 */
export default function HomeView() {
  const trafficChartOption = useMemo(
    () => buildDistributionRingOption(MOCK_TRAFFIC_DISTRIBUTION),
    [],
  );
  const protocolChartOption = useMemo(
    () => buildDistributionRingOption(MOCK_PROTOCOL_DISTRIBUTION),
    [],
  );
  return (
    <div className="h-full w-full rounded-[8px]">
      <DataFlowMetricsSection />
      {/* relative + z-index + -mt-[16px]：上移 16px 并盖住指标区底部 */}
      <div className="relative p-[12px] z-10 -mt-[36px] h-full w-full rounded-[16px] bg-[#f6faff]" >
        <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          整体分布
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="mb-3 text-[14px] font-medium text-[#333]">
              流量分布
            </h3>
            <EChartsRingChart
              option={trafficChartOption}
              height={CHART_HEIGHT}
            />
          </div>
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="mb-3 text-[14px] font-medium text-[#333]">
              协议分布
            </h3>
            <EChartsRingChart
              option={protocolChartOption}
              height={CHART_HEIGHT}
            />
          </div>
        </div>
        <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          流量分析
        </div>
      </div>
    </div>
  );
}
