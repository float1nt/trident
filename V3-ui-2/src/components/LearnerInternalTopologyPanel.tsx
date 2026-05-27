import { useMemo, type ReactNode } from "react";
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
};

function buildSortedLearnerOptions(
  data: LearnerNetworkTopologyJson,
): LearnerTopologyOption[] {
  const names = data.learners?.length
    ? data.learners.filter((k) => data.views[k])
    : Object.keys(data.views);

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
export function LearnerInternalTopologyPanel({ data, onRiskClick }: Props) {
  const sortedOptions = useMemo(() => {
    if (!data) return [] as LearnerTopologyOption[];
    return buildSortedLearnerOptions(data);
  }, [data]);

  if (!data || sortedOptions.length === 0) {
    return (
      <Empty
        description="暂无学习器拓扑数据，请调整筛选条件后重试。"
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] h-[calc(100vh-325px)] pt-[20px] !m-0"
      />
    );
  }

  return (
    <div className="space-y-3">

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
            <Col key={`learner-topology-grid-${option.name}`} xs={24} sm={12} xl={6}>
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
                <TopologyChartPane
                  hostGraph={gridView.host}
                  endpointGraph={gridView.endpoint}
                  viewIsBenign={null}
                  repulsion={TOPOLOGY_REPULSION}
                  minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                  chartHeight={GRID_CHART_HEIGHT}
                  compact
                />
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}
