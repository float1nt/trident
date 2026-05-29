import { useMemo, useState } from "react";
import { Button, Tag, message } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import type {
  TrafficLogInterfaceBlock,
  TrafficLogInterfaceDetail,
} from "@/types/trafficLogDetail";

type TrafficLogInterfaceDetailPanelProps = {
  data: TrafficLogInterfaceDetail;
};

function CodeViewer({ content }: { content: string }) {
  const lines = useMemo(() => content.split("\n"), [content]);
  const displayContent = content || " ";

  return (
    <div className="flex max-h-[280px] min-h-[120px] overflow-auto rounded-[4px] border border-[#e8eaed] bg-white font-mono text-[12px] leading-[20px]">
      <div className="shrink-0 select-none border-r border-[#e8eaed] bg-[#fafafa] px-[10px] py-[8px] text-right text-[#bfbfbf]">
        {lines.map((_, index) => (
          <div key={`line-no-${index + 1}`}>{index + 1}</div>
        ))}
      </div>
      <pre className="m-0 min-w-0 flex-1 overflow-x-auto whitespace-pre p-[8px] text-[#333]">
        {displayContent}
      </pre>
    </div>
  );
}

function InterfaceSubTabs({
  panes,
  activeKey,
  onChange,
}: {
  panes: TrafficLogInterfaceBlock["panes"];
  activeKey: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-[16px]">
      {panes.map((pane) => {
        const active = pane.key === activeKey;
        return (
          <button
            key={pane.key}
            type="button"
            className={[
              "border-none bg-transparent p-0 text-[13px] leading-[20px] transition-colors",
              active
                ? "font-medium text-[#1777ff]"
                : "text-[#666] hover:text-[#333]",
            ].join(" ")}
            onClick={() => onChange(pane.key)}
          >
            {pane.label}
          </button>
        );
      })}
    </div>
  );
}

export function HttpMessageBlock({ block }: { block: TrafficLogInterfaceBlock }) {
  const [activePaneKey, setActivePaneKey] = useState(block.defaultPaneKey);

  const activePane = useMemo(
    () =>
      block.panes.find((pane) => pane.key === activePaneKey) ?? block.panes[0],
    [activePaneKey, block.panes],
  );

  const handleCopy = async () => {
    const text = activePane?.content ?? "";
    if (!text.trim()) {
      message.warning("暂无内容可复制");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      message.success("已复制");
    } catch {
      message.error("复制失败");
    }
  };

  return (
    <section className="flex flex-col gap-[8px]">
      {/* <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-[6px]">
          <span className="text-[14px] font-medium text-[#333]">
            {block.titlePrefix} ({block.sizeLabel})
          </span>
          <Button
            type="text"
            size="small"
            className="!h-[22px] !w-[22px] !min-w-[22px] !p-0 text-[#8c8c8c] hover:!text-[#1777ff]"
            icon={<CopyOutlined className="text-[13px]" />}
            aria-label={`复制${block.titlePrefix}`}
            onClick={() => void handleCopy()}
          />
        </div>
        <InterfaceSubTabs
          panes={block.panes}
          activeKey={activePane?.key ?? block.defaultPaneKey}
          onChange={setActivePaneKey}
        />
      </div> */}

      {block.dataTags && block.dataTags.length > 0 ? (
        <div className="flex flex-wrap gap-[8px]">
          {block.dataTags.map((tag) => (
            <Tag
              key={tag}
              className="!m-0 !rounded-[2px] !border-[#b3d4ff] !bg-[#e8f1ff] !px-[8px] !py-[2px] !text-[12px] !leading-[20px] !text-[#1777ff]"
            >
              {tag}
            </Tag>
          ))}
        </div>
      ) : null}

      <CodeViewer content={activePane?.content ?? ""} />
    </section>
  );
}

export function TrafficLogInterfaceDetailPanel({
  data,
}: TrafficLogInterfaceDetailPanelProps) {
  return (
    <div className="flex flex-col gap-[20px]">
      <HttpMessageBlock block={data.request} />
      <HttpMessageBlock block={data.response} />
    </div>
  );
}
