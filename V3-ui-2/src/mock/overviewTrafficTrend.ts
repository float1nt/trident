import type { TimeRange } from "@/api/services/OverviewService";

export type TrafficTrendPoint = {
  label: string;
  normal: number;
  abnormal: number;
};

/** 生成带波动的 mock 数值（单位：GB） */
function mockTrafficGb(
  index: number,
  kind: "normal" | "abnormal",
  base: number,
): number {
  const wave = 0.85 + Math.sin(index * 0.65) * 0.15 + (index % 3) * 0.04;
  const share = kind === "normal" ? 0.72 : 0.28;
  return Math.max(1, Math.round(base * wave * share));
}

function buildHourlyTrend(): TrafficTrendPoint[] {
  return Array.from({ length: 24 }, (_, hour) => ({
    label: `${String(hour).padStart(2, "0")}:00`,
    normal: mockTrafficGb(hour, "normal", 48),
    abnormal: mockTrafficGb(hour, "abnormal", 48),
  }));
}

function buildDailyTrend(): TrafficTrendPoint[] {
  const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  return weekdays.map((label, index) => ({
    label,
    normal: mockTrafficGb(index, "normal", 320),
    abnormal: mockTrafficGb(index, "abnormal", 320),
  }));
}

function buildWeeklyTrend(): TrafficTrendPoint[] {
  return Array.from({ length: 5 }, (_, week) => ({
    label: `第${week + 1}周`,
    normal: mockTrafficGb(week, "normal", 1280),
    abnormal: mockTrafficGb(week, "abnormal", 1280),
  }));
}

/** 总览流量趋势柱状图 mock 数据 */
export function getMockTrafficTrend(timeRange: TimeRange): TrafficTrendPoint[] {
  switch (timeRange) {
    case "24h":
      return buildHourlyTrend();
    case "7d":
      return buildDailyTrend();
    case "30d":
      return buildWeeklyTrend();
    default:
      return buildHourlyTrend();
  }
}

export function getTrafficTrendChartTitle(timeRange: TimeRange): string {
  switch (timeRange) {
    case "24h":
      return "流量趋势（按小时）";
    case "7d":
      return "流量趋势（按天）";
    case "30d":
      return "流量趋势（按周）";
    default:
      return "流量趋势";
  }
}
