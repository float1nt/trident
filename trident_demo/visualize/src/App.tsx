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

function StageBars({ stages }: { stages: JsonRecord }) {
  const rows = Object.entries(stages)
    .filter(([, value]) => typeof value === 'number')
    .sort((a, b) => Number(b[1]) - Number(a[1]))
  const max = Number(rows[0]?.[1] || 1)
  if (rows.length === 0) return <div className="chart-empty">没有阶段耗时数据</div>
  return (
    <div className="bar-list">
      {rows.map(([key, value]) => {
        const width = Math.max(1, (Number(value) / max) * 100)
        return (
          <div className="bar-row" key={key}>
            <div className="bar-label" title={key}>
              {key}
            </div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${width}%` }} />
            </div>
            <div className="bar-value">{formatSeconds(value)}</div>
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
  const stages = asRecord(summary.stages_seconds)
  const throughput = asRecord(trident.throughput_flows_per_second)
  const resource = asRecord(trident.resource_usage)
  const streamPerf = asRecord(trident.stream_perf_stats)
  const qualification = asRecord(trident.qualification_detail)
  const redisSummary = asRecord(detail?.redis?.summary)
  const redisSamples = asArray(detail?.redis?.samples || asRecord(summary.redis).samples)
  const dockerSamples = asArray(detail?.docker?.samples)
  const redisPoints: Point[] = redisSamples.map((sample) => ({
    timestamp: typeof sample.timestamp === 'string' ? sample.timestamp : undefined,
    xlen: asNumber(sample.xlen),
    ops: asNumber(sample.instantaneous_ops_per_sec),
    mem: asNumber(sample.used_memory) == null ? null : Number(sample.used_memory) / 1048576,
  }))
  const dockerPoints: Point[] = dockerSamples
    .filter((sample) => sample.container === 'suricata-cic-live' || sample.Name === 'suricata-cic-live')
    .map((sample) => ({
      timestamp: typeof sample.timestamp === 'string' ? sample.timestamp : undefined,
      cpu: parsePercent(sample.CPUPerc),
      mem: parseMemMiB(sample.MemUsage),
    }))
  const redisLabels = redisPoints.filter((_, index) => index % Math.max(1, Math.floor(redisPoints.length / 4)) === 0).map((point) => formatTime(point.timestamp))
  const dockerLabels = dockerPoints.filter((_, index) => index % Math.max(1, Math.floor(dockerPoints.length / 4)) === 0).map((point) => formatTime(point.timestamp))

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
              压测概览
            </a>
            <a className="nav-link" href="#timeline">
              时序指标
            </a>
            <a className="nav-link" href="#artifacts">
              产物
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
          <MetricCard label="Redis XLEN" value={formatNumber(redisSummary.xlen_last ?? detail?.run.xlen_last, 0)} note={String(detail?.run.stream || '')} />
          <MetricCard label="E2E FPS" value={formatNumber(throughput.flows_per_second_end_to_end ?? detail?.run.e2e_fps, 2)} note="pipeline core throughput" />
          <MetricCard label="Inference FPS" value={formatNumber(throughput.flows_per_second_inference ?? detail?.run.inference_fps, 2)} note={`${formatNumber(trident.flow_count, 0)} flows`} />
          <MetricCard label="RSS Peak" value={asNumber(resource.process_rss_peak_mb) == null ? '-' : `${formatNumber(resource.process_rss_peak_mb, 1)} MB`} note={`${formatNumber(streamPerf.windows_count, 0)} windows`} />
        </section>

        <section className="layout-two">
          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Stage Breakdown</p>
                <h3>压测阶段耗时</h3>
              </div>
            </div>
            <StageBars stages={stages} />
          </article>

          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Trident Benchmark</p>
                <h3>核心吞吐与资源</h3>
              </div>
            </div>
            <div className="mini-grid">
              <MetricCard label="Device" value={String(resource.compute_device || '-')} note={resource.gpu_available ? 'GPU available' : 'CPU path'} />
              <MetricCard label="CPU Avg" value={asNumber(resource.process_cpu_percent_one_core_avg) == null ? '-' : `${formatNumber(resource.process_cpu_percent_one_core_avg, 2)}%`} note={`${formatNumber(resource.cpu_logical_count, 0)} logical cores`} />
              <MetricCard label="Window Avg" value={formatSeconds(streamPerf.avg_window_seconds)} note={`${formatNumber(streamPerf.new_learner_count, 0)} new learners`} />
              <MetricCard label="Audit Flows" value={formatNumber(qualification.audited_flow_count, 0)} note={`${formatSeconds(qualification.qualification_total_seconds)} qualification`} />
            </div>
          </article>
        </section>

        <section className="layout-two" id="timeline">
          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Redis Stream</p>
                <h3>流长度与 Ops</h3>
              </div>
            </div>
            <div className="chart">
              <LineChart
                labels={redisLabels}
                series={[
                  { name: 'XLEN', keyName: 'xlen', color: colors.blue, points: redisPoints },
                  { name: 'Ops/sec', keyName: 'ops', color: colors.green, points: redisPoints },
                  { name: 'Memory MiB', keyName: 'mem', color: colors.orange, points: redisPoints },
                ]}
              />
            </div>
          </article>

          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Docker Stats</p>
                <h3>容器 CPU 与内存</h3>
              </div>
            </div>
            <div className="chart">
              <LineChart
                labels={dockerLabels}
                series={[
                  { name: 'Suricata CPU %', keyName: 'cpu', color: colors.red, points: dockerPoints },
                  { name: 'Suricata Mem MiB', keyName: 'mem', color: colors.blue, points: dockerPoints },
                ]}
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

        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Artifact Paths</p>
              <h3>当前 Run 产物</h3>
            </div>
          </div>
          <dl className="artifact-list">
            <dt>stress run</dt>
            <dd title={detail?.run.run_dir || String(summary.run_dir || '-')}>{detail?.run.run_dir || String(summary.run_dir || '-')}</dd>
            <dt>trident run</dt>
            <dd title={detail?.run.trident_run_dir || String(summary.trident_run_dir || '-')}>{detail?.run.trident_run_dir || String(summary.trident_run_dir || '-')}</dd>
            <dt>redis stream</dt>
            <dd title={detail?.run.stream || '-'}>{detail?.run.stream || '-'}</dd>
            <dt>finished at</dt>
            <dd>{String(summary.finished_at || '-')}</dd>
          </dl>
        </section>
      </main>
    </div>
  )
}

export default App
