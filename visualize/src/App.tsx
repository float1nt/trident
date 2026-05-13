import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import GraphAnalysisPage from './pages/GraphAnalysisPage'
import RunsComparePage from './pages/RunsComparePage'

function App() {
  return (
    <div className="min-h-screen bg-[#f7f6f3] text-slate-900">
      <header className="border-b border-slate-200 bg-[#ffffff]">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Trident Security Console</p>
            <h1 className="text-lg font-semibold tracking-wide text-slate-900">Threat Ops Dashboard</h1>
          </div>
          <nav className="flex gap-2 rounded-xl border border-slate-200 bg-[#fbfbfa] p-1">
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
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-5">
        <Routes>
          <Route path="/runs-compare" element={<RunsComparePage />} />
          <Route path="/run-detail" element={<GraphAnalysisPage />} />
          <Route path="/graph-analysis" element={<Navigate to="/run-detail" replace />} />
          <Route path="/run/:runId" element={<GraphAnalysisPage />} />
          <Route path="*" element={<Navigate to="/runs-compare" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
