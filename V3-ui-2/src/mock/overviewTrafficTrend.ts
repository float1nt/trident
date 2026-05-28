import type {
  TimeRange,
  TrafficTrendPoint,
} from "@/api/services/OverviewService";

export type { TrafficTrendPoint };

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

function addDays(base: Date, days: number): Date {
  const next = new Date(base);
  next.setDate(next.getDate() + days);
  return next;
}

function startOfDay(date: Date): Date {
  const day = new Date(date);
  day.setHours(0, 0, 0, 0);
  return day;
}

/** 柱状图横轴日期，如 05-22 */
function formatChartDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${month}-${day}`;
}

/** 柱状图横轴日期范围，如 05-19~05-25 */
function formatChartDateRange(start: Date, end: Date): string {
  return `${formatChartDate(start)}~${formatChartDate(end)}`;
}

function buildHourlyTrend(): TrafficTrendPoint[] {
  return Array.from({ length: 24 }, (_, hour) => ({
    label: `${String(hour).padStart(2, "0")}:00`,
    normal: mockTrafficGb(hour, "normal", 48),
    abnormal: mockTrafficGb(hour, "abnormal", 48),
  }));
}

/** 近 7 天，横轴为具体日期 */
function buildDailyTrend(): TrafficTrendPoint[] {
  const today = startOfDay(new Date());
  return Array.from({ length: 7 }, (_, index) => {
    const day = addDays(today, index - 6);
    return {
      label: formatChartDate(day),
      normal: mockTrafficGb(index, "normal", 320),
      abnormal: mockTrafficGb(index, "abnormal", 320),
    };
  });
}

/** 近 4 个自然周，横轴为日期范围 */
function buildWeeklyTrend(): TrafficTrendPoint[] {
  const today = startOfDay(new Date());
  const weekCount = 4;
  return Array.from({ length: weekCount }, (_, index) => {
    const weekEnd = addDays(today, -(weekCount - 1 - index) * 7);
    const weekStart = addDays(weekEnd, -6);
    return {
      label: formatChartDateRange(weekStart, weekEnd),
      normal: mockTrafficGb(index, "normal", 1280),
      abnormal: mockTrafficGb(index, "abnormal", 1280),
    };
  });
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

export { getTrafficTrendChartTitle } from "@/api/services/OverviewService";
