import { Tooltip } from "antd";
import { Status } from "@/api/types";

interface TaskDotProps {
  status: Status;
  taskName?: string;
  progress?: string;
}

const TaskDot = ({ status, taskName, progress }: TaskDotProps) => {
  const getStatusColor = () => {
    switch (status) {
      case Status.IDLE:
        return "bg-gray-300";
      case Status.RUNNING:
        return "bg-blue-500 animate-pulse";
      case Status.COMPLETED:
        return "bg-green-500";
      case Status.FAILED:
        return "bg-red-500";
      case Status.CANCELLING:
      case Status.CANCELLED:
        return "bg-yellow-400";
      default:
        return "bg-gray-300";
    }
  };

  const getStatusText = (s: Status): string => {
    switch (s) {
      case Status.IDLE:
        return "未启动";
      case Status.RUNNING:
        return "进行中";
      case Status.COMPLETED:
        return "已完成";
      case Status.FAILED:
        return "失败";
      case Status.CANCELLING:
        return "取消中";
      case Status.CANCELLED:
        return "已取消";
      default:
        return "未启动";
    }
  };

  const statusText = getStatusText(status);
  let tooltipText = taskName ? `${taskName} (${statusText})` : statusText;
  if (progress) tooltipText += `\n${progress}`;

  return (
    <Tooltip title={tooltipText} mouseEnterDelay={0} mouseLeaveDelay={0}>
      <div
        className={`w-2 h-2 rounded-full ${getStatusColor()} cursor-pointer`}
      />
    </Tooltip>
  );
};

interface StepTitleProps {
  title: string;
  tasks?: Array<{
    id: string | number;
    status: Status;
    name?: string;
    progress?: string;
  }>;
  showTitle?: boolean;
  variant?: "default" | "table";
}

export const StepTitle = ({
  title,
  tasks = [],
  showTitle = true,
  variant = "default",
}: StepTitleProps) => {
  const isTable = variant === "table";
  const titleClass = isTable ? "text-center" : "text-base font-medium";
  const containerClass = isTable ? "flex flex-col items-center gap-2" : "gap-2";
  const dotsContainerClass = isTable
    ? "flex items-center justify-center gap-1"
    : "flex items-center gap-1";

  return (
    <div className={containerClass}>
      {showTitle && <span className={titleClass}>{title}</span>}
      {tasks.length > 0 && (
        <div className={dotsContainerClass}>
          {tasks.map((task, index) => (
            <TaskDot
              key={task.id || index}
              status={task.status}
              taskName={task.name}
              progress={task.progress}
            />
          ))}
        </div>
      )}
    </div>
  );
};
