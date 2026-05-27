import type { EChartsOption } from "echarts";
import {
  OVERVIEW_CHART_GRADIENTS,
  TRAFFIC_ABNORMAL_GRADIENT,
  TRAFFIC_NORMAL_GRADIENT,
} from "@/constants/overviewChartGradients";
import {
  TRAFFIC_NORMAL_LABEL,
  TRAFFIC_SUSPECTED_ABNORMAL_LABEL,
} from "@/constants/overviewTrafficColors";
import {
  pickOverviewChartGradient,
  toEChartsLinearGradient,
} from "@/utils/chartGradient";

export type DistributionItem = {
  name: string;
  value: number;
  color?: string;
};

function resolveTrafficDistributionGradient(
  name: string,
  index: number,
): ReturnType<typeof toEChartsLinearGradient> {
  if (name === TRAFFIC_NORMAL_LABEL || name.includes("正常")) {
    return toEChartsLinearGradient(TRAFFIC_NORMAL_GRADIENT);
  }
  if (
    name === TRAFFIC_SUSPECTED_ABNORMAL_LABEL ||
    name.includes("疑似") ||
    name.includes("异常")
  ) {
    return toEChartsLinearGradient(TRAFFIC_ABNORMAL_GRADIENT);
  }
  return toEChartsLinearGradient(
    pickOverviewChartGradient(OVERVIEW_CHART_GRADIENTS, index),
  );
}

/** 构建流量分布环形图（正常 / 疑似异常流量配色与趋势柱状图一致） */
export function buildTrafficDistributionRingOption(
  data: DistributionItem[],
): EChartsOption {
  return buildDistributionRingOption(data, resolveTrafficDistributionGradient);
}

/** 构建协议分布环形图（按背景色系列循环配色） */
export function buildProtocolDistributionRingOption(
  data: DistributionItem[],
): EChartsOption {
  return buildDistributionRingOption(
    data,
    (_name, index) =>
      toEChartsLinearGradient(
        pickOverviewChartGradient(OVERVIEW_CHART_GRADIENTS, index),
      ),
  );
}

type DistributionGradientResolver = (
  name: string,
  index: number,
) => ReturnType<typeof toEChartsLinearGradient>;

/** 构建环形图 ECharts 配置（协议分布等按背景色系列循环配色） */
export function buildDistributionRingOption(
  data: DistributionItem[],
  resolveGradient: DistributionGradientResolver = (name, index) =>
    resolveTrafficDistributionGradient(name, index),
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
            color: resolveGradient(item.name, index),
          },
        })),
      },
    ],
  };
}
