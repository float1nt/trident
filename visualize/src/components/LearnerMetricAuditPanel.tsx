import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import type { LearnerMetricAuditItem, LearnerMetricAuditView } from '../types/learnerTopology'
import { metricBadgeStyle, metricBarColor } from '../theme/metricAuditTheme'
import {
  CHART_AXIS_LINE,
  CHART_SPLIT_LINE,
  CHART_TEXT_PRIMARY,
  CHART_TEXT_SECONDARY,
  notionTheme,
} from '../theme/notionTheme'

function groupMetrics(metrics: LearnerMetricAuditItem[]): { group: string; items: LearnerMetricAuditItem[] }[] {
  const order: string[] = []
  const map = new Map<string, LearnerMetricAuditItem[]>()
  for (const m of metrics) {
    if (!map.has(m.group)) {
      map.set(m.group, [])
      order.push(m.group)
    }
    map.get(m.group)!.push(m)
  }
  return order.map((group) => ({ group, items: map.get(group)! }))
}

function displayTag(m: LearnerMetricAuditItem): string {
  return m.semantic_tag || m.strength_label || m.semantic_level || '—'
}

function barOption(group: string, items: LearnerMetricAuditItem[]): EChartsOption {
  const names = items.map((m) => m.metric_name)
  const scores = items.map((m) => Number(m.score_0_100.toFixed(1)))
  const colors = items.map((m) => metricBarColor(m.trait_axis, m.score_0_100))

  return {
    backgroundColor: 'transparent',
    grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const p = (Array.isArray(params) ? params[0] : params) as { dataIndex?: number }
        const idx = p?.dataIndex ?? 0
        const m = items[idx]
        if (!m) return ''
        const axis = m.trait_axis_label ? `维度：${m.trait_axis_label}` : ''
        return [
          `<b>${m.metric_name}</b>`,
          `强度 ${m.score_0_100.toFixed(1)} · ${displayTag(m)}（${m.strength_label ?? '—'}）`,
          axis,
          `原始值 ${m.raw_value}`,
          m.semantic_text,
        ]
          .filter(Boolean)
          .join('<br/>')
      },
    },
    xAxis: {
      type: 'value',
      max: 100,
      name: '特征强度',
      nameTextStyle: { color: CHART_TEXT_SECONDARY, fontSize: 10 },
      axisLabel: { color: CHART_TEXT_SECONDARY, fontSize: 10 },
      splitLine: { lineStyle: { color: CHART_SPLIT_LINE } },
      axisLine: { lineStyle: { color: CHART_AXIS_LINE } },
    },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true,
      axisLabel: {
        color: CHART_TEXT_PRIMARY,
        fontSize: 11,
        width: 140,
        overflow: 'truncate',
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: scores.map((v, i) => ({
          value: v,
          itemStyle: { color: colors[i], borderRadius: [0, 4, 4, 0] },
        })),
        barMaxWidth: 14,
        label: {
          show: true,
          position: 'right',
          formatter: '{c}',
          fontSize: 10,
          color: CHART_TEXT_SECONDARY,
        },
      },
    ],
    title: { show: false, text: group },
  }
}

type Props = {
  auditView: LearnerMetricAuditView | null
}

export function LearnerMetricAuditPanel({ auditView }: Props) {
  const groups = useMemo(
    () => (auditView?.metrics?.length ? groupMetrics(auditView.metrics) : []),
    [auditView],
  )

  if (!auditView) {
    return (
      <div className="rounded-xl border border-dashed border-notion-border-strong bg-notion-surface-alt p-6 text-sm text-notion-secondary">
        选择学习器后展示审计指标；若本 run 无数据，请执行：
        <pre className="mt-2 overflow-x-auto rounded-lg bg-notion-surface p-3 text-xs text-notion-text">
          python3 scripts/export_learner_topology_metric_audit.py outputs/runs/&lt;run_id&gt;
        </pre>
      </div>
    )
  }

  if (!groups.length) {
    return (
      <div className="rounded-xl border border-notion-border bg-notion-surface-alt p-4 text-sm text-notion-secondary">
        该学习器暂无审计指标记录。
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-notion-border bg-notion-surface-alt px-3 py-2 text-[11px] leading-relaxed text-notion-secondary">
        分数表示<strong className="font-medium text-notion-text">该拓扑特征的表现强度</strong>
        （0–100），不是风险分或异常分。颜色按<strong className="font-medium text-notion-text">特征维度</strong>
        区分（分散/集中/突发等），高分仅表示该维度上「更强」，需结合语义说明判断形态。
      </p>

      {auditView.qualitative_hints && auditView.qualitative_hints.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {auditView.qualitative_hints.map((h) => (
            <div
              key={h.hint_key}
              className="max-w-full rounded-lg border border-notion-info-border bg-notion-info-bg px-3 py-2 text-xs"
            >
              <span className="font-semibold text-notion-info">{h.hint_key}</span>
              <span className="ml-2 text-notion-text">{h.hint_text}</span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {groups.map(({ group, items }) => (
          <article
            key={group}
            className="overflow-hidden rounded-xl border border-notion-border bg-notion-surface shadow-sm"
          >
            <header className="flex items-center justify-between border-b border-notion-border bg-notion-surface-alt px-4 py-2.5">
              <h3 className="text-sm font-semibold text-notion-text">{group}</h3>
              <span className="text-[11px] text-notion-secondary">{items.length} 项指标</span>
            </header>
            <div className="px-2 py-2">
              <ReactECharts
                option={barOption(group, items)}
                style={{ height: Math.max(160, items.length * 36) }}
                notMerge
                lazyUpdate
              />
            </div>
            <div className="grid gap-2 border-t border-notion-border p-3 sm:grid-cols-2">
              {items.map((m) => {
                const badge = metricBadgeStyle(m.trait_axis, m.score_0_100)
                const barColor = metricBarColor(m.trait_axis, m.score_0_100)
                return (
                  <div
                    key={m.metric_key}
                    className="rounded-lg border border-notion-border bg-notion-surface-alt/80 p-2.5"
                  >
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="text-xs font-medium text-notion-text">{m.metric_name}</span>
                        {m.trait_axis_label ? (
                          <span className="mt-0.5 block text-[10px] text-notion-tertiary">
                            {m.trait_axis_label}
                          </span>
                        ) : null}
                      </div>
                      <span
                        className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
                        style={{
                          background: badge.background,
                          color: badge.color,
                          border: badge.border,
                        }}
                        title={m.strength_label ?? undefined}
                      >
                        {displayTag(m)}
                      </span>
                    </div>
                    <div className="mb-1 h-1.5 overflow-hidden rounded-full bg-notion-border">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.min(100, m.score_0_100)}%`,
                          background: barColor,
                        }}
                      />
                    </div>
                    <p className="text-[10px] leading-snug text-notion-secondary">
                      强度 {m.score_0_100.toFixed(1)}
                      {m.strength_label ? ` · ${m.strength_label}` : null}
                      {' · 原始 '}
                      {m.raw_value}
                    </p>
                    <p className="mt-1 text-[11px] leading-relaxed text-notion-text">{m.semantic_text}</p>
                  </div>
                )
              })}
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
