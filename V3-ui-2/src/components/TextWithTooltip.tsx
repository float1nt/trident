import OverflowTooltip from "@/components/OverflowTooltip";

interface TextWithTooltipProps {
  text: string;
  emptyText?: string;
  className?: string;
  style?: React.CSSProperties;
}

export const TextWithTooltip = ({
  text,
  emptyText = "-",
  className = "",
  style,
}: TextWithTooltipProps) => {
  const displayText = text || emptyText;

  return (
    <OverflowTooltip
      title={displayText}
      getPopupContainer={(triggerNode) =>
        triggerNode.parentElement || document.body
      }
    >
      <div
        className={className}
        style={{
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          width: "100%",
          ...style,
        }}
      >
        {displayText}
      </div>
    </OverflowTooltip>
  );
};
