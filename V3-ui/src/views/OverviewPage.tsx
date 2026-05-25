import '../modules/overview/styles/overview.css'
import '../modules/overview/styles/overview-app.css'
import GraphAnalysisPage from '@/modules/overview/pages/GraphAnalysisPage'

/** 总览页：V3 壳 + Run 详情内容 */
export default function OverviewPage() {
  return (
    <div className="bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <div className="overview-module page bg-white rounded-[8px] p-[16px] min-h-full shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        <GraphAnalysisPage />
      </div>
    </div>
  )
}
