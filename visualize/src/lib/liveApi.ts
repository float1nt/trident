import type {
  LearnerMetricAuditView,
  LearnerTopologyMetricAuditJson,
} from '../types/learnerTopology'

export type LiveStreamConfig = {
  enabled: boolean
  runsRoot: string
  pollIntervalMs: number
}

export type LiveStreamEnvelope = {
  msg_id?: string
  event_id?: string
  run_id?: string
  ts?: string
  payload?: unknown
}

export type WindowClosedPayload = {
  window_end_time?: string
  window_left?: number
  window_right?: number
  learner_count?: number
  unknown_buffer_size?: number
}

export type LearnerLabelDistributionRow = {
  learner_name: string
  attack_ratio?: number | string
  dominant_label?: string
  dominant_ratio?: number | string
  total_assigned_samples?: number | string
}

export type LiveTridentState = {
  connected: boolean
  connecting: boolean
  error: string | null
  runId: string | null
  runStartedAt: string | null
  runFinished: boolean
  windows: WindowClosedPayload[]
  metricAudit: LearnerTopologyMetricAuditJson | null
  labelDistributionRows: LearnerLabelDistributionRow[]
  eventCount: number
  lastEventType: string | null
  lastEventAt: string | null
}

export const initialLiveTridentState: LiveTridentState = {
  connected: false,
  connecting: false,
  error: null,
  runId: null,
  runStartedAt: null,
  runFinished: false,
  windows: [],
  metricAudit: null,
  labelDistributionRows: [],
  eventCount: 0,
  lastEventType: null,
  lastEventAt: null,
}

export async function fetchLiveStreamConfig(): Promise<LiveStreamConfig> {
  const resp = await fetch('/api/live/config')
  if (!resp.ok) {
    throw new Error(`加载 live config 失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

export function createLiveEventSource(lastId = '0-0'): EventSource {
  const url = `/api/live/events?last_id=${encodeURIComponent(lastId)}`
  return new EventSource(url)
}

export function isMetricAuditPayload(payload: unknown): payload is LearnerTopologyMetricAuditJson {
  if (!payload || typeof payload !== 'object') return false
  return Array.isArray((payload as LearnerTopologyMetricAuditJson).learners)
}

export function pickAuditView(
  audit: LearnerTopologyMetricAuditJson | null,
  learnerName: string,
): LearnerMetricAuditView | null {
  if (!audit?.learners?.length || !learnerName) return null
  return audit.learners.find((l) => l.learner_name === learnerName) ?? null
}

export function labelRowsToOptions(rows: LearnerLabelDistributionRow[]) {
  return rows
    .filter((r) => r.learner_name)
    .map((r) => ({
      name: r.learner_name,
      attackRatio: Number(r.attack_ratio) || 0,
      dominantLabel: r.dominant_label || '—',
      flowCount: Number(r.total_assigned_samples) || undefined,
    }))
}
