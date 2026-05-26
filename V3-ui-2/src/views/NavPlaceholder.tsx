/** 一级侧栏占位页：页边距与背景色与风险页一致 */
export default function NavPlaceholder({ title }: { title: string }) {
  return (
    <div className="bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <div className="bg-white rounded-[8px] p-8 min-h-[400px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        <span className="text-[#8c8c8c] text-sm">{title}（静态占位）</span>
      </div>
    </div>
  );
}
