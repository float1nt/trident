import Papa from 'papaparse'

export type RunInfo = {
  id: string
  timestamp: string
}

export type RunsResponse = {
  runs: RunInfo[]
  latestRunId: string | null
}

/** Trident run 数据 API 前缀，与后端 /api 代理隔离 */
export const TRIDENT_API_PREFIX = '/trident-api'

export function runDataUrl(runId: string, fileName: string): string {
  return `${TRIDENT_API_PREFIX}/run-data/${encodeURIComponent(runId)}/${encodeURIComponent(fileName)}`
}

async function readHttpErrorDetail(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { error?: string }
    if (body?.error) return body.error
  } catch {
    /* not json */
  }
  try {
    const text = (await resp.text()).trim()
    if (text) return text.slice(0, 200)
  } catch {
    /* ignore */
  }
  return resp.statusText || 'Unknown error'
}

export async function fetchRuns(): Promise<RunsResponse> {
  const resp = await fetch(`${TRIDENT_API_PREFIX}/runs`)
  if (!resp.ok) {
    const detail = await readHttpErrorDetail(resp)
    throw new Error(`获取 runs 列表失败: HTTP ${resp.status} (${detail})`)
  }
  return resp.json()
}

export async function parseCsv<T>(url: string): Promise<T[]> {
  const resp = await fetch(url)
  if (!resp.ok) {
    const detail = await readHttpErrorDetail(resp)
    throw new Error(`加载 CSV 失败: HTTP ${resp.status} — ${detail}`)
  }
  const text = await resp.text()
  const parsed = Papa.parse<T>(text, {
    header: true,
    skipEmptyLines: true,
  })
  if (parsed.errors?.length) {
    const first = parsed.errors[0]
    throw new Error(`CSV 解析失败: ${first.message ?? 'unknown'}`)
  }
  return parsed.data
}

export async function fetchRunJson<T>(runId: string, fileName: string): Promise<T> {
  const resp = await fetch(runDataUrl(runId, fileName))
  if (!resp.ok) {
    const detail = await readHttpErrorDetail(resp)
    throw new Error(`加载 ${fileName} 失败: HTTP ${resp.status} (${detail})`)
  }
  return resp.json()
}

export async function fetchRunJsonOptional<T>(runId: string, fileName: string): Promise<T | null> {
  const resp = await fetch(runDataUrl(runId, fileName))
  if (resp.status === 404) {
    return null
  }
  if (!resp.ok) {
    const detail = await readHttpErrorDetail(resp)
    throw new Error(`加载 ${fileName} 失败: HTTP ${resp.status} (${detail})`)
  }
  return resp.json()
}
