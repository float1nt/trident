import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Select, Slider } from 'antd'
import * as echarts from 'echarts'
import ReactECharts from 'echarts-for-react'
import { fetchRunJsonOptional, fetchRuns, parseCsv, type RunInfo } from '../lib/runApi'

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
}

type CountRow = {
  window_end_time: string
  window_left: string
  window_right: string
  learner_count: string
  unknown_buffer_size: string
}

type DatasetLabelRow = {
  label: string
  count: string
  ratio: string
  is_benign: string | boolean
  year_tag: string
  base_label: string
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
  const [datasetLabelSummary, setDatasetLabelSummary] = useState<DatasetLabelSummaryJson | null>(null)
  const [metrics, setMetrics] = useState<MetricsJson | null>(null)
  const [perf, setPerf] = useState<PerfJson | null>(null)
  const [aggSummary, setAggSummary] = useState<AggSummaryJson | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>('')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<LinkData | null>(null)
  const [learnerQuery, setLearnerQuery] = useState('')
  const [learnerSortBy, setLearnerSortBy] = useState<'attackRatio' | 'samples' | 'creationSamples' | 'dominantRatio' | 'name'>('attackRatio')
  const [learnerSortDir, setLearnerSortDir] = useState<'asc' | 'desc'>('desc')

  useEffect(() => {
    const loadRuns = async () => {
      try {
        const result = await fetchRuns()
        setRuns(result.runs || [])
        if (routeRunId) {
          setSelectedRunId(routeRunId)
        } else if (result.latestRunId) {
          setSelectedRunId(result.latestRunId)
        } else if (result.runs.length > 0) {
          setSelectedRunId(result.runs[0].id)
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
        const run = encodeURIComponent(selectedRunId)
        const [pairs, aggs, learners, counts, labelDistRows, labelDistSummary, metricJson, perfJson, aggSummaryJson] = await Promise.all([
          parseCsv<PairRow>(`/api/run-data/${run}/debug_true_overlap_pairs.csv`),
          parseCsv<AggRow>(`/api/run-data/${run}/learner_aggregated_distribution.csv`),
          parseCsv<LearnerDistRow>(`/api/run-data/${run}/learner_label_distribution.csv`),
          parseCsv<CountRow>(`/api/run-data/${run}/learner_count_over_time.csv`).catch(() => []),
          parseCsv<DatasetLabelRow>(`/api/run-data/${run}/dataset_label_distribution.csv`).catch(() => []),
          fetchRunJsonOptional<DatasetLabelSummaryJson>(selectedRunId, 'dataset_label_distribution_summary.json'),
          fetchRunJsonOptional<MetricsJson>(selectedRunId, 'metrics.json'),
          fetchRunJsonOptional<PerfJson>(selectedRunId, 'performance_metrics.json'),
          fetchRunJsonOptional<AggSummaryJson>(selectedRunId, 'learner_aggregation_summary.json'),
        ])
        setPairRows(pairs)
        setAggRows(aggs)
        setLearnerRows(learners)
        setCountRows(counts)
        setDatasetLabelRows(labelDistRows)
        setDatasetLabelSummary(labelDistSummary)
        setMetrics(metricJson)
        setPerf(perfJson)
        setAggSummary(aggSummaryJson)
        setSelectedNodeId(null)
        setSelectedEdge(null)
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
    aggRows.forEach((row) => {
      const ratio = Number(row.attack_ratio)
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
        ratioMap.set(member, ratio)
        sampleMap.set(member, perLearnerSample)
      })
    })
    return { ratioMap, sampleMap }
  }, [aggRows])

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

      let color = '#94a3b8'
      let borderColor = '#64748b'
      let borderWidth = 1.2
      if (ratio !== null) {
        if (ratio >= 0.3 && ratio <= 0.7) {
          color = '#f8fafc'
          borderColor = '#ca8a04'
          borderWidth = 2.4
        } else if (ratio < 0.3) {
          color = '#16a34a'
          borderColor = '#166534'
          borderWidth = 1.2
        } else {
          color = '#e11d48'
          borderColor = '#9f1239'
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
        formatter: (params: { dataType?: string; data: NodeData | LinkData }) => {
          if (params.dataType === 'edge') {
            const edge = params.data as LinkData
            return [
              `<b>${edge.source} ↔ ${edge.target}</b>`,
              `jaccard=${edge.value.toFixed(4)}`,
              `intersection=${edge.intersectionCount}`,
              `union=${edge.unionCount}`,
              `A→B=${edge.acceptRateAToB.toFixed(4)}`,
              `B→A=${edge.acceptRateBToA.toFixed(4)}`,
            ].join('<br/>')
          }
          const node = params.data as NodeData
          const ratioText = node.ratio == null ? 'N/A' : node.ratio.toFixed(4)
          const detail = learnerDetailMap.get(node.id)
          return [
            `<b>${node.id}</b>`,
            `attack_ratio=${ratioText}`,
            `samples=${Math.round(node.samples)}`,
            `degree=${node.degree.toFixed(4)}`,
            `dominant=${detail?.dominantLabel ?? '-'}`,
            `dominant_ratio=${detail?.dominantRatio == null ? 'N/A' : detail.dominantRatio.toFixed(4)}`,
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
          lineStyle: { color: '#64748b', opacity: 0.95, width: 1.6 },
          force: { repulsion, gravity: 0.08, edgeLength: [40, 180], layoutAnimation: true },
          label: { show: true, position: 'right', color: '#334155', fontSize: 10 },
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
      xAxis: { type: 'category', data: x, axisLabel: { color: '#64748b' } },
      yAxis: { type: 'value', axisLabel: { color: '#64748b' } },
      series: [
        { name: 'Learner Count', type: 'line', data: learner, smooth: true, lineStyle: { color: '#2563eb' } },
      ],
    }
  }, [countRows])

  const unknownTrendOption = useMemo(() => {
    const x = countRows.map((_, idx) => idx + 1)
    const unknown = countRows.map((r) => Number(r.unknown_buffer_size || 0))
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: x, axisLabel: { color: '#64748b' } },
      yAxis: { type: 'value', axisLabel: { color: '#64748b' } },
      series: [
        { name: 'Unknown Buffer', type: 'line', data: unknown, smooth: true, lineStyle: { color: '#d97706' } },
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
      legend: { data: ['创建样本量', '增量匹配量'], textStyle: { color: '#475569' } },
      xAxis: { type: 'value', axisLabel: { color: '#64748b' } },
      yAxis: { type: 'category', data: top.map((x) => x.name), axisLabel: { color: '#64748b' } },
      series: [
        {
          name: '创建样本量',
          type: 'bar',
          stack: 'samples',
          data: top.map((x) => x.creation),
          itemStyle: { color: '#64748b' },
        },
        {
          name: '增量匹配量',
          type: 'bar',
          stack: 'samples',
          data: top.map((x) => x.incremental),
          itemStyle: { color: '#2563eb' },
        },
      ],
    }
  }, [learnerRows])

  const datasetLabelAll = useMemo(() => {
    return [...datasetLabelRows]
      .map((r) => ({
        label: String(r.label),
        count: Number(r.count || 0),
        ratio: Number(r.ratio || 0),
        isBenign: String(r.is_benign).toLowerCase() === 'true',
        yearTag: String(r.year_tag || ''),
        baseLabel: String(r.base_label || ''),
      }))
      .sort((a, b) => b.count - a.count)
  }, [datasetLabelRows])

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
          return `${name}<br/>数量: ${value.toLocaleString()}<br/>占比: ${ratio.toFixed(2)}%`
        },
      },
      legend: {
        bottom: 0,
        textStyle: { color: '#64748b' },
      },
      series: [
        {
          type: 'pie',
          radius: ['48%', '74%'],
          center: ['50%', '45%'],
          label: { color: '#334155', formatter: '{b}: {d}%' },
          data: [
            { name: '正常(BENIGN)', value: benign, itemStyle: { color: '#10b981' } },
            { name: '异常(ATTACK)', value: attack, itemStyle: { color: '#e11d48' } },
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
            `正常: ${row.benign.toLocaleString()} (${benignPct.toFixed(2)}%)`,
            `异常: ${row.attack.toLocaleString()} (${attackPct.toFixed(2)}%)`,
            `总量: ${row.total.toLocaleString()}`,
          ].join('<br/>')
        },
      },
      legend: {
        top: 0,
        textStyle: { color: '#64748b' },
      },
      grid: { left: 48, right: 24, top: 36, bottom: 32 },
      xAxis: {
        type: 'category',
        data: yearLabels,
        axisLabel: { color: '#64748b' },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { color: '#64748b', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#e2e8f0' } },
      },
      series: [
        {
          name: '正常占比',
          type: 'bar',
          stack: 'ratio',
          data: benignRatio,
          itemStyle: { color: '#10b981' },
        },
        {
          name: '异常占比',
          type: 'bar',
          stack: 'ratio',
          data: attackRatio,
          itemStyle: { color: '#e11d48' },
        },
      ],
    }
  }, [datasetBenignAttackStats])

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
    const list = learnerRows.map((row) => ({
      name: row.learner_name,
      attackRatio: Number(row.attack_ratio || 0),
      samples: Number(row.total_assigned_samples || 0),
      creationSamples: Number(row.creation_sample_count || 0),
      dominantLabel: row.dominant_label || '-',
      dominantRatio: Number(row.dominant_ratio || 0),
    }))
    const q = learnerQuery.trim().toLowerCase()
    const filtered = q
      ? list.filter((r) => r.name.toLowerCase().includes(q) || r.dominantLabel.toLowerCase().includes(q))
      : list
    const sorted = [...filtered].sort((a, b) => {
      if (learnerSortBy === 'name') {
        const cmp = a.name.localeCompare(b.name)
        return learnerSortDir === 'asc' ? cmp : -cmp
      }
      const va = a[learnerSortBy]
      const vb = b[learnerSortBy]
      return learnerSortDir === 'asc' ? va - vb : vb - va
    })
    return sorted
  }, [learnerRows, learnerQuery, learnerSortBy, learnerSortDir])

  const selectedDetail = selectedNodeId ? learnerDetailMap.get(selectedNodeId) : null

  return (
    <div className="space-y-5">
      <section className="panel">
        <p className="eyebrow">Threat Relationship Intelligence</p>
        <h1 className="text-2xl font-semibold tracking-wide text-slate-900">
          Run 详情
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          {detailMode ? `当前路由: /run/${routeRunId}` : ''}
        </p>
        {detailMode ? (
          <p className="mt-2 text-xs text-slate-600">
            <Link to="/runs-compare" className="hover:underline">返回 Run 对比</Link>
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
        {loading ? <p className="text-sm text-slate-600">正在载入图谱数据...</p> : null}
        {error ? <p className="text-sm text-rose-600">{error}</p> : null}
      </section>

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <article className="metric-card"><p className="metric-label">Risk FPR</p><p className="metric-value">{kpi.fpr == null ? '-' : `${(kpi.fpr * 100).toFixed(2)}%`}</p></article>
        <article className="metric-card"><p className="metric-label">Risk FNR</p><p className="metric-value">{kpi.fnr == null ? '-' : `${(kpi.fnr * 100).toFixed(2)}%`}</p></article>
        <article className="metric-card"><p className="metric-label">Risk TPR</p><p className="metric-value">{kpi.tpr == null ? '-' : `${(kpi.tpr * 100).toFixed(2)}%`}</p></article>
        <article className="metric-card"><p className="metric-label">Windows</p><p className="metric-value">{kpi.windows ?? '-'}</p></article>
        <article className="metric-card"><p className="metric-label">New Learners</p><p className="metric-value">{kpi.newLearners ?? '-'}</p></article>
        <article className="metric-card"><p className="metric-label">Aggregates</p><p className="metric-value">{kpi.aggregateCount ?? '-'}</p></article>
      </section>

      <section className="panel">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-slate-600">数据集标签分布（Run输入，全量）</h2>
        <div className="mb-3 text-xs text-slate-500">
          rows={datasetLabelSummary?.total_rows ?? '-'} | labels={datasetLabelSummary?.label_count ?? datasetLabelRows.length}
          {' '}| benign={datasetLabelSummary?.benign_rows ?? '-'} | attack={datasetLabelSummary?.attack_rows ?? '-'}
        </div>
        <div className="mb-4 grid gap-4 xl:grid-cols-2">
          <article className="rounded-lg border border-slate-200 bg-white p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">总体正常/异常占比</h3>
            <ReactECharts option={datasetOverallOption} style={{ height: 250 }} />
          </article>
          <article className="rounded-lg border border-slate-200 bg-white p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">每年正常/异常占比</h3>
            <ReactECharts option={datasetYearlyRatioOption} style={{ height: 250 }} />
          </article>
        </div>
        <div className="max-h-[520px] overflow-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="sticky top-0 bg-slate-50/95">
              <tr className="border-b border-slate-200 text-left text-slate-600">
                <th className="px-3 py-2">Label</th>
                <th className="px-3 py-2">Count</th>
                <th className="px-3 py-2">Ratio</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Year</th>
                <th className="px-3 py-2">Base Label</th>
              </tr>
            </thead>
            <tbody>
              {datasetLabelAll.map((row) => (
                <tr key={row.label} className="border-b border-slate-100 text-slate-800 hover:bg-slate-50">
                  <td className={`px-3 py-2 font-mono text-xs ${row.isBenign ? 'text-emerald-700' : 'text-rose-700'}`}>
                    {row.label}
                  </td>
                  <td className="px-3 py-2">{row.count.toLocaleString()}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div
                        className="h-2.5 w-36 overflow-hidden rounded-full bg-slate-200"
                        title={`${(row.ratio * 100).toFixed(3)}%`}
                      >
                        <div
                          className={`h-full rounded-full ${row.isBenign ? 'bg-emerald-500' : 'bg-rose-500'}`}
                          style={{ width: `${Math.max(0, Math.min(100, row.ratio * 100))}%` }}
                        />
                      </div>
                      <span className={`text-xs ${row.isBenign ? 'text-emerald-700' : 'text-rose-700'}`}>
                        {(row.ratio * 100).toFixed(3)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <span className={row.isBenign ? 'rounded-md bg-emerald-100 px-2 py-1 text-emerald-700' : 'rounded-md bg-rose-100 px-2 py-1 text-rose-700'}>
                      {row.isBenign ? 'BENIGN' : 'ATTACK'}
                    </span>
                  </td>
                  <td className="px-3 py-2">{row.yearTag}</td>
                  <td className="px-3 py-2">{row.baseLabel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-slate-600">Learner 趋势</h2>
          <ReactECharts option={learnerTrendOption} style={{ height: 300 }} />
        </article>
        <article className="panel">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-slate-600">Unknown Buffer 趋势</h2>
          <ReactECharts option={unknownTrendOption} style={{ height: 300 }} />
        </article>
      </section>

      <section className="panel">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-widest text-slate-600">Learner 创建样本量 Top15</h2>
        <ReactECharts option={creationOption} style={{ height: 340 }} />
      </section>

      <section className="panel">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-600">学习器效果总览（全部）</h2>
          <div className="flex flex-wrap gap-2">
            <input
              className="input-base w-72"
              placeholder="搜索 learner / 主导标签..."
              value={learnerQuery}
              onChange={(e) => setLearnerQuery(e.target.value)}
            />
            <select
              className="input-base"
              value={learnerSortBy}
              onChange={(e) => setLearnerSortBy(e.target.value as typeof learnerSortBy)}
            >
              <option value="samples">按样本量</option>
              <option value="attackRatio">按attack_ratio</option>
              <option value="creationSamples">按创建样本量</option>
              <option value="dominantRatio">按主导占比</option>
              <option value="name">按学习器名称</option>
            </select>
            <button
              type="button"
              className="btn-primary"
              onClick={() => setLearnerSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
            >
              排序方向: {learnerSortDir === 'desc' ? '降序' : '升序'}
            </button>
          </div>
        </div>

        <div className="mb-2 text-xs text-slate-500">
          共 {learnerRows.length} 个学习器，当前显示 {allLearnerRows.length} 个
        </div>

        <div className="max-h-[520px] overflow-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="sticky top-0 bg-slate-50/95">
              <tr className="border-b border-slate-200 text-left text-slate-600">
                <th className="px-3 py-2">Learner</th>
                <th className="px-3 py-2">Attack Ratio</th>
                <th className="px-3 py-2">总样本</th>
                <th className="px-3 py-2">创建样本</th>
                <th className="px-3 py-2">主导标签</th>
                <th className="px-3 py-2">主导占比</th>
              </tr>
            </thead>
            <tbody>
              {allLearnerRows.map((row) => (
                <tr key={row.name} className="border-b border-slate-100 text-slate-800 hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{row.name}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        row.attackRatio > 0.7
                          ? 'rounded-md bg-rose-100 px-2 py-1 text-rose-700'
                          : row.attackRatio < 0.3
                            ? 'rounded-md bg-emerald-100 px-2 py-1 text-emerald-700'
                            : 'rounded-md border border-yellow-400 bg-yellow-50 px-2 py-1 text-yellow-700'
                      }
                    >
                      {(row.attackRatio * 100).toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-3 py-2">{row.samples.toLocaleString()}</td>
                  <td className="px-3 py-2">{row.creationSamples.toLocaleString()}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        row.attackRatio > 0.7
                          ? 'text-rose-700'
                          : row.attackRatio < 0.3
                            ? 'text-emerald-700'
                            : 'text-yellow-700'
                      }
                    >
                      {row.dominantLabel}
                    </span>
                  </td>
                  <td className="px-3 py-2">{(row.dominantRatio * 100).toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-4">
        <article className="panel xl:col-span-3">
          <div ref={chartRef} className="h-[72vh] w-full" />
        </article>
        <aside className="space-y-4">
          <article className="panel">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-slate-600">图谱配置</h2>
            <div className="space-y-3">
              <div>
                <label className="field-label">阈值 {threshold.toFixed(2)}</label>
                <Slider
                  min={0}
                  max={1}
                  step={0.01}
                  value={threshold}
                  onChange={(value) => setThreshold(Array.isArray(value) ? value[0] : value)}
                  tooltip={{ formatter: (v) => `${Number(v || 0).toFixed(2)}` }}
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
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-slate-600">详情面板</h2>
            {selectedEdge ? (
              <div className="space-y-1 text-sm text-slate-700">
                <p className="font-semibold text-slate-900">边: {selectedEdge.source} ↔ {selectedEdge.target}</p>
                <p>Jaccard: {selectedEdge.value.toFixed(6)}</p>
                <p>交集: {selectedEdge.intersectionCount}</p>
                <p>并集: {selectedEdge.unionCount}</p>
                <p>A→B: {selectedEdge.acceptRateAToB.toFixed(6)}</p>
                <p>B→A: {selectedEdge.acceptRateBToA.toFixed(6)}</p>
              </div>
            ) : null}
            {!selectedEdge && selectedDetail ? (
              <div className="space-y-1 text-sm text-slate-700">
                <p className="font-semibold text-slate-900">节点: {selectedDetail.learnerName}</p>
                <p>attack_ratio: {selectedDetail.attackRatio == null ? 'N/A' : selectedDetail.attackRatio.toFixed(6)}</p>
                <p>总样本数: {selectedDetail.totalSamples}</p>
                <p>主导标签: {selectedDetail.dominantLabel}</p>
                <p>主导占比: {selectedDetail.dominantRatio == null ? 'N/A' : selectedDetail.dominantRatio.toFixed(6)}</p>
              </div>
            ) : null}
            {!selectedEdge && !selectedDetail ? <p className="text-sm text-slate-500">点击图谱节点或边查看详情。</p> : null}
          </article>
        </aside>
      </section>
    </div>
  )
}
