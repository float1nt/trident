import type { EChartsOption } from "echarts";

export type DistributionItem = {
  name: string;
  value: number;
  color?: string;
};

/** 流量分布 mock：正常 / 疑似异常 */
export const MOCK_TRAFFIC_DISTRIBUTION: DistributionItem[] = [
  { name: "正常流量", value: 7234, color: "#52c41a" },
  { name: "疑似异常流量", value: 2812, color: "#ff7875" },
];

/** 协议分布 mock */
export const MOCK_PROTOCOL_DISTRIBUTION: DistributionItem[] = [
  { name: "HTTP", value: 3520, color: "#4368f0" },
  { name: "HTTPS", value: 2840, color: "#1777ff" },
  { name: "DNS", value: 1260, color: "#52c41a" },
  { name: "SSH", value: 820, color: "#722ed1" },
  { name: "FTP", value: 510, color: "#fa8c16" },
  { name: "其他", value: 1096, color: "#8c8c8c" },
];

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
        const name = typeof params === "object" && params && "name" in params
          ? String(params.name ?? "-")
          : "-";
        const value = typeof params === "object" && params && "value" in params
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
