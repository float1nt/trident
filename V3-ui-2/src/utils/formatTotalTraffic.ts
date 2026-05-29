/** 总流量卡片展示（接口 totalTraffic 单位为字节） */
export type FormattedTrafficVolume = {
  value: string;
  unit: string;
};

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

function trimTrailingZeros(text: string): string {
  return text.replace(/\.?0+$/, "");
}

function formatScaledNumber(value: number, maxFractionDigits = 2): string {
  if (value >= 100) {
    return Math.round(value).toLocaleString("zh-CN");
  }
  if (value >= 10) {
    return trimTrailingZeros(value.toFixed(1));
  }
  return trimTrailingZeros(value.toFixed(maxFractionDigits));
}

/** 字节单位换算：B / KB / MB / GB / TB（1024 进位） */
export function formatTotalTrafficBytes(bytes: number): FormattedTrafficVolume {
  let value = Math.max(0, Number(bytes) || 0);
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < BYTE_UNITS.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return {
    value: formatScaledNumber(value),
    unit: BYTE_UNITS[unitIndex],
  };
}

/** 图表/tooltip 等场景：格式化为「数值 + 单位」文本 */
export function formatTrafficVolumeText(bytes: number): string {
  const { value, unit } = formatTotalTrafficBytes(bytes);
  return unit ? `${value} ${unit}` : value;
}

/** 数量单位换算：个 / 万个 / 亿个（10000 进位） */
export function formatMetricCount(count: number): FormattedTrafficVolume {
  const n = Math.max(0, Number(count) || 0);

  if (n >= 100_000_000) {
    return {
      value: formatScaledNumber(n / 100_000_000),
      unit: "亿个",
    };
  }

  if (n >= 10_000) {
    return {
      value: formatScaledNumber(n / 10_000),
      unit: "万个",
    };
  }

  return {
    value: n.toLocaleString("zh-CN"),
    unit: "个",
  };
}

/** 次数单位换算：次 / 万次 / 亿次（10000 进位） */
export function formatMetricTimes(count: number): FormattedTrafficVolume {
  const n = Math.max(0, Number(count) || 0);

  if (n >= 100_000_000) {
    return {
      value: formatScaledNumber(n / 100_000_000),
      unit: "亿次",
    };
  }

  if (n >= 10_000) {
    return {
      value: formatScaledNumber(n / 10_000),
      unit: "万次",
    };
  }

  return {
    value: n.toLocaleString("zh-CN"),
    unit: "次",
  };
}

/** 详情页等场景：格式化为「数值+单位」触发次数文本 */
export function formatTriggerCountText(count: number): string {
  const { value, unit } = formatMetricTimes(count);
  return `${value}${unit}`;
}
