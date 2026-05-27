/** V3-ui 主题 — charts & programmatic styling */
export const notionTheme = {
  bg: '#ffffff',
  surface: '#ffffff',
  surfaceAlt: '#f6faff',
  surfaceHover: '#ecf2ff',
  border: '#e8eaed',
  borderStrong: '#d9e4fa',
  text: '#333333',
  textSecondary: '#666666',
  textTertiary: '#8c8c8c',
  accent: '#4368f0',
  accentHover: '#3a5bd9',
  accentText: '#4368f0',
  accentBg: '#ecf2ff',
  success: '#52c41a',
  successBg: '#f6ffed',
  successBgHover: '#d9f7be',
  successBorder: '#b7eb8f',
  danger: '#ff4d4f',
  dangerBg: '#fff2f0',
  dangerBgHover: '#ffccc7',
  dangerBorder: '#ffa39e',
  warning: '#faad14',
  warningBg: '#fffbe6',
  warningBgHover: '#fff1b8',
  warningBorder: '#ffe58f',
  info: '#4368f0',
  infoBg: '#ecf2ff',
  infoBgHover: '#d9e4fa',
  infoBorder: '#b8c9f5',
  orange: '#fa8c16',
  orangeBg: '#fff7e6',
  purple: '#722ed1',
  chart: {
    text: '#333333',
    textSecondary: '#666666',
    axis: '#d9e4fa',
    splitLine: '#e8eaed',
    edge: '#8c8c8c',
    green: '#52c41a',
    greenBorder: '#52c41a',
    greenFill: '#f6ffed',
    red: '#ff4d4f',
    redBorder: '#ff4d4f',
    redFill: '#fff2f0',
    blue: '#4368f0',
    accent: '#4368f0',
    orange: '#fa8c16',
    yellow: '#faad14',
    cyan: '#1777FF',
    purple: '#722ed1',
    white: '#ffffff',
    nodeInternal: '#ecf2ff',
    nodeExternal: '#f6faff',
    nodeInternalBorder: '#4368f0',
    nodeExternalBorder: '#666666',
    aggregate: '#f6faff',
    aggregateBorder: '#faad14',
  },
} as const

export const CHART_TEXT_PRIMARY = notionTheme.chart.text
export const CHART_TEXT_SECONDARY = notionTheme.chart.textSecondary
export const CHART_AXIS_LINE = notionTheme.chart.axis
export const CHART_SPLIT_LINE = notionTheme.chart.splitLine
export const CHART_EDGE = notionTheme.chart.edge
export const CHART_GREEN = notionTheme.chart.green
export const CHART_GREEN_BORDER = notionTheme.chart.greenBorder
export const CHART_RED = notionTheme.chart.red
export const CHART_RED_BORDER = notionTheme.chart.redBorder
