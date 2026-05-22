import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Select } from 'antd'
import { LearnerInternalTopologyPanel } from '../components/LearnerInternalTopologyPanel'
import { LearnerMetricAuditPanel } from '../components/LearnerMetricAuditPanel'
import {
  fetchRunJsonOptional,
  fetchRuns,
  parseCsv,
  runDataUrl,
  type RunInfo,
} from '../lib/runApi'
import type {
  LearnerNetworkTopologyJson,
  LearnerTopologyMetricAuditJson,
  LearnerTopologyOption,
} from '../types/learnerTopology'

type LearnerDistRow = {
  learner_name: string
  attack_ratio: string
  dominant_label: string
  dominant_ratio: string
  total_assigned_samples: string
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-notion-border bg-notion-surface px-4 py-3 shadow-sm">
      <p className="text-[11px] uppercase tracking-wide text-notion-secondary">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-notion-text">{value}</p>
      {sub ? <p className="mt-0.5 text-xs text-notion-secondary">{sub}</p> : null}
    </div>
  )
}

export default function LearnerDetailPage() {
  const params = useParams<{ runId?: string }>()
  const routeRunId = params.runId ? decodeURIComponent(params.runId) : ''
  const [searchParams, setSearchParams] = useSearchParams()
  const learnerFromUrl = searchParams.get('learner')?.trim() || ''

  const [runs, setRuns] = useState<RunInfo[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [selectedLearner, setSelectedLearner] = useState(learnerFromUrl)
  const [topology, setTopology] = useState<LearnerNetworkTopologyJson | null>(null)
  const [metricAudit, setMetricAudit] = useState<LearnerTopologyMetricAuditJson | null>(null)
  const [learnerMeta, setLearnerMeta] = useState<LearnerTopologyOption[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchRuns()
      .then((result) => {
        const available = result.runs || []
        setRuns(available)
        if (routeRunId && available.some((r) => r.id === routeRunId)) {
          setSelectedRunId(routeRunId)
        } else if (result.latestRunId) {
          setSelectedRunId(result.latestRunId)
        } else if (available[0]) {
          setSelectedRunId(available[0].id)
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err))
      })
  }, [routeRunId])

  useEffect(() => {
    if (!selectedRunId) return
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const [topologyJson, auditJson, distRows] = await Promise.all([
          fetchRunJsonOptional<LearnerNetworkTopologyJson>(
            selectedRunId,
            'learner_network_topology.json',
          ),
          fetchRunJsonOptional<LearnerTopologyMetricAuditJson>(
            selectedRunId,
            'learner_topology_metric_audit.json',
          ),
          parseCsv<LearnerDistRow>(
            runDataUrl(selectedRunId, 'learner_label_distribution.csv'),
          ).catch(() => [] as LearnerDistRow[]),
        ])
        setTopology(topologyJson)
        setMetricAudit(auditJson)
        setLearnerMeta(
          distRows
            .filter((r) => r.learner_name)
            .map((r) => ({
              name: r.learner_name,
              attackRatio: Number(r.attack_ratio) || 0,
              dominantLabel: r.dominant_label || '—',
              flowCount: Number(r.total_assigned_samples) || undefined,
            })),
        )
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [selectedRunId])

  const sortedLearnerOptions = useMemo(() => {
    const names = new Set<string>()
    topology?.learners?.forEach((n) => names.add(n))
    metricAudit?.learners?.forEach((l) => names.add(l.learner_name))
    learnerMeta.forEach((m) => names.add(m.name))

    const metaMap = new Map(learnerMeta.map((m) => [m.name, m]))
    const auditMap = new Map(
      (metricAudit?.learners ?? []).map((l) => [l.learner_name, l]),
    )
    const topoMap = topology?.views ?? {}

    return [...names]
      .map((name) => {
        const meta = metaMap.get(name)
        const audit = auditMap.get(name)
        const topo = topoMap[name]
        return {
          name,
          attackRatio:
            topo?.attack_ratio ?? audit?.attack_ratio ?? meta?.attackRatio ?? 0,
          dominantLabel:
            topo?.dominant_label ?? audit?.dominant_label ?? meta?.dominantLabel ?? '—',
          flowCount:
            audit?.flow_count ??
            topo?.host?.flow_count ??
            meta?.flowCount,
        } satisfies LearnerTopologyOption
      })
      .sort((a, b) => b.attackRatio - a.attackRatio || a.name.localeCompare(b.name))
  }, [topology, metricAudit, learnerMeta])

  const effectiveLearner = useMemo(() => {
    if (!sortedLearnerOptions.length) return ''
    if (
      learnerFromUrl &&
      sortedLearnerOptions.some((o) => o.name === learnerFromUrl)
    ) {
      return learnerFromUrl
    }
    if (
      selectedLearner &&
      sortedLearnerOptions.some((o) => o.name === selectedLearner)
    ) {
      return selectedLearner
    }
    return sortedLearnerOptions[0].name
  }, [learnerFromUrl, selectedLearner, sortedLearnerOptions])

  const handleLearnerChange = (name: string) => {
    setSelectedLearner(name)
    const next = new URLSearchParams(searchParams)
    next.set('learner', name)
    setSearchParams(next, { replace: true })
  }

  const auditView = useMemo(
    () =>
      metricAudit?.learners?.find((l) => l.learner_name === effectiveLearner) ?? null,
    [metricAudit, effectiveLearner],
  )

  const auditSkip = useMemo(
    () =>
      metricAudit?.learners_skipped?.find((s) => s.learner_name === effectiveLearner) ?? null,
    [metricAudit, effectiveLearner],
  )

  const summary = useMemo(() => {
    const opt = sortedLearnerOptions.find((o) => o.name === effectiveLearner)
    const audit = auditView
    const topo = topology?.views[effectiveLearner]
    const flowCount =
      audit?.flow_count ??
      topo?.host?.flow_count ??
      opt?.flowCount
    const attack =
      topo?.attack_ratio ?? audit?.attack_ratio ?? opt?.attackRatio
    const domLabel = topo?.dominant_label ?? audit?.dominant_label ?? opt?.dominantLabel
    const domRatio = topo?.dominant_ratio ?? audit?.dominant_ratio
    return { flowCount, attack, domLabel, domRatio }
  }, [effectiveLearner, sortedLearnerOptions, auditView, topology])

  const selectOptions = sortedLearnerOptions.map((o) => ({
    value: o.name,
    label: `${o.name} · 攻击 ${(o.attackRatio * 100).toFixed(1)}% · ${o.dominantLabel}${o.flowCount != null ? ` · ${o.flowCount.toLocaleString()} 流` : ''}`,
  }))

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-notion-secondary">Learner drill-down</p>
          <h2 className="text-xl font-semibold text-notion-text">学习器详情</h2>
          <p className="mt-1 max-w-2xl text-sm text-notion-secondary">
            切换学习器查看内部网络拓扑与分组审计指标；指标分数仅表示单项强弱，需结合语义说明综合判断。
          </p>
        </div>
        <Link
          to={selectedRunId ? `/run/${encodeURIComponent(selectedRunId)}` : '/run-detail'}
          className="btn-secondary shrink-0 text-sm"
        >
          ← 返回 Run 详情
        </Link>
      </div>

      <section className="panel space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="field-label">Run</label>
            <select
              className="input-base w-full font-mono text-xs"
              value={selectedRunId}
              onChange={(e) => setSelectedRunId(e.target.value)}
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">学习器（按攻击占比降序）</label>
            <Select
              className="w-full"
              showSearch
              optionFilterProp="label"
              loading={loading}
              value={effectiveLearner || undefined}
              onChange={(v) => handleLearnerChange(String(v))}
              options={selectOptions}
              popupMatchSelectWidth={false}
              dropdownStyle={{ minWidth: 560 }}
            />
          </div>
        </div>
        {error ? (
          <p className="rounded-lg border border-notion-danger-border bg-notion-danger-bg px-3 py-2 text-sm text-notion-danger">
            {error}
          </p>
        ) : null}
      </section>

      {effectiveLearner ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="流数量"
              value={
                summary.flowCount != null
                  ? summary.flowCount.toLocaleString()
                  : '—'
              }
            />
            <StatCard
              label="攻击占比"
              value={
                summary.attack != null
                  ? `${(summary.attack * 100).toFixed(2)}%`
                  : '—'
              }
            />
            <StatCard label="主导标签" value={summary.domLabel || '—'} />
            <StatCard
              label="主导标签占比"
              value={
                summary.domRatio != null
                  ? `${(summary.domRatio * 100).toFixed(2)}%`
                  : '—'
              }
            />
          </section>

          <section className="panel">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-widest text-notion-secondary">
              内部网络拓扑
            </h3>
            <LearnerInternalTopologyPanel
              data={topology}
              learnerOptions={sortedLearnerOptions}
              selectedLearner={effectiveLearner}
              onLearnerChange={handleLearnerChange}
              singleLearnerMode
            />
          </section>

          <section className="panel">
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-widest text-notion-secondary">
              拓扑审计指标
            </h3>
            <p className="mb-4 text-xs text-notion-secondary">
              按指标分组展示分数与语义；不提供组合总分。
              {metricAudit?.export_filters?.min_samples != null ? (
                <> 导出阈值：至少 {metricAudit.export_filters.min_samples} 条已 join 流。</>
              ) : null}
            </p>
            {auditSkip ? (
              <div className="mb-4 rounded-lg border border-notion-warning-border bg-notion-warning-bg px-3 py-2 text-sm text-notion-text">
                该学习器无审计指标：<span className="font-mono text-xs">{auditSkip.reason}</span>
                {auditSkip.label_distribution_samples != null ? (
                  <>（标签表样本 {auditSkip.label_distribution_samples.toLocaleString()}，但未 join 到流式分配）</>
                ) : auditSkip.flow_count_joined != null ? (
                  <>（已 join {auditSkip.flow_count_joined} 条流）</>
                ) : null}
              </div>
            ) : null}
            <LearnerMetricAuditPanel auditView={auditView} />
          </section>
        </>
      ) : (
        <div className="panel text-sm text-notion-secondary">
          {loading ? '加载中…' : '暂无学习器数据，请先选择有效 Run 或导出审计/拓扑 JSON。'}
        </div>
      )}
    </div>
  )
}
