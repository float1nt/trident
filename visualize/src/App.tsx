import './App.css'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import GraphAnalysisPage from './pages/GraphAnalysisPage'
import LearnerDetailPage from './pages/LearnerDetailPage'
import LiveMonitorPage from './pages/LiveMonitorPage'
import RunsComparePage from './pages/RunsComparePage'

function App() {
  return (
    <div className="page min-h-screen bg-[var(--notion-bg)] text-[var(--notion-text-primary)]">
      <header className="border-b border-[var(--notion-border)] bg-[var(--notion-surface)]">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-notion-secondary">Trident Security Console</p>
            <h1 className="text-lg font-semibold tracking-wide text-notion-text">Threat Ops Dashboard</h1>
          </div>
          <nav className="flex gap-2 rounded-xl border border-notion-border bg-notion-surface-alt p-1">
            <NavLink
              to="/runs-compare"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              Run 对比
            </NavLink>
            <NavLink
              to="/run-detail"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              Run 详情
            </NavLink>
            <NavLink
              to="/live-monitor"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              实时监控
            </NavLink>
            <NavLink
              to="/learner-detail"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              学习器详情
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-5">
        <Routes>
          <Route path="/live-monitor" element={<LiveMonitorPage />} />
          <Route path="/runs-compare" element={<RunsComparePage />} />
          <Route path="/run-detail" element={<GraphAnalysisPage />} />
          <Route path="/learner-detail" element={<LearnerDetailPage />} />
          <Route path="/learner-detail/:runId" element={<LearnerDetailPage />} />
          <Route path="/graph-analysis" element={<Navigate to="/run-detail" replace />} />
          <Route path="/run/:runId" element={<GraphAnalysisPage />} />
          <Route path="*" element={<Navigate to="/runs-compare" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
