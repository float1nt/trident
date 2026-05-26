// import { useSearchParams } from "react-router-dom";
// import { getMockRiskById } from "@/mock/riskTasks";
// import "./RiskDetailPlaceholder.css";
import taskDetailIcon from "@/assets/蒙版组 152.png";

/** 风险任务详情占位页 */
export default function RiskDetailPlaceholder() {
  // const [searchParams] = useSearchParams();
  // const taskId = searchParams.get("id");
  // const task = taskId ? getMockTaskById(Number(taskId)) : undefined;

  return (
    <div className="h-full w-full rounded-[8px]">
      <div
        className="bg-[#f6faff] h-[96px] rounded-[8px]"
      >
        <div className="pl-[12px]  pt-[7px] flex items-center gap-[12px]">
          <img
            src={taskDetailIcon}
            alt=""
            className="w-[82px] h-[82px] object-contain shrink-0"
            aria-hidden
          />
          <h2 className="text-lg font-medium text-[#333] m-0">
            任务详情
          </h2>
        </div>
      </div>
      <div className="bg-[#fff] h-[16px] w-full " />

      <div className="bg-[#f6faff] h-full w-full rounded-[8px] p-[12px]" >
      （占位）
      </div>
    </div>
  );
}
