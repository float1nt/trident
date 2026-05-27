import { useCallback, useEffect, useMemo, useState } from "react";
import DataFlowMetricsSection from "@/components/DataFlowMetricsSection";
import EChartsRingChart from "@/components/EChartsRingChart";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import {
  OverviewService,
  type OverviewMetrics,
  type TimeRange,
} from "@/api/services/OverviewService";
import {
  buildDistributionRingOption,
  type DistributionItem,
} from "@/utils/chartDistribution";
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
  const [loading, setLoading] = useState(false);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const [metricsData, distributions, topology] = await Promise.all([
        OverviewService.getMetrics(timeRange),
        OverviewService.getDistributions(timeRange),
        OverviewService.getNetworkTopology(timeRange),
      ]);
      setMetrics(metricsData);
      setTrafficDist(distributions.traffic);
      setProtocolDist(distributions.protocol);
      setNetworkTopology(topology);
    } catch (error) {
      console.error("加载总览数据失败", error);
    } finally {
      setLoading(false);
    }
  }, [timeRange]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const trafficChartOption = useMemo(
    () => buildDistributionRingOption(trafficDist),
    [trafficDist],
  );
  const protocolChartOption = useMemo(
    () => buildDistributionRingOption(protocolDist),
    [protocolDist],
  );

  const combinedView = networkTopology?.views.__combined__;
  const benignView = networkTopology?.views.__benign__;
  const attackView = networkTopology?.views.__attack__;

  return (
    <div className="h-[calc(100vh-85px)] w-full rounded-[8px] overflow-y-auto">
      <DataFlowMetricsSection
        timeRange={timeRange}
        metrics={metrics}
        loading={loading}
        onTimeRangeChange={setTimeRange}
        onRefresh={() => void loadOverview()}
      />
      <div className="relative p-[12px] z-10  -mt-[36px] w-full rounded-[16px] bg-[#f6faff]">
        <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          整体分布
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="mb-3 text-[14px] font-medium text-[#333]">流量分布</h3>
            <EChartsRingChart option={trafficChartOption} height={CHART_HEIGHT} />
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
        <div className="mt-4 flex flex-col gap-4">
          <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
            <h3 className="text-[14px] font-medium text-[#333]">总拓扑</h3>
            <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
              <TopologyChartPane
                title="IP（主机）"
                graph={combinedView?.host}
                viewIsBenign={combinedView?.is_benign}
                repulsion={TOPOLOGY_REPULSION}
                minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                chartHeight={TOPOLOGY_CHART_HEIGHT}
              />
              <TopologyChartPane
                title="IP:端口（服务）"
                graph={combinedView?.endpoint}
                viewIsBenign={combinedView?.is_benign}
                repulsion={TOPOLOGY_REPULSION}
                minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                chartHeight={TOPOLOGY_CHART_HEIGHT}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
              <h3 className="text-[14px] font-medium text-[#333]">良性流量总拓扑</h3>
              <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
                <TopologyChartPane
                  title="IP（主机）"
                  graph={benignView?.host}
                  viewIsBenign={benignView?.is_benign}
                  repulsion={TOPOLOGY_REPULSION}
                  minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                  chartHeight={TOPOLOGY_SPLIT_CHART_HEIGHT}
                  compact
                />
                <TopologyChartPane
                  title="IP:端口（服务）"
                  graph={benignView?.endpoint}
                  viewIsBenign={benignView?.is_benign}
                  repulsion={TOPOLOGY_REPULSION}
                  minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                  chartHeight={TOPOLOGY_SPLIT_CHART_HEIGHT}
                  compact
                />
              </div>
            </div>

            <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
              <h3 className="text-[14px] font-medium text-[#333]">攻击流量总拓扑</h3>
              <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
                <TopologyChartPane
                  title="IP（主机）"
                  graph={attackView?.host}
                  viewIsBenign={attackView?.is_benign}
                  repulsion={TOPOLOGY_REPULSION}
                  minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                  chartHeight={TOPOLOGY_SPLIT_CHART_HEIGHT}
                  compact
                />
                <TopologyChartPane
                  title="IP:端口（服务）"
                  graph={attackView?.endpoint}
                  viewIsBenign={attackView?.is_benign}
                  repulsion={TOPOLOGY_REPULSION}
                  minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                  chartHeight={TOPOLOGY_SPLIT_CHART_HEIGHT}
                  compact
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
