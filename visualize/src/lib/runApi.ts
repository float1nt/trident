import Papa from 'papaparse'

export type RunInfo = {
  id: string
  timestamp: string
}

export type RunsResponse = {
  runs: RunInfo[]
  latestRunId: string | null
}

export async function fetchRuns(): Promise<RunsResponse> {
  const resp = await fetch('/api/runs')
  if (!resp.ok) {
    throw new Error(`获取 runs 列表失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

export function parseCsv<T>(url: string): Promise<T[]> {
  return new Promise((resolve, reject) => {
    Papa.parse<T>(url, {
      download: true,
      header: true,
      skipEmptyLines: true,
      complete: (result) => resolve(result.data),
      error: (err) => reject(err),
    })
  })
}

export async function fetchRunJson<T>(runId: string, fileName: string): Promise<T> {
  const run = encodeURIComponent(runId)
  const file = encodeURIComponent(fileName)
  const resp = await fetch(`/api/run-data/${run}/${file}`)
  if (!resp.ok) {
    throw new Error(`加载 ${fileName} 失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function fetchRunJsonOptional<T>(runId: string, fileName: string): Promise<T | null> {
  const run = encodeURIComponent(runId)
  const file = encodeURIComponent(fileName)
  const resp = await fetch(`/api/run-data/${run}/${file}`)
  if (resp.status === 404) {
    return null
  }
  if (!resp.ok) {
    throw new Error(`加载 ${fileName} 失败: HTTP ${resp.status}`)
  }
  return resp.json()
}
