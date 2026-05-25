/** 一级侧栏占位页 */
export default function NavPlaceholder({
  title,
  layout = "default",
}: {
  title: string;
  /** 与风险页一致：浅蓝底 + 12px 内边距 + 圆角 */
  layout?: "default" | "risk";
}) {
  const content = (
    <span className="text-[#8c8c8c] text-sm">{title}（静态占位）</span>
  );

  if (layout === "risk") {
    return (
      <div className="bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
        {content}
      </div>
    );
  }

  return <div className="p-6">{content}</div>;
}
