import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Spin } from "antd";
import { API_SUCCESS_MESSAGE } from "@/hooks/useApi";
import DataFlowMetricsSection from "@/components/DataFlowMetricsSection";
import { message } from "@/utils/message";
import { getErrorMessage, isErrorToastShown } from "@/utils/apiError";
import EChartsRingChart from "@/components/EChartsRingChart";
import { TopologyChartPane } from "@/components/NetworkTopologyPanel";
import {
  OverviewService,
  getTrafficTrendChartTitle,
  type OverviewMetrics,
  type TimeRange,
  type TrafficTrendPoint,
} from "@/api/services/OverviewService";
import {
  buildProtocolDistributionRingOption,
  buildTrafficDistributionRingOption,
  type DistributionItem,
} from "@/utils/chartDistribution";
import { buildTrafficTrendBarOption } from "@/utils/chartTrafficTrend";
import type {
  DatasetNetworkTopologyJson,
  TopologyGraphMode,
} from "@/components/NetworkTopologyPanel";

const CHART_HEIGHT = 280;
const TOPOLOGY_CHART_HEIGHT = 320;
const TOPOLOGY_SPLIT_CHART_HEIGHT = 220;
const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;
type ProtocolDistributionMode = "network" | "application";

const EMPTY_METRICS: OverviewMetrics = {
  totalTraffic: 0,
  protocolCount: 0,
  riskTypeCount: 0,
  suspiciousIpCount: 0,
};

type OverviewLoadingKey =
  | "metrics"
  | "trafficDist"
  | "trafficTrend"
  | "protocolDist"
  | "topology";

const INITIAL_LOADING: Record<OverviewLoadingKey, boolean> = {
  metrics: false,
  trafficDist: false,
  trafficTrend: false,
  protocolDist: false,
  topology: false,
};

/** 总览：数据流动看板 */
export default function HomeView() {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [metrics, setMetrics] = useState<OverviewMetrics>(EMPTY_METRICS);
  const [trafficDist, setTrafficDist] = useState<DistributionItem[]>([]);
  const [protocolDist, setProtocolDist] = useState<DistributionItem[]>([]);
  const [applicationProtocolDist, setApplicationProtocolDist] = useState<
    DistributionItem[]
  >([]);
  const [protocolMode, setProtocolMode] =
    useState<ProtocolDistributionMode>("network");
  const [networkTopology, setNetworkTopology] =
    useState<DatasetNetworkTopologyJson | null>(null);
  const [topologyMode, setTopologyMode] = useState<TopologyGraphMode>("host");
  const [trafficTrend, setTrafficTrend] = useState<TrafficTrendPoint[]>([]);
  const [loadingState, setLoadingState] =
    useState<Record<OverviewLoadingKey, boolean>>(INITIAL_LOADING);

  const runSection = useCallback(
    async <T,>(
      keys: OverviewLoadingKey | OverviewLoadingKey[],
      fn: () => Promise<T>,
      onSuccess: (data: T) => void,
    ) => {
      const keyList = Array.isArray(keys) ? keys : [keys];
      setLoadingState((prev) => ({
        ...prev,
        ...Object.fromEntries(keyList.map((key) => [key, true])),
      }));
      try {
        const data = await fn();
        onSuccess(data);
      } catch (error) {
        console.error(error);
        if (!isErrorToastShown(error)) {
          message.error(getErrorMessage(error));
        }
      } finally {
        setLoadingState((prev) => ({
          ...prev,
          ...Object.fromEntries(keyList.map((key) => [key, false])),
        }));
      }
    },
    [],
  );

  const loadOverview = useCallback(
    async (
      mode: TopologyGraphMode = topologyMode,
      options?: { showSuccess?: boolean },
    ) => {
      await Promise.all([
        runSection(
          "metrics",
          () => OverviewService.getMetrics(timeRange),
          setMetrics,
        ),
        runSection(
          ["trafficDist", "protocolDist"],
          () => OverviewService.getDistributions(timeRange),
          (distributions) => {
            setTrafficDist(distributions.traffic);
            setProtocolDist(distributions.protocol);
            setApplicationProtocolDist(distributions.applicationProtocol ?? []);
          },
        ),
        runSection(
          "trafficTrend",
          () => OverviewService.getTrafficTrend(timeRange),
          setTrafficTrend,
        ),
        runSection(
          "topology",
          () => OverviewService.getNetworkTopology(timeRange, mode),
          setNetworkTopology,
        ),
      ]);
      if (options?.showSuccess) {
        message.success(API_SUCCESS_MESSAGE);
      }
    },
    [runSection, timeRange, topologyMode],
  );

  const handleTopologyModeChange = useCallback(
    (mode: TopologyGraphMode) => {
      if (mode !== topologyMode) {
        setTopologyMode(mode);
        void runSection(
          "topology",
          () => OverviewService.getNetworkTopology(timeRange, mode),
          setNetworkTopology,
        );
      }
    },
    [runSection, timeRange, topologyMode],
  );

  useEffect(() => {
    void loadOverview(topologyMode);
  }, [timeRange]);

  const trafficChartOption = useMemo(
    () => buildTrafficDistributionRingOption(trafficDist),
    [trafficDist],
  );
  const protocolChartOption = useMemo(
    () =>
      buildProtocolDistributionRingOption(
        protocolMode === "network" ? protocolDist : applicationProtocolDist,
        { compactTransport: protocolMode === "network" },
      ),
    [applicationProtocolDist, protocolDist, protocolMode],
  );

  const trafficTrendChartOption = useMemo(
    () => buildTrafficTrendBarOption(trafficTrend),
    [trafficTrend],
  );
  const trafficTrendChartTitle = useMemo(
    () => getTrafficTrendChartTitle(timeRange),
    [timeRange],
  );

  const combinedView = networkTopology?.views.__combined__;
  const benignView = networkTopology?.views.__benign__;
  const attackView = networkTopology?.views.__attack__;

  return (
    <div className="block w-full">
      <div className="h-[calc(100vh-85px)] w-full overflow-y-auto rounded-[8px]">
        <DataFlowMetricsSection
          timeRange={timeRange}
          metrics={metrics}
          loading={loadingState.metrics}
          onTimeRangeChange={setTimeRange}
          onRefresh={() => void loadOverview(topologyMode, { showSuccess: true })}
        />
        <div className="relative z-10 -mt-[36px] w-full rounded-[16px] bg-[#f6faff] p-[12px]">
          <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
            <span
              className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
              aria-hidden
            />
            整体概览
          </div>
          <div className="mt-4 grid grid-cols-1 gap-[12px] lg:grid-cols-[2fr_3fr_2fr]">
            <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
              <h3 className="mb-3 text-[14px] font-medium text-[#333]">
                流量分布
              </h3>
              <Spin spinning={loadingState.trafficDist}>
                <EChartsRingChart
                  option={trafficChartOption}
                  height={CHART_HEIGHT}
                />
              </Spin>
            </div>
            <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
              <h3 className="mb-3 text-[14px] font-medium text-[#333]">
                {trafficTrendChartTitle}
              </h3>
              <Spin spinning={loadingState.trafficTrend}>
                <EChartsRingChart
                  option={trafficTrendChartOption}
                  height={CHART_HEIGHT}
                />
              </Spin>
            </div>
            <div className="min-w-0 rounded-[8px] border border-[#e8eaed] bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="m-0 text-[14px] font-medium text-[#333]">
                  协议分布
                </h3>
                <div className="topology-graph-mode-toggle">
                  <Button
                    type="default"
                    size="small"
                    className={
                      protocolMode === "network"
                        ? "ant-btn-topology-selected"
                        : undefined
                    }
                    onClick={() => setProtocolMode("network")}
                  >
                    网络层
                  </Button>
                  <Button
                    type="default"
                    size="small"
                    className={
                      protocolMode === "application"
                        ? "ant-btn-topology-selected"
                        : undefined
                    }
                    onClick={() => setProtocolMode("application")}
                  >
                    应用层
                  </Button>
                </div>
              </div>
              <Spin spinning={loadingState.protocolDist}>
                <EChartsRingChart
                  option={protocolChartOption}
                  height={CHART_HEIGHT}
                />
              </Spin>
            </div>
          </div>
          <div className="mt-[12px] flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
            <span
              className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
              aria-hidden
            />
            流量分析
          </div>
          <div className="relative mt-4 grid grid-cols-1 gap-[12px] lg:min-h-[520px] lg:grid-cols-[3fr_2fr] lg:grid-rows-[1fr_1fr] lg:items-stretch">
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
                activeGraphMode={topologyMode}
                onGraphModeChange={handleTopologyModeChange}
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
                activeGraphMode={topologyMode}
                onGraphModeChange={handleTopologyModeChange}
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
                activeGraphMode={topologyMode}
                onGraphModeChange={handleTopologyModeChange}
              />
            </div>
            {loadingState.topology ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[8px] bg-white/60">
                <Spin spinning />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
