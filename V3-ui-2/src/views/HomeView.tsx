import DataFlowMetricsSection from "@/components/DataFlowMetricsSection";

/** 总览：数据流动看板 — 当前仅实现核心指标区 */
export default function HomeView() {
  return (
    <div className="h-full w-full rounded-[8px]">
      <DataFlowMetricsSection />
      {/* relative + z-index + -mt-[16px]：上移 16px 并盖住指标区底部 */}
      <div className="relative p-[12px] z-10 -mt-[36px] h-full w-full rounded-[16px] bg-[#f6faff]" >
        <div className="flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]">
          <span
            className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
            aria-hidden
          />
          整体分布
        </div>
      </div>
    </div>
  );
}
