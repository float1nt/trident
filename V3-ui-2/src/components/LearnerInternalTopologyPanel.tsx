import { Component, type ErrorInfo, useMemo, type ReactNode } from "react";
import { Button, Card, Col, Empty, Row, Typography } from "antd";
import {
  GRID_CHART_HEIGHT,
  TopologyChartPane,
} from "@/components/NetworkTopologyPanel";
import type {
  LearnerNetworkTopologyJson,
  LearnerTopologyOption,
} from "@/types/learnerTopology";

const { Text } = Typography;

const TOPOLOGY_REPULSION = 70;
const TOPOLOGY_MIN_EDGE_FLOWS = 1;

export type { LearnerNetworkTopologyJson, LearnerTopologyOption };

type Props = {
  data: LearnerNetworkTopologyJson | null;
  onRiskClick?: (riskId: number) => void;
  emptyHint?: string;
};

class ChartPaneErrorBoundary extends Component<
  { children: ReactNode; title: string },
  { hasError: boolean; message?: string }
> {
  state: { hasError: boolean; message?: string } = { hasError: false };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[TopologyChartPane:${this.props.title}]`, error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded border border-dashed border-[#ffd8bf] bg-[#fff7e6] p-2 text-[11px] text-[#ad6800]">
          {this.props.title} 图渲染失败
          {this.state.message ? `：${this.state.message}` : ""}
        </div>
      );
    }
    return this.props.children;
  }
}

function buildSortedLearnerOptions(
  data: LearnerNetworkTopologyJson,
): LearnerTopologyOption[] {
  // 以 views 为主，learners 作为补充，避免 learners 与 views 键名轻微不一致时被筛空
  const viewKeys = Object.keys(data.views ?? {});
  const learnerKeys = data.learners ?? [];
  const names = Array.from(new Set([...viewKeys, ...learnerKeys])).filter(
    (k) => Boolean(data.views[k]),
  );

  const items: LearnerTopologyOption[] = names.map((name) => {
    const fromView = data.views[name];
    return {
      name,
      riskId: fromView?.risk_id ?? 0,
      riskName: fromView?.risk_name ?? name,
      riskDescription: fromView?.risk_description ?? "—",
      triggerTime: fromView?.trigger_time ?? "—",
      attackRatio: fromView?.attack_ratio ?? 0,
      dominantLabel: fromView?.dominant_label ?? "—",
      flowCount: fromView?.host?.flow_count ?? fromView?.endpoint?.flow_count,
    };
  });

  return items.sort(
    (a, b) => b.attackRatio - a.attackRatio || a.name.localeCompare(b.name),
  );
}

function EventCardInfoItem({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-1.5 last:mb-0">
      <div className="text-[10px] leading-tight text-[#8c8c8c]">{label}</div>
      <div className="text-[11px] leading-[16px] text-[#333]">{children}</div>
    </div>
  );
}

/** 事件视角 — 学习器网络拓扑网格 */
export function LearnerInternalTopologyPanel({
  data,
  onRiskClick,
  emptyHint,
}: Props) {
  const sortedOptions = useMemo(() => {
    if (!data) return [] as LearnerTopologyOption[];
    return buildSortedLearnerOptions(data);
  }, [data]);

  if (!data) {
    return (
      <Empty
        description={
          emptyHint ??
          "暂无学习器拓扑数据（build-debug-1908）。请点「重置」清空触发时段，或确认 /api/risk/events/topology 返回 learners/views 非空。"
        }
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] py-10"
      />
    );
  }

  const learnerNames = data.learners ?? [];
  const viewCount = Object.keys(data.views ?? {}).length;
  const missingViews = learnerNames.filter((name) => !data.views[name]);
  if (sortedOptions.length === 0 && (learnerNames.length > 0 || viewCount > 0)) {
    return (
      <Empty
        description={`渲染后为 0 项（learners=${learnerNames.length}, views=${viewCount}, 缺失views=${missingViews.length}），请检查前端过滤逻辑与后端键名一致性。`}
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] py-10"
      />
    );
  }

  if (sortedOptions.length === 0) {
    return (
      <Empty
        description={
          emptyHint ??
          `暂无学习器拓扑数据（build-debug-1908，learners=${learnerNames.length}，views=${viewCount}）。请点「重置」清空触发时段，或确认 /api/risk/events/topology 返回 learners/views 非空。`
        }
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] py-10"
      />
    );
  }

  return (
    <div className="space-y-3 pb-2">

      <Row gutter={[8, 8]}>
        {sortedOptions.map((option) => {
          const gridView = data.views[option.name];
          if (!gridView) return null;
          const itemFlowCount =
            gridView.host?.flow_count ?? gridView.endpoint?.flow_count;
          const itemAttackPct = `${(gridView.attack_ratio * 100).toFixed(2)}%`;
          const itemDominant = gridView.dominant_label || option.dominantLabel || "—";
          const metaText = `攻击 ${itemAttackPct} · ${itemDominant}${
            itemFlowCount != null ? ` · ${itemFlowCount.toLocaleString()} 流` : ""
          }`;

          return (
            <Col key={`learner-topology-grid-${option.name}`} xs={24} md={12}>
              <Card
                size="small"
                className="risk-event-topology-card"
                title={
                  <div className="flex items-center justify-between gap-2">
                    <Text
                      ellipsis={{ tooltip: option.riskName }}
                      className="min-w-0 flex-1 text-[11px]"
                    >
                      {option.riskName}
                    </Text>
                    <Button
                      type="link"
                      size="small"
                      className="!h-auto shrink-0 !p-0 text-[11px]"
                      disabled={option.riskId <= 0}
                      onClick={() => {
                        if (option.riskId > 0) {
                          onRiskClick?.(option.riskId);
                        }
                      }}
                    >
                      查看详情
                    </Button>
                  </div>
                }
                styles={{
                  header: { minHeight: 36, padding: "4px 8px" },
                  body: { padding: "8px 8px 4px" },
                }}
              >
                 <EventCardInfoItem label="">
                  {option.triggerTime}
                </EventCardInfoItem>
                   <EventCardInfoItem label="">
                  <span
                    className="line-clamp-2 text-[11px] leading-[16px]"
                    title={option.riskDescription}
                  >
                    {option.riskDescription}
                  </span>
                </EventCardInfoItem>
                <Text
                  type="secondary"
                  ellipsis={{ tooltip: metaText }}
                  className="mb-1 mt-0.5 block text-[10px] leading-tight"
                >
                  {metaText}
                </Text>
                <ChartPaneErrorBoundary title="拓扑图">
                  <TopologyChartPane
                    title=" "
                    hostGraph={gridView.host}
                    endpointGraph={gridView.endpoint}
                    viewIsBenign={gridView.is_benign}
                    repulsion={TOPOLOGY_REPULSION}
                    minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                    chartHeight={GRID_CHART_HEIGHT}
                   
                  />
                </ChartPaneErrorBoundary>
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}
