import { useMemo, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Tag } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import {
  getMockProtocolDistribution,
  getMockRiskById,
} from "@/mock/riskTasks";
import {
  CHART_TEXT_PRIMARY,
  CHART_TEXT_SECONDARY,
} from "@/modules/overview/theme/notionTheme";

const PROTOCOL_COLORS = [
  "#4368f0",
  "#52c41a",
  "#fa8c16",
  "#722ed1",
  "#1777FF",
  "#faad14",
  "#ff4d4f",
  "#8c8c8c",
];

function InfoItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-4 last:mb-0">
      <div className="text-[12px] text-[#8c8c8c] mb-1">{label}</div>
      <div className="text-[14px] text-[#333] leading-[22px] break-words">
        {children}
      </div>
    </div>
  );
}

/** 风险详情页 */
export default function RiskDetailPlaceholder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const riskId = searchParams.get("id");
  const risk = riskId ? getMockRiskById(Number(riskId)) : undefined;

  const protocolDistribution = useMemo(
    () => (riskId ? getMockProtocolDistribution(Number(riskId)) : []),
    [riskId]
  );

  const protocolPieOption = useMemo(() => {
    const total = protocolDistribution.reduce((sum, item) => sum + item.value, 0);

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (params: { name?: string; value?: number }) => {
          const name = params.name || "-";
          const value = Number(params.value || 0);
          const ratio = total > 0 ? (value / total) * 100 : 0;
          return `${name}<br/>流量占比: ${ratio.toFixed(1)}%<br/>会话数: ${value}`;
        },
      },
      legend: {
        bottom: 0,
        textStyle: { color: CHART_TEXT_SECONDARY },
      },
      series: [
        {
          type: "pie",
          radius: ["42%", "68%"],
          center: ["50%", "45%"],
          label: {
            color: CHART_TEXT_PRIMARY,
            formatter: "{b}: {d}%",
          },
          data: protocolDistribution.map((item, index) => ({
            name: item.name,
            value: item.value,
            itemStyle: {
              color: PROTOCOL_COLORS[index % PROTOCOL_COLORS.length],
            },
          })),
        },
      ],
    };
  }, [protocolDistribution]);

  const featureTags = risk?.features
    ? risk.features.split("、").map((item) => item.trim()).filter(Boolean)
    : [];

  return (
    <div className="bg-[#f6faff]  h-full w-full rounded-[8px]">
      <div className=" rounded-[8px] p-[16px] min-h-full shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        {/* <Button
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate("/risk")}
          className="mb-2 pl-0"
        >
          返回列表
        </Button> */}

        {!risk ? (
          <p className="text-[#666] text-sm">
            {riskId ? `未找到风险 ID：${riskId}` : "未指定风险 ID"}
          </p>
        ) : (
          <>
            <div className="rounded-[8px] border border-[#e8eaed] bg-[#fff] p-[16px] mb-[16px]">
              <div className="grid grid-cols-3 gap-x-[24px] gap-y-[8px]">
                <div>
                  <InfoItem label="风险主体（IP）">
                    <span className="font-medium">{risk.subjectIp}</span>
                  </InfoItem>
                  <InfoItem label="触发时间">{risk.triggerTime}</InfoItem>
                </div>
                <div>
                  <InfoItem label="风险名称">
                    <Tag color="processing" className="!m-0">
                      {risk.name}
                    </Tag>
                  </InfoItem>
                  <InfoItem label="风险说明">{risk.description}</InfoItem>
                </div>
                <div>
                  <InfoItem label="风险特征">
                    {featureTags.length > 0 ? (
                      <div className="flex flex-wrap gap-[8px]">
                        {featureTags.map((tag) => (
                          <Tag key={tag} className="!m-0">
                            {tag}
                          </Tag>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[#8c8c8c]">-</span>
                    )}
                  </InfoItem>
                </div>
              </div>
            </div>

            <div className="rounded-[8px] border border-[#e8eaed] p-[16px] bg-[#fff]">
              <h3 className="text-[14px] font-medium text-[#333] mb-[12px]">
                协议分布占比
              </h3>
              <ReactECharts option={protocolPieOption} style={{ height: 320 }} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
