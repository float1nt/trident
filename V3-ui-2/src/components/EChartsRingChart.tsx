import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

type EChartsRingChartProps = {
  option: EChartsOption;
  /** 固定高度；不传则撑满父容器（父级需有高度） */
  height?: number;
  className?: string;
};

/** 基于 ECharts 的图表容器，自动处理 resize 与销毁 */
export default function EChartsRingChart({
  option,
  height,
  className,
}: EChartsRingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = echarts.init(el);
    chartRef.current = chart;

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  const fillParent = height == null;

  return (
    <div
      ref={containerRef}
      className={[className, fillParent ? "h-full" : undefined]
        .filter(Boolean)
        .join(" ")}
      style={{
        width: "100%",
        height: fillParent ? "100%" : height,
      }}
    />
  );
}
