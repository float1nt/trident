import type { EChartsOption } from "echarts";
import type { TrafficTrendPoint } from "@/mock/overviewTrafficTrend";
import {
  TRAFFIC_NORMAL_COLOR,
  TRAFFIC_NORMAL_LABEL,
  TRAFFIC_SUSPECTED_ABNORMAL_COLOR,
  TRAFFIC_SUSPECTED_ABNORMAL_LABEL,
} from "@/constants/overviewTrafficColors";

/** 构建正常 / 疑似异常流量堆叠柱状图 */
export function buildTrafficTrendBarOption(
  data: TrafficTrendPoint[],
): EChartsOption {
  return {
    backgroundColor: "transparent",
    color: [TRAFFIC_NORMAL_COLOR, TRAFFIC_SUSPECTED_ABNORMAL_COLOR],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        if (!Array.isArray(params) || params.length === 0) return "";
        const first = params[0] as { axisValue?: string; name?: string };
        const axisLabel = first.axisValue ?? first.name ?? "";
        const lines = params.map((item) => {
          const value = Number(item.value ?? 0);
          return `${item.marker}${item.seriesName}: ${value.toLocaleString("zh-CN")} GB`;
        });
        return [axisLabel, ...lines].join("<br/>");
      },
    },
    legend: {
      data: [TRAFFIC_NORMAL_LABEL, TRAFFIC_SUSPECTED_ABNORMAL_LABEL],
      bottom: 0,
      textStyle: { color: "#8c8c8c" },
    },
    grid: {
      left: 52,
      right: 16,
      top: 16,
      bottom: 40,
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
        rotate: data.length > 12 ? 45 : 0,
      },
    },
    yAxis: {
      type: "value",
      name: "GB",
      nameTextStyle: { color: "#8c8c8c", fontSize: 12 },
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
        itemStyle: { color: TRAFFIC_NORMAL_COLOR },
        data: data.map((item) => item.normal),
      },
      {
        name: TRAFFIC_SUSPECTED_ABNORMAL_LABEL,
        type: "bar",
        stack: "traffic",
        barMaxWidth: 28,
        emphasis: { focus: "series" },
        itemStyle: { color: TRAFFIC_SUSPECTED_ABNORMAL_COLOR },
        data: data.map((item) => item.abnormal),
      },
    ],
  };
}
