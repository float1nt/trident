import request, { type ResponseData } from "@/utils/request";

// 登录请求参数
export interface LoginParams {
    username: string;
    password: string;
}

// 登录响应数据
export interface LoginResponse {
    token: string;
    user: {
        id: number;
        username: string;
        email?: string;
        nickname?: string;
    };
}

// 获取当前用户信息响应数据
export interface CurrentUserResponse {
    user: {
        id: number;
        username: string;
        email?: string | null;
        nickname?: string | null;
    };
}

export class AuthService {
    // 用户登录
    static login(data: LoginParams): Promise<ResponseData<LoginResponse>> {
        return request<LoginResponse>({
            url: "/auth/login",
            method: "post",
            data,
        });
    }

    // 获取当前用户信息
    static getCurrentUser(): Promise<ResponseData<CurrentUserResponse>> {
        return request<CurrentUserResponse>({
            url: "/auth/me",
            method: "get",
        });
    }

    // 退出登录
    static logout(): Promise<ResponseData<null>> {
        return request<null>({
            url: "/auth/logout",
            method: "post",
        });
    }
}

// 向后兼容：导出函数式 API
export const login = (data: LoginParams): Promise<ResponseData<LoginResponse>> =>
    AuthService.login(data);

export const getCurrentUser = (): Promise<ResponseData<CurrentUserResponse>> =>
    AuthService.getCurrentUser();

export const logout = (): Promise<ResponseData<null>> => AuthService.logout();

