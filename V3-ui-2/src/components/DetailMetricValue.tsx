import { formatMetricCount } from "@/utils/formatTotalTraffic";

/** 详情页顶栏指标：≥1 万显示万个/亿个，否则仅数字 */
export function DetailMetricValue({ count }: { count: number }) {
  const n = Math.max(0, Number(count) || 0);
  const { value, unit } = formatMetricCount(n);
  const showUnit = n >= 10_000;
  return (
    <div className="flex w-full items-baseline justify-center gap-1 text-center font-medium leading-none text-[#333]">
      <span className="text-[28px] tabular-nums">{value}</span>
      {showUnit ? (
        <span className="text-sm font-normal text-[#8c8c8c]">{unit}</span>
      ) : null}
    </div>
  );
}
