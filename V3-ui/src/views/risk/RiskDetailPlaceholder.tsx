import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { getMockRiskById } from "@/mock/riskTasks";

/** 风险详情占位页 */
export default function RiskDetailPlaceholder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const riskId = searchParams.get("id");
  const risk = riskId ? getMockRiskById(Number(riskId)) : undefined;

  return (
    <div className="bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <div className="bg-white rounded-[8px] p-8 min-h-[400px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
        <Button
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate("/risk")}
          className="mb-4 pl-0"
        >
          返回列表
        </Button>
        <h2 className="text-lg font-medium text-[#333] mb-2">
          风险详情（占位）
        </h2>
        {risk ? (
          <p className="text-[#666] text-sm mb-4">
            风险主体：{risk.subjectIp}，名称：{risk.name}
          </p>
        ) : (
          <p className="text-[#666] text-sm mb-4">
            {riskId ? `未找到风险 ID：${riskId}` : "未指定风险 ID"}
          </p>
        )}
        <p className="text-[#8c8c8c] text-sm">
          详情页功能开发中，后续将接入完整风险处置流程。
        </p>
      </div>
    </div>
  );
}
