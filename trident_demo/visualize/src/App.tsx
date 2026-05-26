import { useEffect, useMemo, useState } from 'react'
import { fetchStressRunDetail, fetchStressRuns, type JsonRecord, type StressRun, type StressRunDetail } from './lib/stressApi'

type Point = {
  timestamp?: string
  [key: string]: number | string | undefined | null
}

const colors = {
  blue: '#2383e2',
  green: '#448361',
  red: '#d44c47',
  orange: '#d9730d',
  slate: '#787774',
}

type StageRow = {
  key: string
  label: string
  desc: string
  seconds: number
  focus?: 'suricata' | 'trident' | 'overall'
}

const SUMMARY_STAGE_META: Record<string, { label: string; desc: string; focus?: StageRow['focus'] }> = {
  preflight: { label: '预检查', desc: '检查运行环境、依赖与配置有效性', focus: 'overall' },
  start_services: { label: '启动服务', desc: '启动或重建 Suricata / Redis 容器', focus: 'overall' },
  baseline: { label: '基线采样', desc: '压测前采集空载基线指标', focus: 'overall' },
  tcpreplay: { label: '流量回放', desc: '向 Suricata 网卡回放 pcap 触发解析', focus: 'suricata' },
  wait_after_replay: { label: '回放后等待', desc: '等待 Suricata 继续解析并写入 Redis', focus: 'suricata' },
  trident_total: { label: 'Trident 分析总耗时', desc: 'Trident 拉流、推理与产物输出总耗时', focus: 'trident' },
  wall_clock_total: { label: '总耗时', desc: '整轮压测从开始到结束的总耗时', focus: 'overall' },
}

const TRIDENT_STAGE_META: Record<string, { label: string; desc: string }> = {
  pipeline_preflight: { label: 'Trident 预检查', desc: 'Trident 启动前参数与资源检查' },
  io_source_read: { label: '读取数据源', desc: '从 Redis Stream 拉取流量数据' },
  io_preprocess: { label: '预处理', desc: '字段清洗与数据规整' },
  io_feature_matrix: { label: '特征矩阵构建', desc: '将流量转为模型输入特征' },
  io_load_total: { label: '数据加载总耗时', desc: '读取 + 预处理 + 特征构建总耗时' },
  init_learners: { label: '初始学习器构建', desc: '初始化已知模式学习器' },
  stream_inference: { label: '流式推理', desc: '核心在线检测阶段' },
  stream_cluster: { label: '聚类判定', desc: '未知流量的聚类与判定' },
  stream_create_learner: { label: '增量建模', desc: '新类学习器创建' },
  stream_retrain: { label: '增量重训练', desc: '已有学习器增量更新' },
  stream_window_total: { label: '窗口处理总耗时', desc: '每批窗口推理与更新总耗时' },
  pipeline_experiment: { label: '实验核心总耗时', desc: 'Trident 分析主流程总耗时' },
  pipeline_postrun: { label: '收尾阶段', desc: '保存指标并做结束处理' },
  pipeline_total: { label: 'Trident Pipeline 总耗时', desc: 'Trident 全流程总耗时' },
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : {}
}

function asArray(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((item): item is JsonRecord => !!item && typeof item === 'object' && !Array.isArray(item)) : []
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatNumber(value: unknown, digits = 2): string {
  const n = asNumber(value)
  if (n == null) return '-'
  return n.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function formatSeconds(value: unknown): string {
  const n = asNumber(value)
  if (n == null) return '-'
  if (n >= 60) return `${formatNumber(n / 60, 2)} min`
  return `${formatNumber(n, 2)} s`
}

function formatBytes(value: unknown): string {
  const n = asNumber(value)
  if (n == null) return '-'
  const abs = Math.abs(n)
  if (abs >= 1024 ** 3) return `${formatNumber(n / 1024 ** 3, 2)} GiB`
  if (abs >= 1024 ** 2) return `${formatNumber(n / 1024 ** 2, 2)} MiB`
  if (abs >= 1024) return `${formatNumber(n / 1024, 2)} KiB`
  return `${formatNumber(n, 0)} B`
}

function formatFlowRate(value: unknown): string {
  const n = asNumber(value)
  if (n == null) return '-'
  return `${formatNumber(n, 2)} flow/s`
}

function flowRateToGBps(flowRate: unknown, avgBytesPerFlow: unknown): number | null {
  const fps = asNumber(flowRate)
  const bytesPerFlow = asNumber(avgBytesPerFlow)
  if (fps == null || bytesPerFlow == null) return null
  return (fps * bytesPerFlow) / 1_000_000_000
}

function formatGBps(value: unknown): string {
  const n = asNumber(value)
  if (n == null) return '-'
  return `${formatNumber(n, 4)} GB/s`
}

function formatPercent(value: unknown, digits = 2): string {
  const n = asNumber(value)
  if (n == null) return '-'
  return `${formatNumber(n * 100, digits)}%`
}

function formatTime(value: unknown): string {
  if (typeof value !== 'string') return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toISOString().slice(11, 19)
}

function parsePercent(value: unknown): number | null {
  if (typeof value === 'number') return value
  if (typeof value !== 'string') return null
  const parsed = Number.parseFloat(value.replace('%', ''))
  return Number.isFinite(parsed) ? parsed : null
}

function parseMemMiB(value: unknown): number | null {
  if (typeof value !== 'string') return null
  const first = value.split('/')[0]?.trim()
  const match = first.match(/^([\d.]+)\s*([KMGT]?i?B)$/i)
  if (!match) return null
  const amount = Number.parseFloat(match[1])
  const unit = match[2].toLowerCase()
  if (!Number.isFinite(amount)) return null
  const factors: Record<string, number> = {
    b: 1 / 1048576,
    kb: 1 / 1024,
    kib: 1 / 1024,
    mb: 1,
    mib: 1,
    gb: 1024,
    gib: 1024,
    tb: 1048576,
    tib: 1048576,
  }
  return amount * (factors[unit] || 1)
}

function MetricCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <article className="metric-card">
      <p className="metric-label">{label}</p>
      <p className="metric-value" title={value}>
        {value}
      </p>
      {note ? (
        <p className="metric-note" title={note}>
          {note}
        </p>
      ) : null}
    </article>
  )
}

function statusClass(status: string): string {
  if (status === 'finished') return 'status status-finished'
  if (status === 'error') return 'status status-error'
  return 'status status-other'
}

function StageBars({ rows }: { rows: StageRow[] }) {
  if (rows.length === 0) return <div className="chart-empty">没有阶段耗时数据</div>
  const max = Math.max(...rows.map((row) => row.seconds), 1)
  return (
    <div className="bar-list">
      {rows.map((row) => {
        const width = Math.max(1, (row.seconds / max) * 100)
        const fillClass = row.focus === 'suricata' ? 'bar-fill bar-fill-suricata' : row.focus === 'trident' ? 'bar-fill bar-fill-trident' : 'bar-fill'
        return (
          <div className="bar-row" key={row.key}>
            <div className="bar-label">
              <p className="bar-label-main" title={row.label}>
                {row.label}
              </p>
              <p className="bar-label-desc" title={row.desc}>
                {row.desc}
              </p>
            </div>
            <div className="bar-track">
              <div className={fillClass} style={{ width: `${width}%` }} />
            </div>
            <div className="bar-value">{formatSeconds(row.seconds)}</div>
          </div>
        )
      })}
    </div>
  )
}

function polyline(points: Point[], keyName: string, width: number, height: number, padding: { top: number; right: number; bottom: number; left: number }): string {
  const values = points
    .map((point, index) => ({ index, y: asNumber(point[keyName]) }))
    .filter((point): point is { index: number; y: number } => point.y != null)
  if (values.length < 2) return ''
  const maxY = Math.max(...values.map((point) => point.y), 1)
  const maxX = Math.max(values.length - 1, 1)
  return values
    .map((point, index) => {
      const x = padding.left + (index / maxX) * (width - padding.left - padding.right)
      const y = height - padding.bottom - (point.y / maxY) * (height - padding.top - padding.bottom)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function LineChart({
  series,
  labels,
}: {
  series: Array<{ name: string; keyName: string; color: string; points: Point[] }>
  labels: string[]
}) {
  const valid = series.filter((item) => item.points.length > 1 && polyline(item.points, item.keyName, 820, 280, { top: 18, right: 18, bottom: 34, left: 48 }))
  if (valid.length === 0) return <div className="chart-empty">没有可绘制的时序数据</div>
  const width = 820
  const height = 280
  const padding = { top: 18, right: 18, bottom: 34, left: 48 }
  const labelSlice = labels.slice(0, 4)
  return (
    <>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="time series chart">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = padding.top + ratio * (height - padding.top - padding.bottom)
          return <line className="chart-grid" key={ratio} x1={padding.left} y1={y} x2={width - padding.right} y2={y} />
        })}
        <line className="chart-axis" x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} />
        <line className="chart-axis" x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} />
        {valid.map((item) => (
          <polyline key={item.name} fill="none" stroke={item.color} strokeWidth="2.4" points={polyline(item.points, item.keyName, width, height, padding)} />
        ))}
        {labelSlice.map((label, index) => {
          const x = padding.left + (index / Math.max(labelSlice.length - 1, 1)) * (width - padding.left - padding.right)
          return (
            <text className="chart-label" key={`${label}-${index}`} x={x} y={height - 10} textAnchor="middle">
              {label}
            </text>
          )
        })}
      </svg>
      <div className="legend">
        {valid.map((item) => (
          <span className="legend-item" key={item.name}>
            <span className="legend-dot" style={{ background: item.color }} />
            {item.name}
          </span>
        ))}
      </div>
    </>
  )
}

function App() {
  const [runs, setRuns] = useState<StressRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [detail, setDetail] = useState<StressRunDetail | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadRuns = async (preferredRunId = selectedRunId) => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetchStressRuns()
      setRuns(resp.runs || [])
      const nextRunId = preferredRunId || resp.latestRunId || resp.runs[0]?.id || ''
      setSelectedRunId(nextRunId)
      if (nextRunId) {
        setDetail(await fetchStressRunDetail(nextRunId))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadRuns('')
  }, [])

  const selectRun = async (runId: string) => {
    setSelectedRunId(runId)
    setLoading(true)
    setError('')
    try {
      setDetail(await fetchStressRunDetail(runId))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const filteredRuns = useMemo(() => {
    const q = query.trim().toLowerCase()
    return runs.filter((run) => (q ? run.id.toLowerCase().includes(q) : true))
  }, [query, runs])

  const summary = detail?.summary || {}
  const trident = detail?.trident_benchmark || asRecord(summary.trident_benchmark)
  const derivedTiming = asRecord(summary.derived_timing)
  const componentMetrics = asRecord(summary.derived_component_metrics)
  const suricataMetrics = asRecord(componentMetrics.suricata)
  const suricataResource = asRecord(suricataMetrics.resource)
  const tridentDerivedMetrics = asRecord(componentMetrics.trident)
  const tridentDerivedResource = asRecord(tridentDerivedMetrics.resource)
  const summaryStages = asRecord(summary.stages_seconds)
  const throughput = asRecord(trident.throughput_flows_per_second)
  const redisSummary = asRecord(detail?.redis?.summary)
  const replayStats = asRecord(detail?.replay_stats)
  const replayAvgBytesPerFlow = asNumber(replayStats.avg_bytes_per_flow)
  const replayRatedMbps = asNumber(replayStats.rated_mbps_avg)
  const replayLineGBps = replayRatedMbps == null ? null : replayRatedMbps / 8000
  const e2eGBps = flowRateToGBps(throughput.flows_per_second_end_to_end ?? detail?.run.e2e_fps, replayAvgBytesPerFlow)
  const suricataTotalGBps = flowRateToGBps(suricataMetrics.flow_fps_total, replayAvgBytesPerFlow)
  const suricataReplayGBps = flowRateToGBps(suricataMetrics.flow_fps_replay_only, replayAvgBytesPerFlow)
  const suricataTailGBps = flowRateToGBps(suricataMetrics.flow_fps_tail_only, replayAvgBytesPerFlow)
  const tridentAnalysisGBps = flowRateToGBps(tridentDerivedMetrics.analysis_fps_true, replayAvgBytesPerFlow)
  const tridentRuntimeGBps = flowRateToGBps(tridentDerivedMetrics.runtime_fps_true, replayAvgBytesPerFlow)
  const tridentPureInferenceGBps = flowRateToGBps(tridentDerivedMetrics.reported_fps_inference, replayAvgBytesPerFlow)
  const tridentWindowGBps = flowRateToGBps(tridentDerivedMetrics.stream_window_fps, replayAvgBytesPerFlow)
  const computeDuty = asNumber(tridentDerivedMetrics.compute_duty_cycle)
  const waitRatio = asNumber(tridentDerivedMetrics.wait_ratio)
  const backlogFps = (asNumber(suricataMetrics.flow_fps_total) ?? 0) - (asNumber(tridentDerivedMetrics.runtime_fps_true) ?? 0)

  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar-inner">
          <div>
            <p className="eyebrow">Trident Demo Console</p>
            <h1>Stress Dashboard</h1>
          </div>
          <nav className="nav-tabs" aria-label="Dashboard sections">
            <a className="nav-link nav-link-active" href="#overview">
              关键指标
            </a>
            <a className="nav-link" href="#artifacts">
              历史对比
            </a>
          </nav>
        </div>
      </header>

      <main className="container">
        <section className="panel hero-panel" id="overview">
          <div>
            <p className="eyebrow">E2E Stress Benchmark</p>
            <h2>Suricata → Redis → Trident 压测视图</h2>
            <p className="subtle">
              直接读取 <code>trident_demo/stress_outputs</code>，用于检查压测状态、吞吐、阶段耗时和资源曲线。
            </p>
          </div>
          <div className="controls">
            <label className="field">
              <span className="field-label">Run</span>
              <select className="input-base" value={selectedRunId} onChange={(event) => void selectRun(event.target.value)}>
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.id}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn-primary" type="button" onClick={() => void loadRuns()} disabled={loading}>
              {loading ? '加载中...' : '刷新数据'}
            </button>
          </div>
        </section>

        {error ? <section className="error-panel">加载失败：{error}</section> : null}

        <section className="metric-grid" aria-label="Run summary">
          <MetricCard label="Status" value={String(summary.status || detail?.run.status || '-')} note={String(summary.error || detail?.run.id || '')} />
          <MetricCard label="回放线速" value={formatGBps(replayLineGBps)} note={`${formatNumber(replayRatedMbps, 2)} Mbps（实测）`} />
          <MetricCard
            label="总发送流量"
            value={formatBytes(replayStats.total_bytes)}
            note={`${formatNumber(replayStats.total_packets, 0)} packets / ${formatNumber(replayStats.total_flows, 0)} flows / ${formatNumber(replayStats.rounds, 0)} 轮`}
          />
          <MetricCard
            label="Trident 纯推理速度"
            value={formatGBps(tridentPureInferenceGBps)}
            note={`${formatFlowRate(tridentDerivedMetrics.reported_fps_inference)}（仅模型推理阶段）`}
          />
          <MetricCard
            label="Trident 窗口处理速度"
            value={formatGBps(tridentWindowGBps)}
            note={`${formatFlowRate(tridentDerivedMetrics.stream_window_fps)}（窗口处理，不含上游等待）`}
          />
          <MetricCard
            label="Trident 联机有效速度"
            value={formatGBps(tridentRuntimeGBps)}
            note={`${formatFlowRate(tridentDerivedMetrics.runtime_fps_true)}（含上游等待）`}
          />
          <MetricCard
            label="Trident 计算占空比"
            value={formatPercent(computeDuty)}
            note={`等待占比 ${formatPercent(waitRatio)}（等待上游流量/窗口凑齐）`}
          />
        </section>

        <section className="layout-two">
          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">输入链路（仅参考）</p>
                <h3>Suricata 产出速率受流超时机制影响</h3>
              </div>
            </div>
            <div className="mini-grid">
              <MetricCard
                label="观测产出速度"
                value={formatGBps(suricataTotalGBps)}
                note={`${formatFlowRate(suricataMetrics.flow_fps_total)}（仅用于排队趋势观察）`}
              />
              <MetricCard
                label="回放期产出速度"
                value={formatGBps(suricataReplayGBps)}
                note={`${formatFlowRate(suricataMetrics.flow_fps_replay_only)} / ${formatSeconds(suricataMetrics.replay_seconds)} 回放阶段`}
              />
              <MetricCard
                label="尾部产出速度"
                value={formatGBps(suricataTailGBps)}
                note={`${formatFlowRate(suricataMetrics.flow_fps_tail_only)} / ${formatSeconds(suricataMetrics.settle_seconds)} 收敛阶段`}
              />
              <MetricCard
                label="容器 CPU"
                value={`${formatNumber(suricataResource.cpu_percent_avg, 2)}%`}
                note={`峰值 ${formatNumber(suricataResource.cpu_percent_max, 2)}%`}
              />
              <MetricCard
                label="输入积压速度差"
                value={formatFlowRate(backlogFps)}
                note={backlogFps > 0 ? '正值表示输入快于Trident联机处理' : '负值表示Trident可追平输入'}
              />
              <MetricCard
                label="容器内存峰值"
                value={suricataResource.mem_mib_max ? `${formatNumber(suricataResource.mem_mib_max, 1)} MiB` : '-'}
                note={`${formatNumber(suricataMetrics.flow_delta_total, 0)} flows 输出`}
              />
            </div>
          </article>

          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Trident 真实处理能力</p>
                <h3>优先看纯计算速度，不受 Suricata 出流延迟影响</h3>
              </div>
            </div>
            <div className="mini-grid">
              <MetricCard
                label="纯推理速度（主指标）"
                value={formatGBps(tridentPureInferenceGBps)}
                note={`${formatFlowRate(tridentDerivedMetrics.reported_fps_inference)} / ${formatSeconds(tridentDerivedMetrics.inference_seconds_total)} 推理耗时`}
              />
              <MetricCard
                label="窗口处理速度（次主指标）"
                value={formatGBps(tridentWindowGBps)}
                note={`${formatFlowRate(tridentDerivedMetrics.stream_window_fps)} / ${formatSeconds(tridentDerivedMetrics.stream_window_seconds_total)} 窗口处理耗时`}
              />
              <MetricCard
                label="运行期真实速度"
                value={formatGBps(tridentRuntimeGBps)}
                note={`${formatFlowRate(tridentDerivedMetrics.runtime_fps_true)} / ${formatSeconds(tridentDerivedMetrics.runtime_seconds_total)} 线程运行时长（含等待）`}
              />
              <MetricCard
                label="等待占比"
                value={formatPercent(waitRatio)}
                note={`实验总耗时 ${formatSeconds(tridentDerivedMetrics.experiment_seconds_total)}，可帮助识别上游限速`}
              />
              <MetricCard
                label="离散分析速度"
                value={formatGBps(tridentAnalysisGBps)}
                note={`${formatFlowRate(tridentDerivedMetrics.analysis_fps_true)} / ${formatSeconds(tridentDerivedMetrics.analysis_seconds_total)} 离散统计口径`}
              />
              <MetricCard
                label="进程 CPU"
                value={`${formatNumber(tridentDerivedResource.cpu_percent_one_core_avg, 2)}%`}
                note={`峰值 ${formatNumber(tridentDerivedResource.cpu_percent_one_core_max, 2)}%`}
              />
              <MetricCard
                label="GPU 利用率"
                value={`${formatNumber(tridentDerivedResource.gpu_utilization_percent_avg, 2)}%`}
                note={`峰值 ${formatNumber(tridentDerivedResource.gpu_utilization_percent_max, 2)}%，显存峰值 ${formatNumber(tridentDerivedResource.gpu_memory_used_mb_max, 0)} MB`}
              />
              <MetricCard
                label="端到端速度（参考）"
                value={formatGBps(e2eGBps)}
                note={`${formatFlowRate(tridentDerivedMetrics.reported_fps_end_to_end || throughput.flows_per_second_end_to_end)}（受上游出流节奏影响）`}
              />
            </div>
          </article>
        </section>

        <section className="panel" id="artifacts">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Runs Compare</p>
              <h3>历史压测列表</h3>
            </div>
            <input className="input-base search-input" placeholder="搜索 run_id..." value={query} onChange={(event) => setQuery(event.target.value)} />
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>时间</th>
                  <th>状态</th>
                  <th>Redis XLEN</th>
                  <th>Wall Clock</th>
                  <th>E2E FPS</th>
                  <th>Flows</th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.map((run) => (
                  <tr key={run.id} className={run.id === selectedRunId ? 'active' : ''} onClick={() => void selectRun(run.id)}>
                    <td>{run.id}</td>
                    <td>{run.timestamp || '-'}</td>
                    <td>
                      <span className={statusClass(run.status)}>{run.status || 'unknown'}</span>
                    </td>
                    <td>{formatNumber(run.xlen_last, 0)}</td>
                    <td>{formatSeconds(run.wall_clock_total)}</td>
                    <td>{formatNumber(run.e2e_fps, 2)}</td>
                    <td>{formatNumber(run.flow_count, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

      </main>
    </div>
  )
}

export default App
