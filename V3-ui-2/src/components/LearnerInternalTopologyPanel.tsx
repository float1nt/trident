import { useMemo } from "react";
import { Card, Col, Empty, Row, Typography } from "antd";
import {
  GRID_CHART_HEIGHT,
  TopologyChartPane,
} from "@/components/NetworkTopologyPanel";
import type {
  LearnerNetworkTopologyJson,
  LearnerTopologyOption,
} from "@/types/learnerTopology";

const { Text, Paragraph } = Typography;

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
      attackRatio: fromView?.attack_ratio ?? 0,
      dominantLabel: fromView?.dominant_label ?? "—",
      flowCount: fromView?.host?.flow_count ?? fromView?.endpoint?.flow_count,
    };
  });

  return items.sort(
    (a, b) => b.attackRatio - a.attackRatio || a.name.localeCompare(b.name),
  );
}

/** 事件视角 — 学习器网络拓扑网格（点击进入风险详情） */
export function LearnerInternalTopologyPanel({ data, onRiskClick }: Props) {
  const sortedOptions = useMemo(() => {
    if (!data) return [] as LearnerTopologyOption[];
    return buildSortedLearnerOptions(data);
  }, [data]);

  if (!data || sortedOptions.length === 0) {
    return (
      <Empty
        description="暂无学习器拓扑数据，请调整筛选条件后重试。"
        className="rounded-lg border border-dashed border-[#d9e4fa] bg-[#f6faff] py-10"
      />
    );
  }

  return (
    <div className="space-y-3">
      <Paragraph type="secondary" className="!mb-0 text-xs">
        展示全部风险事件拓扑（左 IP / 右 IP:端口），绿=良性、红=攻击。点击卡片查看详情。
      </Paragraph>

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
          const cardTitle = option.riskName || option.name;

          return (
            <Col key={`learner-topology-grid-${option.name}`} xs={24} sm={12} xl={6}>
              <Card
                size="small"
                hoverable
                className="risk-event-topology-card"
                title={
                  <Text ellipsis={{ tooltip: cardTitle }} className="text-[11px]">
                    {cardTitle}
                  </Text>
                }
                styles={{
                  header: { minHeight: 36, padding: "4px 8px" },
                  body: { padding: 4 },
                }}
                onClick={() => {
                  if (option.riskId > 0) {
                    onRiskClick?.(option.riskId);
                  }
                }}
              >
                <Text
                  type="secondary"
                  ellipsis={{ tooltip: metaText }}
                  className="mb-1 block text-[10px] leading-tight"
                >
                  {metaText}
                </Text>
                <Row gutter={4} className="pointer-events-none">
                  <Col span={12}>
                    <TopologyChartPane
                      title="IP"
                      graph={gridView.host}
                      viewIsBenign={null}
                      repulsion={TOPOLOGY_REPULSION}
                      minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                      chartHeight={GRID_CHART_HEIGHT}
                      compact
                    />
                  </Col>
                  <Col span={12}>
                    <TopologyChartPane
                      title="端口"
                      graph={gridView.endpoint}
                      viewIsBenign={null}
                      repulsion={TOPOLOGY_REPULSION}
                      minEdgeFlows={TOPOLOGY_MIN_EDGE_FLOWS}
                      chartHeight={GRID_CHART_HEIGHT}
                      compact
                    />
                  </Col>
                </Row>
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}
