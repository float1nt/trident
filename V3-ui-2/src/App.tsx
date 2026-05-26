import { useEffect } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { Modal } from "antd";
import type { MenuProps } from "antd";
import Sidebar from "./components/Sidebar";
import AppHeader from "./components/AppHeader";
import { useUserStore } from "./stores";
import { logout } from "@/api/services/AuthService";
import { message } from "@/utils/message";

/**
 * 顶栏展示的账号文案：填非空则始终用该固定文案；留空则用接口/Store 的昵称 → 用户名 → 公司名占位。
 */
const HEADER_USER_DISPLAY_OVERRIDE = "ci测试-订阅";

function App() {
    const navigate = useNavigate();
    const location = useLocation();
    const displayNameFromStore = useUserStore((state) => state.getDisplayName());
    const headerUserLabel = HEADER_USER_DISPLAY_OVERRIDE.trim() || displayNameFromStore;
    const clearUserInfo = useUserStore((state) => state.clearUserInfo);
    const fetchUserInfo = useUserStore((state) => state.fetchUserInfo);

    useEffect(() => {
        const token = localStorage.getItem("token");
        if (location.pathname !== "/login" && token) {
            fetchUserInfo();
        }
    }, [location.pathname, fetchUserInfo]);

    const handleLogout = () => {
        Modal.confirm({
            title: "提示",
            content: "确定要退出登录吗？",
            okText: "确定",
            cancelText: "取消",
            onOk: async () => {
                try {
                    await logout();
                } catch (error) {
                    console.error("退出登录接口调用失败:", error);
                }

                localStorage.removeItem("token");
                localStorage.removeItem("userInfo");
                clearUserInfo();

                message.success("已退出登录");
                navigate("/login");
            },
        });
    };

    const menuItems: MenuProps["items"] = [
        {
            key: "logout",
            label: "退出登录",
            onClick: handleLogout,
        },
    ];

    return (
        <div className="min-h-screen bg-[#f1f5fe] flex min-w-[1024px]">
            <Sidebar />

            <div className="flex-1 flex min-h-0 min-w-[600px] flex-col overflow-hidden rounded-tl-[20px] bg-white">
                <AppHeader userName={headerUserLabel} dropdownItems={menuItems} />

                <div className="flex-1 overflow-auto p-[16px]">
                  <Outlet />
                </div>
            </div>
        </div>
    );
}

export default App;
