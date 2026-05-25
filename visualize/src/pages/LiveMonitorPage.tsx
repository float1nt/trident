import { useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { Select } from 'antd'
import { LearnerMetricAuditPanel } from '../components/LearnerMetricAuditPanel'
import { useLiveTridentStream } from '../hooks/useLiveTridentStream'
import { labelRowsToOptions, pickAuditView } from '../lib/liveApi'
import {
  CHART_AXIS_LINE,
  CHART_SPLIT_LINE,
  CHART_TEXT_PRIMARY,
  CHART_TEXT_SECONDARY,
} from '../theme/notionTheme'

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-amber-500'}`}
    />
  )
}

export default function LiveMonitorPage() {
  const live = useLiveTridentStream({ enabled: true })
  const [selectedLearner, setSelectedLearner] = useState('')

  const learnerOptions = useMemo(() => {
    const fromAudit = live.metricAudit?.learners?.map((l) => l.learner_name) ?? []
    const fromLabels = labelRowsToOptions(live.labelDistributionRows).map((r) => r.name)
    const names = Array.from(new Set([...fromAudit, ...fromLabels])).sort()
    return names
  }, [live.metricAudit, live.labelDistributionRows])

  const effectiveLearner = selectedLearner || learnerOptions[0] || ''
  const auditView = pickAuditView(live.metricAudit, effectiveLearner)
  const meta = labelRowsToOptions(live.labelDistributionRows).find((m) => m.name === effectiveLearner)

  const chartOption: EChartsOption = useMemo(() => {
    const xs = live.windows.map((w) => String(w.window_end_time || `${w.window_left}-${w.window_right}`))
    const ys = live.windows.map((w) => Number(w.learner_count) || 0)
    return {
      backgroundColor: 'transparent',
      grid: { left: 48, right: 24, top: 24, bottom: 48 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: xs,
        axisLabel: { color: CHART_TEXT_SECONDARY, rotate: 35, fontSize: 10 },
        axisLine: { lineStyle: { color: CHART_AXIS_LINE } },
      },
      yAxis: {
        type: 'value',
        name: '学习器数量',
        axisLabel: { color: CHART_TEXT_SECONDARY },
        splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          data: ys,
          symbolSize: 6,
          lineStyle: { width: 2, color: CHART_TEXT_PRIMARY },
        },
      ],
    }
  }, [live.windows])

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-notion-border bg-notion-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-notion-secondary">Live Stream</p>
            <h2 className="mt-1 text-xl font-semibold text-notion-text">Trident 实时监控</h2>
            <p className="mt-2 max-w-3xl text-sm text-notion-secondary">
              监听 <code className="text-xs">outputs/runs/&lt;run_id&gt;/</code> 下的静态产物文件（窗口 CSV、指标审计
              JSON、标签分布 CSV），规则层结果随文件更新实时刷新。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm text-notion-secondary">
              <StatusDot ok={live.connected} />
              {live.connecting ? '连接中…' : live.connected ? '已连接' : '未连接'}
            </div>
            <button
              type="button"
              className="rounded-lg border border-notion-border px-3 py-1.5 text-sm hover:bg-notion-surface-alt"
              onClick={() => live.reconnect()}
            >
              重新连接
            </button>
          </div>
        </div>

        {live.error ? (
          <div className="mt-4 rounded-xl border border-amber-300/40 bg-amber-50/60 px-4 py-3 text-sm text-amber-900">
            {live.error}
          </div>
        ) : null}

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-notion-border bg-notion-surface-alt px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-notion-secondary">Run ID</p>
            <p className="mt-1 truncate text-sm font-medium">{live.runId || '—'}</p>
          </div>
          <div className="rounded-xl border border-notion-border bg-notion-surface-alt px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-notion-secondary">窗口事件</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">{live.windows.length}</p>
          </div>
          <div className="rounded-xl border border-notion-border bg-notion-surface-alt px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-notion-secondary">已审计学习器</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {live.metricAudit?.learners?.length ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-notion-border bg-notion-surface-alt px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-notion-secondary">状态</p>
            <p className="mt-1 text-sm font-medium">
              {live.runFinished ? 'Run 已结束' : live.runId ? '运行中' : '等待 run_started'}
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-notion-border bg-notion-surface p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-notion-text">学习器数量（实时）</h3>
        <div className="mt-3 h-[280px]">
          {live.windows.length > 0 ? (
            <ReactECharts option={chartOption} style={{ height: '100%', width: '100%' }} notMerge />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-notion-secondary">
              等待 window_closed 事件…
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-notion-border bg-notion-surface p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-notion-text">规则层 & 指标审计（实时）</h3>
            <p className="mt-1 text-xs text-notion-secondary">
              规则由 Python 后端计算并通过 Redis 推送；前端只负责展示 reference_rules 匹配结果。
            </p>
          </div>
          <Select
            showSearch
            placeholder="选择学习器"
            className="min-w-[260px]"
            value={effectiveLearner || undefined}
            onChange={setSelectedLearner}
            options={learnerOptions.map((name) => ({ label: name, value: name }))}
          />
        </div>

        {auditView ? (
          <LearnerMetricAuditPanel auditView={auditView} />
        ) : (
          <div className="rounded-xl border border-dashed border-notion-border px-4 py-8 text-center text-sm text-notion-secondary">
            {live.metricAudit ? '当前学习器尚无足够样本或未进入审计列表。' : '等待 learner_metric_audit 事件…'}
          </div>
        )}

        {meta ? (
          <p className="mt-3 text-xs text-notion-secondary">
            分配样本 {meta.flowCount ?? '—'} · 攻击占比 {(meta.attackRatio * 100).toFixed(1)}% · 主标签{' '}
            {meta.dominantLabel}
          </p>
        ) : null}
      </section>
    </div>
  )
}
