import { useEffect, useMemo, useState } from "react";
import { Button, Drawer, Tooltip } from "antd";
import { CloseOutlined, InfoCircleOutlined } from "@ant-design/icons";
import type { RiskTrafficLogItem } from "@/api/services/RiskService";
import {
  buildBasicInfoSections,
  buildMockTrafficLogDetail,
  buildMockTrafficLogInterfaceDetail,
} from "@/mock/trafficLogDetailMock";
import { TrafficLogInterfaceDetailPanel } from "@/components/TrafficLogInterfaceDetailPanel";
import type { TrafficLogDetailSection } from "@/types/trafficLogDetail";
import { whiteTooltipProps } from "@/components/AppTooltip";

type TrafficLogDetailDrawerProps = {
  open: boolean;
  logs: RiskTrafficLogItem[];
  activeIndex: number;
  onClose: () => void;
  onActiveIndexChange: (index: number) => void;
};

const DETAIL_TABS = [
  { key: "basic", label: "基本信息" },
  { key: "interface", label: "接口详情" },
] as const;

type DetailTabKey = (typeof DETAIL_TABS)[number]["key"];

function DetailField({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  const showHint = value === "-" && hint;

  return (
    <div className="flex min-w-0 items-start gap-2 py-[6px]">
      <span className="w-[108px] shrink-0 text-[14px] leading-[22px] text-[#8c8c8c]">
        {label}
      </span>
      <span className="flex min-w-0 flex-1 items-center gap-1 text-[14px] leading-[22px] text-[#333]">
        <span className="min-w-0 break-all">{value}</span>
        {showHint ? (
          <Tooltip title={hint} {...whiteTooltipProps}>
            <InfoCircleOutlined className="shrink-0 text-[12px] text-[#bfbfbf]" />
          </Tooltip>
        ) : null}
      </span>
    </div>
  );
}

function DetailSection({ section }: { section: TrafficLogDetailSection }) {
  return (
    <section className="overflow-hidden rounded-[4px] border border-[#e8eaed]">
      <div className="bg-[#eef4ff] px-[12px] py-[8px] text-[14px] font-medium text-[#333]">
        {section.title}
      </div>
      <div className="grid grid-cols-1 gap-x-[24px] px-[12px] py-[4px] md:grid-cols-2">
        {section.fields.map((field) => (
          <DetailField
            key={`${section.title}-${field.label}`}
            label={field.label}
            value={field.value}
            hint={field.hint}
          />
        ))}
      </div>
    </section>
  );
}

export function TrafficLogDetailDrawer({
  open,
  logs,
  activeIndex,
  onClose,
  onActiveIndexChange,
}: TrafficLogDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<DetailTabKey>("basic");

  const activeLog = logs[activeIndex] ?? null;
  const detail = useMemo(
    () => (activeLog ? buildMockTrafficLogDetail(activeLog) : null),
    [activeLog],
  );

  const basicSections = useMemo(
    () => (detail ? buildBasicInfoSections(detail) : []),
    [detail],
  );

  const interfaceDetail = useMemo(
    () => (detail ? buildMockTrafficLogInterfaceDetail(detail) : null),
    [detail],
  );

  useEffect(() => {
    if (open) {
      setActiveTab("basic");
    }
  }, [open, activeIndex]);

  const canGoPrev = activeIndex > 0;
  const canGoNext = activeIndex >= 0 && activeIndex < logs.length - 1;

  return (
    <Drawer
      title="详情"
      closable={false}
      extra={
        <Button
          type="text"
          icon={<CloseOutlined />}
          aria-label="关闭"
          onClick={onClose}
        />
      }
      open={open}
      onClose={onClose}
      width="min(720px, 45vw)"
      destroyOnClose
      styles={{
        body: { padding: 0 },
      }}
    >
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#f0f0f0] px-[20px]">
          <div className="flex items-center gap-[24px]">
            {DETAIL_TABS.map((tab) => {
              const active = tab.key === activeTab;
              return (
                <button
                  key={tab.key}
                  type="button"
                  className={[
                    "relative border-none bg-transparent px-0 py-[12px] text-[14px] leading-[22px] transition-colors",
                    active
                      ? "font-medium text-[#1777ff]"
                      : "text-[#666] hover:text-[#333]",
                  ].join(" ")}
                  onClick={() => setActiveTab(tab.key)}
                >
                  {tab.label}
                  {active ? (
                    <span
                      className="absolute bottom-0 left-0 h-[2px] w-full rounded-[1px] bg-[#1777ff]"
                      aria-hidden
                    />
                  ) : null}
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-[8px] pb-[8px] pt-[8px] text-[14px] text-[#666]">
            <span>当前序号: {activeIndex >= 0 ? activeIndex + 1 : "-"}</span>
            <Button
              size="small"
              disabled={!canGoPrev}
              onClick={() => onActiveIndexChange(activeIndex - 1)}
            >
              上一条
            </Button>
            <Button
              size="small"
              disabled={!canGoNext}
              onClick={() => onActiveIndexChange(activeIndex + 1)}
            >
              下一条
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-[20px] py-[16px]">
          {!detail ? (
            <p className="text-[14px] text-[#8c8c8c]">暂无日志详情</p>
          ) : activeTab === "basic" ? (
            <div className="flex flex-col gap-[12px]">
              {basicSections.map((section) => (
                <DetailSection key={section.title} section={section} />
              ))}
            </div>
          ) : interfaceDetail ? (
            <TrafficLogInterfaceDetailPanel
              key={activeLog?.id ?? activeIndex}
              data={interfaceDetail}
            />
          ) : null}
        </div>
      </div>
    </Drawer>
  );
}
