import { Component, type ErrorInfo, useMemo, type ReactNode } from "react";
import { Button, Card, Col, Empty, Row, Spin, Typography } from "antd";
import { whiteTooltipProps } from "@/components/AppTooltip";
import OverflowTooltip from "@/components/OverflowTooltip";
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
  loading?: boolean;
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

/** 事件视角 — 学习器网络拓扑网格 */
export function LearnerInternalTopologyPanel({
  data,
  onRiskClick,
  emptyHint,
  loading = false,
}: Props) {
  const sortedOptions = useMemo(() => {
    if (!data) return [] as LearnerTopologyOption[];
    return buildSortedLearnerOptions(data);
  }, [data]);

  if (loading) {
    return (
      <div className="flex min-h-[200px] items-center justify-center rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] py-10">
        <Spin />
      </div>
    );
  }

  if (!data) {
    return (
      <Empty
        description={
          emptyHint ?? "暂无学习器拓扑数据，请点「重置」刷新数据。"
        }
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] py-10"
      />
    );
  }

  const learnerNames = data.learners ?? [];
  const viewCount = Object.keys(data.views ?? {}).length;
  if (sortedOptions.length === 0 && (learnerNames.length > 0 || viewCount > 0)) {
    const missingViews = learnerNames.filter((name) => !data.views[name]);
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
          emptyHint ?? "当前筛选条件下暂无学习器拓扑数据"
        }
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] h-[calc(100vh-330px)] py-10"
      />
    );
  }

  return (
    <div className="space-y-3 pb-2">
      <Row gutter={[8, 8]}>
        {sortedOptions.map((option) => {
          const gridView = data.views[option.name];
          if (!gridView) return null;
          return (
            <Col key={`learner-topology-grid-${option.name}`} xs={24} md={12}>
              <Card
                size="small"
                className="risk-event-topology-card"
                title={
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <Text
                        ellipsis={{
                          tooltip: {
                            title: option.riskName,
                            ...whiteTooltipProps,
                          },
                        }}
                        className="min-w-0 flex-1 text-[16px]"
                      >
                        {option.riskName}
                      </Text>
                      <Button
                        type="link"
                       
                        className="!h-auto shrink-0 !p-0 text-[16px]"
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
                    <div className="mt-1 flex min-w-0 items-center gap-2 text-[11px] font-normal leading-[16px]">
                      <span className="shrink-0 whitespace-nowrap font-normal text-[#8c8c8c]">
                        [{option.triggerTime}]
                      </span>
                      <OverflowTooltip title={option.riskDescription}>
                        <span className="block min-w-0 flex-1 truncate font-normal text-[#8c8c8c]">
                          {option.riskDescription}
                        </span>
                      </OverflowTooltip>
                    </div>
                  </div>
                }
                styles={{
                  header: { minHeight: 36, padding: "4px 8px" },
                  body: { padding: "8px 8px 4px" },
                }}
              >
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
