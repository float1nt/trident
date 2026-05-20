import { useEffect, useMemo, useState } from 'react'
import { Select, Slider } from 'antd'
import { TopologyChartPane, type TopologyGraph } from './NetworkTopologyPanel'

export type LearnerTopologyView = {
  learner: string
  attack_ratio: number
  dominant_label?: string
  dominant_ratio?: number
  is_benign: boolean | null
  host: TopologyGraph
  endpoint: TopologyGraph
}

export type LearnerNetworkTopologyJson = {
  version: number
  learners: string[]
  default_learner: string
  views: Record<string, LearnerTopologyView>
}

export type LearnerTopologyOption = {
  name: string
  attackRatio: number
  dominantLabel: string
}

type Props = {
  data: LearnerNetworkTopologyJson | null
  learnerOptions?: LearnerTopologyOption[]
  selectedLearner?: string | null
  onLearnerChange?: (learner: string) => void
}

function formatLearnerOptionLabel(
  name: string,
  attackRatio: number,
  dominantLabel: string,
): string {
  const dom = dominantLabel && dominantLabel !== '-' ? dominantLabel : '—'
  return `${name}（攻击占比 ${(attackRatio * 100).toFixed(2)}% · 主导 ${dom}）`
}

function buildSortedLearnerOptions(
  data: LearnerNetworkTopologyJson,
  learnerOptions?: LearnerTopologyOption[],
): LearnerTopologyOption[] {
  const metaFromTable = new Map((learnerOptions ?? []).map((o) => [o.name, o]))
  const names = data.learners?.length
    ? data.learners.filter((k) => data.views[k])
    : Object.keys(data.views)

  const items: LearnerTopologyOption[] = names.map((name) => {
    const fromTable = metaFromTable.get(name)
    const fromView = data.views[name]
    return {
      name,
      attackRatio: fromView?.attack_ratio ?? fromTable?.attackRatio ?? 0,
      dominantLabel:
        fromView?.dominant_label ?? fromTable?.dominantLabel ?? '—',
    }
  })

  return items.sort((a, b) => b.attackRatio - a.attackRatio || a.name.localeCompare(b.name))
}

export function LearnerInternalTopologyPanel({
  data,
  learnerOptions,
  selectedLearner,
  onLearnerChange,
}: Props) {
  const [pickedLearner, setPickedLearner] = useState<string>('')
  const [repulsion, setRepulsion] = useState(180)
  const [minEdgeFlows, setMinEdgeFlows] = useState(1)

  const sortedOptions = useMemo(() => {
    if (!data) return [] as LearnerTopologyOption[]
    return buildSortedLearnerOptions(data, learnerOptions)
  }, [data, learnerOptions])

  const effectiveLearner = useMemo(() => {
    if (!data || !sortedOptions.length) return ''
    const external = selectedLearner?.trim()
    if (external && data.views[external]) return external
    if (pickedLearner && data.views[pickedLearner]) return pickedLearner
    return sortedOptions[0]?.name ?? data.default_learner ?? ''
  }, [data, selectedLearner, pickedLearner, sortedOptions])

  useEffect(() => {
    if (selectedLearner && data?.views[selectedLearner]) {
      setPickedLearner(selectedLearner)
    }
  }, [selectedLearner, data])

  const view = data?.views[effectiveLearner]
  const hostGraph = view?.host
  const endpointGraph = view?.endpoint

  if (!data) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
        本 run 尚无 <span className="font-mono">learner_network_topology.json</span>。重新跑实验，或执行：
        <pre className="mt-2 overflow-x-auto rounded bg-white p-2 text-xs text-slate-700">
          python3 scripts/export_learner_network_topology.py outputs/runs/&lt;run_id&gt;
        </pre>
      </div>
    )
  }

  const flowCount = hostGraph?.flow_count ?? endpointGraph?.flow_count
  const attackPct =
    view?.attack_ratio != null ? `${(view.attack_ratio * 100).toFixed(2)}%` : '—'
  const dominantLabel =
    view?.dominant_label ||
    sortedOptions.find((o) => o.name === effectiveLearner)?.dominantLabel ||
    '—'
  const dominantRatio =
    view?.dominant_ratio != null
      ? `${(view.dominant_ratio * 100).toFixed(2)}%`
      : '—'

  const handleLearnerChange = (v: string) => {
    setPickedLearner(v)
    onLearnerChange?.(v)
  }

  const selectOptions = sortedOptions.map((o) => ({
    value: o.name,
    label: formatLearnerOptionLabel(o.name, o.attackRatio, o.dominantLabel),
  }))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[180px] flex-1">
          <label className="field-label">斥力 {repulsion}</label>
          <Slider min={40} max={500} value={repulsion} onChange={setRepulsion} />
        </div>
        <div className="min-w-[180px] flex-1">
          <label className="field-label">最小边流量 {minEdgeFlows}</label>
          <Slider min={1} max={500} step={1} value={minEdgeFlows} onChange={setMinEdgeFlows} />
        </div>
        <div className="w-full min-w-[min(100%,420px)] flex-[3] sm:ml-auto sm:max-w-[720px]">
          <label className="field-label">学习器（按攻击占比降序）</label>
          <Select
            className="w-full"
            showSearch
            optionFilterProp="label"
            popupMatchSelectWidth={false}
            dropdownStyle={{ minWidth: 640 }}
            value={effectiveLearner || undefined}
            onChange={(v) => handleLearnerChange(String(v))}
            options={selectOptions}
          />
        </div>
      </div>

      <p className="text-xs text-slate-500">
        左：IP；右：IP:端口。边按流真实标签着色（绿=良性、红=攻击）；蓝框=内网。当前：攻击占比={attackPct}
        ，主导标签={dominantLabel}
        {dominantRatio !== '—' ? <>（占比 {dominantRatio}）</> : null}
        {flowCount != null ? <> · {flowCount.toLocaleString()} 条流</> : null}
      </p>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <TopologyChartPane
          title="IP（主机）"
          graph={hostGraph}
          viewIsBenign={null}
          repulsion={repulsion}
          minEdgeFlows={minEdgeFlows}
        />
        <TopologyChartPane
          title="IP:端口（服务）"
          graph={endpointGraph}
          viewIsBenign={null}
          repulsion={repulsion}
          minEdgeFlows={minEdgeFlows}
        />
      </div>
    </div>
  )
}