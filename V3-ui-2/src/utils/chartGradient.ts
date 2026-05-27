import type { OverviewChartGradient } from "@/constants/overviewChartGradients";

type EChartsLinearGradient = {
  type: "linear";
  x: number;
  y: number;
  x2: number;
  y2: number;
  colorStops: { offset: number; color: string }[];
  global?: boolean;
};

/** 将渐变定义转为 CSS `linear-gradient(...)` */
export function toCssLinearGradient(gradient: OverviewChartGradient): string {
  const stops = gradient.stops
    .map((stop) => `${stop.color} ${Math.round(stop.offset * 100)}%`)
    .join(", ");
  return `linear-gradient(${gradient.angleDeg}deg, ${stops})`;
}

/** 将 CSS 角度线性渐变转为 ECharts 线性渐变（用于扇区、柱条等） */
export function toEChartsLinearGradient(
  gradient: OverviewChartGradient,
): EChartsLinearGradient {
  const rad = ((90 - gradient.angleDeg) * Math.PI) / 180;
  const x = 0.5 - Math.cos(rad) * 0.5;
  const y = 0.5 + Math.sin(rad) * 0.5;
  const x2 = 0.5 + Math.cos(rad) * 0.5;
  const y2 = 0.5 - Math.sin(rad) * 0.5;

  return {
    type: "linear",
    x,
    y,
    x2,
    y2,
    colorStops: gradient.stops.map((stop) => ({
      offset: stop.offset,
      color: stop.color,
    })),
  };
}

/** 按索引循环取渐变（用于多分类环形图） */
export function pickOverviewChartGradient(
  gradients: OverviewChartGradient[],
  index: number,
): OverviewChartGradient {
  return gradients[index % gradients.length]!;
}
