import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchRunJsonOptional, fetchRuns, type RunInfo } from '../lib/runApi'

type MetricsJson = {
  risk_false_positive_rate?: number
  risk_false_negative_rate?: number
}

type PerfJson = {
  windows_count?: number
  new_learner_count?: number
  avg_window_seconds?: number
}

type RunRow = {
  id: string
  timestamp: string
  fpr: number | null
  fnr: number | null
  tpr: number | null
  windows: number | null
  learners: number | null
  avgWindowSeconds: number | null
}

function extractTimeFromRunId(runId: string): string {
  const match = runId.match(/(\d{8})_(\d{6})/)
  if (!match) return '-'
  const [, ymd, hms] = match
  const year = ymd.slice(0, 4)
  const month = ymd.slice(4, 6)
  const day = ymd.slice(6, 8)
  const hour = hms.slice(0, 2)
  const minute = hms.slice(2, 4)
  const second = hms.slice(4, 6)
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`
}

function pct(v: number | null): string {
  if (v == null || Number.isNaN(v)) return '-'
  return `${(v * 100).toFixed(4)}%`
}

function num(v: number | null, digits = 4): string {
  if (v == null || Number.isNaN(v)) return '-'
  return digits === 0 ? Math.round(v).toLocaleString() : v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

const RUN_SORT_DEFAULT_KEY: keyof RunRow = 'timestamp'
const RUN_SORT_DEFAULT_DIR: 'asc' | 'desc' = 'desc'

const RUN_SORT_LABELS: Record<keyof RunRow, string> = {
  id: 'Run',
  timestamp: '时间',
  fpr: 'FPR',
  fnr: 'FNR',
  tpr: 'TPR',
  windows: 'Windows',
  learners: 'New Learners',
  avgWindowSeconds: 'Avg Window(s)',
}

const RUNS_COMPARE_STICKY_FIRST_TH =
  'sticky left-0 z-30 border-r border-notion-border bg-notion-surface py-2 pr-4 shadow-[2px_0_10px_-4px_rgba(55,53,47,0.12)]'
const RUNS_COMPARE_STICKY_FIRST_TD =
  'sticky left-0 z-10 border-r border-notion-border bg-notion-surface py-2 pr-4 shadow-[2px_0_8px_-4px_rgba(55,53,47,0.08)] group-hover:bg-notion-surface-alt'

function RunsCompareSortTag({
  columnLabel,
  dir,
  onClear,
  clearDisabled,
}: {
  columnLabel: string
  dir: 'asc' | 'desc'
  onClear: () => void
  clearDisabled?: boolean
}) {
  return (
    <span className="inline-flex max-w-[min(100%,380px)] items-center gap-1 rounded-md border border-notion-border bg-notion-surface-alt px-2 py-1 text-xs text-notion-text shadow-sm">
      <span className="shrink-0 text-notion-secondary">排序</span>
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

export default function RunsComparePage() {
  const [rows, setRows] = useState<RunRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sortBy, setSortBy] = useState<keyof RunRow>(RUN_SORT_DEFAULT_KEY)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(RUN_SORT_DEFAULT_DIR)
  const [query, setQuery] = useState('')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const runsResp = await fetchRuns()
        const runs = runsResp.runs || []
        const selectedRuns = runs.slice(0, 120)
        const detailRows = await Promise.all(
          selectedRuns.map(async (run: RunInfo): Promise<RunRow> => {
            const [metrics, perf] = await Promise.all([
              fetchRunJsonOptional<MetricsJson>(run.id, 'metrics.json'),
              fetchRunJsonOptional<PerfJson>(run.id, 'performance_metrics.json'),
            ])
            const fpr = typeof metrics?.risk_false_positive_rate === 'number' ? metrics.risk_false_positive_rate : null
            const fnr = typeof metrics?.risk_false_negative_rate === 'number' ? metrics.risk_false_negative_rate : null
            return {
              id: run.id,
              timestamp: extractTimeFromRunId(run.id),
              fpr,
              fnr,
              tpr: fnr == null ? null : 1 - fnr,
              windows: typeof perf?.windows_count === 'number' ? perf.windows_count : null,
              learners: typeof perf?.new_learner_count === 'number' ? perf.new_learner_count : null,
              avgWindowSeconds: typeof perf?.avg_window_seconds === 'number' ? perf.avg_window_seconds : null,
            }
          }),
        )
        setRows(detailRows)
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setError(`加载 run 对比失败: ${message}`)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = rows.filter((row) => (q ? row.id.toLowerCase().includes(q) : true))
    const sorted = [...list]
    sorted.sort((a, b) => {
      if (sortBy === 'timestamp' || sortBy === 'id') {
        const cmp = String(a[sortBy]).localeCompare(String(b[sortBy]))
        return sortDir === 'asc' ? cmp : -cmp
      }
      const va = (a[sortBy] as number | null) ?? Number.NEGATIVE_INFINITY
      const vb = (b[sortBy] as number | null) ?? Number.NEGATIVE_INFINITY
      return sortDir === 'asc' ? va - vb : vb - va
    })
    return sorted
  }, [query, rows, sortBy, sortDir])

  const switchSort = (key: keyof RunRow) => {
    if (sortBy === key) {
      setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))
      return
    }
    setSortBy(key)
    setSortDir(key === 'id' || key === 'timestamp' ? 'asc' : 'desc')
  }

  const sortIndicator = (key: keyof RunRow) => {
    if (sortBy !== key) return ''
    return sortDir === 'desc' ? '▼' : '▲'
  }

  const summary = useMemo(() => {
    const withMetrics = rows.filter((r) => r.fpr != null && r.fnr != null)
    if (withMetrics.length === 0) {
      return { total: rows.length, bestRun: '-', bestFnr: null as number | null, avgFpr: null as number | null }
    }
    const best = [...withMetrics].sort((a, b) => (a.fnr ?? 1) - (b.fnr ?? 1))[0]
    const avgFpr = withMetrics.reduce((acc, cur) => acc + (cur.fpr ?? 0), 0) / withMetrics.length
    return { total: rows.length, bestRun: best.id, bestFnr: best.fnr, avgFpr }
  }, [rows])

  return (
    <div className="space-y-5">
      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">Run Security Benchmark</p>
            <h1 className="text-2xl font-semibold tracking-wide text-notion-text">全部 Run 效果对比</h1>
            <p className="mt-1 text-sm text-notion-secondary">聚焦 risk FPR / FNR / TPR，快速筛选最稳配置。</p>
          </div>
          <button
            type="button"
            className="btn-primary"
            onClick={() => window.location.reload()}
            disabled={loading}
          >
            {loading ? '加载中...' : '刷新数据'}
          </button>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <article className="metric-card">
          <p className="metric-label">Run 数量</p>
          <p className="metric-value">{summary.total}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">平均 FPR</p>
          <p className="metric-value">{pct(summary.avgFpr)}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">最佳 FNR</p>
          <p className="metric-value">{pct(summary.bestFnr)}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">最佳 Run</p>
          <p className="truncate text-sm text-notion-text">{summary.bestRun}</p>
        </article>
      </section>

      <section className="panel">
        <div className="mb-4 flex flex-wrap items-center justify-end gap-3">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <RunsCompareSortTag
              columnLabel={RUN_SORT_LABELS[sortBy]}
              dir={sortDir}
              clearDisabled={sortBy === RUN_SORT_DEFAULT_KEY && sortDir === RUN_SORT_DEFAULT_DIR}
              onClear={() => {
                setSortBy(RUN_SORT_DEFAULT_KEY)
                setSortDir(RUN_SORT_DEFAULT_DIR)
              }}
            />
            <span className="text-xs text-notion-secondary">点击表头切换排序</span>
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索 run_id..."
            className="input-base w-72"
          />
        </div>

        {error ? <p className="text-sm text-notion-danger">{error}</p> : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b border-notion-border text-left text-notion-secondary">
                <th className={RUNS_COMPARE_STICKY_FIRST_TH}>
                  <button type="button" onClick={() => switchSort('id')} className="sortable-head">
                    Run {sortIndicator('id')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('timestamp')} className="sortable-head">
                    时间 {sortIndicator('timestamp')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('fpr')} className="sortable-head">
                    FPR {sortIndicator('fpr')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('fnr')} className="sortable-head">
                    FNR {sortIndicator('fnr')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('tpr')} className="sortable-head">
                    TPR {sortIndicator('tpr')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('windows')} className="sortable-head">
                    Windows {sortIndicator('windows')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('learners')} className="sortable-head">
                    New Learners {sortIndicator('learners')}
                  </button>
                </th>
                <th className="py-2 pr-4">
                  <button type="button" onClick={() => switchSort('avgWindowSeconds')} className="sortable-head">
                    Avg Window(s) {sortIndicator('avgWindowSeconds')}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => (
                <tr key={row.id} className="group border-b border-notion-border text-notion-text hover:bg-notion-surface-alt">
                  <td className={`max-w-[480px] font-mono text-xs ${RUNS_COMPARE_STICKY_FIRST_TD}`}>
                    <Link to={`/run/${encodeURIComponent(row.id)}`} className="text-notion-text hover:text-notion-text hover:underline">
                      {row.id}
                    </Link>
                  </td>
                  <td className="py-2 pr-4 font-mono text-xs text-notion-secondary">{row.timestamp}</td>
                  <td className="py-2 pr-4">
                    <span className="rounded-md bg-notion-danger-bg px-2 py-1 text-notion-danger">{pct(row.fpr)}</span>
                  </td>
                  <td className="py-2 pr-4">
                    <span className="rounded-md bg-notion-warning-bg px-2 py-1 text-notion-warning">{pct(row.fnr)}</span>
                  </td>
                  <td className="py-2 pr-4">
                    <span className="rounded-md bg-notion-success-bg px-2 py-1 text-notion-success">{pct(row.tpr)}</span>
                  </td>
                  <td className="py-2 pr-4">{num(row.windows, 0)}</td>
                  <td className="py-2 pr-4">{num(row.learners, 0)}</td>
                  <td className="py-2 pr-4">{row.avgWindowSeconds == null ? '-' : `${num(row.avgWindowSeconds)} s`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
