import { Tooltip, type TooltipProps } from "antd";
import { CHART_AXIS_LINE, CHART_TEXT_PRIMARY, chartTheme } from "@/theme/chartTheme";

/** 与 ECharts 图表 tooltip 一致的白底样式，供 Tooltip / Typography ellipsis 复用 */
export const whiteTooltipProps: Pick<
  TooltipProps,
  "color" | "overlayInnerStyle"
> = {
  color: chartTheme.white,
  overlayInnerStyle: {
    color: CHART_TEXT_PRIMARY,
    border: `1px solid ${CHART_AXIS_LINE}`,
  },
};

/** 项目统一白底悬停浮层（不含 ECharts 内置 tooltip） */
export default function AppTooltip(props: TooltipProps) {
  return <Tooltip {...whiteTooltipProps} {...props} />;
}
