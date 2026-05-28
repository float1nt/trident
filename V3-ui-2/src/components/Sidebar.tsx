import { useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import logoImg from "@/assets/top-svg/logo3.0.png";
import homeOff from "@/assets/svg/navigation-only-home-off.svg";
import homeOn from "@/assets/svg/navigation-only-home-on.svg";
import riskOff from "@/assets/svg/navigation-only-risk-off.svg";
import riskOn from "@/assets/svg/navigation-only-risk-on.svg";
import settingOff from "@/assets/svg/navigation-only-setting-off.svg";
import settingOn from "@/assets/svg/navigation-only-setting-on.svg";

type NavId =
  | "home"
  | "posture"
  | "property"
  | "user"
  | "audit"
  | "risk"
  | "governance"
  | "tactics"
  | "setting"
  | "lab";

const MENU: {
  id: NavId;
  label: string;
  path: string;
  off: string;
  on: string;
}[] = [
    { id: "home", label: "总览", path: "/", off: homeOff, on: homeOn },
    // { id: "posture", label: "态势", path: "/posture", off: postureOff, on: postureOn },
    // { id: "property", label: "资产", path: "/property", off: propertyOff, on: propertyOn },
    // { id: "user", label: "用户", path: "/user", off: userOff, on: userOn },
    // { id: "audit", label: "审计", path: "/audit", off: auditOff, on: auditOn },
    { id: "risk", label: "风险", path: "/risk", off: riskOff, on: riskOn },
    // { id: "governance", label: "治理", path: "/governance", off: governanceOff, on: governanceOn },
    // { id: "tactics", label: "策略", path: "/tactics", off: tacticsOff, on: tacticsOn },
    { id: "setting", label: "设置", path: "/setting", off: settingOff, on: settingOn },
    // { id: "lab", label: "实验室", path: "/lab", off: labOff, on: labOn },
  ];

function isHomePath(pathname: string): boolean {
  return pathname === "/" || pathname === "";
}

function pathMatchesMenu(pathname: string, item: (typeof MENU)[number]): boolean {
  if (item.id === "home") return isHomePath(pathname);
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}

const TEXT_IDLE = "#666666";
const TEXT_ACTIVE = "#333333";

const Sidebar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [hoveredId, setHoveredId] = useState<NavId | null>(null);

  const activeItem = MENU.find((item) => pathMatchesMenu(location.pathname, item)) ?? MENU[0];

  return (
    <aside className="w-[90px] min-w-[90px] h-screen flex-shrink-0 flex flex-col items-center bg-[#ECF2FF] border-r border-[#d9e4fa]">
      <button
        type="button"
        onClick={() => navigate("/")}
        className="w-[90px] flex items-center justify-center cursor-pointer border-0 bg-transparent p-0 shrink-0"
      >
        <img
          src={logoImg}
          alt=""
          className="w-[86px] h-[86px] mt-[2px]  mb-0 mx-[5px] object-contain select-none pointer-events-none"
        />
      </button>

      <nav className="mt-[8px] flex min-h-0 w-full flex-1 flex-col gap-[20px] overflow-y-auto overflow-x-hidden pb-3 pl-[6px] pt-[12px]">
        {MENU.map((item) => {
          const onAsset = activeItem.id === item.id || hoveredId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => navigate(item.path)}
              onMouseEnter={() => setHoveredId(item.id)}
              onMouseLeave={() => setHoveredId(null)}
              className={[
                "flex flex-row items-center justify-start gap-[4px] h-[34px] w-[84px] shrink-0 pl-3 pr-1.5 rounded-l-[25px] cursor-pointer border-0",
                "transition-[color,background-color] text-left font-medium",
                onAsset ? "bg-[#FFFFFF]" : "bg-transparent hover:bg-[#FFFFFF]",
                onAsset
                  ? [
                      "relative z-[1]",
                      "before:content-[''] before:pointer-events-none before:absolute before:-top-[12px] before:right-0 before:h-[12px] before:w-[12px] before:bg-transparent before:rounded-br-[12px] before:shadow-[5px_5px_0_5px_#ffffff] before:z-[1]",
                      "after:content-[''] after:pointer-events-none after:absolute after:-bottom-[12px] after:right-0 after:h-[12px] after:w-[12px] after:bg-transparent after:rounded-tr-[12px] after:shadow-[5px_-5px_0_5px_#ffffff] after:z-[1]",
                    ].join(" ")
                  : "",
              ]
                .filter(Boolean)
                .join(" ")}
              style={{ color: onAsset ? TEXT_ACTIVE : TEXT_IDLE }}
            >
              <img
                src={onAsset ? item.on : item.off}
                alt=""
                className="w-[20px] h-[20px] block pointer-events-none shrink-0"
                draggable={false}
              />
              <span className="text-[13px] leading-[18px] min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
                {item.label}
              </span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
};

export default Sidebar;
