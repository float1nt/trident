export const RISK_BASE = '/risk'

export const riskPaths = {
  runsCompare: `${RISK_BASE}/runs-compare`,
  runDetail: `${RISK_BASE}/run-detail`,
  learnerDetail: `${RISK_BASE}/learner-detail`,
  run: (runId: string) => `${RISK_BASE}/run/${encodeURIComponent(runId)}`,
  learnerDetailRun: (runId: string, learner?: string) => {
    const base = `${RISK_BASE}/learner-detail/${encodeURIComponent(runId)}`
    return learner ? `${base}?learner=${encodeURIComponent(learner)}` : base
  },
} as const
