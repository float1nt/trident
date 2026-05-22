import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import type { IncomingMessage, ServerResponse } from 'node:http'

function runDataApiPlugin(): Plugin {
  return {
    name: 'run-data-api',
    configureServer(server) {
      const repoRoot = path.resolve(server.config.root, '..')
      const runsRoot = path.resolve(repoRoot, 'outputs', 'runs')

      const sendJson = (res: ServerResponse, code: number, data: unknown) => {
        res.statusCode = code
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        res.end(JSON.stringify(data))
      }

      const isCompleteRun = (runId: string) => {
        const summary = path.resolve(runsRoot, runId, 'run_summary.txt')
        const overlap = path.resolve(runsRoot, runId, 'debug_true_overlap_pairs.csv')
        return summary.startsWith(runsRoot) && overlap.startsWith(runsRoot) && fs.existsSync(summary) && fs.existsSync(overlap)
      }

      const getRunDirs = () => {
        if (!fs.existsSync(runsRoot)) return []
        return fs
          .readdirSync(runsRoot, { withFileTypes: true })
          .filter((d) => d.isDirectory() && isCompleteRun(d.name))
          .map((d) => d.name)
      }

      const sortByTimestampDesc = (runs: string[]) => {
        return [...runs].sort((a, b) => {
          const ta = a.slice(0, 15)
          const tb = b.slice(0, 15)
          if (ta === tb) return b.localeCompare(a)
          return tb.localeCompare(ta)
        })
      }

      server.middlewares.use('/api/runs', (_req: IncomingMessage, res: ServerResponse) => {
        const runs = sortByTimestampDesc(getRunDirs()).map((name) => ({
          id: name,
          timestamp: name.slice(0, 15),
        }))
        sendJson(res, 200, {
          runs,
          latestRunId: runs.length > 0 ? runs[0].id : null,
        })
      })

      const parseRunDataPath = (url: string): { runId: string; fileName: string } | null => {
        const parts = url.split('?')[0].split('/').filter(Boolean)
        const idx = parts.indexOf('run-data')
        const slice = idx >= 0 ? parts.slice(idx + 1) : parts
        if (slice.length < 2) return null
        return {
          runId: decodeURIComponent(slice[0] || ''),
          fileName: decodeURIComponent(slice[1] || ''),
        }
      }

      server.middlewares.use('/api/run-data', (req: IncomingMessage, res: ServerResponse) => {
        const parsed = parseRunDataPath(req.url || '')
        if (!parsed) {
          sendJson(res, 400, { error: 'Invalid run-data path.' })
          return
        }
        const { runId, fileName } = parsed
        const allowed = new Set([
          'debug_true_overlap_pairs.csv',
          'learner_aggregated_distribution.csv',
          'learner_label_distribution.csv',
          'learner_count_over_time.csv',
          'learner_train_batch_label_distribution.csv',
          'learner_creation_distribution.csv',
          'dataset_label_distribution.csv',
          'dataset_label_distribution_summary.json',
          'dataset_label_feature_attack_correlation.json',
          'metrics.json',
          'performance_metrics.json',
          'learner_aggregation_summary.json',
          'learner_feature_attack_ratio_correlation.json',
          'learner_creation_flow_previews.json',
          'decision_tree_summary.json',
          'decision_tree_visualization.json',
          'dataset_network_topology.json',
          'learner_network_topology.json',
          'learner_topology_metric_audit.json',
        ])
        if (!allowed.has(fileName)) {
          sendJson(res, 400, { error: `Unsupported file: ${fileName}` })
          return
        }
        if (!runId || runId.includes('..') || runId.includes('/')) {
          sendJson(res, 400, { error: 'Invalid run id.' })
          return
        }
        const target = path.resolve(runsRoot, runId, fileName)
        if (!target.startsWith(runsRoot)) {
          sendJson(res, 400, { error: 'Invalid target path.' })
          return
        }
        if (!fs.existsSync(target)) {
          sendJson(res, 404, { error: `File not found: ${runId}/${fileName}` })
          return
        }
        res.statusCode = 200
        const isJson = fileName.endsWith('.json')
        res.setHeader('Content-Type', isJson ? 'application/json; charset=utf-8' : 'text/csv; charset=utf-8')
        fs.createReadStream(target).pipe(res)
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), runDataApiPlugin()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    fs: {
      // Allow reading run outputs from project root.
      allow: ['..'],
    },
  },
})
