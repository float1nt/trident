/** Notion light theme — charts & programmatic styling */
export const notionTheme = {
  bg: '#ffffff',
  surface: '#ffffff',
  surfaceAlt: '#f7f6f3',
  surfaceHover: '#efefef',
  border: '#e9e9e7',
  borderStrong: '#d3d1cb',
  text: '#37352f',
  textSecondary: '#787774',
  textTertiary: '#9b9a97',
  accent: '#2383e2',
  accentHover: '#1a73d1',
  accentText: '#337ea9',
  accentBg: '#d3e5ef',
  success: '#448361',
  successBg: '#dbeddb',
  successBgHover: '#c7e0c7',
  successBorder: '#c7ddc4',
  danger: '#d44c47',
  dangerBg: '#fdebec',
  dangerBgHover: '#f9d7d9',
  dangerBorder: '#f5c4c7',
  warning: '#92702d',
  warningBg: '#fbf3db',
  warningBgHover: '#f5ead0',
  warningBorder: '#eee3c7',
  info: '#337ea9',
  infoBg: '#d3e5ef',
  infoBgHover: '#c0d9e8',
  infoBorder: '#b8d4e8',
  orange: '#d9730d',
  orangeBg: '#faebdd',
  purple: '#9065b0',
  chart: {
    text: '#37352f',
    textSecondary: '#787774',
    axis: '#d3d1cb',
    splitLine: '#e9e9e7',
    edge: '#9b9a97',
    green: '#448361',
    greenBorder: '#448361',
    greenFill: '#dbeddb',
    red: '#d44c47',
    redBorder: '#d44c47',
    redFill: '#fdebec',
    blue: '#337ea9',
    accent: '#2383e2',
    orange: '#d9730d',
    yellow: '#cb912f',
    cyan: '#337ea9',
    purple: '#9065b0',
    white: '#ffffff',
    nodeInternal: '#d3e5ef',
    nodeExternal: '#f1f1ef',
    nodeInternalBorder: '#337ea9',
    nodeExternalBorder: '#787774',
    aggregate: '#f7f6f3',
    aggregateBorder: '#cb912f',
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
