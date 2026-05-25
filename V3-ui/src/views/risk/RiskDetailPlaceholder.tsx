import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { getMockTaskById } from "@/mock/riskTasks";

/** 风险任务详情占位页 */
export default function RiskDetailPlaceholder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("id");
  const task = taskId ? getMockTaskById(Number(taskId)) : undefined;

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
          任务详情（占位）
        </h2>
        {task ? (
          <p className="text-[#666] text-sm mb-4">
            任务 ID：{task.id}，名称：{task.name}
          </p>
        ) : (
          <p className="text-[#666] text-sm mb-4">
            {taskId ? `未找到任务 ID：${taskId}` : "未指定任务 ID"}
          </p>
        )}
        <p className="text-[#8c8c8c] text-sm">
          详情页功能开发中，后续将接入完整标注流程。
        </p>
      </div>
    </div>
  );
}
