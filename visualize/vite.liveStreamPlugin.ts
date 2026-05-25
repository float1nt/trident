import fs from 'node:fs'
import path from 'node:path'
import type { ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

export type LiveArtifactConfig = {
  enabled: boolean
  runsRoot: string
  pollIntervalMs: number
}

const LIVE_STATUS_FILE = 'live_run_status.json'
const WATCHED_FILES = [
  LIVE_STATUS_FILE,
  'learner_count_over_time.csv',
  'learner_topology_metric_audit.json',
  'learner_label_distribution.csv',
] as const

function readLiveConfig(repoRoot: string): LiveArtifactConfig {
  const runsRoot = path.resolve(repoRoot, 'outputs', 'runs')
  const envEnabled = process.env.TRIDENT_LIVE_ARTIFACTS_ENABLED?.trim().toLowerCase()
  let enabled = envEnabled === '1' || envEnabled === 'true'

  const configPath = path.resolve(repoRoot, 'configs', 'config.yaml')
  if (fs.existsSync(configPath)) {
    const text = fs.readFileSync(configPath, 'utf-8')
    const vizBlock = text.match(/visualization:\s*\n(?:[ \t].*\n)*?(?=^[a-zA-Z_#]|\Z)/m)?.[0] ?? ''
    const enabledMatch = vizBlock.match(/^\s+live_flush_enabled:\s*(.+)$/m)
    if (enabledMatch?.[1]) {
      const raw = enabledMatch[1].trim().toLowerCase()
      if (raw === 'auto') {
        const inputSource = text.match(/^\s*source:\s*(\S+)/m)?.[1]?.trim().toLowerCase()
        enabled =
          inputSource === 'redis' || inputSource === 'redis_list' || inputSource === 'redis_stream'
      } else {
        enabled = raw === 'true' || raw === '1'
      }
    }
  }

  if (envEnabled === '0' || envEnabled === 'false') {
    enabled = false
  }

  return {
    enabled,
    runsRoot,
    pollIntervalMs: 1000,
  }
}

function writeSse(res: ServerResponse, event: string, data: unknown, id?: string) {
  if (id) res.write(`id: ${id}\n`)
  res.write(`event: ${event}\n`)
  res.write(`data: ${JSON.stringify(data)}\n\n`)
}

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/)
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map((h) => h.trim())
  return lines.slice(1).map((line) => {
    const cols = line.split(',')
    const row: Record<string, string> = {}
    headers.forEach((header, idx) => {
      row[header] = (cols[idx] ?? '').trim()
    })
    return row
  })
}

function findActiveRunId(runsRoot: string, preferredRunId?: string): string | null {
  if (preferredRunId) {
    const statusPath = path.resolve(runsRoot, preferredRunId, LIVE_STATUS_FILE)
    if (statusPath.startsWith(runsRoot) && fs.existsSync(statusPath)) {
      return preferredRunId
    }
  }

  if (!fs.existsSync(runsRoot)) return null
  let best: { runId: string; updatedAt: number } | null = null
  for (const entry of fs.readdirSync(runsRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const statusPath = path.resolve(runsRoot, entry.name, LIVE_STATUS_FILE)
    if (!statusPath.startsWith(runsRoot) || !fs.existsSync(statusPath)) continue
    try {
      const payload = JSON.parse(fs.readFileSync(statusPath, 'utf-8')) as {
        status?: string
        updated_at?: string
      }
      if (payload.status !== 'running') continue
      const updatedAt = payload.updated_at ? Date.parse(payload.updated_at) : fs.statSync(statusPath).mtimeMs
      if (!best || updatedAt > best.updatedAt) {
        best = { runId: entry.name, updatedAt }
      }
    } catch {
      /* skip invalid */
    }
  }
  return best?.runId ?? null
}

function readJsonFile<T>(filePath: string): T | null {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as T
  } catch {
    return null
  }
}

function emitFileEvent(
  res: ServerResponse,
  runId: string,
  fileName: string,
  filePath: string,
  eventId: string,
) {
  if (fileName === LIVE_STATUS_FILE) {
    const status = readJsonFile<{
      run_id?: string
      status?: string
      windows_count?: number
      learner_count?: number
      updated_at?: string
    }>(filePath)
    if (!status) return
    const envelope = {
      run_id: runId,
      ts: status.updated_at,
      payload: status,
    }
    if (status.status === 'finished') {
      writeSse(res, 'run_finished', envelope, eventId)
    } else {
      writeSse(res, 'run_started', envelope, eventId)
    }
    return
  }

  if (fileName === 'learner_count_over_time.csv') {
    const rows = parseCsv(fs.readFileSync(filePath, 'utf-8'))
    if (!rows.length) return
    const last = rows[rows.length - 1]
    writeSse(
      res,
      'window_closed',
      {
        run_id: runId,
        ts: new Date().toISOString(),
        payload: {
          window_end_time: last.window_end_time,
          window_left: Number(last.window_left),
          window_right: Number(last.window_right),
          learner_count: Number(last.learner_count),
          unknown_buffer_size: Number(last.unknown_buffer_size),
        },
      },
      eventId,
    )
    return
  }

  if (fileName === 'learner_topology_metric_audit.json') {
    const audit = readJsonFile<Record<string, unknown>>(filePath)
    if (!audit) return
    writeSse(
      res,
      'learner_metric_audit',
      {
        run_id: runId,
        ts: new Date().toISOString(),
        payload: audit,
      },
      eventId,
    )
    return
  }

  if (fileName === 'learner_label_distribution.csv') {
    const rows = parseCsv(fs.readFileSync(filePath, 'utf-8'))
    writeSse(
      res,
      'learner_label_distribution',
      {
        run_id: runId,
        ts: new Date().toISOString(),
        payload: { rows, learner_count: rows.length },
      },
      eventId,
    )
  }
}

export function liveStreamApiPlugin(): Plugin {
  return {
    name: 'live-artifact-api',
    configureServer(server) {
      const repoRoot = path.resolve(server.config.root, '..')
      const liveConfig = readLiveConfig(repoRoot)

      const sendJson = (res: ServerResponse, code: number, data: unknown) => {
        res.statusCode = code
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        res.end(JSON.stringify(data))
      }

      server.middlewares.use('/api/live/config', (_req, res) => {
        sendJson(res, 200, liveConfig)
      })

      server.middlewares.use('/api/live/events', (req, res) => {
        if (!liveConfig.enabled) {
          sendJson(res, 503, {
            error:
              'Live artifact watch disabled. Set visualization.live_flush_enabled=true or TRIDENT_LIVE_ARTIFACTS_ENABLED=1.',
          })
          return
        }

        const url = req.url || ''
        const qIndex = url.indexOf('?')
        const params = qIndex >= 0 ? new URLSearchParams(url.slice(qIndex + 1)) : new URLSearchParams()
        const preferredRunId = params.get('run_id')?.trim() || undefined

        res.writeHead(200, {
          'Content-Type': 'text/event-stream; charset=utf-8',
          'Cache-Control': 'no-cache, no-transform',
          Connection: 'keep-alive',
          'X-Accel-Buffering': 'no',
        })
        res.write(': connected\n\n')

        let closed = false
        req.on('close', () => {
          closed = true
        })

        const mtimes = new Map<string, number>()
        let activeRunId = findActiveRunId(liveConfig.runsRoot, preferredRunId)

        writeSse(res, 'connected', {
          runsRoot: liveConfig.runsRoot,
          run_id: activeRunId,
          source: 'disk',
        })

        const poll = () => {
          if (closed) return
          activeRunId = findActiveRunId(liveConfig.runsRoot, preferredRunId) ?? activeRunId
          if (!activeRunId) {
            res.write(': waiting-for-run\n\n')
            return
          }

          const runDir = path.resolve(liveConfig.runsRoot, activeRunId)
          if (!runDir.startsWith(liveConfig.runsRoot)) return

          for (const fileName of WATCHED_FILES) {
            const filePath = path.resolve(runDir, fileName)
            if (!filePath.startsWith(runDir) || !fs.existsSync(filePath)) continue
            const mtime = fs.statSync(filePath).mtimeMs
            const key = `${activeRunId}:${fileName}`
            const prev = mtimes.get(key)
            if (prev !== undefined && mtime <= prev) continue
            mtimes.set(key, mtime)
            emitFileEvent(res, activeRunId, fileName, filePath, `${key}:${mtime}`)
          }
        }

        poll()
        const timer = setInterval(poll, liveConfig.pollIntervalMs)
        req.on('close', () => clearInterval(timer))
      })
    },
  }
}

export function getLiveArtifactConfig(repoRoot: string): LiveArtifactConfig {
  return readLiveConfig(repoRoot)
}
