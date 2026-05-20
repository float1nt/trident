import { useMemo, useState } from 'react'
import { Select } from 'antd'
import ReactECharts from 'echarts-for-react'

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
  const tasks = data?.tasks ?? []
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
      series: [{ type: 'bar', data: rows.map((r) => r.importance).reverse(), itemStyle: { color: '#2563eb' } }],
      tooltip: { trigger: 'axis' },
    }
  }, [selected])

  if (!tasks.length) {
    return (
      <p className="text-sm text-slate-500">
        暂无决策树结果。请确认主流程已开启 decision_tree.enabled 并完成 run。
      </p>
    )
  }

  const activeId = selected?.id ?? ''

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-slate-600">分析任务</span>
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
          <span className="text-xs text-slate-500">n = {selected.n_samples.toLocaleString()}</span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">CV 准确率</div>
          <div className="text-lg font-semibold text-slate-800">{pct(selected?.cv_accuracy_mean)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">CV F1 macro</div>
          <div className="text-lg font-semibold text-slate-800">{pct(selected?.cv_f1_macro_mean)}</div>
        </div>
        <div className="rounded-lg border border-rose-200 bg-rose-50/80 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-rose-700">CV 误报率 FPR</div>
          <div className="text-lg font-semibold text-rose-800">{pct(selected?.cv_fpr)}</div>
          <div className="text-[10px] text-rose-600">良性判为攻击</div>
        </div>
        <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-amber-800">CV 漏报率 FNR</div>
          <div className="text-lg font-semibold text-amber-900">{pct(selected?.cv_fnr)}</div>
          <div className="text-[10px] text-amber-700">攻击判为良性</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="rounded-lg border border-slate-200 p-2">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-600">特征重要性 Top16</h3>
          <ReactECharts option={importanceOption} style={{ height: 360 }} />
        </article>
        <article className="rounded-lg border border-slate-200 p-2">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-600">决策规则树</h3>
          <pre className="max-h-[520px] overflow-auto rounded bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-emerald-100">
            {selected?.tree_rules?.trim() || '（无规则文本）'}
          </pre>
        </article>
      </div>
    </div>
  )
}