import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import EChartsRingChart from "@/components/EChartsRingChart";
import {
  CHART_AXIS_LINE,
  CHART_GREEN,
  CHART_RED,
  CHART_TEXT_PRIMARY,
  chartTheme,
} from "@/theme/chartTheme";

export type TopologyNode = {
  id: string;
  ip: string;
  port: number | null;
  flow_count: number;
  is_internal: boolean;
};

export type TopologyLink = {
  source: string;
  target: string;
  value: number;
  is_benign?: boolean;
};

export type TopologyGraph = {
  flow_count: number;
  node_mode: string;
  nodes: TopologyNode[];
  links: TopologyLink[];
  stats: Record<string, number>;
};

export type TopologyLabelView = {
  label: string;
  view_kind?: "label" | "aggregate";
  is_benign: boolean | null;
  endpoint: TopologyGraph;
  host: TopologyGraph;
};

export type DatasetNetworkTopologyJson = {
  version: number;
  total_flows: number;
  labels: string[];
  default_label: string;
  default_node_mode?: "endpoint" | "host";
  aggregate_views?: string[];
  views: Record<string, TopologyLabelView>;
};

export const GRID_CHART_HEIGHT = 120;

type GraphNode = {
  id: string;
  name: string;
  value: number;
  flow_count: number;
  is_internal: boolean;
  symbolSize: number;
  itemStyle: { color: string; borderColor: string; borderWidth: number };
};

type GraphLink = TopologyLink & {
  lineStyle: {
    width: number;
    opacity: number;
    color: string;
    curveness: number;
  };
};

function initialGraphZoom(nodeCount: number, compact = false): number {
  let z = 0.28;
  if (nodeCount <= 10) z = 1;
  else if (nodeCount <= 20) z = 0.82;
  else if (nodeCount <= 35) z = 0.62;
  else if (nodeCount <= 55) z = 0.48;
  else if (nodeCount <= 75) z = 0.36;
  const base = Math.min(1, z * 2);
  if (!compact) return base;
  if (nodeCount <= 8) return base * 0.55;
  if (nodeCount <= 15) return base * 0.45;
  if (nodeCount <= 30) return base * 0.36;
  if (nodeCount <= 50) return base * 0.3;
  return Math.max(0.08, base * 0.24);
}

function compactForceParams(
  nodeCount: number,
  repulsion: number,
  compact = false,
) {
  const n = Math.max(nodeCount, 1);
  if (compact) {
    return {
      repulsion: Math.min(repulsion * 0.55, 28 + n * 1.2),
      edgeLength: [14, Math.min(56, 20 + n * 0.7)] as [number, number],
      gravity: 0.24,
    };
  }
  return {
    repulsion: Math.min(repulsion, 50 + n * 2.5),
    edgeLength: [28, Math.min(120, 36 + n)] as [number, number],
    gravity: 0.14,
  };
}

function buildGraphData(
  graph: TopologyGraph | undefined,
  viewIsBenign: boolean | null | undefined,
  minEdgeFlows: number,
  compact = false,
): { nodes: GraphNode[]; links: GraphLink[] } {
  if (!graph) return { nodes: [], links: [] };
  const maxFlow = Math.max(...graph.nodes.map((n) => n.flow_count), 1);

  const nodes: GraphNode[] = graph.nodes.map((n) => {
    const t = n.flow_count / maxFlow;
    const size = compact
      ? 4 + Math.sqrt(t) * 5
      : 6 + Math.sqrt(t) * 14;
    const minSize = compact ? 3 : 5;
    const maxSize = compact ? 10 : 22;
    return {
      id: n.id,
      name: n.id,
      value: n.flow_count,
      flow_count: n.flow_count,
      is_internal: n.is_internal,
      symbolSize: Math.max(minSize, Math.min(size, maxSize)),
      itemStyle: {
        color: n.is_internal
          ? chartTheme.nodeInternal
          : chartTheme.nodeExternal,
        borderColor: n.is_internal
          ? chartTheme.nodeInternalBorder
          : chartTheme.nodeExternalBorder,
        borderWidth: compact
          ? n.is_internal
            ? 1
            : 0.8
          : n.is_internal
            ? 1.5
            : 1,
      },
    };
  });

  const linksRaw = graph.links.filter((l) => l.value >= minEdgeFlows);
  const weights = linksRaw.map((l) => l.value);
  const minW = weights.length ? Math.min(...weights) : 0;
  const maxW = weights.length ? Math.max(...weights) : 0;
  const edgeIsBenign = (l: TopologyLink) =>
    l.is_benign !== undefined ? l.is_benign : Boolean(viewIsBenign);

  const links: GraphLink[] = linksRaw.map((l) => {
    const scale = maxW > minW ? (l.value - minW) / (maxW - minW) : 0.5;
    const benign = edgeIsBenign(l);
    return {
      ...l,
      lineStyle: {
        width: compact ? 0.4 + scale * 2 : 0.6 + scale * 4,
        opacity: compact ? 0.3 + scale * 0.4 : 0.35 + scale * 0.5,
        color: benign ? CHART_GREEN : CHART_RED,
        curveness: benign ? 0.22 : -0.22,
      },
    };
  });

  return { nodes, links };
}

function buildChartOption(
  graphData: { nodes: GraphNode[]; links: GraphLink[] },
  repulsion: number,
  viewIsBenign: boolean | null | undefined,
  compact = false,
): EChartsOption {
  const n = graphData.nodes.length;
  const force = compactForceParams(n, repulsion, compact);
  const zoom = initialGraphZoom(n, compact);

  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: chartTheme.white,
      borderColor: CHART_AXIS_LINE,
      textStyle: { color: CHART_TEXT_PRIMARY },
      formatter: (params: unknown) => {
        if (!params || typeof params !== "object") return "";
        const p = params as {
          dataType?: string;
          data?: GraphNode | GraphLink;
        };
        if (p.dataType === "edge" && p.data) {
          const e = p.data as GraphLink;
          const benign =
            e.is_benign !== undefined ? e.is_benign : Boolean(viewIsBenign);
          return [
            `<b>${e.source} → ${e.target}</b>`,
            `flows=${e.value.toLocaleString()}`,
            `type=${benign ? "良性" : "攻击"}`,
          ].join("<br/>");
        }
        if (p.data) {
          const node = p.data as GraphNode;
          return [
            `<b>${node.id}</b>`,
            `flows=${node.flow_count.toLocaleString()}`,
            `scope=${node.is_internal ? "内网" : "外网"}`,
          ].join("<br/>");
        }
        return "";
      },
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        scaleLimit: { min: 0.08, max: 4 },
        zoom,
        center: ["50%", "50%"],
        draggable: true,
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: compact ? 4 : 6,
        data: graphData.nodes,
        links: graphData.links,
        lineStyle: { curveness: 0.1 },
        force: {
          ...force,
          initLayout: "circular",
          layoutAnimation: true,
          friction: 0.55,
        },
        label: {
          show: !compact && n <= 24,
          position: "right",
          fontSize: compact ? 7 : 9,
          color: CHART_TEXT_PRIMARY,
        },
        emphasis: { focus: "adjacency", lineStyle: { opacity: 0.85 } },
      },
    ],
  };
}

function TopologyStatCard({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string | number;
  compact?: boolean;
}) {
  return (
    <div
      className={`min-w-0 flex-1 rounded-[4px] border border-[#e8eef4] bg-[#f6faff] ${
        compact ? "px-2 py-1.5" : "px-3 py-2"
      }`}
    >
      <div className={`text-[#8c8c8c] ${compact ? "text-[11px]" : "text-[12px]"}`}>
        {label}
      </div>
      <div
        className={`truncate font-medium text-[#262626] ${
          compact ? "text-[16px]" : "text-[20px]"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

/** 单张拓扑子图（IP 或 IP:端口），样式对齐 V3-ui 风险详情页 */
export function TopologyChartPane({
  title,
  graph,
  viewIsBenign,
  repulsion,
  minEdgeFlows,
  chartHeight = 320,
  compact = false,
}: {
  title: string;
  graph: TopologyGraph | undefined;
  viewIsBenign: boolean | null | undefined;
  repulsion: number;
  minEdgeFlows: number;
  chartHeight?: number;
  /** 缩小节点与边，便于一屏展示更多结点 */
  compact?: boolean;
}) {
  const graphData = useMemo(
    () => buildGraphData(graph, viewIsBenign, minEdgeFlows, compact),
    [graph, viewIsBenign, minEdgeFlows, compact],
  );
  const option = useMemo(
    () => buildChartOption(graphData, repulsion, viewIsBenign, compact),
    [graphData, repulsion, viewIsBenign, compact],
  );
  const stats = graph?.stats ?? {};

  return (
    <div className="min-w-0 flex-1 rounded-lg border border-[#e8eaed] bg-white">
      <div className="border-b border-[#e8eaed] px-3 py-2">
        <h4 className="text-sm font-medium text-[#333]">{title}</h4>
        {graph ? (
          <div className={`flex gap-2 ${compact ? "mt-1.5" : "mt-2"}`}>
            <TopologyStatCard
              label="IP数量"
              value={graph.nodes.length}
              compact={compact}
            />
            <TopologyStatCard
              label="访问次数"
              value={graph.links.length}
              compact={compact}
            />
            <TopologyStatCard
              label="主目的端口"
              value={stats.top_dst_port != null ? stats.top_dst_port : "—"}
              compact={compact}
            />
            <TopologyStatCard
              label="主目的端口访问比"
              value={
                stats.top_dst_port_ratio != null
                  ? `${(Number(stats.top_dst_port_ratio) * 100).toFixed(1)}%`
                  : "—"
              }
              compact={compact}
            />
          </div>
        ) : null}
      </div>
      <EChartsRingChart option={option} height={chartHeight} />
    </div>
  );
}
