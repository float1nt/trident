/** 总览：正常流量（与流量分布环形图、趋势柱状图一致） */
export const TRAFFIC_NORMAL_COLOR = "#52c41a";

/** 总览：异常流量 */
export const TRAFFIC_SUSPECTED_ABNORMAL_COLOR = "#ff4d4f";

export const TRAFFIC_NORMAL_LABEL = "正常流量";
export const TRAFFIC_SUSPECTED_ABNORMAL_LABEL = "异常流量";

const TRAFFIC_COLOR_BY_NAME: Record<string, string> = {
  [TRAFFIC_NORMAL_LABEL]: TRAFFIC_NORMAL_COLOR,
  [TRAFFIC_SUSPECTED_ABNORMAL_LABEL]: TRAFFIC_SUSPECTED_ABNORMAL_COLOR,
};

/** 按分类名称解析流量分布配色 */
export function resolveTrafficDistributionColor(
  name: string,
  fallback?: string,
): string | undefined {
  if (TRAFFIC_COLOR_BY_NAME[name]) {
    return TRAFFIC_COLOR_BY_NAME[name];
  }
  if (name.includes("正常")) {
    return TRAFFIC_NORMAL_COLOR;
  }
  if (name.includes("") || name.includes("异常")) {
    return TRAFFIC_SUSPECTED_ABNORMAL_COLOR;
  }
  return fallback;
}
