import type { ReactNode } from "react";
import "./PageTabs.css";

export type PageTabItem = {
  key: string;
  label: ReactNode;
};

type PageTabsProps = {
  activeKey: string;
  onChange: (key: string) => void;
  items: PageTabItem[];
};

export default function PageTabs({ activeKey, onChange, items }: PageTabsProps) {
  return (
    <div className="page-tabs" role="tablist">
      {items.map((item) => {
        const active = item.key === activeKey;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={`page-tabs__item${active ? " page-tabs__item--active" : ""}`}
            onClick={() => onChange(item.key)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
