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
import { formatTrafficVolumeText } from "@/utils/formatTotalTraffic";

export type DistributionItem = {
  name: string;
  value: number;
  color?: string;
};

const PROTOCOL_DISTRIBUTION_ORDER = ["TCP", "UDP", "其他"] as const;

function protocolDistributionBucket(name: string): (typeof PROTOCOL_DISTRIBUTION_ORDER)[number] {
  const text = name.trim();
  if (!text) {
    return "其他";
  }
  const upper = text.toUpperCase();
  if (upper === "TCP" || text === "6") {
    return "TCP";
  }
  if (upper === "UDP" || text === "17") {
    return "UDP";
  }
  return "其他";
}

/** 协议分布仅展示 TCP / UDP，其余协议合并为「其他」 */
export function normalizeProtocolDistribution(
  data: DistributionItem[],
): DistributionItem[] {
  const totals: Record<(typeof PROTOCOL_DISTRIBUTION_ORDER)[number], number> = {
    TCP: 0,
    UDP: 0,
    其他: 0,
  };
  for (const item of data) {
    const value = Number(item.value) || 0;
    if (value <= 0) {
      continue;
    }
    totals[protocolDistributionBucket(item.name)] += value;
  }
  return PROTOCOL_DISTRIBUTION_ORDER.filter((name) => totals[name] > 0).map(
    (name) => ({ name, value: totals[name] }),
  );
}

function resolveTrafficDistributionGradient(
  name: string,
  index: number,
): ReturnType<typeof toEChartsLinearGradient> {
  if (name === TRAFFIC_NORMAL_LABEL || name.includes("正常")) {
    return toEChartsLinearGradient(TRAFFIC_NORMAL_GRADIENT);
  }
  if (
    name === TRAFFIC_SUSPECTED_ABNORMAL_LABEL ||
    name.includes("") ||
    name.includes("异常")
  ) {
    return toEChartsLinearGradient(TRAFFIC_ABNORMAL_GRADIENT);
  }
  return toEChartsLinearGradient(
    pickOverviewChartGradient(OVERVIEW_CHART_GRADIENTS, index),
  );
}

const TRAFFIC_DISTRIBUTION_LABELS = [
  TRAFFIC_NORMAL_LABEL,
  TRAFFIC_SUSPECTED_ABNORMAL_LABEL,
] as const;

/** 构建流量分布环形图（正常 / 异常流量配色与趋势柱状图一致） */
export function buildTrafficDistributionRingOption(
  data: DistributionItem[],
): EChartsOption {
  const labeled = data.map((item, index) => ({
    ...item,
    name:
      index < TRAFFIC_DISTRIBUTION_LABELS.length
        ? TRAFFIC_DISTRIBUTION_LABELS[index]
        : item.name,
  }));
  return buildDistributionRingOption(
    labeled,
    resolveTrafficDistributionGradient,
  );
}

/** 构建协议分布环形图（按背景色系列循环配色） */
export function buildProtocolDistributionRingOption(
  data: DistributionItem[],
): EChartsOption {
  return buildDistributionRingOption(
    normalizeProtocolDistribution(data),
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
        return `${name}<br/>占比: ${ratio.toFixed(1)}%<br/>流量: ${formatTrafficVolumeText(value)}`;
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
