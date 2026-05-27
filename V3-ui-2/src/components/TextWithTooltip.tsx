import { useRef, useLayoutEffect, useState } from "react";
import { Tooltip } from "antd";

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
  const textRef = useRef<HTMLDivElement>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useLayoutEffect(() => {
    const checkOverflow = () => {
      if (textRef.current) {
        const isOverflow =
          textRef.current.scrollWidth > textRef.current.clientWidth;
        setIsOverflowing(isOverflow);
      }
    };

    timerRef.current = setTimeout(() => {
      checkOverflow();
      const element = textRef.current;
      if (element && window.ResizeObserver) {
        resizeObserverRef.current = new ResizeObserver(checkOverflow);
        resizeObserverRef.current.observe(element);
      }
    }, 0);

    window.addEventListener("resize", checkOverflow);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect();
        resizeObserverRef.current = null;
      }
      window.removeEventListener("resize", checkOverflow);
    };
  }, [text]);

  const displayText = text || emptyText;

  const textElement = (
    <div
      ref={textRef}
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
  );

  if (isOverflowing) {
    return (
      <Tooltip
        title={displayText}
        getPopupContainer={(triggerNode) =>
          triggerNode.parentElement || document.body
        }
      >
        {textElement}
      </Tooltip>
    );
  }

  return textElement;
};
