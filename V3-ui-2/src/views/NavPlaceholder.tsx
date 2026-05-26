/** 一级侧栏占位页：除首页外各入口暂用 */
export default function NavPlaceholder({ title }: { title: string }) {
  return (
    <div className="p-6 text-[#8c8c8c] text-sm">
      {title}（静态占位）
    </div>
  );
}
