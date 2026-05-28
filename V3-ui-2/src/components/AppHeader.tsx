import { Dropdown } from "antd";
import OverflowTooltip from "@/components/OverflowTooltip";
import type { MenuProps } from "antd";
import BreadcrumbNav from "@/components/BreadcrumbNav";
import favicon from "@/assets/top-svg/l-favicon.svg";
import nightMode from "@/assets/top-svg/l-night-mode.svg";
import infoIcon from "@/assets/top-svg/l-info.svg";
import assignmentIcon from "@/assets/top-svg/l-assignment.svg";
import chevronDown from "@/assets/top-svg/l-direction1-down.svg";
import avatarImg from "@/assets/top-svg/avatar.png";

const PLATFORM_TITLE = "数据流动治理平台";
/** 静态展示，与稿一致 */
const VERSION_TEXT = "v-demo";

type AppHeaderProps = {
  userName: string;
  dropdownItems: MenuProps["items"];
};

/** 顶部圆点（消息 / 任务），静态展示 */
function IconWithDot({ src }: { src: string }) {
  return (
    <div className="relative shrink-0 w-6 h-6 flex items-center justify-center" aria-hidden>
      <img src={src} alt="" className="w-6 h-6 block" />
      <span className="absolute -top-[0.5px] -right-[3px] w-[6.4px] h-[6.4px] rounded-full bg-[#1777FF] box-content border-[1px] border-solid border-white pointer-events-none" />
    </div>
  );
}

export default function AppHeader({ userName, dropdownItems }: AppHeaderProps) {
  return (
    <header className="flex h-[53px] shrink-0 items-center justify-between overflow-hidden rounded-tl-[20px] border-b border-[#e8eaed] bg-white pl-4 pr-10 text-[#333]">
      {/* 左侧：与 Vue navbar .titles 一致 — 总览标 + 平台名 + 竖线 + 面包屑 */}
      <div className="flex items-center min-w-0 -ml-4">
        <img src={favicon} alt="" className="w-[18px] h-[18px] shrink-0 ml-[18px] mr-2" />
        <span
          className="font-['PingFang_SC'] text-[14px] leading-[18px] text-[#333333] whitespace-nowrap shrink-0 tracking-[0.3px]"
        >
          {PLATFORM_TITLE}
        </span>
        <span className="shrink-0 mx-[12px] text-[12px] leading-[18px] select-none text-[#D9D9D9]" aria-hidden>|</span>
        <div className="min-w-0">
          <BreadcrumbNav />
        </div>
      </div>

      {/* 右侧：版本号 + 夜间 + 通知 + 任务 + 用户（与 Vue 间距 ml-20≈） */}
      <div className="flex items-center shrink-0 gap-0">
        <div
          className="flex items-center rounded-[8px] px-[6px] h-6 text-[14px] text-[#7c88b1] whitespace-nowrap cursor-default line-height-[24px]"
          style={{ border: "1px solid #7c88b1" }}
        >
          <span className="mr-1">版本号</span>
          <span>{VERSION_TEXT}</span>
        </div>

        <button type="button" className="ml-5 p-0 border-0 bg-transparent cursor-default shrink-0" aria-hidden>
          <img src={nightMode} alt="" className="w-6 h-6 block" />
        </button>

        <div className="ml-5 flex items-center">
          <IconWithDot src={infoIcon} />
        </div>
        <div className="ml-5 flex items-center">
          <IconWithDot src={assignmentIcon} />
        </div>

        <div className="w-[26px] shrink-0" aria-hidden />

        <Dropdown menu={{ items: dropdownItems }} trigger={["click"]}>
          <div className="flex items-center cursor-pointer group">
            <div className="w-8 h-8 rounded-full overflow-hidden border border-[#e0e8f5] shrink-0 bg-[#f5f7fa]">
              <img src={avatarImg} alt="" className="w-full h-full object-cover block" />
            </div>
            <OverflowTooltip title={userName}>
              <span className="ml-4 block min-w-0 max-w-[200px] truncate text-base font-normal text-[#5a607f]">
                {userName}
              </span>
            </OverflowTooltip>
            <img
              src={chevronDown}
              alt=""
              className="w-5 h-5 ml-[18px] shrink-0 block opacity-70 group-hover:opacity-100"
            />
          </div>
        </Dropdown>
      </div>
    </header>
  );
}
