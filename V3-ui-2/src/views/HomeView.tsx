import { useCallback, useEffect, useMemo, useState } from "react";
import { Spin } from "antd";
import { useApi } from "@/hooks/useApi";
import DataFlowMetricsSection from "@/components/DataFlowMetricsSection";
import EChartsRingChart from "@/components/EChartsRingChart";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import {
  OverviewService,
  type OverviewMetrics,
  type TimeRange,
} from "@/api/services/OverviewService";
import {
  buildProtocolDistributionRingOption,
  buildTrafficDistributionRingOption,
  type DistributionItem,
} from "@/utils/chartDistribution";
import { buildTrafficTrendBarOption } from "@/utils/chartTrafficTrend";
import {
  getMockTrafficTrend,
  getTrafficTrendChartTitle,
} from "@/mock/overviewTrafficTrend";
import type { DatasetNetworkTopologyJson } from "@/components/NetworkTopologyPanel";

const CHART_HEIGHT = 280;
const TOPOLOGY_CHART_HEIGHT = 320;
const TOPOLOGY_SPLIT_CHART_HEIGHT = 220;
const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;

const EMPTY_METRICS: OverviewMetrics = {
  totalTraffic: 0,
  protocolCount: 0,
  riskTypeCount: 0,
  suspiciousIpCount: 0,
};

/** 总览：数据流动看板 */
export default function HomeView() {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [metrics, setMetrics] = useState<OverviewMetrics>(EMPTY_METRICS);
  const [trafficDist, setTrafficDist] = useState<DistributionItem[]>([]);
  const [protocolDist, setProtocolDist] = useState<DistributionItem[]>([]);
  const [networkTopology, setNetworkTopology] =
    useState<DatasetNetworkTopologyJson | null>(null);
  const { loading, run } = useApi();

  const loadOverview = useCallback(async () => {
    await run(async () => {
      const [metricsData, distributions, topology] = await Promise.all([
        OverviewService.getMetrics(timeRange),
        OverviewService.getDistributions(timeRange),
        OverviewService.getNetworkTopology(timeRange),
      ]);
      setMetrics(metricsData);
      setTrafficDist(distributions.traffic);
      setProtocolDist(distributions.protocol);
      setNetworkTopology(topology);
    });
  }, [timeRange, run]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const trafficChartOption = useMemo(
    () => buildTrafficDistributionRingOption(trafficDist),
    [trafficDist],
  );
  const protocolChartOption = useMemo(
    () => buildProtocolDistributionRingOption(protocolDist),
    [protocolDist],
  );

  const trafficTrendData = useMemo(
    () => getMockTrafficTrend(timeRange),
    [timeRange],
  );
  const trafficTrendChartOption = useMemo(
    () => buildTrafficTrendBarOption(trafficTrendData),
    [trafficTrendData],
  );
  const trafficTrendChartTitle = useMemo(
    () => getTrafficTrendChartTitle(timeRange),
    [timeRange],
  );

  const combinedView = networkTopology?.views.__combined__;
  const benignView = networkTopology?.views.__benign__;
  const attackView = networkTopology?.views.__attack__;

  return (
    <Spin spinning={loading} className="block w-full">
      <div className="h-[calc(100vh-85px)] w-full rounded-[8px] overflow-y-auto">
        <DataFlowMetricsSection
          timeRange={timeRange}
          metrics={metrics}
          onTimeRangeChange={setTimeRange}
          onRefresh={() => void loadOverview()}
        />
      <div className="relative p-[12px] z-10  -mt-[36px] w-full rounded-[16px] bg-[#f6faff]">
        <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          整体概览
        </div>
        <div className="mt-4 grid grid-cols-1 gap-[12px] lg:grid-cols-[2fr_3fr_2fr]">
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="mb-3 text-[14px] font-medium text-[#333]">流量分布</h3>
            <EChartsRingChart option={trafficChartOption} height={CHART_HEIGHT} />
          </div>
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="mb-3 text-[14px] font-medium text-[#333]">
         {trafficTrendChartTitle}
            </h3>
            <EChartsRingChart
              option={trafficTrendChartOption}
              height={CHART_HEIGHT}
            />
          </div>
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="mb-3 text-[14px] font-medium text-[#333]">协议分布</h3>
            <EChartsRingChart option={protocolChartOption} height={CHART_HEIGHT} />
          </div>
        </div>
        <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333] mt-[12px]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          流量分析
        </div>
        <div className="mt-4 grid grid-cols-1 gap-[12px] lg:min-h-[520px] lg:grid-cols-[3fr_2fr] lg:grid-rows-[1fr_1fr] lg:items-stretch">
          <div className="flex min-h-0 min-w-0 flex-col rounded-[8px] border border-[#e8eaed] bg-white p-[8px] lg:row-span-2">
            <TopologyChartPane
              title="总拓扑"
              hostGraph={combinedView?.host}
              endpointGraph={combinedView?.endpoint}
              viewIsBenign={combinedView?.is_benign}
              repulsion={TOPOLOGY_REPULSION}
              minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
              chartHeight={TOPOLOGY_CHART_HEIGHT}
              fillContainer
            />
          </div>

          <div className="flex min-h-0 min-w-0 flex-col rounded-[8px] border border-[#e8eaed] bg-white p-[8px]">
            <TopologyChartPane
              title="异常流量总拓扑"
              hostGraph={attackView?.host}
              endpointGraph={attackView?.endpoint}
              viewIsBenign={attackView?.is_benign}
              repulsion={TOPOLOGY_REPULSION}
              minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
              chartHeight={TOPOLOGY_SPLIT_CHART_HEIGHT}
              compact
              fillContainer
            />
          </div>

          <div className="flex min-h-0 min-w-0 flex-col rounded-[8px] border border-[#e8eaed] bg-white p-[8px]">
            <TopologyChartPane
              title="正常流量总拓扑"
              hostGraph={benignView?.host}
              endpointGraph={benignView?.endpoint}
              viewIsBenign={benignView?.is_benign}
              repulsion={TOPOLOGY_REPULSION}
              minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
              chartHeight={TOPOLOGY_SPLIT_CHART_HEIGHT}
              compact
              fillContainer
            />
          </div>
        </div>
      </div>
      </div>
    </Spin>
  );
}
