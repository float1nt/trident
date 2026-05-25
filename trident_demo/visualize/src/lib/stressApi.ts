export type StressRun = {
  id: string
  timestamp: string
  status: string
  finished_at?: string | null
  stream?: string | null
  xlen_last?: number | null
  wall_clock_total?: number | null
  trident_total?: number | null
  flow_count?: number | null
  e2e_fps?: number | null
  inference_fps?: number | null
  run_dir?: string | null
  trident_run_dir?: string | null
}

export type StressRunListResponse = {
  runs: StressRun[]
  latestRunId: string | null
}

export type JsonRecord = Record<string, unknown>

export type StressRunDetail = {
  run: StressRun
  summary: JsonRecord
  redis: JsonRecord | null
  docker: JsonRecord | null
  suricata: JsonRecord | null
  trident_benchmark: JsonRecord | null
}

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
  return (await resp.json()) as T
}

export function fetchStressRuns(): Promise<StressRunListResponse> {
  return fetchJson<StressRunListResponse>('/api/stress-runs')
}

export function fetchStressRunDetail(runId: string): Promise<StressRunDetail> {
  return fetchJson<StressRunDetail>(`/api/stress-runs/${encodeURIComponent(runId)}`)
}
