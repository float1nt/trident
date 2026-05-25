import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Checkbox, Popover, Select, Slider } from 'antd'
import * as echarts from 'echarts'
import ReactECharts from 'echarts-for-react'
import { DecisionTreePanel, type DecisionTreeVizJson } from '../components/DecisionTreePanel'
import { LearnerInternalTopologyPanel } from '../components/LearnerInternalTopologyPanel'
import { NetworkTopologyPanel, type DatasetNetworkTopologyJson } from '../components/NetworkTopologyPanel'
import type { LearnerNetworkTopologyJson } from '../types/learnerTopology'
import { TableFilterBar } from '../components/TableFilterBar'
import { fetchRunJsonOptional, fetchRuns, parseCsv, runDataUrl, type RunInfo } from '../lib/runApi'
import { overviewPaths } from '../overviewPaths'
import { useTablePreferencesStore } from '../stores/tablePreferencesStore'
import {
  CHART_AXIS_LINE,
  CHART_EDGE,
  CHART_GREEN,
  CHART_GREEN_BORDER,
  CHART_RED,
  CHART_RED_BORDER,
  CHART_SPLIT_LINE,
  CHART_TEXT_PRIMARY,
  CHART_TEXT_SECONDARY,
  notionTheme,
} from '../theme/notionTheme'

type PairRow = {
  learner_a_raw: string
  learner_b_raw: string
  learner_a: string
  learner_b: string
  accept_count_a: string
  accept_count_b: string
  intersection_count: string
  union_count: string
  jaccard_acceptance: string
  accept_rate_a_to_b: string
  accept_rate_b_to_a: string
}

type AggRow = {
  attack_ratio: string
  aggregate_name: string
  member_count: string
  total_assigned_samples: string
  members_json: string
}

type LearnerDistRow = {
  attack_ratio: string
  learner_name: string
  total_assigned_samples: string
  creation_sample_count: string
  post_creation_added_samples: string
  dominant_label: string
  dominant_ratio: string
  label_distribution_json: string
  [key: string]: string
}

type CountRow = {
  window_end_time: string
  window_left: string
  window_right: string
  learner_count: string
  unknown_buffer_size: string
}

type TrainBatchRow = {
  stage: string
  learner_name: string
}

type DatasetLabelRow = {
  label: string
  count: string
  ratio: string
  is_benign: string | boolean
  year_tag: string
  base_label: string
  [key: string]: string | boolean
}

type MetricsJson = {
  risk_false_positive_rate?: number
  risk_false_negative_rate?: number
}

type PerfJson = {
  windows_count?: number
  new_learner_count?: number
  avg_window_seconds?: number
  detect_seconds_total?: number
  cluster_seconds_total?: number
  create_learner_seconds_total?: number
  retrain_seconds_total?: number
}

type AggSummaryJson = {
  aggregate_count?: number
  learner_count?: number
  selected_edge_count?: number
}

type DatasetLabelSummaryJson = {
  total_rows?: number
  label_count?: number
  benign_rows?: number
  attack_rows?: number
  benign_ratio?: number
  attack_ratio?: number
}

type FeatureCorrRow = {
  feature: string
  pearson_corr: number
  spearman_corr: number
  abs_pearson_corr: number
  abs_spearman_corr: number
}

type FeatureCorrJson = {
  feature_family?: string
  feature_count?: number
  top_k_default?: number
  rows?: FeatureCorrRow[]
}

type CreationFlowPreviewEntry = {
  learner_name: string
  creation_source: string
  window_left: number
  window_right: number
  cluster_size: number
  flows_preview: Array<Record<string, unknown>>
}

type CreationFlowPreviewJson = {
  preview_flow_count?: number
  entries?: CreationFlowPreviewEntry[]
}

const CREATION_PREVIEW_COL_PRIORITY = [
  'row_index',
  'Timestamp',
  'LabelNorm',
  'Protocol',
  'Flow Duration',
  'Total Fwd Packet',
  'Total Bwd packets',
  'Total Length of Fwd Packet',
  'Total Length of Bwd Packet',
]

function orderedCreationPreviewColumns(rows: Record<string, unknown>[]): string[] {
  const keys = new Set<string>()
  rows.forEach((r) => {
    Object.keys(r).forEach((k) => keys.add(k))
  })
  const out: string[] = []
  CREATION_PREVIEW_COL_PRIORITY.forEach((k) => {
    if (keys.has(k)) out.push(k)
  })
  const rest = [...keys].filter((k) => !out.includes(k)).sort((a, b) => a.localeCompare(b))
  return [...out, ...rest]
}

function orderedCreationPreviewDisplayColumns(rows: Record<string, unknown>[]): MetricTableColumn[] {
  return buildMetricTableColumns(orderedCreationPreviewColumns(rows))
}

function formatCreationPreviewCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—'
    if (Math.abs(value) >= 1e9 || (Math.abs(value) < 1e-4 && value !== 0)) return value.toExponential(4)
    return Number.isInteger(value) ? String(value) : value.toFixed(METRIC_DECIMAL_PLACES)
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  const s = String(value)
  return s.length > 56 ? `${s.slice(0, 53)}…` : s
}

type NodeData = {
  id: string
  name: string
  value: number
  ratio: number | null
  samples: number
  degree: number
  symbolSize: number
  itemStyle: {
    color: string
    borderColor?: string
    borderWidth?: number
  }
}

type LinkData = {
  source: string
  target: string
  value: number
  intersectionCount: number
  unionCount: number
  acceptCountA: number
  acceptCountB: number
  acceptRateAToB: number
  acceptRateBToA: number
  lineStyle?: {
    width: number
    opacity: number
  }
}

type LearnerDetail = {
  learnerName: string
  attackRatio: number | null
  totalSamples: number
  dominantLabel: string
  dominantRatio: number | null
  topLabels: Array<[string, number]>
}

/** 雷达无可绘内容时保持空白面板，不占位文案 */
const EMPTY_RADAR_CHART_OPTION = { animation: false, backgroundColor: 'transparent' as const }

const FEATURE_BASE_ZH_MAP: Record<string, string> = {
  'FWD Init Win Bytes': '前向初始窗口字节',
  'Bwd Init Win Bytes': '后向初始窗口字节',
  'ACK Flag Count': 'ACK 标志计数',
  'PSH Flag Count': 'PSH 标志计数',
  'Flow IAT Mean': '流间隔均值',
  'Bwd Packet Length Mean': '后向包长均值',
  'Total Fwd Packet': '前向包数',
  'Total Bwd packets': '后向包数',
  'Total Length of Fwd Packet': '前向总字节数',
  'Total Length of Bwd Packet': '后向总字节长度',
  'Bwd Packet Length Min': '后向包长最小值',
  'Bwd Bulk Rate Avg': '后向批量速率均值',
  'Fwd Bulk Rate Avg': '前向批量速率均值',
  'Active Max': '活跃时长最大值',
  'Idle Mean': '空闲时长均值',
  'Bwd Header Length': '后向包头长度',
  'Bwd Packet Length Max': '后向包长最大值',
  count: '样本数',
  ratio: '占比',
}

const FEATURE_SUFFIX_ZH_MAP: Record<string, string> = {
  mean: '均值',
  cv: '变异系数',
  max: '最大值',
  min: '最小值',
}

const metricDisplayName = (rawKey: string): string => {
  const key = String(rawKey || '').trim()
  if (!key) return '-'
  const direct = FEATURE_BASE_ZH_MAP[key]
  if (direct) return direct

  const marker = key.indexOf('__')
  if (marker >= 0) {
    const base = key.slice(0, marker)
    const suffix = key.slice(marker + 2)
    const baseZh = FEATURE_BASE_ZH_MAP[base] || base
    const suffixZh = FEATURE_SUFFIX_ZH_MAP[suffix] || suffix
    return `${baseZh}（${suffixZh}）`
  }

  return FEATURE_BASE_ZH_MAP[key] || key
}

type MetricAggSuffix = 'mean' | 'cv' | 'max' | 'min'

function metricStatSuffix(col: string): MetricAggSuffix | null {
  const i = col.lastIndexOf('__')
  if (i < 0) return null
  const s = col.slice(i + 2)
  if (s === 'mean' || s === 'cv' || s === 'max' || s === 'min') return s
  return null
}

function metricStatBaseName(col: string): string {
  const i = col.lastIndexOf('__')
  return i >= 0 ? col.slice(0, i) : col
}

function metricStatBaseZh(col: string): string {
  const base = metricStatBaseName(col)
  return FEATURE_BASE_ZH_MAP[base] || base
}

/** 表头：均值 μ / 变异系数 CV 分图标，便于扫列 */
function MetricStatColumnHeader({ col }: { col: string }) {
  const suf = metricStatSuffix(col)
  const baseZh = metricStatBaseZh(col)
  if (suf === 'mean') {
    return (
      <span className="inline-flex max-w-[14rem] items-center gap-1.5 font-sans">
        <span
          className="inline-flex h-[18px] shrink-0 items-center justify-center rounded-sm bg-indigo-100 px-1 font-serif text-[13px] font-semibold leading-none text-indigo-800"
          title="均值（mean）"
          aria-label="均值"
        >
          μ
        </span>
        <span className="min-w-0 truncate">{baseZh}</span>
      </span>
    )
  }
  if (suf === 'cv') {
    return (
      <span className="inline-flex max-w-[14rem] items-center gap-1.5 font-sans">
        <span
          className="inline-flex h-[18px] shrink-0 items-center justify-center rounded-sm bg-notion-warning-bg px-1 text-[10px] font-bold leading-none tracking-tight text-notion-warning"
          title="变异系数（CV）"
          aria-label="变异系数"
        >
          CV
        </span>
        <span className="min-w-0 truncate">{baseZh}</span>
      </span>
    )
  }
  return <span className="font-sans">{metricDisplayName(col)}</span>
}

const METRIC_MEAN_CV_COL_PREFIX = 'mean_cv::'

type MetricTableColumn =
  | { kind: 'single'; id: string; col: string }
  | { kind: 'mean_cv'; id: string; base: string; meanCol: string; cvCol: string }

function metricColComboId(base: string): string {
  return `${METRIC_MEAN_CV_COL_PREFIX}${base}`
}

function isMetricColComboId(id: string): boolean {
  return id.startsWith(METRIC_MEAN_CV_COL_PREFIX)
}

function metricColComboBase(id: string): string {
  return id.slice(METRIC_MEAN_CV_COL_PREFIX.length)
}

/** 将 CSV 指标列分组：同一底层特征的 mean+cv 合并为一列展示 */
function buildMetricTableColumns(csvColumns: string[]): MetricTableColumn[] {
  const singles: string[] = []
  const byBase = new Map<string, Partial<Record<MetricAggSuffix, string>>>()
  const baseOrder: string[] = []

  for (const col of csvColumns) {
    const suf = metricStatSuffix(col)
    if (!suf) {
      singles.push(col)
      continue
    }
    const base = metricStatBaseName(col)
    if (!byBase.has(base)) {
      byBase.set(base, {})
      baseOrder.push(base)
    }
    byBase.get(base)![suf] = col
  }

  const out: MetricTableColumn[] = singles.map((col) => ({ kind: 'single', id: col, col }))
  const suffixOrder: MetricAggSuffix[] = ['mean', 'cv', 'max', 'min']
  for (const base of baseOrder) {
    const parts = byBase.get(base)!
    if (parts.mean && parts.cv) {
      out.push({
        kind: 'mean_cv',
        id: metricColComboId(base),
        base,
        meanCol: parts.mean,
        cvCol: parts.cv,
      })
    }
    for (const suf of suffixOrder) {
      if (suf === 'mean' || suf === 'cv') {
        if (parts.mean && parts.cv) continue
      }
      const c = parts[suf]
      if (c) out.push({ kind: 'single', id: c, col: c })
    }
  }
  return out
}

function metricTableColumnLabel(col: MetricTableColumn): string {
  if (col.kind === 'mean_cv') {
    const baseZh = FEATURE_BASE_ZH_MAP[col.base] || col.base
    return `${baseZh}（μ + CV）`
  }
  return metricDisplayName(col.col)
}

function MetricMeanCvColumnHeader({ base }: { base: string }) {
  const baseZh = FEATURE_BASE_ZH_MAP[base] || base
  return (
    <span className="inline-flex max-w-[14rem] flex-col items-start gap-0.5 font-sans leading-tight">
      <span className="min-w-0 truncate text-[11px] font-medium text-notion-text">{baseZh}</span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-flex h-[16px] shrink-0 items-center justify-center rounded-sm bg-indigo-100 px-1 font-serif text-[12px] font-semibold leading-none text-indigo-800"
          title="均值（mean）"
        >
          μ
        </span>
        <span
          className="inline-flex h-[16px] shrink-0 items-center justify-center rounded-sm bg-notion-warning-bg px-1 text-[9px] font-bold leading-none tracking-tight text-notion-warning"
          title="变异系数（CV）"
        >
          CV
        </span>
      </span>
    </span>
  )
}

function formatMeanCvCombinedCell(
  meanRaw: string | boolean | undefined,
  cvRaw: string | boolean | undefined,
  formatValue: (raw: string | boolean | undefined) => string,
): ReactNode {
  const meanText = formatValue(meanRaw)
  const cvText = formatValue(cvRaw)
  if (meanText === '—' && cvText === '—') return '—'
  return (
    <span className="inline-flex flex-col gap-0.5 leading-tight">
      <span className="inline-flex items-baseline gap-1">
        <span className="shrink-0 font-serif text-[10px] font-semibold text-indigo-700">μ</span>
        <span>{meanText}</span>
      </span>
      <span className="inline-flex items-baseline gap-1">
        <span className="shrink-0 text-[9px] font-bold text-notion-warning">CV</span>
        <span>{cvText}</span>
      </span>
    </span>
  )
}

function normalizeMetricVisibleColumnIds(
  visible: string[],
  displayColumns: MetricTableColumn[],
): string[] {
  const displayIds = new Set(displayColumns.map((c) => c.id))
  const rawCols = new Set<string>()
  displayColumns.forEach((c) => {
    if (c.kind === 'single') rawCols.add(c.col)
    else {
      rawCols.add(c.meanCol)
      rawCols.add(c.cvCol)
    }
  })
  const out = new Set<string>()
  for (const v of visible) {
    if (displayIds.has(v)) {
      out.add(v)
      continue
    }
    if (rawCols.has(v)) {
      const suf = metricStatSuffix(v)
      if (suf === 'mean' || suf === 'cv') {
        const base = metricStatBaseName(v)
        const combo = metricColComboId(base)
        if (displayIds.has(combo)) {
          out.add(combo)
          continue
        }
      }
      out.add(v)
    }
  }
  return [...out]
}

function isMetricDisplayColumnVisible(
  col: MetricTableColumn,
  visibleSet: Set<string>,
): boolean {
  if (visibleSet.has(col.id)) return true
  if (col.kind === 'mean_cv') {
    return visibleSet.has(col.meanCol) || visibleSet.has(col.cvCol)
  }
  return false
}

/** 不展示标准差画像：后缀 __std，或底层特征名为 *Std（再聚合的均值/CV等亦隐藏） */
function isDroppedStdVarianceColumn(csvColName: string): boolean {
  if (!csvColName) return false
  if (csvColName.endsWith('__std')) return true
  const i = csvColName.lastIndexOf('__')
  const base = i >= 0 ? csvColName.slice(0, i) : csvColName
  return /\bStd\b|\bstd\b|\bSTD\b/i.test(base)
}

const LEARNER_LABEL_CSV_PRIMARY_KEYS = new Set([
  'learner_name',
  'attack_ratio',
  'total_assigned_samples',
  'creation_sample_count',
  'dominant_label',
  'dominant_ratio',
  'protocol_tcp_ratio',
  'protocol_udp_ratio',
  'protocol_concentration',
  'protocol_cluster_type',
])

/** 界面浮点指标统一保留的小数位数 */
const METRIC_DECIMAL_PLACES = 4

/** 表格等指标：整数按整数展示；一般浮点固定小数位；极大/极小用科学计数法 */
function formatMetricNumber(n: number): string {
  const abs = Math.abs(n)
  const d = METRIC_DECIMAL_PLACES
  if (abs >= 1e12 || (abs > 0 && abs < 10 ** -(d + 6))) return n.toExponential(d)
  if (Math.abs(n - Math.round(n)) < 1e-9) return Math.round(n).toLocaleString()
  return n.toFixed(d)
}

function compactLearnerJsonForDisplay(raw: string): string {
  const s = raw.trim()
  if (!s) return '—'
  try {
    return JSON.stringify(JSON.parse(s))
  } catch {
    return s.replace(/\r?\n/g, ' ')
  }
}

function formatLearnerResidualCsvCell(col: string, raw: string | undefined): string {
  const s = raw === undefined ? '' : String(raw).trim()
  if (!s) return '—'
  if (/_json$/i.test(col) || col === 'label_distribution_json') {
    const oneLine = compactLearnerJsonForDisplay(s)
    if (oneLine === '—') return '—'
    return oneLine.length <= 480 ? oneLine : `${oneLine.slice(0, 477)}…`
  }
  const n = Number(s)
  if (Number.isFinite(n)) {
    return formatMetricNumber(n)
  }
  return s.length > 140 ? `${s.slice(0, 137)}…` : s
}

function formatDatasetDistributionMetricCell(raw: string | boolean | undefined): string {
  if (typeof raw === 'boolean') return raw ? 'true' : 'false'
  const s = String(raw ?? '').trim()
  if (!s) return '—'
  const n = Number(s)
  if (Number.isFinite(n)) {
    return formatMetricNumber(n)
  }
  return s.length > 140 ? `${s.slice(0, 137)}…` : s
}

/** 数值列底部汇总：总和 / 均值 / 最值 / 总体标准差（σ，单样本时 0） */
type ColumnStatAggregate = {
  sum: number
  mean: number
  max: number
  min: number
  std: number
  n: number
}

function computeNumericColumnStats(values: number[]): ColumnStatAggregate | null {
  const nums = values.filter((x) => Number.isFinite(x))
  const n = nums.length
  if (n === 0) return null
  const sum = nums.reduce((a, b) => a + b, 0)
  const mean = sum / n
  const max = Math.max(...nums)
  const min = Math.min(...nums)
  const variance = n === 1 ? 0 : nums.reduce((acc, x) => acc + (x - mean) ** 2, 0) / n
  const std = Math.sqrt(variance)
  return { sum, mean, max, min, std, n }
}

function formatColumnStatField(stats: ColumnStatAggregate | null, field: keyof Omit<ColumnStatAggregate, 'n'>): string {
  if (!stats) return '—'
  return formatMetricNumber(stats[field])
}

const TABLE_COLUMN_STAT_ROWS: Array<{ field: keyof Omit<ColumnStatAggregate, 'n'>; label: string }> = [
  { field: 'sum', label: '总和' },
  { field: 'mean', label: '均值' },
  { field: 'max', label: '最大值' },
  { field: 'min', label: '最小值' },
  { field: 'std', label: '标准差' },
]

/** 可排序表头：悬浮仅用浅底，不改变字色（避免 hover 变黑） */
const TABLE_SORT_HEAD_BTN_CLASS =
  'inline-flex max-w-full min-w-0 items-center gap-1 rounded-sm px-0.5 py-0.5 text-inherit transition-colors hover:bg-notion-surface-hover/55'

/** 横向滚动时冻结首列表头（需与 thead 顶固定叠加 left；纯色底避免叠字） */
const STICKY_FIRST_COL_TH =
  'sticky left-0 top-0 z-[31] border-r border-notion-border bg-notion-surface-alt bg-clip-padding shadow-[2px_0_10px_-4px_rgba(55,53,47,0.14)]'
/** 冻结首列数据格：仅布局与阴影，背景由 stickyFirstColTdBg* 单独指定不透明色 */
const STICKY_FIRST_COL_TD_FRAME =
  'sticky left-0 z-10 border-r border-notion-border bg-clip-padding shadow-[2px_0_8px_-4px_rgba(55,53,47,0.08)]'

/** 使用 index.css 的 sticky-table-bg-*，保证冻结列不透明背景 */
function stickyFirstColTdBgDataset(isBenign: boolean): string {
  return isBenign ? 'sticky-table-bg-success' : 'sticky-table-bg-danger'
}

function stickyFirstColTdBgLearner(attackRatio: number): string {
  const r = Number(attackRatio)
  if (!Number.isFinite(r)) return 'sticky-table-bg-neutral'
  if (r > 0.7) return 'sticky-table-bg-danger'
  if (r < 0.3) return 'sticky-table-bg-success'
  return 'sticky-table-bg-warning'
}

const TABLE_ROW_NEUTRAL =
  'border-b border-notion-border bg-notion-surface-alt text-notion-text hover:bg-notion-surface-hover'
const TABLE_ROW_BENIGN_BAND =
  'border-b border-notion-success/30 bg-notion-success-bg text-notion-text hover:bg-notion-success-bg/90'
const TABLE_ROW_ATTACK_BAND =
  'border-b border-notion-danger/30 bg-notion-danger-bg text-notion-text hover:bg-notion-danger-bg/90'
const TABLE_ROW_MIXED_BAND =
  'border-b border-notion-warning/30 bg-notion-warning-bg text-notion-text hover:bg-notion-warning-bg/90'

function learnerTableRowClassFromAttackRatio(attackRatio: number): string {
  const r = Number(attackRatio)
  if (!Number.isFinite(r)) {
    return TABLE_ROW_NEUTRAL
  }
  if (r > 0.7) {
    return TABLE_ROW_ATTACK_BAND
  }
  if (r < 0.3) {
    return TABLE_ROW_BENIGN_BAND
  }
  return TABLE_ROW_MIXED_BAND
}

/** Label 表：良性 / 攻击两类行底与学习器表绿、红带一致（无 per-label attack_ratio 时不强制黄带） */
function datasetLabelTableRowClassName(isBenign: boolean): string {
  return isBenign ? TABLE_ROW_BENIGN_BAND : TABLE_ROW_ATTACK_BAND
}

const DATASET_DEFAULT_SORT_KEY = 'count'
const DATASET_DEFAULT_SORT_DIR: 'asc' | 'desc' = 'desc'
const LEARNER_DEFAULT_SORT_KEY = 'samples'
const LEARNER_DEFAULT_SORT_DIR: 'asc' | 'desc' = 'desc'

function TableSortTag({
  scopeLabel,
  columnLabel,
  dir,
  onClear,
  clearDisabled,
}: {
  scopeLabel: string
  columnLabel: string
  dir: 'asc' | 'desc'
  onClear: () => void
  clearDisabled?: boolean
}) {
  return (
    <span className="inline-flex max-w-[min(100%,420px)] items-center gap-1 rounded-md border border-notion-border bg-notion-surface-alt px-2 py-1 text-xs text-notion-text shadow-sm">
      <span className="shrink-0 text-notion-secondary">{scopeLabel}</span>
      <span className="min-w-0 truncate font-medium text-notion-text">{columnLabel}</span>
      <span className="shrink-0 tabular-nums text-notion-secondary">{dir === 'asc' ? '↑' : '↓'}</span>
      <button
        type="button"
        disabled={clearDisabled}
        className="ml-0.5 shrink-0 rounded px-1 leading-none text-notion-secondary hover:bg-notion-surface-hover hover:text-notion-text disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
        aria-label="恢复默认排序"
        onClick={onClear}
      >
        ×
      </button>
    </span>
  )
}

export default function GraphAnalysisPage() {
  const params = useParams<{ runId?: string }>()
  const routeRunId = params.runId ? decodeURIComponent(params.runId) : ''
  const detailMode = Boolean(routeRunId)

  const chartRef = useRef<HTMLDivElement | null>(null)
  const chartInstanceRef = useRef<echarts.ECharts | null>(null)
  const [threshold, setThreshold] = useState<number>(0.05)
  const [connectionMode, setConnectionMode] = useState<'all' | 'strongest' | 'mutual'>('all')
  const [repulsion, setRepulsion] = useState<number>(280)
  const [runs, setRuns] = useState<RunInfo[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [pairRows, setPairRows] = useState<PairRow[]>([])
  const [aggRows, setAggRows] = useState<AggRow[]>([])
  const [learnerRows, setLearnerRows] = useState<LearnerDistRow[]>([])
  const [countRows, setCountRows] = useState<CountRow[]>([])
  const [datasetLabelRows, setDatasetLabelRows] = useState<DatasetLabelRow[]>([])
  const [trainBatchRows, setTrainBatchRows] = useState<TrainBatchRow[]>([])
  const [datasetLabelSummary, setDatasetLabelSummary] = useState<DatasetLabelSummaryJson | null>(null)
  const [metrics, setMetrics] = useState<MetricsJson | null>(null)
  const [perf, setPerf] = useState<PerfJson | null>(null)
  const [aggSummary, setAggSummary] = useState<AggSummaryJson | null>(null)
  const [featureCorr, setFeatureCorr] = useState<FeatureCorrJson | null>(null)
  const [datasetLabelFeatureCorr, setDatasetLabelFeatureCorr] = useState<FeatureCorrJson | null>(null)
  const [creationFlowPreview, setCreationFlowPreview] = useState<CreationFlowPreviewJson | null>(null)
  const [decisionTreeViz, setDecisionTreeViz] = useState<DecisionTreeVizJson | null>(null)
  const [datasetNetworkTopology, setDatasetNetworkTopology] = useState<DatasetNetworkTopologyJson | null>(null)
  const [learnerNetworkTopology, setLearnerNetworkTopology] = useState<LearnerNetworkTopologyJson | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>('')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<LinkData | null>(null)
  const [learnerSortBy, setLearnerSortBy] = useState<string>(LEARNER_DEFAULT_SORT_KEY)
  const [learnerSortDir, setLearnerSortDir] = useState<'asc' | 'desc'>(LEARNER_DEFAULT_SORT_DIR)
  const [datasetSortBy, setDatasetSortBy] = useState<string>(DATASET_DEFAULT_SORT_KEY)
  const [datasetSortDir, setDatasetSortDir] = useState<'asc' | 'desc'>(DATASET_DEFAULT_SORT_DIR)
  /** null = 默认展示当前 run 的全部标签（与数据同步，无时序上的“空白一帧”） */
  const [radarFilterOpen, setRadarFilterOpen] = useState(false)
  const [radarLabelSelection, setRadarLabelSelection] = useState<string[] | null>(null)
  const [learnerRadarFilterOpen, setLearnerRadarFilterOpen] = useState(false)
  /** null = 默认展示全部学习器 */
  const [learnerRadarNameSelection, setLearnerRadarNameSelection] = useState<string[] | null>(null)
  const datasetFilterTags = useTablePreferencesStore((s) => s.datasetFilterTags)
  const learnerFilterTags = useTablePreferencesStore((s) => s.learnerFilterTags)
  const addDatasetFilterTag = useTablePreferencesStore((s) => s.addDatasetFilterTag)
  const removeDatasetFilterTag = useTablePreferencesStore((s) => s.removeDatasetFilterTag)
  const clearDatasetFilterTags = useTablePreferencesStore((s) => s.clearDatasetFilterTags)
  const addLearnerFilterTag = useTablePreferencesStore((s) => s.addLearnerFilterTag)
  const removeLearnerFilterTag = useTablePreferencesStore((s) => s.removeLearnerFilterTag)
  const clearLearnerFilterTags = useTablePreferencesStore((s) => s.clearLearnerFilterTags)
  const datasetVisibleColumns = useTablePreferencesStore((s) => s.datasetVisibleColumns)
  const setDatasetVisibleColumns = useTablePreferencesStore((s) => s.setDatasetVisibleColumns)
  const learnerVisibleColumns = useTablePreferencesStore((s) => s.learnerVisibleColumns)
  const setLearnerVisibleColumns = useTablePreferencesStore((s) => s.setLearnerVisibleColumns)
  const datasetColumnsCustomized = useTablePreferencesStore((s) => s.datasetColumnsCustomized)
  const learnerColumnsCustomized = useTablePreferencesStore((s) => s.learnerColumnsCustomized)

  useEffect(() => {
    const loadRuns = async () => {
      try {
        const result = await fetchRuns()
        const available = result.runs || []
        setRuns(available)
        if (routeRunId) {
          const exists = available.some((r) => r.id === routeRunId)
          if (exists) {
            setSelectedRunId(routeRunId)
          } else {
            const fallback = result.latestRunId || available[0]?.id || ''
            setSelectedRunId(fallback)
            if (fallback) {
              setError(`Run「${routeRunId}」未完成或不存在，已切换到 ${fallback}`)
            }
          }
        } else if (result.latestRunId) {
          setSelectedRunId(result.latestRunId)
        } else if (available.length > 0) {
          setSelectedRunId(available[0].id)
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setError(`run 列表加载失败: ${message}`)
      }
    }
    loadRuns()
  }, [routeRunId])

  useEffect(() => {
    if (!selectedRunId) return
    const load = async () => {
      setLoading(true)
      setError('')
      try {
          const [pairs, aggs, learners, counts, trainBatches, labelDistRows, labelDistSummary, metricJson, perfJson, aggSummaryJson, featureCorrJson, datasetLabelFeatureCorrJson, creationPreviewJson, decisionTreeJson, datasetTopologyJson, learnerTopologyJson] = await Promise.all([
          parseCsv<PairRow>(runDataUrl(selectedRunId, 'debug_true_overlap_pairs.csv')),
          parseCsv<AggRow>(runDataUrl(selectedRunId, 'learner_aggregated_distribution.csv')),
          parseCsv<LearnerDistRow>(runDataUrl(selectedRunId, 'learner_label_distribution.csv')),
          parseCsv<CountRow>(runDataUrl(selectedRunId, 'learner_count_over_time.csv')).catch(() => []),
          parseCsv<TrainBatchRow>(runDataUrl(selectedRunId, 'learner_train_batch_label_distribution.csv')).catch(() => []),
          parseCsv<DatasetLabelRow>(runDataUrl(selectedRunId, 'dataset_label_distribution.csv')).catch(() => []),
          fetchRunJsonOptional<DatasetLabelSummaryJson>(selectedRunId, 'dataset_label_distribution_summary.json'),
          fetchRunJsonOptional<MetricsJson>(selectedRunId, 'metrics.json'),
          fetchRunJsonOptional<PerfJson>(selectedRunId, 'performance_metrics.json'),
          fetchRunJsonOptional<AggSummaryJson>(selectedRunId, 'learner_aggregation_summary.json'),
          fetchRunJsonOptional<FeatureCorrJson>(selectedRunId, 'learner_feature_attack_ratio_correlation.json'),
          fetchRunJsonOptional<FeatureCorrJson>(selectedRunId, 'dataset_label_feature_attack_correlation.json'),
          fetchRunJsonOptional<CreationFlowPreviewJson>(selectedRunId, 'learner_creation_flow_previews.json'),
          fetchRunJsonOptional<DecisionTreeVizJson>(selectedRunId, 'decision_tree_visualization.json'),
          fetchRunJsonOptional<DatasetNetworkTopologyJson>(selectedRunId, 'dataset_network_topology.json'),
          fetchRunJsonOptional<LearnerNetworkTopologyJson>(selectedRunId, 'learner_network_topology.json'),
        ])
        setPairRows(pairs)
        setAggRows(aggs)
        setLearnerRows(learners)
        setCountRows(counts)
        setTrainBatchRows(trainBatches)
        setDatasetLabelRows(labelDistRows)
        setDatasetLabelSummary(labelDistSummary)
        setMetrics(metricJson)
        setPerf(perfJson)
        setAggSummary(aggSummaryJson)
        setFeatureCorr(featureCorrJson)
        setDatasetLabelFeatureCorr(datasetLabelFeatureCorrJson)
        setCreationFlowPreview(creationPreviewJson)
        setDecisionTreeViz(decisionTreeJson)
        setDatasetNetworkTopology(datasetTopologyJson)
        setLearnerNetworkTopology(learnerTopologyJson)
        setSelectedNodeId(null)
        setSelectedEdge(null)
        setRadarLabelSelection(null)
        setLearnerRadarNameSelection(null)
        setRadarFilterOpen(false)
        setLearnerRadarFilterOpen(false)
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setError(`数据加载失败: ${message}`)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [selectedRunId])

  const kpi = useMemo(() => {
    const fpr = metrics?.risk_false_positive_rate
    const fnr = metrics?.risk_false_negative_rate
    return {
      fpr: typeof fpr === 'number' ? fpr : null,
      fnr: typeof fnr === 'number' ? fnr : null,
      tpr: typeof fnr === 'number' ? 1 - fnr : null,
      windows: typeof perf?.windows_count === 'number' ? perf.windows_count : null,
      newLearners: typeof perf?.new_learner_count === 'number' ? perf.new_learner_count : null,
      avgWindowSeconds: typeof perf?.avg_window_seconds === 'number' ? perf.avg_window_seconds : null,
      aggregateCount: typeof aggSummary?.aggregate_count === 'number' ? aggSummary.aggregate_count : null,
      learnerCount: typeof aggSummary?.learner_count === 'number' ? aggSummary.learner_count : null,
      edgeCount: typeof aggSummary?.selected_edge_count === 'number' ? aggSummary.selected_edge_count : null,
    }
  }, [aggSummary, metrics, perf])

  const learnerDetailMap = useMemo(() => {
    const detailMap = new Map<string, LearnerDetail>()
    learnerRows.forEach((row) => {
      const learnerName = row.learner_name
      if (!learnerName) return
      let distribution: Record<string, number>
      try {
        distribution = JSON.parse(row.label_distribution_json)
      } catch {
        distribution = {}
      }
      const topLabels = Object.entries(distribution).sort((a, b) => b[1] - a[1]).slice(0, 8)
      detailMap.set(learnerName, {
        learnerName,
        attackRatio: Number.isFinite(Number(row.attack_ratio)) ? Number(row.attack_ratio) : null,
        totalSamples: Number(row.total_assigned_samples || 0),
        dominantLabel: row.dominant_label || '-',
        dominantRatio: Number.isFinite(Number(row.dominant_ratio)) ? Number(row.dominant_ratio) : null,
        topLabels,
      })
    })
    return detailMap
  }, [learnerRows])

  const learnerMeta = useMemo(() => {
    const ratioMap = new Map<string, number>()
    const sampleMap = new Map<string, number>()

    // attack_ratio 与表格保持同源：统一来自 learner_label_distribution.csv
    learnerRows.forEach((row) => {
      const learnerName = String(row.learner_name || '')
      if (!learnerName) return
      const ratio = Number(row.attack_ratio)
      if (Number.isFinite(ratio)) {
        ratioMap.set(learnerName, ratio)
      }
      const totalSamples = Number(row.total_assigned_samples || 0)
      if (Number.isFinite(totalSamples) && totalSamples >= 0) {
        sampleMap.set(learnerName, totalSamples)
      }
    })

    // aggRows 仅用于样本量兜底，不再覆盖 attack_ratio
    aggRows.forEach((row) => {
      const total = Number(row.total_assigned_samples || 0)
      let members: string[]
      try {
        members = JSON.parse(row.members_json)
      } catch {
        members = []
      }
      if (!Array.isArray(members) || members.length === 0) return
      const perLearnerSample = total / members.length
      members.forEach((member) => {
        if (!sampleMap.has(member)) {
          sampleMap.set(member, perLearnerSample)
        }
      })
    })
    return { ratioMap, sampleMap }
  }, [learnerRows, aggRows])

  const learnerDistRowByName = useMemo(() => {
    const m = new Map<string, LearnerDistRow>()
    learnerRows.forEach((row) => {
      const name = row.learner_name
      if (name) m.set(name, row)
    })
    return m
  }, [learnerRows])

  const creationPreviewByLearner = useMemo(() => {
    const m = new Map<string, CreationFlowPreviewEntry>()
    ;(creationFlowPreview?.entries ?? []).forEach((e) => {
      const name = String(e?.learner_name ?? '').trim()
      if (name) m.set(name, e)
    })
    return m
  }, [creationFlowPreview])

  const graphData = useMemo(() => {
    const nodeSet = new Set<string>()
    const weightedDegree = new Map<string, number>()
    const rawLinks: LinkData[] = []

    pairRows.forEach((row) => {
      const a = row.learner_a_raw
      const b = row.learner_b_raw
      const weight = Number(row.jaccard_acceptance || 0)
      if (!a || !b || a === b || Number.isNaN(weight) || weight < threshold) return
      nodeSet.add(a)
      nodeSet.add(b)
      rawLinks.push({
        source: a,
        target: b,
        value: weight,
        intersectionCount: Number(row.intersection_count || 0),
        unionCount: Number(row.union_count || 0),
        acceptCountA: Number(row.accept_count_a || 0),
        acceptCountB: Number(row.accept_count_b || 0),
        acceptRateAToB: Number(row.accept_rate_a_to_b || 0),
        acceptRateBToA: Number(row.accept_rate_b_to_a || 0),
      })
      weightedDegree.set(a, (weightedDegree.get(a) || 0) + weight)
      weightedDegree.set(b, (weightedDegree.get(b) || 0) + weight)
    })

    learnerMeta.ratioMap.forEach((_, name) => nodeSet.add(name))
    learnerDetailMap.forEach((_, name) => nodeSet.add(name))

    const nodes: NodeData[] = Array.from(nodeSet).map((id) => {
      const ratio = learnerMeta.ratioMap.has(id) ? learnerMeta.ratioMap.get(id)! : null
      const degree = weightedDegree.get(id) || 0
      const detail = learnerDetailMap.get(id)
      const samples = learnerMeta.sampleMap.get(id) ?? detail?.totalSamples ?? 0

      let color: string = notionTheme.chart.edge
      let borderColor: string = notionTheme.chart.nodeExternalBorder
      let borderWidth = 1.2
      if (ratio !== null) {
        if (ratio >= 0.3 && ratio <= 0.7) {
          color = notionTheme.chart.aggregate
          borderColor = notionTheme.chart.aggregateBorder
          borderWidth = 2.4
        } else if (ratio < 0.3) {
          color = notionTheme.chart.greenFill
          borderColor = CHART_GREEN_BORDER
          borderWidth = 1.2
        } else {
          color = notionTheme.chart.redFill
          borderColor = CHART_RED_BORDER
          borderWidth = 1.2
        }
      }

      const sampleSize = 8 + Math.sqrt(Math.max(0, samples)) * 0.06
      const symbolSize = sampleSize
      return {
        id,
        name: id,
        value: degree,
        ratio,
        degree,
        samples,
        symbolSize: Math.max(8, Math.min(symbolSize, 64)),
        itemStyle: { color, borderColor, borderWidth },
      }
    })

    const strongestNeighbor = new Map<string, { target: string; weight: number }>()
    rawLinks.forEach((link) => {
      const a = String(link.source)
      const b = String(link.target)
      const aw = strongestNeighbor.get(a)
      const bw = strongestNeighbor.get(b)
      if (!aw || link.value > aw.weight) strongestNeighbor.set(a, { target: b, weight: link.value })
      if (!bw || link.value > bw.weight) strongestNeighbor.set(b, { target: a, weight: link.value })
    })

    const edgeKey = (a: string, b: string) => [a, b].sort().join('::')
    let filteredRawLinks = rawLinks
    if (connectionMode === 'strongest') {
      const keep = new Set<string>()
      strongestNeighbor.forEach((v, k) => keep.add(edgeKey(k, v.target)))
      filteredRawLinks = rawLinks.filter((l) => keep.has(edgeKey(String(l.source), String(l.target))))
    } else if (connectionMode === 'mutual') {
      const keep = new Set<string>()
      strongestNeighbor.forEach((v, k) => {
        const rev = strongestNeighbor.get(v.target)
        if (rev && rev.target === k) keep.add(edgeKey(k, v.target))
      })
      filteredRawLinks = rawLinks.filter((l) => keep.has(edgeKey(String(l.source), String(l.target))))
    }

    const weights = filteredRawLinks.map((link) => link.value)
    const minWeight = weights.length > 0 ? Math.min(...weights) : 0
    const maxWeight = weights.length > 0 ? Math.max(...weights) : 0
    const links = filteredRawLinks.map((link) => {
      const scale = maxWeight > minWeight ? (link.value - minWeight) / (maxWeight - minWeight) : 0.5
      return {
        ...link,
        lineStyle: {
          width: 0.8 + scale * 3.5,
          opacity: 0.2 + scale * 0.45,
        },
      }
    })
    return { nodes, links }
  }, [pairRows, learnerMeta, learnerDetailMap, threshold, connectionMode])

  const option = useMemo(() => {
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: notionTheme.chart.white,
        borderColor: CHART_AXIS_LINE,
        textStyle: { color: CHART_TEXT_PRIMARY },
        formatter: (params: { dataType?: string; data: NodeData | LinkData }) => {
          if (params.dataType === 'edge') {
            const edge = params.data as LinkData
            return [
              `<b>${edge.source} ↔ ${edge.target}</b>`,
              `jaccard=${edge.value.toFixed(METRIC_DECIMAL_PLACES)}`,
              `intersection=${edge.intersectionCount}`,
              `union=${edge.unionCount}`,
              `A→B=${edge.acceptRateAToB.toFixed(METRIC_DECIMAL_PLACES)}`,
              `B→A=${edge.acceptRateBToA.toFixed(METRIC_DECIMAL_PLACES)}`,
            ].join('<br/>')
          }
          const node = params.data as NodeData
          const ratioText = node.ratio == null ? 'N/A' : node.ratio.toFixed(METRIC_DECIMAL_PLACES)
          const detail = learnerDetailMap.get(node.id)
          return [
            `<b>${node.id}</b>`,
            `attack_ratio=${ratioText}`,
            `samples=${Math.round(node.samples)}`,
            `degree=${node.degree.toFixed(METRIC_DECIMAL_PLACES)}`,
            `dominant=${detail?.dominantLabel ?? '-'}`,
            `dominant_ratio=${detail?.dominantRatio == null ? 'N/A' : detail.dominantRatio.toFixed(METRIC_DECIMAL_PLACES)}`,
          ].join('<br/>')
        },
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          data: graphData.nodes,
          links: graphData.links,
          lineStyle: { color: CHART_EDGE, opacity: 0.95, width: 1.6 },
          force: { repulsion, gravity: 0.08, edgeLength: [40, 180], layoutAnimation: true },
          label: { show: true, position: 'right', color: CHART_TEXT_PRIMARY, fontSize: 10 },
          emphasis: { focus: 'adjacency', lineStyle: { opacity: 0.9, width: 2.2 } },
        },
      ],
    }
  }, [graphData, learnerDetailMap, repulsion])

  const learnerTrendOption = useMemo(() => {
    const x = countRows.map((_, idx) => idx + 1)
    const learner = countRows.map((r) => Number(r.learner_count || 0))
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: x, axisLabel: { color: CHART_TEXT_SECONDARY } },
      yAxis: { type: 'value', axisLabel: { color: CHART_TEXT_SECONDARY } },
      series: [
        { name: 'Learner Count', type: 'line', data: learner, smooth: true, lineStyle: { color: notionTheme.chart.accent } },
      ],
    }
  }, [countRows])

  const unknownTrendOption = useMemo(() => {
    const x = countRows.map((_, idx) => idx + 1)
    const unknown = countRows.map((r) => Number(r.unknown_buffer_size || 0))
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: x, axisLabel: { color: CHART_TEXT_SECONDARY } },
      yAxis: { type: 'value', axisLabel: { color: CHART_TEXT_SECONDARY } },
      series: [
        { name: 'Unknown Buffer', type: 'line', data: unknown, smooth: true, lineStyle: { color: notionTheme.chart.orange } },
      ],
    }
  }, [countRows])

  const creationOption = useMemo(() => {
    const top = [...learnerRows]
      .map((r) => {
        const creation = Number(r.creation_sample_count || 0)
        const total = Number(r.total_assigned_samples || 0)
        const incrementalRaw = Number(r.post_creation_added_samples || 0)
        const incremental = Number.isFinite(incrementalRaw) && incrementalRaw >= 0 ? incrementalRaw : Math.max(0, total - creation)
        return { name: r.learner_name, creation, incremental, total: creation + incremental }
      })
      .sort((a, b) => b.total - a.total)
      .slice(0, 15)
      .reverse()
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { data: ['创建样本量', '增量匹配量'], textStyle: { color: CHART_TEXT_SECONDARY } },
      xAxis: { type: 'value', axisLabel: { color: CHART_TEXT_SECONDARY } },
      yAxis: { type: 'category', data: top.map((x) => x.name), axisLabel: { color: CHART_TEXT_SECONDARY } },
      series: [
        {
          name: '创建样本量',
          type: 'bar',
          stack: 'samples',
          data: top.map((x) => x.creation),
          itemStyle: { color: notionTheme.chart.accent },
        },
        {
          name: '增量匹配量',
          type: 'bar',
          stack: 'samples',
          data: top.map((x) => x.incremental),
          itemStyle: { color: notionTheme.chart.blue },
        },
      ],
    }
  }, [learnerRows])

  const retrainCountMap = useMemo(() => {
    const m = new Map<string, number>()
    trainBatchRows.forEach((row) => {
      const name = String(row.learner_name || '')
      if (!name) return
      if (String(row.stage || '').toLowerCase() !== 'increment') return
      m.set(name, (m.get(name) || 0) + 1)
    })
    return m
  }, [trainBatchRows])

  const learnerResidualCsvColumns = useMemo(() => {
    const cols = new Set<string>()
    learnerRows.forEach((row) => {
      Object.keys(row).forEach((k) => {
        if (!k || LEARNER_LABEL_CSV_PRIMARY_KEYS.has(k) || isDroppedStdVarianceColumn(k)) return
        cols.add(k)
      })
    })
    return [...cols].sort((a, b) => a.localeCompare(b))
  }, [learnerRows])

  const learnerResidualColSet = useMemo(() => new Set(learnerResidualCsvColumns), [learnerResidualCsvColumns])

  const learnerMetricDisplayColumns = useMemo(
    () => buildMetricTableColumns(learnerResidualCsvColumns),
    [learnerResidualCsvColumns],
  )

  const retrainTopOption = useMemo(() => {
    const top = Array.from(retrainCountMap.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
      .reverse()
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'value', axisLabel: { color: CHART_TEXT_SECONDARY } },
      yAxis: { type: 'category', data: top.map((x) => x.name), axisLabel: { color: CHART_TEXT_SECONDARY } },
      series: [{ type: 'bar', data: top.map((x) => x.value), itemStyle: { color: notionTheme.chart.blue } }],
    }
  }, [retrainCountMap])

  const datasetLabelAll = useMemo(() => {
    const mappedRows = [...datasetLabelRows]
      .map((r) => ({
        label: String(r.label),
        count: Number(r.count || 0),
        ratio: Number(r.ratio || 0),
        isBenign: String(r.is_benign).toLowerCase() === 'true',
        yearTag: String(r.year_tag || ''),
        baseLabel: String(r.base_label || ''),
        protocolType: String(r.protocol_cluster_type || 'UNKNOWN'),
        protocolConcentration: Number(r.protocol_concentration || 0),
        protocolTcpRatio: Number(r.protocol_tcp_ratio || 0),
        protocolUdpRatio: Number(r.protocol_udp_ratio || 0),
        raw: r,
      }))
    const toSortableNumber = (v: unknown, missing: number): number => {
      const n = Number(v)
      return Number.isFinite(n) ? n : missing
    }
    const getSortValue = (row: typeof mappedRows[number], key: string): string | number => {
      switch (key) {
        case 'label':
          return row.label
        case 'count':
          return row.count
        case 'ratio':
          return row.ratio
        case 'type':
          return row.isBenign ? 1 : 0
        case 'yearTag':
          return Number(row.yearTag) || 0
        case 'baseLabel':
          return row.baseLabel
        case 'protocolType':
          return row.protocolType
        case 'protocolConcentration':
          return row.protocolConcentration
        case 'protocolTcpRatio':
          return row.protocolTcpRatio
        case 'protocolUdpRatio':
          return row.protocolUdpRatio
        default: {
          if (isMetricColComboId(key)) {
            const base = metricColComboBase(key)
            const meanKey = `${base}__mean`
            const rawVal = row.raw[meanKey] as string | boolean | undefined
            const asNum = Number(rawVal ?? NaN)
            if (Number.isFinite(asNum)) return asNum
            return String(rawVal ?? '')
          }
          const rawVal = row.raw[key] as string | boolean | undefined
          const asNum = Number(rawVal ?? NaN)
          if (Number.isFinite(asNum)) return asNum
          return String(rawVal ?? '')
        }
      }
    }
    return mappedRows.sort((a, b) => {
      const av = getSortValue(a, datasetSortBy)
      const bv = getSortValue(b, datasetSortBy)
      if (typeof av === 'string' || typeof bv === 'string') {
        const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
        return datasetSortDir === 'asc' ? cmp : -cmp
      }
      const na = toSortableNumber(av, datasetSortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY)
      const nb = toSortableNumber(bv, datasetSortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY)
      if (na === nb) return b.count - a.count
      return datasetSortDir === 'asc' ? na - nb : nb - na
    })
  }, [datasetLabelRows, datasetSortBy, datasetSortDir])

  const allRadarLabels = useMemo(() => datasetLabelAll.map((r) => r.label), [datasetLabelAll])

  const effectiveRadarLabels = useMemo(() => {
    if (radarLabelSelection === null) return allRadarLabels
    const ok = new Set(allRadarLabels)
    return radarLabelSelection.filter((l) => ok.has(l))
  }, [allRadarLabels, radarLabelSelection])

  const datasetMetricColumns = useMemo(() => {
    const excluded = new Set([
      'label',
      'count',
      'ratio',
      'is_benign',
      'year_tag',
      'base_label',
      'protocol_cluster_type',
      'protocol_concentration',
      'protocol_tcp_ratio',
      'protocol_udp_ratio',
    ])
    const seen = new Set<string>()
    const columns: string[] = []
    datasetLabelRows.forEach((row) => {
      Object.keys(row).forEach((key) => {
        if (
          !key ||
          excluded.has(key) ||
          seen.has(key) ||
          isDroppedStdVarianceColumn(key)
        ) return
        seen.add(key)
        columns.push(key)
      })
    })
    return columns
  }, [datasetLabelRows])

  const datasetMetricDisplayColumns = useMemo(
    () => buildMetricTableColumns(datasetMetricColumns),
    [datasetMetricColumns],
  )

  const datasetColumnOptions = useMemo(() => {
    const fixed = [
      { value: 'label', label: 'Label' },
      { value: 'count', label: 'Count' },
      { value: 'ratio', label: 'Ratio' },
      { value: 'type', label: 'Type' },
      { value: 'yearTag', label: 'Year' },
      { value: 'baseLabel', label: 'Base Label' },
      { value: 'protocolType', label: '协议簇类型' },
      { value: 'protocolConcentration', label: '协议聚集性' },
      { value: 'protocolTcpRatio', label: 'TCP占比' },
      { value: 'protocolUdpRatio', label: 'UDP占比' },
    ]
    return [
      ...fixed,
      ...datasetMetricDisplayColumns.map((col) => ({
        value: col.id,
        label: metricTableColumnLabel(col),
      })),
    ]
  }, [datasetMetricDisplayColumns])

  const datasetSortColumnLabel = useMemo(() => {
    const opt = datasetColumnOptions.find((o) => o.value === datasetSortBy)
    return opt?.label ?? datasetSortBy
  }, [datasetColumnOptions, datasetSortBy])

  const effectiveDatasetVisibleColumns = useMemo(() => {
    const all = datasetColumnOptions.map((x) => x.value)
    const normalized = normalizeMetricVisibleColumnIds(datasetVisibleColumns, datasetMetricDisplayColumns)
    const valid = normalized.filter((x) => all.includes(x))
    // First load defaults to all columns; once user customizes, honor exact selection (including empty).
    if (!datasetColumnsCustomized && valid.length === 0) return all
    return valid
  }, [datasetColumnOptions, datasetVisibleColumns, datasetColumnsCustomized, datasetMetricDisplayColumns])

  const datasetVisibleColumnSet = useMemo(() => new Set(effectiveDatasetVisibleColumns), [effectiveDatasetVisibleColumns])

  const visibleDatasetMetricDisplayColumns = useMemo(
    () => datasetMetricDisplayColumns.filter((col) => isMetricDisplayColumnVisible(col, datasetVisibleColumnSet)),
    [datasetMetricDisplayColumns, datasetVisibleColumnSet],
  )

  const filteredDatasetLabelRows = useMemo(() => {
    const tags = datasetFilterTags.map((t) => t.trim().toLowerCase()).filter(Boolean)
    if (!tags.length) return datasetLabelAll
    return datasetLabelAll.filter((row) => {
      const haystack = [
        row.label,
        row.baseLabel,
        row.yearTag,
        row.protocolType,
        row.isBenign ? 'benign' : 'attack',
      ]
        .join(' ')
        .toLowerCase()
      return tags.every((tag) => haystack.includes(tag))
    })
  }, [datasetLabelAll, datasetFilterTags])

  const datasetBenignAttackStats = useMemo(() => {
    let benign = 0
    let attack = 0
    const yearMap = new Map<string, { benign: number; attack: number }>()

    datasetLabelAll.forEach((row) => {
      if (row.isBenign) {
        benign += row.count
      } else {
        attack += row.count
      }
      const yearKey = row.yearTag || 'unknown'
      const current = yearMap.get(yearKey) || { benign: 0, attack: 0 }
      if (row.isBenign) {
        current.benign += row.count
      } else {
        current.attack += row.count
      }
      yearMap.set(yearKey, current)
    })

    const years = Array.from(yearMap.entries())
      .map(([year, val]) => ({
        year,
        benign: val.benign,
        attack: val.attack,
        total: val.benign + val.attack,
      }))
      .sort((a, b) => a.year.localeCompare(b.year, undefined, { numeric: true }))

    return {
      benign,
      attack,
      total: benign + attack,
      years,
    }
  }, [datasetLabelAll])

  const datasetOverallOption = useMemo(() => {
    const { benign, attack, total } = datasetBenignAttackStats
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: { name?: string; value?: number }) => {
          const name = params.name || '-'
          const value = Number(params.value || 0)
          const ratio = total > 0 ? (value / total) * 100 : 0
          return `${name}<br/>数量: ${value.toLocaleString()}<br/>占比: ${ratio.toFixed(METRIC_DECIMAL_PLACES)}%`
        },
      },
      legend: {
        bottom: 0,
        textStyle: { color: CHART_TEXT_SECONDARY },
      },
      series: [
        {
          type: 'pie',
          radius: ['48%', '74%'],
          center: ['50%', '45%'],
          label: { color: CHART_TEXT_PRIMARY, formatter: '{b}: {d}%' },
          data: [
            { name: '正常(BENIGN)', value: benign, itemStyle: { color: CHART_GREEN } },
            { name: '异常(ATTACK)', value: attack, itemStyle: { color: CHART_RED } },
          ],
        },
      ],
    }
  }, [datasetBenignAttackStats])

  const datasetYearlyRatioOption = useMemo(() => {
    const years = datasetBenignAttackStats.years
    const yearLabels = years.map((x) => (x.year && x.year !== 'unknown' ? x.year : 'Unknown'))
    const benignRatio = years.map((x) => (x.total > 0 ? (x.benign / x.total) * 100 : 0))
    const attackRatio = years.map((x) => (x.total > 0 ? (x.attack / x.total) * 100 : 0))

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: Array<{ axisValue?: string; seriesName?: string; value?: number; dataIndex?: number }>) => {
          if (!params.length) return ''
          const idx = Number(params[0].dataIndex || 0)
          const row = years[idx]
          if (!row) return ''
          const benignPct = row.total > 0 ? (row.benign / row.total) * 100 : 0
          const attackPct = row.total > 0 ? (row.attack / row.total) * 100 : 0
          return [
            `${params[0].axisValue || '-'}`,
            `正常: ${row.benign.toLocaleString()} (${benignPct.toFixed(METRIC_DECIMAL_PLACES)}%)`,
            `异常: ${row.attack.toLocaleString()} (${attackPct.toFixed(METRIC_DECIMAL_PLACES)}%)`,
            `总量: ${row.total.toLocaleString()}`,
          ].join('<br/>')
        },
      },
      legend: {
        top: 0,
        textStyle: { color: CHART_TEXT_SECONDARY },
      },
      grid: { left: 48, right: 24, top: 36, bottom: 32 },
      xAxis: {
        type: 'category',
        data: yearLabels,
        axisLabel: { color: CHART_TEXT_SECONDARY },
        axisLine: { lineStyle: { color: CHART_AXIS_LINE } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { color: CHART_TEXT_SECONDARY, formatter: '{value}%' },
        splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
      },
      series: [
        {
          name: '正常占比',
          type: 'bar',
          stack: 'ratio',
          data: benignRatio,
          itemStyle: { color: CHART_GREEN },
        },
        {
          name: '异常占比',
          type: 'bar',
          stack: 'ratio',
          data: attackRatio,
          itemStyle: { color: CHART_RED },
        },
      ],
    }
  }, [datasetBenignAttackStats])

  const datasetLabelFilteredCorrRows = useMemo(() => {
    return [...(datasetLabelFeatureCorr?.rows || [])].filter((row) => {
      const feature = String(row.feature || '').trim()
      const lowered = feature.toLowerCase()
      if (!feature) return false
      if (lowered === 'count' || lowered === 'ratio') return false
      if (isDroppedStdVarianceColumn(feature)) return false
      return true
    })
  }, [datasetLabelFeatureCorr])

  const datasetLabelTopCorrRows = useMemo(() => {
    return [...datasetLabelFilteredCorrRows]
      .sort((a, b) => Number(b.abs_pearson_corr || 0) - Number(a.abs_pearson_corr || 0))
      .slice(0, 24)
  }, [datasetLabelFilteredCorrRows])

  const datasetLabelFeatureCorrOption = useMemo(() => {
    const labels = datasetLabelTopCorrRows.map((r) => metricDisplayName(r.feature)).reverse()
    const values = datasetLabelTopCorrRows.map((r) => Number(r.pearson_corr || 0)).reverse()
    const colors = values.map((v) => (v >= 0 ? CHART_RED : CHART_GREEN))
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 240, right: 28, top: 24, bottom: 24 },
      xAxis: {
        type: 'value',
        min: -1,
        max: 1,
        axisLabel: { color: CHART_TEXT_SECONDARY },
        splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: CHART_TEXT_SECONDARY, fontSize: 10 },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
        },
      ],
    }
  }, [datasetLabelTopCorrRows])

  const datasetLabelTopFeatureRadarOption = useMemo(() => {
    const topFeatures = datasetLabelTopCorrRows.slice(0, 5)
    if (!topFeatures.length) {
      return EMPTY_RADAR_CHART_OPTION
    }

    const visibleSet = new Set(effectiveRadarLabels)
    const labels = [...datasetLabelAll]
      .filter((row) => visibleSet.has(row.label))
      .sort((a, b) => b.count - a.count)
    if (!labels.length) {
      return EMPTY_RADAR_CHART_OPTION
    }
    const featureRows = topFeatures.map((featureRow) => {
      const feature = String(featureRow.feature || '')
      let maxAbs = 0
      labels.forEach((row) => {
        const rawVal = row.raw[feature] as string | boolean | undefined
        const featureValue = Number(rawVal ?? NaN)
        if (!Number.isFinite(featureValue)) return
        maxAbs = Math.max(maxAbs, Math.abs(featureValue))
      })
      return { feature, scaleBase: Math.max(maxAbs, 1e-6) }
    })

    const radarIndicator = featureRows.map((row) => ({
      name: metricDisplayName(row.feature),
      max: 100,
      min: 0,
    }))

    const seriesData = labels.map((row) => {
      const values = featureRows.map((featureRow) => {
        const rawVal = row.raw[featureRow.feature] as string | boolean | undefined
        const featureValue = Number(rawVal ?? NaN)
        if (!Number.isFinite(featureValue)) return 0
        return (Math.abs(featureValue) / featureRow.scaleBase) * 100
      })
      const color = row.isBenign ? CHART_GREEN : CHART_RED
      const areaColor = row.isBenign ? 'rgba(74, 222, 128, 0.08)' : 'rgba(251, 113, 133, 0.08)'
      return {
        value: values,
        name: row.label,
        lineStyle: { color, width: 1 },
        itemStyle: { color },
        areaStyle: { color: areaColor },
      }
    })

    return {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: { seriesName?: string; value?: number[] }) => {
          const values = Array.isArray(params.value) ? params.value : []
          const target = labels.find((x) => x.label === params.seriesName)
          const flowType = target ? (target.isBenign ? '良性流量' : '恶意流量') : '未知'
          const header = `${params.seriesName || '-'}<br/>流量类型: ${flowType}`
          const lines = featureRows.map((row, idx) => {
            const normalized = Number(values[idx] ?? 0)
            const rawVal = target ? Number((target.raw[row.feature] as string | boolean | undefined) ?? NaN) : NaN
            const raw = Number.isFinite(rawVal) ? rawVal : 0
            return `${metricDisplayName(row.feature)}: ${normalized.toFixed(METRIC_DECIMAL_PLACES)} (原值 ${raw.toFixed(METRIC_DECIMAL_PLACES)})`
          })
          return [header, ...lines].join('<br/>')
        },
      },
      radar: {
        center: ['50%', '56%'],
        radius: '66%',
        indicator: radarIndicator,
        axisName: {
          color: CHART_TEXT_SECONDARY,
          fontSize: 10,
        },
        splitArea: {
          areaStyle: {
            color: ['rgba(148, 163, 184, 0.02)', 'rgba(148, 163, 184, 0.05)'],
          },
        },
        splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
        axisLine: { lineStyle: { color: CHART_AXIS_LINE } },
      },
      series: [
        {
          type: 'radar',
          symbol: 'none',
          data: seriesData,
        },
      ],
    }
  }, [datasetLabelAll, datasetLabelTopCorrRows, effectiveRadarLabels])

  useEffect(() => {
    if (!chartRef.current) return
    const chart = chartInstanceRef.current ?? echarts.init(chartRef.current)
    chartInstanceRef.current = chart
    chart.setOption(option, true)
    chart.off('click')
    chart.on('click', (params) => {
      if (params.dataType === 'node') {
        const node = params.data as NodeData
        setSelectedNodeId(node.id)
        setSelectedEdge(null)
      } else if (params.dataType === 'edge') {
        setSelectedEdge(params.data as LinkData)
        setSelectedNodeId(null)
      }
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [option])

  useEffect(() => {
    return () => {
      chartInstanceRef.current?.dispose()
      chartInstanceRef.current = null
    }
  }, [])

  const allLearnerRows = useMemo(() => {
    const list = learnerRows.map((row) => {
      const residualCsv = Object.fromEntries(
        learnerResidualCsvColumns.map((col) => [col, String(row[col as keyof typeof row] ?? '')]),
      ) as Record<string, string>
      return {
      name: row.learner_name,
      attackRatio: Number(row.attack_ratio || 0),
      samples: Number(row.total_assigned_samples || 0),
      creationSamples: Number(row.creation_sample_count || 0),
      retrainCount: retrainCountMap.get(row.learner_name) || 0,
      protocolType: String(row.protocol_cluster_type || 'UNKNOWN'),
      protocolConcentration: Number(row.protocol_concentration || 0),
      tcpRatio: Number(row.protocol_tcp_ratio || 0),
      udpRatio: Number(row.protocol_udp_ratio || 0),
      dominantLabel: row.dominant_label || '-',
      dominantRatio: Number(row.dominant_ratio || 0),
      residualCsv,
    }})
    const tags = learnerFilterTags.map((t) => t.trim().toLowerCase()).filter(Boolean)
    const filtered = tags.length
      ? list.filter((r) => {
          const haystack = [r.name, r.dominantLabel, r.protocolType].join(' ').toLowerCase()
          return tags.every((tag) => haystack.includes(tag))
        })
      : list
    const sorted = [...filtered].sort((a, b) => {
      if (learnerSortBy === 'name' || learnerSortBy === 'dominantLabel' || learnerSortBy === 'protocolType') {
        const va = String((a as Record<string, unknown>)[learnerSortBy] ?? '')
        const vb = String((b as Record<string, unknown>)[learnerSortBy] ?? '')
        const cmp = va.localeCompare(vb)
        return learnerSortDir === 'asc' ? cmp : -cmp
      }
      if (learnerResidualColSet.has(learnerSortBy) || isMetricColComboId(learnerSortBy)) {
        const sortKey = isMetricColComboId(learnerSortBy)
          ? `${metricColComboBase(learnerSortBy)}__mean`
          : learnerSortBy
        const sa = (a.residualCsv[sortKey] ?? '').trim()
        const sb = (b.residualCsv[sortKey] ?? '').trim()
        const na = Number(sa)
        const nb = Number(sb)
        const aNum = sa !== '' && Number.isFinite(na)
        const bNum = sb !== '' && Number.isFinite(nb)
        if (aNum && bNum) return learnerSortDir === 'asc' ? na - nb : nb - na
        const cmp = sa.localeCompare(sb, undefined, { numeric: true, sensitivity: 'base' })
        return learnerSortDir === 'asc' ? cmp : -cmp
      }
      const vaRaw = (a as Record<string, unknown>)[learnerSortBy]
      const vbRaw = (b as Record<string, unknown>)[learnerSortBy]
      const va = Number.isFinite(Number(vaRaw)) ? Number(vaRaw) : (learnerSortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY)
      const vb = Number.isFinite(Number(vbRaw)) ? Number(vbRaw) : (learnerSortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY)
      return learnerSortDir === 'asc' ? va - vb : vb - va
    })
    return sorted
  }, [learnerRows, retrainCountMap, learnerFilterTags, learnerSortBy, learnerSortDir, learnerResidualCsvColumns, learnerResidualColSet])

  const allLearnerRadarNames = useMemo(() => allLearnerRows.map((r) => r.name), [allLearnerRows])

  const effectiveLearnerRadarNames = useMemo(() => {
    if (learnerRadarNameSelection === null) return allLearnerRadarNames
    const ok = new Set(allLearnerRadarNames)
    return learnerRadarNameSelection.filter((n) => ok.has(n))
  }, [allLearnerRadarNames, learnerRadarNameSelection])

  const learnerColumnOptions = useMemo(() => {
    const fixed = [
      { value: 'name', label: 'Learner' },
      { value: 'attackRatio', label: 'Attack Ratio' },
      { value: 'samples', label: '总样本' },
      { value: 'creationSamples', label: '创建样本' },
      { value: 'retrainCount', label: '重训次数' },
      { value: 'protocolType', label: '协议簇类型' },
      { value: 'protocolConcentration', label: '协议聚集性' },
      { value: 'tcpRatio', label: 'TCP占比' },
      { value: 'udpRatio', label: 'UDP占比' },
      { value: 'dominantLabel', label: '主导标签' },
      { value: 'dominantRatio', label: '主导占比' },
    ]
    return [
      ...fixed,
      ...learnerMetricDisplayColumns.map((col) => ({
        value: col.id,
        label: metricTableColumnLabel(col),
      })),
    ]
  }, [learnerMetricDisplayColumns])

  const learnerSortColumnLabel = useMemo(() => {
    const opt = learnerColumnOptions.find((o) => o.value === learnerSortBy)
    return opt?.label ?? learnerSortBy
  }, [learnerColumnOptions, learnerSortBy])

  const effectiveLearnerVisibleColumns = useMemo(() => {
    const all = learnerColumnOptions.map((x) => x.value)
    const normalized = normalizeMetricVisibleColumnIds(learnerVisibleColumns, learnerMetricDisplayColumns)
    const valid = normalized.filter((x) => all.includes(x))
    // First load defaults to all columns; once user customizes, honor exact selection (including empty).
    if (!learnerColumnsCustomized && valid.length === 0) return all
    return valid
  }, [learnerColumnOptions, learnerVisibleColumns, learnerColumnsCustomized, learnerMetricDisplayColumns])

  const learnerVisibleColumnSet = useMemo(() => new Set(effectiveLearnerVisibleColumns), [effectiveLearnerVisibleColumns])

  const visibleLearnerMetricDisplayColumns = useMemo(
    () => learnerMetricDisplayColumns.filter((col) => isMetricDisplayColumnVisible(col, learnerVisibleColumnSet)),
    [learnerMetricDisplayColumns, learnerVisibleColumnSet],
  )

  const datasetColumnPickerContent = useMemo(() => (
    <div className="max-h-72 w-72 overflow-auto pr-1">
      <Checkbox.Group
        value={effectiveDatasetVisibleColumns}
        onChange={(checkedValues) => setDatasetVisibleColumns((checkedValues as Array<string | number>).map((v) => String(v)))}
        className="flex flex-col gap-2"
      >
        {datasetColumnOptions.map((opt) => (
          <Checkbox key={opt.value} value={opt.value}>
            {opt.label}
          </Checkbox>
        ))}
      </Checkbox.Group>
    </div>
  ), [datasetColumnOptions, effectiveDatasetVisibleColumns, setDatasetVisibleColumns])

  const learnerColumnPickerContent = useMemo(() => (
    <div className="max-h-72 w-72 overflow-auto pr-1">
      <Checkbox.Group
        value={effectiveLearnerVisibleColumns}
        onChange={(checkedValues) => setLearnerVisibleColumns((checkedValues as Array<string | number>).map((v) => String(v)))}
        className="flex flex-col gap-2"
      >
        {learnerColumnOptions.map((opt) => (
          <Checkbox key={opt.value} value={opt.value}>
            {opt.label}
          </Checkbox>
        ))}
      </Checkbox.Group>
    </div>
  ), [learnerColumnOptions, effectiveLearnerVisibleColumns, setLearnerVisibleColumns])

  const sortIndicator = (active: boolean, dir: 'asc' | 'desc'): string => {
    if (!active) return '↕'
    return dir === 'asc' ? '↑' : '↓'
  }

  const toggleDatasetSort = (key: string) => {
    if (datasetSortBy === key) {
      setDatasetSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      return
    }
    setDatasetSortBy(key)
    setDatasetSortDir('desc')
  }

  const toggleLearnerSort = (key: string) => {
    if (learnerSortBy === key) {
      setLearnerSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      return
    }
    setLearnerSortBy(key)
    setLearnerSortDir('desc')
  }

  const datasetColumnStyle = (key: string) => (
    datasetVisibleColumnSet.has(key) ? undefined : { display: 'none' }
  )

  const learnerColumnStyle = (key: string) => (
    learnerVisibleColumnSet.has(key) ? undefined : { display: 'none' }
  )

  const learnerFilteredCorrRows = useMemo(() => {
    return [...(featureCorr?.rows || [])].filter((row) => {
      const feature = String(row.feature || '').trim()
      const lowered = feature.toLowerCase()
      if (!feature) return false
      if (lowered === 'count' || lowered === 'ratio') return false
      if (isDroppedStdVarianceColumn(feature)) return false
      return true
    })
  }, [featureCorr])

  const learnerTopCorrRows = useMemo(() => {
    return [...learnerFilteredCorrRows]
      .sort((a, b) => Number(b.abs_pearson_corr || 0) - Number(a.abs_pearson_corr || 0))
      .slice(0, 24)
  }, [learnerFilteredCorrRows])

  const featureCorrOption = useMemo(() => {
    const labels = learnerTopCorrRows.map((r) => metricDisplayName(r.feature)).reverse()
    const values = learnerTopCorrRows.map((r) => Number(r.pearson_corr || 0)).reverse()
    const colors = values.map((v) => (v >= 0 ? CHART_RED : CHART_GREEN))
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      grid: { left: 240, right: 28, top: 24, bottom: 24 },
      xAxis: {
        type: 'value',
        min: -1,
        max: 1,
        axisLabel: { color: CHART_TEXT_SECONDARY },
        splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: CHART_TEXT_SECONDARY, fontSize: 10 },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v, i) => ({
            value: v,
            itemStyle: { color: colors[i] },
          })),
        },
      ],
    }
  }, [learnerTopCorrRows])

  const learnerTopFeatureRadarOption = useMemo(() => {
    const topFeatures = learnerTopCorrRows.slice(0, 5)
    if (!topFeatures.length) {
      return EMPTY_RADAR_CHART_OPTION
    }

    const visibleSet = new Set(effectiveLearnerRadarNames)
    const learners = [...allLearnerRows]
      .filter((row) => visibleSet.has(row.name))
      .sort((a, b) => b.samples - a.samples)
    if (!learners.length) {
      return EMPTY_RADAR_CHART_OPTION
    }

    const featureRows = topFeatures.map((featureRow) => {
      const feature = String(featureRow.feature || '')
      let maxAbs = 0
      learners.forEach((row) => {
        const rawVal = Number((learnerDistRowByName.get(row.name)?.[feature] as string | undefined) ?? NaN)
        if (!Number.isFinite(rawVal)) return
        maxAbs = Math.max(maxAbs, Math.abs(rawVal))
      })
      return { feature, scaleBase: Math.max(maxAbs, 1e-6) }
    })

    const radarIndicator = featureRows.map((row) => ({
      name: metricDisplayName(row.feature),
      max: 100,
      min: 0,
    }))

    const seriesData = learners.map((row) => {
      const rawLearner = learnerDistRowByName.get(row.name)
      const values = featureRows.map((featureRow) => {
        const rawVal = Number((rawLearner?.[featureRow.feature] as string | undefined) ?? NaN)
        if (!Number.isFinite(rawVal)) return 0
        return (Math.abs(rawVal) / featureRow.scaleBase) * 100
      })
      const isAttackLike = row.attackRatio >= 0.5
      const color = isAttackLike ? CHART_RED : CHART_GREEN
      const areaColor = isAttackLike ? 'rgba(251, 113, 133, 0.08)' : 'rgba(74, 222, 128, 0.08)'
      return {
        value: values,
        name: row.name,
        lineStyle: { color, width: 1 },
        itemStyle: { color },
        areaStyle: { color: areaColor },
      }
    })

    return {
      animation: false,
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: { seriesName?: string; value?: number[] }) => {
          const values = Array.isArray(params.value) ? params.value : []
          const target = learners.find((x) => x.name === params.seriesName)
          const rawTarget = params.seriesName ? learnerDistRowByName.get(params.seriesName) : undefined
          const flowType = target && target.attackRatio >= 0.5 ? '恶意倾向流量' : '良性倾向流量'
          const header = `${params.seriesName || '-'}<br/>流量类型: ${flowType}${
            target ? `<br/>attack_ratio: ${(target.attackRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%` : ''
          }`
          const lines = featureRows.map((row, idx) => {
            const normalized = Number(values[idx] ?? 0)
            const rawVal = Number((rawTarget?.[row.feature] as string | undefined) ?? NaN)
            const raw = Number.isFinite(rawVal) ? rawVal : 0
            return `${metricDisplayName(row.feature)}: ${normalized.toFixed(METRIC_DECIMAL_PLACES)} (原值 ${raw.toFixed(METRIC_DECIMAL_PLACES)})`
          })
          return [header, ...lines].join('<br/>')
        },
      },
      radar: {
        center: ['50%', '56%'],
        radius: '66%',
        indicator: radarIndicator,
        axisName: { color: CHART_TEXT_SECONDARY, fontSize: 10 },
        splitArea: { areaStyle: { color: ['rgba(148, 163, 184, 0.02)', 'rgba(148, 163, 184, 0.05)'] } },
        splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
        axisLine: { lineStyle: { color: CHART_AXIS_LINE } },
      },
      series: [{ type: 'radar', symbol: 'none', data: seriesData }],
    }
  }, [allLearnerRows, learnerDistRowByName, learnerTopCorrRows, effectiveLearnerRadarNames])

  const datasetTableColumnStats = useMemo(() => {
    const rows = filteredDatasetLabelRows
    const agg = (getter: (r: (typeof rows)[0]) => number): ColumnStatAggregate | null => {
      const vals: number[] = []
      for (const row of rows) {
        const x = getter(row)
        if (Number.isFinite(x)) vals.push(x)
      }
      return computeNumericColumnStats(vals)
    }
    const out: Record<string, ColumnStatAggregate | null> = {
      label: null,
      type: null,
      baseLabel: null,
      protocolType: null,
      count: agg((r) => r.count),
      ratio: agg((r) => r.ratio),
      yearTag: agg((r) => {
        const n = Number(r.yearTag)
        return Number.isFinite(n) ? n : Number.NaN
      }),
      protocolConcentration: agg((r) => r.protocolConcentration),
      protocolTcpRatio: agg((r) => r.protocolTcpRatio),
      protocolUdpRatio: agg((r) => r.protocolUdpRatio),
    }
    for (const col of datasetMetricDisplayColumns) {
      if (col.kind === 'mean_cv') {
        out[col.id] = agg((r) => {
          const raw = r.raw[col.meanCol] as string | boolean | undefined
          if (typeof raw === 'boolean') return raw ? 1 : 0
          const s = String(raw ?? '').trim()
          if (!s) return Number.NaN
          return Number(s)
        })
        continue
      }
      out[col.id] = agg((r) => {
        const raw = r.raw[col.col] as string | boolean | undefined
        if (typeof raw === 'boolean') return raw ? 1 : 0
        const s = String(raw ?? '').trim()
        if (!s) return Number.NaN
        return Number(s)
      })
    }
    return out
  }, [filteredDatasetLabelRows, datasetMetricDisplayColumns])

  const learnerTableColumnStats = useMemo(() => {
    const rows = allLearnerRows
    const agg = (getter: (r: (typeof rows)[0]) => number): ColumnStatAggregate | null => {
      const vals: number[] = []
      for (const row of rows) {
        const x = getter(row)
        if (Number.isFinite(x)) vals.push(x)
      }
      return computeNumericColumnStats(vals)
    }
    const out: Record<string, ColumnStatAggregate | null> = {
      name: null,
      protocolType: null,
      dominantLabel: null,
      attackRatio: agg((r) => r.attackRatio),
      samples: agg((r) => r.samples),
      creationSamples: agg((r) => r.creationSamples),
      retrainCount: agg((r) => r.retrainCount),
      protocolConcentration: agg((r) => r.protocolConcentration),
      tcpRatio: agg((r) => r.tcpRatio),
      udpRatio: agg((r) => r.udpRatio),
      dominantRatio: agg((r) => r.dominantRatio),
    }
    for (const col of learnerMetricDisplayColumns) {
      if (col.kind === 'single' && (/_json$/i.test(col.col) || col.col === 'label_distribution_json')) {
        out[col.id] = null
        continue
      }
      if (col.kind === 'mean_cv') {
        out[col.id] = agg((r) => {
          const s = String(r.residualCsv[col.meanCol] ?? '').trim()
          if (!s) return Number.NaN
          return Number(s)
        })
        continue
      }
      out[col.id] = agg((r) => {
        const s = String(r.residualCsv[col.col] ?? '').trim()
        if (!s) return Number.NaN
        return Number(s)
      })
    }
    return out
  }, [allLearnerRows, learnerMetricDisplayColumns])

  const selectedDetail = selectedNodeId ? learnerDetailMap.get(selectedNodeId) : null

  const selectedCreationPreview =
    selectedNodeId && !selectedEdge ? creationPreviewByLearner.get(selectedNodeId) ?? null : null

  return (
    <div className="space-y-5">
      <section className="panel">
        <p className="eyebrow">Threat Relationship Intelligence</p>
        <h1 className="text-2xl font-semibold tracking-wide text-notion-text">
          Run 详情
        </h1>
        <p className="mt-1 text-sm text-notion-secondary">
          {detailMode ? `当前路由: ${overviewPaths.run(routeRunId)}` : ''}
        </p>
        {detailMode ? (
          <p className="mt-2 text-xs text-notion-secondary">
            <Link to={overviewPaths.runDetail} className="hover:underline text-notion-accent">返回总览</Link>
          </p>
        ) : null}
      </section>

      <section className="panel space-y-3">
        <div className="grid gap-3 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <label className="field-label">Run</label>
            {detailMode ? (
              <div className="input-base w-full font-mono text-xs">{selectedRunId}</div>
            ) : (
              <select
                value={selectedRunId}
                onChange={(e) => setSelectedRunId(e.target.value)}
                className="input-base w-full font-mono text-xs"
              >
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.id}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        {loading ? <p className="text-sm text-notion-secondary">正在载入图谱数据...</p> : null}
        {error ? <p className="text-sm text-notion-danger">{error}</p> : null}
      </section>

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <article className="metric-card"><p className="metric-label">Risk FPR</p><p className="metric-value">{kpi.fpr == null ? '-' : `${(kpi.fpr * 100).toFixed(METRIC_DECIMAL_PLACES)}%`}</p></article>
        <article className="metric-card"><p className="metric-label">Risk FNR</p><p className="metric-value">{kpi.fnr == null ? '-' : `${(kpi.fnr * 100).toFixed(METRIC_DECIMAL_PLACES)}%`}</p></article>
        <article className="metric-card"><p className="metric-label">Risk TPR</p><p className="metric-value">{kpi.tpr == null ? '-' : `${(kpi.tpr * 100).toFixed(METRIC_DECIMAL_PLACES)}%`}</p></article>
        <article className="metric-card"><p className="metric-label">Windows</p><p className="metric-value">{kpi.windows ?? '-'}</p></article>
        <article className="metric-card"><p className="metric-label">New Learners</p><p className="metric-value">{kpi.newLearners ?? '-'}</p></article>
        <article className="metric-card"><p className="metric-label">Aggregates</p><p className="metric-value">{kpi.aggregateCount ?? '-'}</p></article>
      </section>

      <section className="panel">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">数据集标签分布（Run输入，全量）</h2>
        <div className="mb-3 text-xs text-notion-secondary">
          rows={datasetLabelSummary?.total_rows ?? '-'} | labels={datasetLabelSummary?.label_count ?? datasetLabelRows.length}
          {' '}| benign={datasetLabelSummary?.benign_rows ?? '-'} | attack={datasetLabelSummary?.attack_rows ?? '-'}
        </div>
        <article className="mb-4 rounded-lg border border-notion-border bg-notion-surface p-3">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-notion-secondary">
            数据集网络拓扑（IP / 端口）
          </h3>
          <NetworkTopologyPanel
            data={datasetNetworkTopology}
            labelOptions={datasetLabelRows.map((r) => r.label).filter(Boolean)}
          />
        </article>
        <div className="mb-4 grid gap-4 xl:grid-cols-2">
          <article className="rounded-lg border border-notion-border bg-notion-surface p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-notion-secondary">总体正常/异常占比</h3>
            <ReactECharts option={datasetOverallOption} style={{ height: 250 }} />
          </article>
          <article className="rounded-lg border border-notion-border bg-notion-surface p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-notion-secondary">每年正常/异常占比</h3>
            <ReactECharts option={datasetYearlyRatioOption} style={{ height: 250 }} />
          </article>
        </div>
        <div className="mb-4 grid gap-4 xl:grid-cols-2">
          <article className="rounded-lg border border-notion-border bg-notion-surface p-3">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-notion-secondary">
              标签级特征相关性 Top24（attack=1）
            </h3>
            <p className="mb-2 text-xs text-notion-secondary">
              红色正相关，绿色负相关；已过滤 `count` / `ratio`，并排除一切标准差与 Std 画像相关指标列。来源{' '}
              <span className="font-mono">dataset_label_feature_attack_correlation.json</span>
            </p>
            <ReactECharts option={datasetLabelFeatureCorrOption} style={{ height: 560 }} />
          </article>
          <article className="rounded-lg border border-notion-border bg-notion-surface p-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-notion-secondary">
                Top5 相关特征：恶意 vs 良性（雷达）
              </h3>
              <Popover
                trigger="click"
                open={radarFilterOpen}
                onOpenChange={(open) => {
                  setRadarFilterOpen(open)
                }}
                placement="leftTop"
                content={(
                  <div className="w-[320px] space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-notion-secondary">
                        已选 {effectiveRadarLabels.length} / {datasetLabelAll.length}
                      </span>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          className="btn-secondary px-2 py-1"
                          onClick={() => setRadarLabelSelection(null)}
                        >
                          全选
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-2 py-1"
                          onClick={() => setRadarLabelSelection([])}
                        >
                          清空
                        </button>
                      </div>
                    </div>
                    <div className="max-h-72 overflow-y-auto rounded border border-notion-border p-2">
                      <Checkbox.Group
                        value={effectiveRadarLabels}
                        onChange={(vals) => setRadarLabelSelection((vals as string[]).map((v) => String(v)))}
                        className="flex w-full flex-col gap-1"
                      >
                        {datasetLabelAll
                          .slice()
                          .sort((a, b) => b.count - a.count)
                          .map((row) => (
                            <Checkbox key={`radar-label-${row.label}`} value={row.label}>
                              <span className={row.isBenign ? 'text-notion-success' : 'text-notion-danger'}>
                                {row.label}
                              </span>
                              <span className="ml-1 text-[11px] text-notion-secondary">({row.count.toLocaleString()})</span>
                            </Checkbox>
                          ))}
                      </Checkbox.Group>
                    </div>
                  </div>
                )}
              >
                <button type="button" className="btn-secondary px-2 py-1">
                  选择展示标签
                </button>
              </Popover>
            </div>
            <p className="mb-2 text-xs text-notion-secondary">
              取相关性绝对值最大的5个特征；通过右上角按钮控制显示哪些标签（恶意红色、良性绿色）
            </p>
            <ReactECharts option={datasetLabelTopFeatureRadarOption} style={{ height: 560 }} />
          </article>
        </div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-notion-secondary">Label 表格筛选与展示列</h3>
          <div className="text-xs text-notion-secondary">
            当前显示 {filteredDatasetLabelRows.length} / {datasetLabelAll.length} 条
          </div>
        </div>
        <p className="mb-3 text-[11px] leading-relaxed text-notion-secondary">
          固定列之外的指标列默认全部展示：<span className="font-mono">dataset_label_distribution.csv</span> 中出现的特征统计字段（如{' '}
          <span className="font-mono">__mean/__cv/__max/__min</span>
          （同一指标的 μ 与 CV 合并在同一单元格；不含标准差与 Std 画像相关列）；可在「⚙ 设置列」中隐藏不需看的列。
        </p>
        <div className="mb-2 flex flex-wrap items-start gap-3">
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <TableSortTag
              scopeLabel="Label表"
              columnLabel={datasetSortColumnLabel}
              dir={datasetSortDir}
              clearDisabled={
                datasetSortBy === DATASET_DEFAULT_SORT_KEY && datasetSortDir === DATASET_DEFAULT_SORT_DIR
              }
              onClear={() => {
                setDatasetSortBy(DATASET_DEFAULT_SORT_KEY)
                setDatasetSortDir(DATASET_DEFAULT_SORT_DIR)
              }}
            />
          </div>
          <div className="ml-auto flex min-w-0 flex-[2] flex-wrap items-start justify-end gap-2 sm:min-w-[min(100%,560px)]">
            <div className="min-w-0 flex-1">
              <TableFilterBar
                inputClassName="min-w-[min(100%,420px)] w-full max-w-[720px]"
                placeholder="搜索 label / base label / year / protocol..."
                tags={datasetFilterTags}
                onAddTag={addDatasetFilterTag}
                onRemoveTag={removeDatasetFilterTag}
                onClearAll={clearDatasetFilterTags}
              />
            </div>
            <Popover
              content={datasetColumnPickerContent}
              trigger="click"
              placement="bottomRight"
            >
              <button type="button" className="btn-primary shrink-0 self-start">
                ⚙ 设置列
              </button>
            </Popover>
          </div>
        </div>
        <div className="max-h-[520px] overflow-x-auto overflow-y-auto rounded-lg border border-notion-border">
          <table className="w-full min-w-[1380px] whitespace-nowrap text-sm">
            <thead className="sticky top-0 bg-notion-surface-alt">
              <tr className="border-b border-notion-border text-left text-notion-secondary">
                <th style={datasetColumnStyle('label')} className={`whitespace-nowrap px-3 py-2 ${STICKY_FIRST_COL_TH}`}><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('label')}>Label <span className="text-xs">{sortIndicator(datasetSortBy === 'label', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('count')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('count')}>Count <span className="text-xs">{sortIndicator(datasetSortBy === 'count', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('ratio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('ratio')}>Ratio <span className="text-xs">{sortIndicator(datasetSortBy === 'ratio', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('type')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('type')}>Type <span className="text-xs">{sortIndicator(datasetSortBy === 'type', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('yearTag')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('yearTag')}>Year <span className="text-xs">{sortIndicator(datasetSortBy === 'yearTag', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('baseLabel')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('baseLabel')}>Base Label <span className="text-xs">{sortIndicator(datasetSortBy === 'baseLabel', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('protocolType')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('protocolType')}>协议簇类型 <span className="text-xs">{sortIndicator(datasetSortBy === 'protocolType', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('protocolConcentration')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('protocolConcentration')}>协议聚集性 <span className="text-xs">{sortIndicator(datasetSortBy === 'protocolConcentration', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('protocolTcpRatio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('protocolTcpRatio')}>TCP占比 <span className="text-xs">{sortIndicator(datasetSortBy === 'protocolTcpRatio', datasetSortDir)}</span></button></th>
                <th style={datasetColumnStyle('protocolUdpRatio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort('protocolUdpRatio')}>UDP占比 <span className="text-xs">{sortIndicator(datasetSortBy === 'protocolUdpRatio', datasetSortDir)}</span></button></th>
                {visibleDatasetMetricDisplayColumns.map((col) => (
                  <th key={`label-col-${col.id}`} style={datasetColumnStyle(col.id)} className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">
                    <button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleDatasetSort(col.id)}>
                      {col.kind === 'mean_cv' ? (
                        <MetricMeanCvColumnHeader base={col.base} />
                      ) : (
                        <MetricStatColumnHeader col={col.col} />
                      )}
                      <span className="text-xs">{sortIndicator(datasetSortBy === col.id, datasetSortDir)}</span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredDatasetLabelRows.map((row) => (
                <tr key={row.label} className={datasetLabelTableRowClassName(row.isBenign)}>
                  <td style={datasetColumnStyle('label')} className={`${STICKY_FIRST_COL_TD_FRAME} ${stickyFirstColTdBgDataset(row.isBenign)} whitespace-nowrap px-3 py-2 font-mono text-xs ${row.isBenign ? 'text-notion-success' : 'text-notion-danger'}`}>
                    {row.label}
                  </td>
                  <td style={datasetColumnStyle('count')} className="whitespace-nowrap px-3 py-2">{row.count.toLocaleString()}</td>
                  <td style={datasetColumnStyle('ratio')} className="whitespace-nowrap px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div
                        className="h-2.5 w-36 overflow-hidden rounded-full bg-notion-surface-hover"
                        title={`${(row.ratio * 100).toFixed(METRIC_DECIMAL_PLACES)}%`}
                      >
                        <div
                          className={`h-full rounded-full ${row.isBenign ? 'bg-notion-success-bg0' : 'bg-notion-danger-bg0'}`}
                          style={{ width: `${Math.max(0, Math.min(100, row.ratio * 100))}%` }}
                        />
                      </div>
                      <span className={`text-xs ${row.isBenign ? 'text-notion-success' : 'text-notion-danger'}`}>
                        {(row.ratio * 100).toFixed(METRIC_DECIMAL_PLACES)}%
                      </span>
                    </div>
                  </td>
                  <td style={datasetColumnStyle('type')} className="whitespace-nowrap px-3 py-2">
                    <span className={row.isBenign ? 'rounded-md bg-notion-success-bg px-2 py-1 text-notion-success' : 'rounded-md bg-notion-danger-bg px-2 py-1 text-notion-danger'}>
                      {row.isBenign ? 'BENIGN' : 'ATTACK'}
                    </span>
                  </td>
                  <td style={datasetColumnStyle('yearTag')} className="whitespace-nowrap px-3 py-2">{row.yearTag}</td>
                  <td style={datasetColumnStyle('baseLabel')} className="whitespace-nowrap px-3 py-2">{row.baseLabel}</td>
                  <td style={datasetColumnStyle('protocolType')} className="whitespace-nowrap px-3 py-2">
                    <span className="rounded-md bg-notion-surface-hover px-2 py-1 text-notion-text">{row.protocolType}</span>
                  </td>
                  <td style={datasetColumnStyle('protocolConcentration')} className="whitespace-nowrap px-3 py-2">{(row.protocolConcentration * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  <td style={datasetColumnStyle('protocolTcpRatio')} className="whitespace-nowrap px-3 py-2 text-notion-success">{(row.protocolTcpRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  <td style={datasetColumnStyle('protocolUdpRatio')} className="whitespace-nowrap px-3 py-2 text-notion-info">{(row.protocolUdpRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  {visibleDatasetMetricDisplayColumns.map((col) => (
                    <td
                      key={`${row.label}-${col.id}`}
                      style={datasetColumnStyle(col.id)}
                      className="max-w-[18rem] whitespace-normal px-3 py-2 font-mono text-[11px]"
                    >
                      {col.kind === 'mean_cv' ? (
                        formatMeanCvCombinedCell(
                          row.raw[col.meanCol] as string | boolean | undefined,
                          row.raw[col.cvCol] as string | boolean | undefined,
                          formatDatasetDistributionMetricCell,
                        )
                      ) : (
                        formatDatasetDistributionMetricCell(row.raw[col.col] as string | boolean | undefined)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t-2 border-notion-border-strong bg-notion-surface-hover text-[11px] text-notion-text">
              {TABLE_COLUMN_STAT_ROWS.map(({ field: statField, label: statLabel }) => (
                <tr key={`ds-foot-${statField}`}>
                  <td
                    style={datasetColumnStyle('label')}
                    className={`${STICKY_FIRST_COL_TD_FRAME} sticky-table-bg-neutral whitespace-nowrap px-3 py-1.5 font-medium text-notion-secondary`}
                  >
                    {statLabel}
                  </td>
                  <td style={datasetColumnStyle('count')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(datasetTableColumnStats.count, statField)}
                  </td>
                  <td style={datasetColumnStyle('ratio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(datasetTableColumnStats.ratio, statField)}
                  </td>
                  <td style={datasetColumnStyle('type')} className="whitespace-nowrap px-3 py-1.5 text-notion-tertiary">—</td>
                  <td style={datasetColumnStyle('yearTag')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(datasetTableColumnStats.yearTag, statField)}
                  </td>
                  <td style={datasetColumnStyle('baseLabel')} className="whitespace-nowrap px-3 py-1.5 text-notion-tertiary">—</td>
                  <td style={datasetColumnStyle('protocolType')} className="whitespace-nowrap px-3 py-1.5 text-notion-tertiary">—</td>
                  <td style={datasetColumnStyle('protocolConcentration')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(datasetTableColumnStats.protocolConcentration, statField)}
                  </td>
                  <td style={datasetColumnStyle('protocolTcpRatio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(datasetTableColumnStats.protocolTcpRatio, statField)}
                  </td>
                  <td style={datasetColumnStyle('protocolUdpRatio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(datasetTableColumnStats.protocolUdpRatio, statField)}
                  </td>
                  {visibleDatasetMetricDisplayColumns.map((col) => (
                    <td
                      key={`ds-foot-${col.id}-${statField}`}
                      style={datasetColumnStyle(col.id)}
                      className="whitespace-nowrap px-3 py-1.5 font-mono text-[11px]"
                    >
                      {formatColumnStatField(datasetTableColumnStats[col.id] ?? null, statField)}
                    </td>
                  ))}
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">
          决策树可解释性（标签 / 学习器）
        </h2>
        <p className="mb-4 text-xs text-notion-secondary">
          主流程在 run 结束时自动训练决策树：区分数据集标签（良性 vs 攻击、base_label 多类）与学习器（attack_ratio 阈值、极性三分类、协议簇）。
          指标为分层 5 折交叉验证 OOF；二分类任务展示 FPR/FNR。
        </p>
        <DecisionTreePanel data={decisionTreeViz} />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">Learner 趋势</h2>
          <ReactECharts option={learnerTrendOption} style={{ height: 300 }} />
        </article>
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">Unknown Buffer 趋势</h2>
          <ReactECharts option={unknownTrendOption} style={{ height: 300 }} />
        </article>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">
            簇特征 vs attack_ratio 相关性（Top24）
          </h2>
          <div className="mb-2 text-xs text-notion-secondary">
            正相关为红色，负相关为绿色；已过滤 `count` / `ratio`，并排除一切标准差与 Std 画像相关指标列；数据来自{' '}
            <span className="font-mono">learner_feature_attack_ratio_correlation.json</span>
          </div>
          <ReactECharts option={featureCorrOption} style={{ height: 560 }} />
        </article>
        <article className="panel">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-notion-secondary">
              学习器 Top5 相关特征雷达图
            </h2>
            <Popover
              trigger="click"
              open={learnerRadarFilterOpen}
              onOpenChange={(open) => {
                setLearnerRadarFilterOpen(open)
              }}
              placement="leftTop"
              content={(
                <div className="w-[320px] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-notion-secondary">
                      已选 {effectiveLearnerRadarNames.length} / {allLearnerRows.length}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        className="rounded border border-notion-border-strong px-2 py-1 text-xs text-notion-text hover:bg-notion-surface-alt"
                        onClick={() => setLearnerRadarNameSelection(null)}
                      >
                        全选
                      </button>
                      <button
                        type="button"
                        className="rounded border border-notion-border-strong px-2 py-1 text-xs text-notion-text hover:bg-notion-surface-alt"
                        onClick={() => setLearnerRadarNameSelection([])}
                      >
                        清空
                      </button>
                    </div>
                  </div>
                  <div className="max-h-72 overflow-y-auto rounded border border-notion-border p-2">
                    <Checkbox.Group
                      value={effectiveLearnerRadarNames}
                      onChange={(vals) => setLearnerRadarNameSelection((vals as string[]).map((v) => String(v)))}
                      className="flex w-full flex-col gap-1"
                    >
                      {allLearnerRows
                        .slice()
                        .sort((a, b) => b.attackRatio - a.attackRatio || b.samples - a.samples)
                        .map((row) => (
                          <Checkbox key={`learner-radar-${row.name}`} value={row.name}>
                            <span className={row.attackRatio >= 0.5 ? 'text-notion-danger' : 'text-notion-success'}>
                              {row.name}
                            </span>
                            <span className="ml-1 text-[11px] text-notion-secondary">
                              （攻击占比 {(row.attackRatio * 100).toFixed(2)}% · 主导 {row.dominantLabel} ·{' '}
                              {row.samples.toLocaleString()} 样本）
                            </span>
                          </Checkbox>
                        ))}
                    </Checkbox.Group>
                  </div>
                </div>
              )}
            >
              <button type="button" className="rounded border border-notion-border-strong px-2 py-1 text-xs text-notion-text hover:bg-notion-surface-alt">
                选择展示学习器
              </button>
            </Popover>
          </div>
          <div className="mb-2 text-xs text-notion-secondary">
            默认展示全部学习器；悬浮可查看流量类型（恶意倾向/良性倾向）与 attack_ratio
          </div>
          <ReactECharts option={learnerTopFeatureRadarOption} style={{ height: 560 }} />
        </article>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">Learner 创建样本量 Top15</h2>
          <ReactECharts option={creationOption} style={{ height: 340 }} />
        </article>
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-notion-secondary">学习器重训次数 Top10</h2>
          <ReactECharts option={retrainTopOption} style={{ height: 340 }} />
        </article>
      </section>

      <section className="panel">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-widest text-notion-secondary">
              学习器内部网络拓扑（IP / 端口）
            </h2>
            <p className="mt-1 text-xs text-notion-secondary">
              默认网格展示全部学习器（左 IP / 右 IP:端口）；可切换单学习器模式。绿/红边为真实标签。分组审计指标见「学习器详情」。
            </p>
          </div>
          <Link
            to={
              selectedRunId
                ? overviewPaths.learnerDetailRun(
                    selectedRunId,
                    selectedNodeId ? selectedNodeId : undefined,
                  )
                : overviewPaths.learnerDetail
            }
            className="btn-secondary shrink-0 text-sm"
          >
            学习器详情（审计指标）→
          </Link>
        </div>
        <LearnerInternalTopologyPanel
          data={learnerNetworkTopology}
          learnerOptions={allLearnerRows.map((r) => ({
            name: r.name,
            attackRatio: r.attackRatio,
            dominantLabel: r.dominantLabel,
          }))}
          selectedLearner={selectedNodeId}
          onLearnerChange={(name) => setSelectedNodeId(name)}
        />
      </section>

      <section className="panel">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-notion-secondary">学习器效果总览（全部）</h2>
        </div>
        <div className="mb-3 flex flex-wrap items-start gap-3">
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <TableSortTag
              scopeLabel="Learner表"
              columnLabel={learnerSortColumnLabel}
              dir={learnerSortDir}
              clearDisabled={
                learnerSortBy === LEARNER_DEFAULT_SORT_KEY && learnerSortDir === LEARNER_DEFAULT_SORT_DIR
              }
              onClear={() => {
                setLearnerSortBy(LEARNER_DEFAULT_SORT_KEY)
                setLearnerSortDir(LEARNER_DEFAULT_SORT_DIR)
              }}
            />
          </div>
          <div className="ml-auto flex min-w-0 flex-[2] flex-wrap items-start justify-end gap-2 sm:min-w-[min(100%,560px)]">
            <div className="min-w-0 flex-1">
              <TableFilterBar
                inputClassName="min-w-[min(100%,420px)] w-full max-w-[720px]"
                placeholder="搜索 learner / 主导标签 / 协议簇..."
                tags={learnerFilterTags}
                onAddTag={addLearnerFilterTag}
                onRemoveTag={removeLearnerFilterTag}
                onClearAll={clearLearnerFilterTags}
              />
            </div>
            <Popover
              content={learnerColumnPickerContent}
              trigger="click"
              placement="bottomRight"
            >
              <button type="button" className="btn-primary shrink-0 self-start">
                ⚙ 设置列
              </button>
            </Popover>
          </div>
        </div>

        <div className="mb-2 text-xs leading-relaxed text-notion-secondary">
          <span className="block">
            固定列之外的字段来自{' '}
            <span className="font-mono">learner_label_distribution.csv</span>：
            <span className="font-semibold text-notion-text">增量样本(post_creation)、dominant_count、protocol_other_ratio、label_distribution_json 以及全部</span>{' '}
            <span className="font-mono">__mean/__cv</span> 等聚合指标列均已追加（同一指标 μ 与 CV 同格展示；标准差列与 Std 画像特征族不在本页展示）。
          </span>
          <span className="mt-0.5 block text-notion-tertiary">
            共 {learnerRows.length} 条学习器 · 筛选后 {allLearnerRows.length} 条
          </span>
        </div>

        <div className="max-h-[520px] overflow-x-auto overflow-y-auto rounded-lg border border-notion-border">
          <table className="w-full min-w-[1380px] whitespace-nowrap text-sm">
            <thead className="sticky top-0 bg-notion-surface-alt">
              <tr className="border-b border-notion-border text-left text-notion-secondary">
                <th style={learnerColumnStyle('name')} className={`whitespace-nowrap px-3 py-2 ${STICKY_FIRST_COL_TH}`}><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('name')}>Learner <span className="text-xs">{sortIndicator(learnerSortBy === 'name', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('attackRatio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('attackRatio')}>Attack Ratio <span className="text-xs">{sortIndicator(learnerSortBy === 'attackRatio', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('samples')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('samples')}>总样本 <span className="text-xs">{sortIndicator(learnerSortBy === 'samples', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('creationSamples')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('creationSamples')}>创建样本 <span className="text-xs">{sortIndicator(learnerSortBy === 'creationSamples', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('retrainCount')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('retrainCount')}>重训次数 <span className="text-xs">{sortIndicator(learnerSortBy === 'retrainCount', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('protocolType')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('protocolType')}>协议簇类型 <span className="text-xs">{sortIndicator(learnerSortBy === 'protocolType', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('protocolConcentration')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('protocolConcentration')}>协议聚集性 <span className="text-xs">{sortIndicator(learnerSortBy === 'protocolConcentration', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('tcpRatio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('tcpRatio')}>TCP占比 <span className="text-xs">{sortIndicator(learnerSortBy === 'tcpRatio', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('udpRatio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('udpRatio')}>UDP占比 <span className="text-xs">{sortIndicator(learnerSortBy === 'udpRatio', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('dominantLabel')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('dominantLabel')}>主导标签 <span className="text-xs">{sortIndicator(learnerSortBy === 'dominantLabel', learnerSortDir)}</span></button></th>
                <th style={learnerColumnStyle('dominantRatio')} className="whitespace-nowrap px-3 py-2"><button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort('dominantRatio')}>主导占比 <span className="text-xs">{sortIndicator(learnerSortBy === 'dominantRatio', learnerSortDir)}</span></button></th>
                {visibleLearnerMetricDisplayColumns.map((col) => (
                  <th key={col.id} style={learnerColumnStyle(col.id)} className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">
                    <button type="button" className={TABLE_SORT_HEAD_BTN_CLASS} onClick={() => toggleLearnerSort(col.id)}>
                      {col.kind === 'mean_cv' ? (
                        <MetricMeanCvColumnHeader base={col.base} />
                      ) : (
                        <MetricStatColumnHeader col={col.col} />
                      )}
                      <span className="text-xs">{sortIndicator(learnerSortBy === col.id, learnerSortDir)}</span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allLearnerRows.map((row) => (
                <tr key={row.name} className={learnerTableRowClassFromAttackRatio(row.attackRatio)}>
                  <td style={learnerColumnStyle('name')} className={`${STICKY_FIRST_COL_TD_FRAME} ${stickyFirstColTdBgLearner(row.attackRatio)} whitespace-nowrap px-3 py-2 font-mono text-xs text-notion-text`}>{row.name}</td>
                  <td style={learnerColumnStyle('attackRatio')} className="whitespace-nowrap px-3 py-2">
                    <span
                      className={
                        row.attackRatio > 0.7
                          ? 'rounded-md bg-notion-danger-bg px-2 py-1 text-notion-danger'
                          : row.attackRatio < 0.3
                            ? 'rounded-md bg-notion-success-bg px-2 py-1 text-notion-success'
                            : 'rounded-md border border-notion-warning bg-notion-warning-bg px-2 py-1 text-notion-warning'
                      }
                    >
                      {(row.attackRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%
                    </span>
                  </td>
                  <td style={learnerColumnStyle('samples')} className="whitespace-nowrap px-3 py-2">{row.samples.toLocaleString()}</td>
                  <td style={learnerColumnStyle('creationSamples')} className="whitespace-nowrap px-3 py-2">{row.creationSamples.toLocaleString()}</td>
                  <td style={learnerColumnStyle('retrainCount')} className="whitespace-nowrap px-3 py-2">{row.retrainCount.toLocaleString()}</td>
                  <td style={learnerColumnStyle('protocolType')} className="whitespace-nowrap px-3 py-2">
                    <span className="rounded-md bg-notion-surface-hover px-2 py-1 text-notion-text">{row.protocolType}</span>
                  </td>
                  <td style={learnerColumnStyle('protocolConcentration')} className="whitespace-nowrap px-3 py-2">{(row.protocolConcentration * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  <td style={learnerColumnStyle('tcpRatio')} className="whitespace-nowrap px-3 py-2 text-notion-success">{(row.tcpRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  <td style={learnerColumnStyle('udpRatio')} className="whitespace-nowrap px-3 py-2 text-notion-info">{(row.udpRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  <td style={learnerColumnStyle('dominantLabel')} className="whitespace-nowrap px-3 py-2">
                    <span
                      className={
                        row.attackRatio > 0.7
                          ? 'text-notion-danger'
                          : row.attackRatio < 0.3
                            ? 'text-notion-success'
                            : 'text-notion-warning'
                      }
                    >
                      {row.dominantLabel}
                    </span>
                  </td>
                  <td style={learnerColumnStyle('dominantRatio')} className="whitespace-nowrap px-3 py-2">{(row.dominantRatio * 100).toFixed(METRIC_DECIMAL_PLACES)}%</td>
                  {visibleLearnerMetricDisplayColumns.map((col) => {
                    if (col.kind === 'mean_cv') {
                      return (
                        <td
                          key={`${row.name}-${col.id}`}
                          style={learnerColumnStyle(col.id)}
                          className="max-w-[16rem] whitespace-normal px-3 py-2 font-mono text-[11px]"
                        >
                          {formatMeanCvCombinedCell(
                            row.residualCsv[col.meanCol],
                            row.residualCsv[col.cvCol],
                            (raw) => formatLearnerResidualCsvCell(col.meanCol, raw === undefined ? undefined : String(raw)),
                          )}
                        </td>
                      )
                    }
                    const csvCol = col.col
                    const jsonCol = /_json$/i.test(csvCol) || csvCol === 'label_distribution_json'
                    return (
                      <td
                        key={`${row.name}-${col.id}`}
                        style={learnerColumnStyle(col.id)}
                        className={
                          jsonCol
                            ? 'max-w-[28rem] overflow-hidden text-ellipsis whitespace-nowrap px-3 py-2 font-mono text-[11px]'
                            : 'max-w-[22rem] whitespace-normal px-3 py-2 font-mono text-[11px]'
                        }
                        title={row.residualCsv[csvCol]?.length ? row.residualCsv[csvCol] : undefined}
                      >
                        {formatLearnerResidualCsvCell(csvCol, row.residualCsv[csvCol])}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t-2 border-notion-border-strong bg-notion-surface-hover text-[11px] text-notion-text">
              {TABLE_COLUMN_STAT_ROWS.map(({ field: statField, label: statLabel }) => (
                <tr key={`lr-foot-${statField}`}>
                  <td
                    style={learnerColumnStyle('name')}
                    className={`${STICKY_FIRST_COL_TD_FRAME} sticky-table-bg-neutral whitespace-nowrap px-3 py-1.5 font-medium text-notion-secondary`}
                  >
                    {statLabel}
                  </td>
                  <td style={learnerColumnStyle('attackRatio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.attackRatio, statField)}
                  </td>
                  <td style={learnerColumnStyle('samples')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.samples, statField)}
                  </td>
                  <td style={learnerColumnStyle('creationSamples')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.creationSamples, statField)}
                  </td>
                  <td style={learnerColumnStyle('retrainCount')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.retrainCount, statField)}
                  </td>
                  <td style={learnerColumnStyle('protocolType')} className="whitespace-nowrap px-3 py-1.5 text-notion-tertiary">—</td>
                  <td style={learnerColumnStyle('protocolConcentration')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.protocolConcentration, statField)}
                  </td>
                  <td style={learnerColumnStyle('tcpRatio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.tcpRatio, statField)}
                  </td>
                  <td style={learnerColumnStyle('udpRatio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.udpRatio, statField)}
                  </td>
                  <td style={learnerColumnStyle('dominantLabel')} className="whitespace-nowrap px-3 py-1.5 text-notion-tertiary">—</td>
                  <td style={learnerColumnStyle('dominantRatio')} className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {formatColumnStatField(learnerTableColumnStats.dominantRatio, statField)}
                  </td>
                  {visibleLearnerMetricDisplayColumns.map((col) => (
                    <td
                      key={`lr-foot-${col.id}-${statField}`}
                      style={learnerColumnStyle(col.id)}
                      className="whitespace-nowrap px-3 py-1.5 font-mono text-[11px]"
                    >
                      {formatColumnStatField(learnerTableColumnStats[col.id] ?? null, statField)}
                    </td>
                  ))}
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-4">
        <article className="panel xl:col-span-3">
          <div ref={chartRef} className="h-[72vh] w-full" />
        </article>
        <aside className="space-y-4">
          <article className="panel">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-notion-secondary">图谱配置</h2>
            <div className="space-y-3">
              <div>
                <label className="field-label">阈值 {threshold.toFixed(METRIC_DECIMAL_PLACES)}</label>
                <Slider
                  min={0}
                  max={1}
                  step={0.01}
                  value={threshold}
                  onChange={(value) => setThreshold(Array.isArray(value) ? value[0] : value)}
                  tooltip={{ formatter: (v) => `${Number(v || 0).toFixed(METRIC_DECIMAL_PLACES)}` }}
                />
              </div>
              <div>
                <label className="field-label">连接模式</label>
                <Select
                  className="w-full"
                  value={connectionMode}
                  onChange={(value) => setConnectionMode(value as 'all' | 'strongest' | 'mutual')}
                  options={[
                    { label: '全部连接', value: 'all' },
                    { label: '节点最强连接', value: 'strongest' },
                    { label: '双向最强连接', value: 'mutual' },
                  ]}
                />
              </div>
              <div>
                <label className="field-label">排斥强度 {repulsion}</label>
                <Slider
                  min={120}
                  max={520}
                  step={10}
                  value={repulsion}
                  onChange={(value) => setRepulsion(Array.isArray(value) ? value[0] : value)}
                />
              </div>
            </div>
          </article>

          <article className="panel">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-notion-secondary">详情面板</h2>
            {selectedEdge ? (
              <div className="space-y-1 text-sm text-notion-text">
                <p className="font-semibold text-notion-text">边: {selectedEdge.source} ↔ {selectedEdge.target}</p>
                <p>Jaccard: {selectedEdge.value.toFixed(METRIC_DECIMAL_PLACES)}</p>
                <p>交集: {selectedEdge.intersectionCount}</p>
                <p>并集: {selectedEdge.unionCount}</p>
                <p>A→B: {selectedEdge.acceptRateAToB.toFixed(METRIC_DECIMAL_PLACES)}</p>
                <p>B→A: {selectedEdge.acceptRateBToA.toFixed(METRIC_DECIMAL_PLACES)}</p>
              </div>
            ) : null}
            {!selectedEdge && selectedDetail ? (
              <div className="space-y-1 text-sm text-notion-text">
                <p className="font-semibold text-notion-text">节点: {selectedDetail.learnerName}</p>
                <p>attack_ratio: {selectedDetail.attackRatio == null ? 'N/A' : selectedDetail.attackRatio.toFixed(METRIC_DECIMAL_PLACES)}</p>
                <p>总样本数: {selectedDetail.totalSamples}</p>
                <p>主导标签: {selectedDetail.dominantLabel}</p>
                <p>主导占比: {selectedDetail.dominantRatio == null ? 'N/A' : selectedDetail.dominantRatio.toFixed(METRIC_DECIMAL_PLACES)}</p>
                {selectedCreationPreview && selectedCreationPreview.flows_preview.length > 0 ? (
                  <div className="mt-3 border-t border-notion-border pt-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-notion-secondary">创建时流预览</p>
                    <p className="mt-1 text-[11px] text-notion-secondary">
                      来源 <span className="font-mono">{selectedCreationPreview.creation_source}</span>
                      ，窗口 [<span className="font-mono">{selectedCreationPreview.window_left}</span>
                      , <span className="font-mono">{selectedCreationPreview.window_right}</span>
                      )，簇大小 <span className="font-mono">{selectedCreationPreview.cluster_size}</span>
                      ，至多 {creationFlowPreview?.preview_flow_count ?? '—'} 条
                    </p>
                    <div className="mt-2 max-h-72 overflow-auto rounded border border-notion-border bg-notion-surface-alt/80">
                      <table className="min-w-max border-collapse text-left text-[11px]">
                        <thead className="sticky top-0 bg-notion-surface-hover text-[10px] uppercase tracking-wide text-notion-secondary">
                          <tr>
                            {orderedCreationPreviewDisplayColumns(selectedCreationPreview.flows_preview).map((col) => (
                              <th key={`cp-col-${col.id}`} className="border-b border-notion-border px-2 py-1.5 whitespace-nowrap">
                                {col.kind === 'mean_cv' ? (
                                  <MetricMeanCvColumnHeader base={col.base} />
                                ) : (
                                  <MetricStatColumnHeader col={col.col} />
                                )}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {selectedCreationPreview.flows_preview.map((flow, fi) => (
                            <tr key={`cp-flow-${selectedDetail.learnerName}-${fi}`} className="odd:bg-notion-surface even:bg-notion-surface-alt">
                              {orderedCreationPreviewDisplayColumns(selectedCreationPreview.flows_preview).map((col) => (
                                <td
                                  key={`cp-cell-${fi}-${col.id}`}
                                  className="border-b border-notion-border px-2 py-1.5 whitespace-normal font-mono"
                                >
                                  {col.kind === 'mean_cv' ? (
                                    formatMeanCvCombinedCell(
                                      flow[col.meanCol] as string | boolean | undefined,
                                      flow[col.cvCol] as string | boolean | undefined,
                                      (raw) => formatCreationPreviewCell(raw),
                                    )
                                  ) : (
                                    formatCreationPreviewCell(flow[col.col])
                                  )}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : null}
                {selectedDetail && !selectedCreationPreview && creationFlowPreview ? (
                  <p className="mt-3 border-t border-notion-border pt-3 text-[11px] text-notion-tertiary">
                    该学习器暂无创建流预览条目。
                  </p>
                ) : null}
                {selectedDetail && !creationFlowPreview ? (
                  <p className="mt-3 border-t border-notion-border pt-3 text-[11px] text-notion-tertiary">
                    未加载 learner_creation_flow_previews.json（旧 run 或未生成）。
                  </p>
                ) : null}
              </div>
            ) : null}
            {!selectedEdge && !selectedDetail ? <p className="text-sm text-notion-secondary">点击图谱节点或边查看详情。</p> : null}
          </article>
        </aside>
      </section>
    </div>
  )
}
