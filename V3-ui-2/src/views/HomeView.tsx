import DataFlowMetricsSection from "@/components/DataFlowMetricsSection";

/** 总览：数据流动看板 — 当前仅实现核心指标区 */
export default function HomeView() {
  return (
    <div className="bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <DataFlowMetricsSection />
    </div>
  );
}
