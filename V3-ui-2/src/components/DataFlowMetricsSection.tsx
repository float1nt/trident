import { ReloadOutlined } from "@ant-design/icons";
import { Select, Button } from "antd";
import metricsSectionBg from "@/assets/编组 58@2x.png";
import titleIcon from "@/assets/路径.png";
import metricIcon1 from "@/assets/总览/生成特定背景图-3-2.png";
import metricIcon2 from "@/assets/总览/生成特定背景图-4-2.png";
import metricIcon3 from "@/assets/总览/生成特定背景图-5-2.png";
import metricIcon4 from "@/assets/总览/生成特定背景图-6-2.png";
import type { OverviewMetrics, TimeRange } from "@/api/services/OverviewService";
import {
  formatMetricCount,
  formatTotalTrafficBytes,
} from "@/utils/formatTotalTraffic";
import "./DataFlowMetricsSection.css";

type MetricItem = {
  label: string;
  key: keyof OverviewMetrics;
  icon: string;
};

const METRIC_DEFS: MetricItem[] = [
  { label: "总流量", key: "totalTraffic", icon: metricIcon1 },
  { label: "协议数", key: "protocolCount", icon: metricIcon2 },
  { label: "风险类型数", key: "riskTypeCount", icon: metricIcon3 },
  { label: "风险 IP 数", key: "suspiciousIpCount", icon: metricIcon4 },
];

const TIME_RANGE_OPTIONS = [
  { value: "24h", label: "近24小时" },
  { value: "7d", label: "近7天" },
  { value: "30d", label: "近一个月" },
];

function DataFlowTitleIcon() {
  return (
    <span className="data-flow-metrics__title-icon" aria-hidden>
      <img src={titleIcon} alt="" className="data-flow-metrics__title-icon-img" />
    </span>
  );
}

type Props = {
  timeRange: TimeRange;
  metrics: OverviewMetrics;
  onTimeRangeChange: (value: TimeRange) => void;
  onRefresh: () => void;
};

function formatMetricValue(
  key: keyof OverviewMetrics,
  raw: number,
): { value: string; unit: string } {
  if (key === "totalTraffic") {
    return formatTotalTrafficBytes(raw);
  }
  return formatMetricCount(raw);
}

function renderMetricValue(key: keyof OverviewMetrics, raw: number) {
  const { value, unit } = formatMetricValue(key, raw);
  return (
    <span className="data-flow-metrics__card-value-row">
      <span className="data-flow-metrics__card-value">{value}</span>
      <span className="data-flow-metrics__card-unit">{unit}</span>
    </span>
  );
}

export default function DataFlowMetricsSection({
  timeRange,
  metrics,
  onTimeRangeChange,
  onRefresh,
}: Props) {
  return (
    <section
      className="data-flow-metrics"
      style={{ backgroundImage: `url(${metricsSectionBg})` }}
    >
      <div className="data-flow-metrics__title-row">
        <DataFlowTitleIcon />
        <h2 className="data-flow-metrics__title-text">总览</h2>
      </div>

      <div className="data-flow-metrics__content-row">
        <div className="data-flow-metrics__cards">
          {METRIC_DEFS.map((item) => (
            <div key={item.label} className="data-flow-metrics__card">
              <div className="data-flow-metrics__card-main">
                <span className="data-flow-metrics__card-label">{item.label}</span>
                {renderMetricValue(item.key, metrics[item.key])}
              </div>
              <img
                src={item.icon}
                alt=""
                className="data-flow-metrics__card-icon"
                aria-hidden
              />
            </div>
          ))}
        </div>

        <div className="data-flow-metrics__filters">
          <Select
            className="data-flow-metrics__select"
            value={timeRange}
            options={TIME_RANGE_OPTIONS}
            onChange={(value) => onTimeRangeChange(value as TimeRange)}
            popupMatchSelectWidth={false}
          />
          <Button
            type="text"
            className="data-flow-metrics__refresh"
            icon={<ReloadOutlined />}
            onClick={onRefresh}
            aria-label="刷新"
          />
        </div>
      </div>
    </section>
  );
}
