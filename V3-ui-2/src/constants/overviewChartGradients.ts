/** 总览图表：线性渐变定义（角度 + 色标） */
export type OverviewChartGradient = {
  angleDeg: number;
  stops: { offset: number; color: string }[];
};

/** 总览页图表背景色系列 */
export const OVERVIEW_CHART_GRADIENTS: OverviewChartGradient[] = [
  {
    angleDeg: 100,
    stops: [
      { offset: 0.02, color: "#b5c7ff" },
      { offset: 0.97, color: "#c8d6ff" },
    ],
  },
  {
    angleDeg: 101,
    stops: [
      { offset: 0.03, color: "#85d3ff" },
      { offset: 0.96, color: "#85d3ff99" },
    ],
  },
  {
    angleDeg: 101,
    stops: [
      { offset: 0.03, color: "#92dab2" },
      { offset: 0.96, color: "#92dab299" },
    ],
  },
  {
    angleDeg: 101,
    stops: [
      { offset: 0.03, color: "#ffce61" },
      { offset: 1, color: "#ffce6199" },
    ],
  },
  {
    angleDeg: 281,
    stops: [
      { offset: 0, color: "#dcbfff99" },
      { offset: 0.97, color: "#dcbfff" },
    ],
  },
  {
    angleDeg: 281,
    stops: [
      { offset: 0.02, color: "#ffb0da99" },
      { offset: 0.96, color: "#ffb0da" },
    ],
  },
  {
    angleDeg: 280,
    stops: [
      { offset: 0, color: "#ffb9b099" },
      { offset: 0.96, color: "#ffb9b0" },
    ],
  },
  {
    angleDeg: 100,
    stops: [
      { offset: 0.04, color: "#ffb98c" },
      { offset: 0.99, color: "#ffb98c99" },
    ],
  },
  {
    angleDeg: 100,
    stops: [
      { offset: 0.02, color: "#a7cafd" },
      { offset: 0.96, color: "#bce3fc" },
    ],
  },
  {
    angleDeg: 100,
    stops: [
      { offset: 0, color: "#dbf9c6" },
      { offset: 0.99, color: "#edfce2" },
    ],
  },
  {
    angleDeg: 100,
    stops: [
      { offset: 0.02, color: "#fec3a8" },
      { offset: 0.96, color: "#fbddbc" },
    ],
  },
];

/** 正常流量系列渐变 */
export const TRAFFIC_NORMAL_GRADIENT = OVERVIEW_CHART_GRADIENTS[2];

/** 疑似异常流量系列渐变 */
export const TRAFFIC_ABNORMAL_GRADIENT = OVERVIEW_CHART_GRADIENTS[6];
