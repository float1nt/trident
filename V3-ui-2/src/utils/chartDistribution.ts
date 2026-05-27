import type { EChartsOption } from "echarts";
import { resolveTrafficDistributionColor } from "@/constants/overviewTrafficColors";

export type DistributionItem = {
  name: string;
  value: number;
  color?: string;
};

const DEFAULT_COLORS = [
  "#4368f0",
  "#52c41a",
  "#fa8c16",
  "#722ed1",
  "#1777ff",
  "#faad14",
  "#ff4d4f",
  "#8c8c8c",
];

/** 构建流量分布环形图（正常 / 疑似异常流量配色与趋势柱状图一致） */
export function buildTrafficDistributionRingOption(
  data: DistributionItem[],
): EChartsOption {
  const colored = data.map((item, index) => ({
    ...item,
    color:
      resolveTrafficDistributionColor(item.name, item.color) ??
      item.color ??
      DEFAULT_COLORS[index % DEFAULT_COLORS.length],
  }));
  return buildDistributionRingOption(colored);
}

/** 构建环形图 ECharts 配置 */
export function buildDistributionRingOption(
  data: DistributionItem[],
): EChartsOption {
  const total = data.reduce((sum, item) => sum + item.value, 0);

  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const name =
          typeof params === "object" && params && "name" in params
            ? String(params.name ?? "-")
            : "-";
        const value =
          typeof params === "object" && params && "value" in params
            ? Number(params.value ?? 0)
            : 0;
        const ratio = total > 0 ? (value / total) * 100 : 0;
        return `${name}<br/>占比: ${ratio.toFixed(1)}%<br/>数量: ${value.toLocaleString("zh-CN")}`;
      },
    },
    legend: {
      bottom: 0,
      textStyle: { color: "#8c8c8c" },
    },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["50%", "45%"],
        label: {
          color: "#333",
          formatter: "{b}: {d}%",
        },
        data: data.map((item, index) => ({
          name: item.name,
          value: item.value,
          itemStyle: {
            color: item.color ?? DEFAULT_COLORS[index % DEFAULT_COLORS.length],
          },
        })),
      },
    ],
  };
}
