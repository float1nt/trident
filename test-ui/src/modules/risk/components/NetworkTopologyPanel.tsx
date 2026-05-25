import { useMemo, useState } from 'react'
import { Select, Slider } from 'antd'
import ReactECharts from 'echarts-for-react'
import {
  CHART_AXIS_LINE,
  CHART_GREEN,
  CHART_RED,
  CHART_TEXT_PRIMARY,
  notionTheme,
} from '../theme/notionTheme'

export type TopologyNode = {
  id: string
  ip: string
  port: number | null
  flow_count: number
  is_internal: boolean
}

export type TopologyLink = {
  source: string
  target: string
  value: number
  is_benign?: boolean
}

export type TopologyGraph = {
  flow_count: number
  node_mode: string
  nodes: TopologyNode[]
  links: TopologyLink[]
  stats: Record<string, number>
}

export type TopologyLabelView = {
  label: string
  view_kind?: 'label' | 'aggregate'
  is_benign: boolean | null
  endpoint: TopologyGraph
  host: TopologyGraph
}

export type DatasetNetworkTopologyJson = {
  version: number
  total_flows: number
  labels: string[]
  default_label: string
  default_node_mode?: 'endpoint' | 'host'
  aggregate_views?: string[]
  views: Record<string, TopologyLabelView>
}

const AGGREGATE_VIEW_LABELS: Record<string, string> = {
  __combined__: '总拓扑（良性+攻击，可双边）',
  __benign__: '良性流量总拓扑',
  __attack__: '攻击流量总拓扑',
  __all__: '全量（旧版，请重新导出）',
}

type Props = {
  data: DatasetNetworkTopologyJson | null
  labelOptions?: string[]
}

export type TopologyViewMode = 'single' | 'grid'

export const GRID_CHART_HEIGHT = 120
export const GRID_LAYOUT_CLASS = 'grid grid-cols-4 gap-2'

export function TopologyViewModeToggle({
  value,
  onChange,
}: {
  value: TopologyViewMode
  onChange: (mode: TopologyViewMode) => void
}) {
  return (
    <div className="inline-flex rounded-lg border border-notion-border bg-notion-surface-alt p-0.5">
      <button
        type="button"
        className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
          value === 'single'
            ? 'bg-notion-surface text-notion-text shadow-sm'
            : 'text-notion-secondary hover:text-notion-text'
        }`}
        onClick={() => onChange('single')}
      >
        单选
      </button>
      <button
        type="button"
        className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
          value === 'grid'
            ? 'bg-notion-surface text-notion-text shadow-sm'
            : 'text-notion-secondary hover:text-notion-text'
        }`}
        onClick={() => onChange('grid')}
      >
        网格
      </button>
    </div>
  )
}

type GraphNode = {
  id: string
  name: string
  value: number
  flow_count: number
  is_internal: boolean
  symbolSize: number
  itemStyle: { color: string; borderColor: string; borderWidth: number }
}

type GraphLink = TopologyLink & {
  lineStyle: { width: number; opacity: number; color: string; curveness: number }
}

/** 节点越多初始缩放越小，便于一屏看到整体 */
function initialGraphZoom(nodeCount: number): number {
  let z = 0.28
  if (nodeCount <= 10) z = 1
  else if (nodeCount <= 20) z = 0.82
  else if (nodeCount <= 35) z = 0.62
  else if (nodeCount <= 55) z = 0.48
  else if (nodeCount <= 75) z = 0.36
  return Math.min(1, z * 2)
}

/** 网格子图：进一步缩小初始视图，便于在小画布内看全拓扑 */
function initialGridGraphZoom(nodeCount: number): number {
  const base = initialGraphZoom(nodeCount)
  if (nodeCount <= 8) return base * 0.5
  if (nodeCount <= 15) return base * 0.42
  if (nodeCount <= 30) return base * 0.34
  if (nodeCount <= 50) return base * 0.28
  return Math.max(0.06, base * 0.22)
}

function compactForceParams(nodeCount: number, repulsion: number, compact = false) {
  const n = Math.max(nodeCount, 1)
  if (compact) {
    return {
      repulsion: Math.min(repulsion * 0.55, 28 + n * 1.2),
      edgeLength: [14, Math.min(56, 20 + n * 0.7)] as [number, number],
      gravity: 0.24,
    }
  }
  return {
    repulsion: Math.min(repulsion, 50 + n * 2.5),
    edgeLength: [28, Math.min(120, 36 + n)] as [number, number],
    gravity: 0.14,
  }
}

function buildGraphData(
  graph: TopologyGraph | undefined,
  viewIsBenign: boolean | null | undefined,
  minEdgeFlows: number,
  compact = false,
): { nodes: GraphNode[]; links: GraphLink[] } {
  if (!graph) return { nodes: [], links: [] }
  const maxFlow = Math.max(...graph.nodes.map((n) => n.flow_count), 1)

  const nodes: GraphNode[] = graph.nodes.map((n) => {
    const t = n.flow_count / maxFlow
    const size = compact ? 4 + Math.sqrt(t) * 8 : 12 + Math.sqrt(t) * 32
    const minSize = compact ? 4 : 12
    const maxSize = compact ? 14 : 56
    return {
      id: n.id,
      name: n.id,
      value: n.flow_count,
      flow_count: n.flow_count,
      is_internal: n.is_internal,
      symbolSize: Math.max(minSize, Math.min(size, maxSize)),
      itemStyle: {
        color: n.is_internal ? notionTheme.chart.nodeInternal : notionTheme.chart.nodeExternal,
        borderColor: n.is_internal ? notionTheme.chart.nodeInternalBorder : notionTheme.chart.nodeExternalBorder,
        borderWidth: n.is_internal ? (compact ? 1.2 : 2) : compact ? 0.8 : 1.2,
      },
    }
  })

  const linksRaw = graph.links.filter((l) => l.value >= minEdgeFlows)
  const weights = linksRaw.map((l) => l.value)
  const minW = weights.length ? Math.min(...weights) : 0
  const maxW = weights.length ? Math.max(...weights) : 0
  const edgeIsBenign = (l: TopologyLink) =>
    l.is_benign !== undefined ? l.is_benign : Boolean(viewIsBenign)
  const links: GraphLink[] = linksRaw.map((l) => {
    const scale = maxW > minW ? (l.value - minW) / (maxW - minW) : 0.5
    const benign = edgeIsBenign(l)
    return {
      ...l,
      lineStyle: {
        width: compact ? 0.4 + scale * 2 : 0.6 + scale * 4,
        opacity: compact ? 0.3 + scale * 0.4 : 0.35 + scale * 0.5,
        color: benign ? CHART_GREEN : CHART_RED,
        curveness: benign ? 0.22 : -0.22,
      },
    }
  })
  return { nodes, links }
}

function buildChartOption(
  graphData: { nodes: GraphNode[]; links: GraphLink[] },
  repulsion: number,
  viewIsBenign: boolean | null | undefined,
  compact = false,
) {
  const n = graphData.nodes.length
  const force = compactForceParams(n, repulsion, compact)
  const zoom = compact ? initialGridGraphZoom(n) : initialGraphZoom(n)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: notionTheme.chart.white,
      borderColor: CHART_AXIS_LINE,
      textStyle: { color: CHART_TEXT_PRIMARY },
      formatter: (params: { dataType?: string; data: GraphNode | GraphLink }) => {
        if (params.dataType === 'edge') {
          const e = params.data as GraphLink
          const benign = e.is_benign !== undefined ? e.is_benign : Boolean(viewIsBenign)
          return [
            `<b>${e.source} → ${e.target}</b>`,
            `flows=${e.value.toLocaleString()}`,
            `type=${benign ? '良性' : '攻击'}`,
          ].join('<br/>')
        }
        const n = params.data as GraphNode
        return [
          `<b>${n.id}</b>`,
          `flows=${n.flow_count.toLocaleString()}`,
          `scope=${n.is_internal ? '内网' : '外网'}`,
        ].join('<br/>')
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        scaleLimit: { min: 0.08, max: 4 },
        zoom,
        center: ['50%', '50%'],
        draggable: true,
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: compact ? 4 : 8,
        data: graphData.nodes,
        links: graphData.links,
        lineStyle: { curveness: 0.1 },
        force: {
          ...force,
          initLayout: 'circular',
          layoutAnimation: true,
          friction: 0.55,
        },
        label: {
          show: !compact && n <= 28,
          position: 'right',
          fontSize: compact ? 7 : 9,
          color: CHART_TEXT_PRIMARY,
        },
        emphasis: { focus: 'adjacency', lineStyle: { opacity: 0.85 } },
      },
    ],
  }
}

export function TopologyChartPane({
  title,
  graph,
  viewIsBenign,
  repulsion,
  minEdgeFlows,
  chartHeight = 560,
  compact = false,
}: {
  title: string
  graph: TopologyGraph | undefined
  viewIsBenign: boolean | null | undefined
  repulsion: number
  minEdgeFlows: number
  chartHeight?: number
  compact?: boolean
}) {
  const graphData = useMemo(
    () => buildGraphData(graph, viewIsBenign, minEdgeFlows, compact),
    [graph, viewIsBenign, minEdgeFlows, compact],
  )
  const option = useMemo(
    () => buildChartOption(graphData, repulsion, viewIsBenign, compact),
    [graphData, repulsion, viewIsBenign, compact],
  )
  const stats = graph?.stats ?? {}

  return (
    <div
      className={`min-w-0 flex-1 rounded-lg bg-notion-surface ${
        compact ? 'border border-notion-border' : 'border border-notion-border'
      }`}
    >
      <div className={`border-b border-notion-border ${compact ? 'px-1.5 py-0.5' : 'px-3 py-2'}`}>
        <h4 className={`font-medium text-notion-text ${compact ? 'text-[10px]' : 'text-sm'}`}>
          {title}
        </h4>
        {graph && !compact ? (
          <p className="mt-0.5 text-xs text-notion-secondary">
            {graph.nodes.length} 节点 · {graph.links.length} 边
            {stats.top_dst_port != null ? (
              <>
                {' '}
                · 主目的端口 {stats.top_dst_port}（
                {(Number(stats.top_dst_port_ratio) * 100).toFixed(1)}%）
              </>
            ) : null}
          </p>
        ) : null}
      </div>
      <ReactECharts
        option={option}
        style={{ height: chartHeight, width: '100%' }}
        notMerge
        lazyUpdate
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}

export function NetworkTopologyPanel({ data, labelOptions }: Props) {
  const [selectedLabel, setSelectedLabel] = useState<string>('')
  const [viewMode, setViewMode] = useState<TopologyViewMode>('grid')
  const [repulsion, setRepulsion] = useState(180)
  const [minEdgeFlows, setMinEdgeFlows] = useState(1)

  const aggregateViews = useMemo(() => {
    if (!data) return [] as string[]
    const fromJson = data.aggregate_views?.filter((k) => data.views[k])
    if (fromJson?.length) return fromJson
    return ['__combined__', '__benign__', '__attack__'].filter((k) => data.views[k])
  }, [data])

  const labels = useMemo(() => {
    if (!data) return []
    const fromViews = data.labels?.length
      ? data.labels.filter((l) => data.views[l])
      : Object.keys(data.views).filter(
          (k) => data.views[k]?.view_kind === 'label' || (!k.startsWith('__') && k !== '__all__'),
        )
    if (labelOptions?.length) {
      const set = new Set(fromViews)
      return labelOptions.filter((l) => set.has(l))
    }
    return fromViews
  }, [data, labelOptions])

  const effectiveLabel = useMemo(() => {
    if (!data) return ''
    if (selectedLabel && data.views[selectedLabel]) return selectedLabel
    if (data.views[data.default_label]) return data.default_label
    if (data.views.__combined__) return '__combined__'
    if (data.views.__all__) return '__all__'
    return aggregateViews[0] ?? labels[0] ?? ''
  }, [data, selectedLabel, labels, aggregateViews])

  const view = data?.views[effectiveLabel]
  const hostGraph = view?.host
  const endpointGraph = view?.endpoint

  const gridViewKeys = useMemo(() => [...aggregateViews, ...labels], [aggregateViews, labels])

  if (!data) {
    return (
      <div className="rounded-lg border border-dashed border-notion-border-strong bg-notion-surface-alt p-4 text-sm text-notion-secondary">
        本 run 尚无 <span className="font-mono">dataset_network_topology.json</span>。重新跑实验，或执行：
        <pre className="mt-2 overflow-x-auto rounded bg-notion-surface p-2 text-xs text-notion-text">
          python3 learner_qualification/export_visualization_artifacts.py outputs/runs/&lt;run_id&gt;
        </pre>
      </div>
    )
  }

  const flowCount = hostGraph?.flow_count ?? endpointGraph?.flow_count

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex shrink-0 flex-col gap-1">
          <label className="field-label">展示模式</label>
          <TopologyViewModeToggle value={viewMode} onChange={setViewMode} />
        </div>
        {viewMode === 'single' ? (
          <div className="min-w-[220px] flex-1">
            <label className="field-label">标签视图</label>
            <Select
              className="w-full"
              value={effectiveLabel || undefined}
              onChange={(v) => setSelectedLabel(String(v))}
              options={[
                ...aggregateViews.map((k) => ({
                  value: k,
                  label: AGGREGATE_VIEW_LABELS[k] ?? k,
                })),
                ...labels.map((l) => ({ value: l, label: l })),
              ]}
            />
          </div>
        ) : (
          <p className="flex-1 text-xs text-notion-secondary">
            网格模式：共 {gridViewKeys.length} 个标签/聚合视图
          </p>
        )}
        <div className="min-w-[200px] flex-[2]">
          <label className="field-label">斥力 {repulsion}</label>
          <Slider min={40} max={500} value={repulsion} onChange={setRepulsion} />
        </div>
        <div className="min-w-[200px] flex-[2]">
          <label className="field-label">最小边流量 {minEdgeFlows}</label>
          <Slider min={1} max={500} step={1} value={minEdgeFlows} onChange={setMinEdgeFlows} />
        </div>
      </div>

      <p className="text-xs text-notion-secondary">
        {viewMode === 'single' ? (
          <>
            左：IP 主机视角；右：IP:端口 服务视角。默认缩放已适配整图，可滚轮缩放/拖拽；节点多时可调低斥力使布局更紧凑。
            {flowCount != null ? (
              <> 当前子集 {flowCount.toLocaleString()} 流</>
            ) : null}
          </>
        ) : (
          <>
            网格模式展示全部标签拓扑（左 IP / 右 IP:端口）；共 {gridViewKeys.length} 项，可滚轮缩放各子图。
          </>
        )}
      </p>

      {viewMode === 'single' ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <TopologyChartPane
            title="IP（主机）"
            graph={hostGraph}
            viewIsBenign={view?.is_benign}
            repulsion={repulsion}
            minEdgeFlows={minEdgeFlows}
          />
          <TopologyChartPane
            title="IP:端口（服务）"
            graph={endpointGraph}
            viewIsBenign={view?.is_benign}
            repulsion={repulsion}
            minEdgeFlows={minEdgeFlows}
          />
        </div>
      ) : (
        <div className={GRID_LAYOUT_CLASS}>
          {gridViewKeys.map((key) => {
            const gridView = data.views[key]
            if (!gridView) return null
            const title = AGGREGATE_VIEW_LABELS[key] ?? key
            const itemFlowCount =
              gridView.host?.flow_count ?? gridView.endpoint?.flow_count
            return (
              <div
                key={`dataset-topology-grid-${key}`}
                className="overflow-hidden rounded-md border border-notion-border bg-notion-surface"
              >
                <div className="border-b border-notion-border px-2 py-1">
                  <h4
                    className="truncate text-[11px] font-medium leading-tight text-notion-text"
                    title={title}
                  >
                    {title}
                  </h4>
                  <p className="truncate text-[10px] leading-tight text-notion-secondary">
                    {gridView.host?.nodes.length ?? 0} 节点 ·{' '}
                    {gridView.host?.links.length ?? 0} 边
                    {itemFlowCount != null ? (
                      <> · {itemFlowCount.toLocaleString()} 流</>
                    ) : null}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-1 p-1">
                  <TopologyChartPane
                    title="IP"
                    graph={gridView.host}
                    viewIsBenign={gridView.is_benign}
                    repulsion={repulsion}
                    minEdgeFlows={minEdgeFlows}
                    chartHeight={GRID_CHART_HEIGHT}
                    compact
                  />
                  <TopologyChartPane
                    title="端口"
                    graph={gridView.endpoint}
                    viewIsBenign={gridView.is_benign}
                    repulsion={repulsion}
                    minEdgeFlows={minEdgeFlows}
                    chartHeight={GRID_CHART_HEIGHT}
                    compact
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
