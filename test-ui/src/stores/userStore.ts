import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { getCurrentUser } from "@/api/services/AuthService";

interface UserInfo {
    companyName: string;
    username: string;
    /** 接口字段，顶栏等展示优先于 username */
    nickname: string;
}

interface UserState {
    userInfo: UserInfo;
    getCompanyName: () => string;
    getUsername: () => string;
    /** 顶栏账号展示：nickname → username → companyName */
    getDisplayName: () => string;
    setUserInfo: (userInfo: Partial<UserInfo>) => void;
    clearUserInfo: () => void;
    fetchUserInfo: () => Promise<void>;
}

export const useUserStore = create<UserState>()(
    immer((set, get) => ({
        userInfo: {
            companyName: "石犀科技",
            username: "admin",
            nickname: "",
        },
        getCompanyName: () => get().userInfo.companyName,
        getUsername: () => get().userInfo.username,
        getDisplayName: () => {
            const { nickname, username, companyName } = get().userInfo;
            const n = (nickname || "").trim();
            const u = (username || "").trim();
            const c = (companyName || "").trim();
            return n || u || c || "石犀科技";
        },
        setUserInfo: (userInfo: Partial<UserInfo>) => {
            set((state) => {
                state.userInfo = { ...state.userInfo, ...userInfo };
            });
        },
        clearUserInfo: () => {
            set((state) => {
                state.userInfo = {
                    companyName: "石犀科技",
                    username: "admin",
                    nickname: "",
                };
            });
        },
        fetchUserInfo: async () => {
            const token = localStorage.getItem("token");
            if (!token) {
                return;
            }

            try {
                const response = await getCurrentUser();
                if (response.data && response.data.user) {
                    const { username, nickname } = response.data.user;
                    const uname = username ?? "";
                    const nname = nickname ?? "";
                    get().setUserInfo({
                        username: uname,
                        nickname: nname,
                        companyName: nname || uname || "石犀科技",
                    });
                }
            } catch (error) {
                console.error("获取用户信息失败:", error);
                // 如果获取失败，可能是 token 过期，清除本地存储
                localStorage.removeItem("token");
                localStorage.removeItem("userInfo");
            }
        },
    }))
);

