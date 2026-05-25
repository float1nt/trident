export const overviewPaths = {
  runDetail: '/',
  run: (runId: string) => `/run/${encodeURIComponent(runId)}`,
  learnerDetail: '/learner-detail',
  learnerDetailRun: (runId: string, learner?: string) => {
    const base = `/learner-detail/${encodeURIComponent(runId)}`
    return learner ? `${base}?learner=${encodeURIComponent(learner)}` : base
  },
} as const
