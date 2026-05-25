import './styles/risk.css'
import './styles/risk-app.css'
import { NavLink, Outlet } from 'react-router-dom'
import { riskPaths } from './riskPaths'

export default function RiskLayout() {
  return (
    <div className="risk-module page min-h-full bg-[var(--notion-bg)] text-[var(--notion-text-primary)]">
      <header className="mb-4 border-b border-[var(--notion-border)] bg-[var(--notion-surface)] -mx-4 -mt-4 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-notion-secondary">Trident Security Console</p>
            <h1 className="text-lg font-semibold tracking-wide text-notion-text">Threat Ops Dashboard</h1>
          </div>
          <nav className="flex gap-2 rounded-xl border border-notion-border bg-notion-surface-alt p-1">
            <NavLink
              to={riskPaths.runsCompare}
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              Run 对比
            </NavLink>
            <NavLink
              to={riskPaths.runDetail}
              end
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              Run 详情
            </NavLink>
            <NavLink
              to={riskPaths.learnerDetail}
              end
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
            >
              学习器详情
            </NavLink>
          </nav>
        </div>
      </header>

      <Outlet />
    </div>
  )
}
