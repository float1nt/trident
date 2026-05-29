import type { TooltipProps } from "antd";
import AppTooltip from "@/components/AppTooltip";

/** 图标说明浮窗：悬停即显示（与 OverflowTooltip 的截断逻辑区分） */
export default function IconTooltip(props: TooltipProps) {
  return <AppTooltip {...props} />;
}
