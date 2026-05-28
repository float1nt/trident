interface SectionTitleProps {
  children: React.ReactNode;
  className?: string;
}

/** 与首页「整体概览」等区块标题一致的样式 */
export function SectionTitle({ children, className }: SectionTitleProps) {
  return (
    <div
      className={[
        "flex h-6 items-center gap-2 text-[16px] font-medium text-[#333]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span
        className="h-[16px] w-[3px] shrink-0 rounded-[2px] bg-[#4368f0]"
        aria-hidden
      />
      {children}
    </div>
  );
}
