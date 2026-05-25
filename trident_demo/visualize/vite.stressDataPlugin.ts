import fs from 'node:fs'
import path from 'node:path'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

type JsonObject = Record<string, unknown>

function readJson(filePath: string): JsonObject | null {
  if (!fs.existsSync(filePath)) return null
  const raw = fs.readFileSync(filePath, 'utf-8')
  const data = JSON.parse(raw) as unknown
  return data && typeof data === 'object' && !Array.isArray(data) ? (data as JsonObject) : null
}

function timestampFromRunId(runId: string): string {
  const match = runId.match(/^(\d{8})_(\d{6})/)
  if (!match) return runId
  const [, ymd, hms] = match
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)} ${hms.slice(0, 2)}:${hms.slice(2, 4)}:${hms.slice(4, 6)}`
}

function getRecord(value: unknown): JsonObject {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : {}
}

function getSamples(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter((item): item is JsonObject => !!item && typeof item === 'object' && !Array.isArray(item)) : []
}

function runRow(runDir: string): JsonObject {
  const runId = path.basename(runDir)
  const summary = readJson(path.join(runDir, 'stress_summary.json')) || {}
  const trident = getRecord(summary.trident_benchmark)
  const throughput = getRecord(trident.throughput_flows_per_second)
  const redis = getRecord(summary.redis)
  const redisSamples = getSamples(redis.samples)
  const redisLast = redisSamples.at(-1) || {}
  const stages = getRecord(summary.stages_seconds)
  return {
    id: runId,
    timestamp: timestampFromRunId(runId),
    status: summary.status || 'unknown',
    finished_at: summary.finished_at || null,
    stream: redis.stream || null,
    xlen_last: redisLast.xlen ?? null,
    wall_clock_total: stages.wall_clock_total ?? null,
    trident_total: stages.trident_total ?? null,
    flow_count: trident.flow_count ?? null,
    e2e_fps: throughput.flows_per_second_end_to_end ?? null,
    inference_fps: throughput.flows_per_second_inference ?? null,
    run_dir: runDir,
    trident_run_dir: summary.trident_run_dir || null,
  }
}

function sendJson(res: ServerResponse, code: number, data: unknown): void {
  res.statusCode = code
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(data))
}

function safeRunDir(stressRoot: string, runId: string): string | null {
  if (!runId || runId.includes('..') || runId.includes('/') || runId.includes('\\')) return null
  const target = path.resolve(stressRoot, runId)
  if (!target.startsWith(stressRoot) || !fs.existsSync(target) || !fs.statSync(target).isDirectory()) return null
  return target
}

export function stressDataApiPlugin(): Plugin {
  return {
    name: 'demo-stress-data-api',
    configureServer(server) {
      const demoRoot = path.resolve(server.config.root, '..')
      const stressRoot = path.resolve(demoRoot, 'stress_outputs')

      server.middlewares.use('/api/stress-runs', (req: IncomingMessage, res: ServerResponse) => {
        const url = req.url || '/'
        const parts = url.split('?')[0].split('/').filter(Boolean)
        if (parts.length === 0) {
          if (!fs.existsSync(stressRoot)) {
            sendJson(res, 200, { runs: [], latestRunId: null })
            return
          }
          const runs = fs
            .readdirSync(stressRoot, { withFileTypes: true })
            .filter((entry) => entry.isDirectory() && fs.existsSync(path.join(stressRoot, entry.name, 'stress_summary.json')))
            .map((entry) => runRow(path.join(stressRoot, entry.name)))
            .sort((a, b) => String(b.id).localeCompare(String(a.id)))
          sendJson(res, 200, { runs, latestRunId: runs.length > 0 ? runs[0].id : null })
          return
        }

        const runId = decodeURIComponent(parts[0] || '')
        const runDir = safeRunDir(stressRoot, runId)
        if (!runDir) {
          sendJson(res, 404, { error: `Run not found: ${runId}` })
          return
        }

        const summary = readJson(path.join(runDir, 'stress_summary.json')) || {}
        const tridentRunDir = typeof summary.trident_run_dir === 'string' ? summary.trident_run_dir : null
        const inlineBenchmark = getRecord(summary.trident_benchmark)
        const benchmarkFromFile = tridentRunDir ? readJson(path.join(tridentRunDir, 'trident_performance_benchmark.json')) : null
        sendJson(res, 200, {
          run: runRow(runDir),
          summary,
          redis: readJson(path.join(runDir, 'redis_metrics.json')),
          docker: readJson(path.join(runDir, 'docker_metrics.json')),
          suricata: readJson(path.join(runDir, 'suricata_metrics.json')),
          trident_benchmark: Object.keys(inlineBenchmark).length > 0 ? inlineBenchmark : benchmarkFromFile,
        })
      })
    },
  }
}
