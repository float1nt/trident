import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Fragment } from "react";
import { getMockTaskById } from "@/mock/riskTasks";

const COLOR_LINK = "#666666";
const COLOR_MUTED = "#A6A6A6";
const COLOR_CURRENT = "#333333";
const SEP_COLOR = "#D9D9D9";

/** 侧栏一级占位路由 title */
const SIDE_PLACEHOLDER: Record<string, string> = {
  posture: "态势",
  property: "资产",
  user: "用户",
  audit: "审计",
  risk: "风险",
  governance: "治理",
  tactics: "策略",
  setting: "设置",
  lab: "实验室",
};

type Crumb = { label: string; to?: string };

function buildCrumbs(pathname: string, taskId: string | null): Crumb[] {
  const path = pathname.replace(/\/$/, "") || "/";
  const segments = path === "/" ? [] : path.slice(1).split("/");
  const first = segments[0] ?? "";

  if (path === "/" || path === "") return [{ label: "首页" }];

  if (first === "risk") {
    if (segments[1] === "detail") {
      const task = taskId ? getMockTaskById(Number(taskId)) : undefined;
      return [
        { label: "风险", to: "/risk" },
        { label: task?.name || "任务详情" },
      ];
    }
    return [{ label: "风险" }];
  }

  const sideLabel = first ? SIDE_PLACEHOLDER[first] : undefined;
  if (sideLabel) return [{ label: sideLabel }];

  return [{ label: "首页", to: "/" }];
}

const BreadcrumbNav = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const crumbs = buildCrumbs(location.pathname, searchParams.get("id"));

  return (
    <nav className="flex items-center text-[12px] leading-[18px] min-w-0" aria-label="面包屑">
      {crumbs.map((crumb, i) => {
        const isCurrent = i === crumbs.length - 1;
        const typoClass = `text-[12px] leading-[18px]`;
        return (
          <Fragment key={`${crumb.label}-${i}`}>
            {i > 0 ? (
              <div
                className="shrink-0 w-[1.5px] h-[13px] mx-[14px] self-center mt-[2px]"
                style={{ backgroundColor: SEP_COLOR }}
                aria-hidden
              />
            ) : null}
            {crumb.to ? (
              <button
                type="button"
                onClick={() => navigate(crumb.to!)}
                className={`shrink-0 border-0 bg-transparent p-0 text-left cursor-pointer hover:opacity-80 transition-opacity ${typoClass}`}
                style={{ color: isCurrent ? COLOR_CURRENT : COLOR_LINK }}
              >
                {crumb.label}
              </button>
            ) : (
              <span
                className={`shrink-0 cursor-default ${typoClass}`}
                style={{ color: isCurrent ? COLOR_CURRENT : COLOR_MUTED }}
              >
                {crumb.label}
              </span>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
};

export default BreadcrumbNav;
