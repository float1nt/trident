import '../modules/overview/styles/overview.css'
import '../modules/overview/styles/overview-app.css'
import LearnerDetailPage from '@/modules/overview/pages/LearnerDetailPage'

/** 学习器详情页：与总览页一致的 V3 布局壳 */
export default function LearnerDetailView() {
  return (
    <div className="bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <div className="overview-module page bg-white rounded-[8px] p-[16px] min-h-full shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        <LearnerDetailPage />
      </div>
    </div>
  )
}
