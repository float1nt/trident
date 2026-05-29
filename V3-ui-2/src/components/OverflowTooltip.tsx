import {
  cloneElement,
  useLayoutEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
  type Ref,
} from "react";
import type { TooltipProps } from "antd";
import AppTooltip from "@/components/AppTooltip";

function mergeRefs<T>(...refs: Array<Ref<T> | undefined>) {
  return (value: T | null) => {
    for (const ref of refs) {
      if (!ref) continue;
      if (typeof ref === "function") {
        ref(value);
      } else {
        (ref as React.MutableRefObject<T | null>).current = value;
      }
    }
  };
}

export type OverflowTooltipProps = Omit<TooltipProps, "title"> & {
  title: ReactNode;
  children: ReactElement;
};

/** 仅在子元素因宽度不足出现省略/截断时显示白底 Tooltip */
export default function OverflowTooltip({
  title,
  children,
  ...tooltipProps
}: OverflowTooltipProps) {
  const ref = useRef<HTMLElement>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useLayoutEffect(() => {
    const checkOverflow = () => {
      const el = ref.current;
      if (!el) return;
      setIsOverflowing(el.scrollWidth > el.clientWidth);
    };

    checkOverflow();

    const element = ref.current;
    if (element && window.ResizeObserver) {
      resizeObserverRef.current = new ResizeObserver(checkOverflow);
      resizeObserverRef.current.observe(element);
    }

    window.addEventListener("resize", checkOverflow);
    return () => {
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      window.removeEventListener("resize", checkOverflow);
    };
  }, [title, children]);

  const childRef = (children as ReactElement & { ref?: Ref<HTMLElement> }).ref;
  const child = cloneElement(children, {
    ref: mergeRefs(childRef, ref),
  } as { ref: Ref<HTMLElement> });

  if (!isOverflowing) {
    return child;
  }

  return (
    <AppTooltip title={title} {...tooltipProps}>
      {child}
    </AppTooltip>
  );
}
