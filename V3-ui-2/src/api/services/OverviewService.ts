import { get } from "@/utils/request";
import type { DatasetNetworkTopologyJson } from "@/components/NetworkTopologyPanel";
import type { DistributionItem } from "@/utils/chartDistribution";

export type OverviewMetrics = {
  totalTraffic: number;
  protocolCount: number;
  riskTypeCount: number;
  suspiciousIpCount: number;
};

export type OverviewDistributions = {
  traffic: DistributionItem[];
  protocol: DistributionItem[];
};

export type TimeRange = "24h" | "7d" | "30d";

export type TrafficTrendPoint = {
  label: string;
  normal: number;
  abnormal: number;
};

export function getTrafficTrendChartTitle(timeRange: TimeRange): string {
  switch (timeRange) {
    case "24h":
      return "流量趋势（按小时）";
    case "7d":
      return "流量趋势（按天）";
    case "30d":
      return "流量趋势（按周）";
    default:
      return "流量趋势";
  }
}

export class OverviewService {
  static async getMetrics(timeRange: TimeRange = "24h"): Promise<OverviewMetrics> {
    const res = await get<OverviewMetrics>("/overview/metrics", { timeRange });
    return (
      res.data ?? {
        totalTraffic: 0,
        protocolCount: 0,
        riskTypeCount: 0,
        suspiciousIpCount: 0,
      }
    );
  }

  static async getDistributions(
    timeRange: TimeRange = "24h",
  ): Promise<OverviewDistributions> {
    const res = await get<OverviewDistributions>("/overview/distributions", {
      timeRange,
    });
    return res.data ?? { traffic: [], protocol: [] };
  }

  static async getTrafficTrend(
    timeRange: TimeRange = "24h",
  ): Promise<TrafficTrendPoint[]> {
    const res = await get<TrafficTrendPoint[]>("/overview/traffic-trend", {
      timeRange,
    });
    return res.data ?? [];
  }

  static async getNetworkTopology(
    timeRange: TimeRange = "24h",
  ): Promise<DatasetNetworkTopologyJson> {
    const res = await get<DatasetNetworkTopologyJson>(
      "/overview/network-topology",
      { timeRange },
    );
      return (
        res.data ?? {
          version: 1,
          total_flows: 0,
          labels: [],
          default_label: "__combined__",
          default_node_mode: "host",
          aggregate_views: [],
          views: {},
          // fallback keeps shape compatible with backend response
        }
      );
  }
}
