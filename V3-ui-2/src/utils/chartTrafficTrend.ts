import type { EChartsOption } from "echarts";
import type { TrafficTrendPoint } from "@/api/services/OverviewService";
import {
  TRAFFIC_ABNORMAL_GRADIENT,
  TRAFFIC_NORMAL_GRADIENT,
} from "@/constants/overviewChartGradients";
import {
  TRAFFIC_NORMAL_LABEL,
  TRAFFIC_SUSPECTED_ABNORMAL_LABEL,
} from "@/constants/overviewTrafficColors";
import {
  formatTotalTrafficBytes,
  formatTrafficVolumeText,
} from "@/utils/formatTotalTraffic";
import { toEChartsLinearGradient } from "@/utils/chartGradient";

const TRAFFIC_NORMAL_FILL = toEChartsLinearGradient(TRAFFIC_NORMAL_GRADIENT);
const TRAFFIC_ABNORMAL_FILL = toEChartsLinearGradient(TRAFFIC_ABNORMAL_GRADIENT);
const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

function trafficTrendYAxisScale(maxBytes: number): { divisor: number; unit: string } {
  const { unit } = formatTotalTrafficBytes(maxBytes);
  const unitIndex = Math.max(0, BYTE_UNITS.indexOf(unit as (typeof BYTE_UNITS)[number]));
  const divisor = unitIndex === 0 ? 1 : 1024 ** unitIndex;
  return { divisor, unit };
}

/** 构建正常 / 异常流量堆叠柱状图（数据单位为字节） */
export function buildTrafficTrendBarOption(
  data: TrafficTrendPoint[],
): EChartsOption {
  const xLabelsRotated = data.length > 12;
  const gridBottom = xLabelsRotated ? 62 : 56;
  const maxBytes = data.reduce(
    (max, item) => Math.max(max, item.normal + item.abnormal),
    0,
  );
  const { divisor, unit } = trafficTrendYAxisScale(maxBytes);
  const toDisplay = (bytes: number) => bytes / divisor;

  return {
    backgroundColor: "transparent",
    color: [TRAFFIC_NORMAL_FILL, TRAFFIC_ABNORMAL_FILL],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        if (!Array.isArray(params) || params.length === 0) return "";
        const first = params[0] as { axisValue?: string; name?: string };
        const axisLabel = first.axisValue ?? first.name ?? "";
        const lines = params.map((item) => {
          const index = Number(item.dataIndex ?? 0);
          const point = data[index];
          const bytes =
            item.seriesName === TRAFFIC_NORMAL_LABEL
              ? point?.normal ?? 0
              : point?.abnormal ?? 0;
          return `${item.marker}${item.seriesName}: ${formatTrafficVolumeText(bytes)}`;
        });
        return [axisLabel, ...lines].join("<br/>");
      },
    },
    legend: {
      data: [TRAFFIC_NORMAL_LABEL, TRAFFIC_SUSPECTED_ABNORMAL_LABEL],
      bottom: 4,
      padding: [16, 0, 0, 0],
      itemGap: 20,
      textStyle: { color: "#8c8c8c" },
    },
    grid: {
      left: 52,
      right: 16,
      top: 16,
      bottom: gridBottom,
      containLabel: false,
    },
    xAxis: {
      type: "category",
      data: data.map((item) => item.label),
      axisLine: { lineStyle: { color: "#e8eaed" } },
      axisTick: { show: false },
      axisLabel: {
        color: "#8c8c8c",
        fontSize: 11,
        interval: 0,
        rotate: xLabelsRotated ? 45 : 0,
      },
    },
    yAxis: {
      type: "value",
      name: `单位：${unit}`,
      nameTextStyle: {
        color: "#8c8c8c",
        fontSize: 12,
        align: "right",
      },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: "#f0f0f0", type: "dashed" } },
      axisLabel: { color: "#8c8c8c" },
    },
    series: [
      {
        name: TRAFFIC_NORMAL_LABEL,
        type: "bar",
        stack: "traffic",
        barMaxWidth: 28,
        emphasis: { focus: "series" },
        itemStyle: { color: TRAFFIC_NORMAL_FILL },
        data: data.map((item) => toDisplay(item.normal)),
      },
      {
        name: TRAFFIC_SUSPECTED_ABNORMAL_LABEL,
        type: "bar",
        stack: "traffic",
        barMaxWidth: 28,
        emphasis: { focus: "series" },
        itemStyle: { color: TRAFFIC_ABNORMAL_FILL },
        data: data.map((item) => toDisplay(item.abnormal)),
      },
    ],
  };
}
