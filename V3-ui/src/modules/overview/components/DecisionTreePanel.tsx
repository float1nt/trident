import { useMemo, useState } from 'react'
import { Select } from 'antd'
import ReactECharts from 'echarts-for-react'
import { notionTheme } from '../theme/notionTheme'

export type DecisionTreeTask = {
  id: string
  scope: 'learner' | 'label' | 'flow'
  n_samples?: number
  cv_accuracy_mean?: number | null
  cv_f1_macro_mean?: number | null
  cv_fpr?: number | null
  cv_fnr?: number | null
  top_feature_importance?: Array<{ feature: string; importance: number }>
  tree_rules?: string
}

export type DecisionTreeVizJson = {
  tasks?: DecisionTreeTask[]
}

const SCOPE_LABEL: Record<string, string> = {
  learner: '学习器',
  label: '数据集标签',
  flow: '原始流',
}

function pct(v: number | null | undefined): string {
  if (typeof v !== 'number' || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(2)}%`
}

type Props = {
  data: DecisionTreeVizJson | null
}

export function DecisionTreePanel({ data }: Props) {
  const tasks = useMemo(() => data?.tasks ?? [], [data])
  const [taskId, setTaskId] = useState<string>('')

  const selected = useMemo(() => {
    if (!tasks.length) return null
    const id = taskId || tasks[0].id
    return tasks.find((t) => t.id === id) ?? tasks[0]
  }, [tasks, taskId])

  const importanceOption = useMemo(() => {
    const rows = (selected?.top_feature_importance ?? []).slice(0, 16)
    return {
      grid: { left: 140, right: 24, top: 16, bottom: 24 },
      xAxis: { type: 'value' },
      yAxis: {
        type: 'category',
        data: rows.map((r) => r.feature).reverse(),
        axisLabel: { fontSize: 10 },
      },
      series: [{ type: 'bar', data: rows.map((r) => r.importance).reverse(), itemStyle: { color: notionTheme.chart.accent } }],
      tooltip: { trigger: 'axis' },
    }
  }, [selected])

  if (!tasks.length) {
    return (
      <p className="text-sm text-notion-secondary">
        暂无决策树结果。请确认主流程已开启 decision_tree.enabled 并完成 run。
      </p>
    )
  }

  const activeId = selected?.id ?? ''

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-notion-secondary">分析任务</span>
        <Select
          className="min-w-[360px]"
          value={activeId}
          onChange={setTaskId}
          options={tasks.map((t) => ({
            value: t.id,
            label: `[${SCOPE_LABEL[t.scope] ?? t.scope}] ${t.id}`,
          }))}
        />
        {selected?.n_samples != null && (
          <span className="text-xs text-notion-secondary">n = {selected.n_samples.toLocaleString()}</span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-notion-border bg-notion-surface-alt px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-notion-secondary">CV 准确率</div>
          <div className="text-lg font-semibold text-notion-text">{pct(selected?.cv_accuracy_mean)}</div>
        </div>
        <div className="rounded-lg border border-notion-border bg-notion-surface-alt px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-notion-secondary">CV F1 macro</div>
          <div className="text-lg font-semibold text-notion-text">{pct(selected?.cv_f1_macro_mean)}</div>
        </div>
        <div className="rounded-lg border border-notion-danger/30 bg-notion-danger-bg/80 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-notion-danger">CV 误报率 FPR</div>
          <div className="text-lg font-semibold text-notion-danger">{pct(selected?.cv_fpr)}</div>
          <div className="text-[10px] text-notion-danger">良性判为攻击</div>
        </div>
        <div className="rounded-lg border border-notion-warning/30 bg-notion-warning-bg/80 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-notion-warning">CV 漏报率 FNR</div>
          <div className="text-lg font-semibold text-notion-warning">{pct(selected?.cv_fnr)}</div>
          <div className="text-[10px] text-notion-warning">攻击判为良性</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="rounded-lg border border-notion-border p-2">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-notion-secondary">特征重要性 Top16</h3>
          <ReactECharts option={importanceOption} style={{ height: 360 }} />
        </article>
        <article className="rounded-lg border border-notion-border p-2">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-notion-secondary">决策规则树</h3>
          <pre className="code-block max-h-[520px]">
            {selected?.tree_rules?.trim() || '（无规则文本）'}
          </pre>
        </article>
      </div>
    </div>
  )
}
