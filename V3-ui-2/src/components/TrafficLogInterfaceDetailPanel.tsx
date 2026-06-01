import { useMemo, useState } from "react";
import { Button, Tag } from "antd";
import "./NetworkTopologyPanel.css";
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
    <div className="flex max-h-[280px] min-h-[120px] overflow-x-hidden overflow-y-auto rounded-[4px] border border-[#e8eaed] bg-white font-mono text-[12px] leading-[20px]">
      <div className="shrink-0 select-none border-r border-[#e8eaed] bg-[#fafafa] px-[10px] py-[8px] text-right text-[#bfbfbf]">
        {lines.map((_, index) => (
          <div key={`line-no-${index + 1}`}>{index + 1}</div>
        ))}
      </div>
      <pre className="m-0 min-w-0 flex-1 whitespace-pre-wrap break-all p-[8px] text-[#333]">
        {displayContent}
      </pre>
    </div>
  );
}

function MessagePaneToggle({
  panes,
  activePaneKey,
  onChange,
}: {
  panes: TrafficLogInterfaceBlock["panes"];
  activePaneKey: string;
  onChange: (key: string) => void;
}) {
  if (panes.length <= 1) return null;

  return (
    <div className="topology-graph-mode-toggle shrink-0">
      {panes.map((pane) => {
        const active = pane.key === activePaneKey;
        return (
          <Button
            key={pane.key}
            type="default"
            size="small"
            className={active ? "ant-btn-topology-selected" : undefined}
            onClick={() => onChange(pane.key)}
          >
            {pane.label}
          </Button>
        );
      })}
    </div>
  );
}

export function HttpMessageBlock({
  block,
  sectionTitle,
}: {
  block: TrafficLogInterfaceBlock;
  sectionTitle?: string;
}) {
  const [activePaneKey, setActivePaneKey] = useState(block.defaultPaneKey);

  const activePane = useMemo(
    () =>
      block.panes.find((pane) => pane.key === activePaneKey) ?? block.panes[0],
    [activePaneKey, block.panes],
  );

  const paneToggle = (
    <MessagePaneToggle
      panes={block.panes}
      activePaneKey={activePaneKey}
      onChange={setActivePaneKey}
    />
  );

  const body = (
    <>
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
    </>
  );

  if (sectionTitle) {
    return (
      <>
        <div className="flex items-center justify-between gap-2 bg-[#eef4ff] px-[12px] py-[8px]">
          <span className="text-[14px] font-medium text-[#333]">{sectionTitle}</span>
          {paneToggle}
        </div>
        <div className="flex flex-col gap-[8px] p-[12px]">{body}</div>
      </>
    );
  }

  return (
    <section className="flex flex-col gap-[8px]">
      {paneToggle}
      {body}
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
