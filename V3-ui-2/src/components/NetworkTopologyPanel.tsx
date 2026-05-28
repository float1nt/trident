import { useMemo, useState } from "react";
import { Button } from "antd";
import type { EChartsOption } from "echarts";
import EChartsRingChart from "@/components/EChartsRingChart";
import "./NetworkTopologyPanel.css";
import {
  CHART_AXIS_LINE,
  CHART_GREEN,
  CHART_ORANGE,
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
  /** 节点关联协议列表（可选，后端扩展字段） */
  protocols?: string[];
  /** 节点主协议（可选，后端扩展字段） */
  protocol?: string;
};

export type TopologyLink = {
  source: string;
  target: string;
  value: number;
  is_benign?: boolean;
  /** 边关联协议列表（可选，后端扩展字段） */
  protocols?: string[];
  /** 边主协议（可选，后端扩展字段） */
  protocol?: string;
};

export type TopologyGraph = {
  flow_count: number;
  total_flow_count: number;
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

export const GRID_CHART_HEIGHT = 280;

const COMPACT_MAX_NODES = 28;

function trimGraphForCompactDisplay(
  graph: TopologyGraph | undefined,
  maxNodes = COMPACT_MAX_NODES,
): TopologyGraph | undefined {
  if (!graph || graph.nodes.length <= maxNodes) return graph;
  const nodes = [...graph.nodes]
    .sort((a, b) => b.flow_count - a.flow_count)
    .slice(0, maxNodes);
  const ids = new Set(nodes.map((n) => n.id));
  const links = graph.links.filter(
    (l) => ids.has(l.source) && ids.has(l.target),
  );
  return { ...graph, nodes, links };
}

type GraphNode = {
  id: string;
  name: string;
  value: number;
  flow_count: number;
  ip: string;
  port: number | null;
  is_internal: boolean;
  protocols?: string[];
  protocol?: string;
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
  // 紧凑模式 + 节点很多时提高 zoom，否则 50 个节点在 120px 里几乎看不见
  if (nodeCount <= 8) return base * 0.55;
  if (nodeCount <= 15) return base * 0.45;
  if (nodeCount <= 30) return base * 0.38;
  if (nodeCount <= 50) return Math.max(0.32, base * 0.22);
  return Math.max(0.2, base * 0.15);
}

function compactForceParams(
  nodeCount: number,
  repulsion: number,
  compact = false,
) {
  const n = Math.max(nodeCount, 1);
  if (compact) {
    return {
      repulsion: Math.min(repulsion * 0.45, 24 + n * 0.8),
      edgeLength: [20, Math.min(48, 16 + n * 0.5)] as [number, number],
      gravity: 0.35,
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
    const nodeCount = graph.nodes.length;
    const size = compact
      ? 8 + Math.sqrt(t) * 6
      : 6 + Math.sqrt(t) * 14;
    const minSize = compact ? (nodeCount > 25 ? 6 : nodeCount > 12 ? 5 : 3) : 5;
    const maxSize = compact ? 18 : 22;
    return {
      id: n.id,
      name: n.id,
      value: n.flow_count,
      flow_count: n.flow_count,
      ip: n.ip,
      port: n.port,
      is_internal: n.is_internal,
      protocols: n.protocols,
      protocol: n.protocol,
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

function getTrafficAnalysisText(
  viewIsBenign: boolean | null | undefined,
): string {
  if (viewIsBenign === true) return "正常";
  if (viewIsBenign === false) return "异常";
  return "部分异常";
}

function formatTrafficAnalysisHtml(label: string): string {
  if (label === "正常") {
    return `流量分析:<span style="color:${CHART_GREEN}">正常</span>`;
  }
  if (label === "异常") {
    return `流量分析:<span style="color:${CHART_RED}">异常</span>`;
  }
  if (label === "部分异常") {
    return `流量分析:<span style="color:${CHART_ORANGE}">部分异常</span>`;
  }
  return `流量分析:${label}`;
}

function formatNodeProtocols(node: Pick<TopologyNode, "protocols" | "protocol">): string {
  if (Array.isArray(node.protocols) && node.protocols.length > 0) {
    return node.protocols.join("、");
  }
  if (node.protocol) {
    return node.protocol;
  }
  return "—";
}

function formatNodeTooltip(
  node: TopologyNode,
  viewIsBenign: boolean | null | undefined,
): string {
  const ipLabel = node.port != null ? node.id : node.ip;
  return [
    ipLabel,
    `访问次数:${node.flow_count.toLocaleString("zh-CN")}`,
    formatTrafficAnalysisHtml(getTrafficAnalysisText(viewIsBenign)),
    `协议:${formatNodeProtocols(node)}`,
  ].join("<br/>");
}

function getEdgeTrafficAnalysisText(
  edge: TopologyLink,
  viewIsBenign: boolean | null | undefined,
): string {
  if (edge.is_benign === true) return "正常";
  if (edge.is_benign === false) return "异常";
  return getTrafficAnalysisText(viewIsBenign);
}

function formatEdgeTooltip(
  edge: TopologyLink,
  viewIsBenign: boolean | null | undefined,
): string {
  return [
    `${edge.source} → ${edge.target}`,
    `访问次数:${edge.value.toLocaleString("zh-CN")}`,
    formatTrafficAnalysisHtml(getEdgeTrafficAnalysisText(edge, viewIsBenign)),
    `协议:${formatNodeProtocols(edge)}`,
  ].join("<br/>");
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
          return formatEdgeTooltip(p.data as GraphLink, viewIsBenign);
        }
        if (p.data) {
          const node = p.data as GraphNode;
          return formatNodeTooltip(node, viewIsBenign);
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
      className={`min-w-0 rounded-[4px] border border-[#e8eef4] bg-[#f6faff] ${
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

export type TopologyGraphMode = "host" | "endpoint";

function TopologyGraphModeToggle({
  value,
  onChange,
  compact = false,
}: {
  value: TopologyGraphMode;
  onChange: (mode: TopologyGraphMode) => void;
  compact?: boolean;
}) {
  const options: { mode: TopologyGraphMode; label: string }[] = [
    { mode: "host", label: "IP" },
    { mode: "endpoint", label: "端口" },
  ];

  return (
    <div
      className={`topology-graph-mode-toggle${
        compact ? " topology-graph-mode-toggle--compact" : ""
      }`}
    >
      {options.map(({ mode, label }) => {
        const selected = value === mode;
        return (
          <Button
            key={mode}
            type="default"
            size="small"
            className={selected ? "ant-btn-topology-selected" : undefined}
            onClick={() => onChange(mode)}
          >
            {label}
          </Button>
        );
      })}
    </div>
  );
}

/** 单张拓扑子图；传 hostGraph+endpointGraph 时可切换 IP/端口，传 graph 时展示单图 */
export function TopologyChartPane({
  title = "拓扑图",
  graph,
  hostGraph,
  endpointGraph,
  viewIsBenign,
  repulsion,
  minEdgeFlows,
  chartHeight = 320,
  compact = false,
  fillContainer = false,
}: {
  /** 标题文本，默认「拓扑图」 */
  title?: string;
  /** 单图模式（与 hostGraph/endpointGraph 二选一） */
  graph?: TopologyGraph | undefined;
  hostGraph?: TopologyGraph | undefined;
  endpointGraph?: TopologyGraph | undefined;
  viewIsBenign: boolean | null | undefined;
  repulsion: number;
  minEdgeFlows: number;
  chartHeight?: number;
  /** 缩小节点与边，便于一屏展示更多结点 */
  compact?: boolean;
  /** 画布占满父容器剩余高度（首页等大图区域）；否则使用固定 chartHeight */
  fillContainer?: boolean;
}) {
  const hasDualGraph = hostGraph !== undefined || endpointGraph !== undefined;
  const [graphMode, setGraphMode] = useState<TopologyGraphMode>("host");
  const activeGraph = hasDualGraph
    ? graphMode === "host"
      ? hostGraph
      : endpointGraph
    : graph;
  const displayGraph = useMemo(
    () => (compact ? trimGraphForCompactDisplay(activeGraph) : activeGraph),
    [activeGraph, compact],
  );
  const graphData = useMemo(
    () => buildGraphData(displayGraph, viewIsBenign, minEdgeFlows, compact),
    [displayGraph, viewIsBenign, minEdgeFlows, compact],
  );
  const option = useMemo(
    () => buildChartOption(graphData, repulsion, viewIsBenign, compact),
    [graphData, repulsion, viewIsBenign, compact],
  );
  const stats = activeGraph?.stats ?? {};

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col rounded-lg border border-[#e8eaed] bg-white">
      <div className="shrink-0 border-b border-[#e8eaed] px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-medium text-[#333]">{title}</h4>
          {hasDualGraph ? (
            <TopologyGraphModeToggle
              value={graphMode}
              onChange={setGraphMode}
              compact={compact}
            />
          ) : null}
        </div>
        {activeGraph ? (
          <div
            className={`grid grid-cols-[2fr_2fr_2fr_3fr] gap-2 ${
              compact ? "mt-1.5" : "mt-2"
            }`}
          >
            <TopologyStatCard
              label={graphMode === "endpoint" ? "端口数量" : "IP数量"}
              value={
                compact && activeGraph.nodes.length > (displayGraph?.nodes.length ?? 0)
                  ? `${displayGraph?.nodes.length ?? 0} / ${activeGraph.nodes.length}`
                  : (displayGraph?.nodes.length ?? activeGraph.nodes.length)
              }
              compact={compact}
            />
            <TopologyStatCard
              label="访问次数"
              value={activeGraph.total_flow_count ?? activeGraph.flow_count}
              compact={compact}
            />
            <TopologyStatCard
              label="主目的端口"
              value={stats.top_dst_port != null ? stats.top_dst_port : "—"}
              compact={compact}
            />
            <TopologyStatCard
              label="主目的端口访问占比"
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
      <div
        className={
          fillContainer
            ? "min-h-0 w-full flex-1"
            : "w-full shrink-0"
        }
        style={
          fillContainer ? { minHeight: chartHeight } : { height: chartHeight }
        }
      >
        {graphData.nodes.length === 0 ? (
          <div
            className="flex h-full w-full items-center justify-center text-xs text-[#8c8c8c]"
            style={fillContainer ? undefined : { height: chartHeight }}
          >
            暂无节点
          </div>
        ) : fillContainer ? (
          <EChartsRingChart option={option} className="h-full w-full" />
        ) : (
          <EChartsRingChart
            option={option}
            height={chartHeight}
            className="w-full"
          />
        )}
      </div>
    </div>
  );
}
