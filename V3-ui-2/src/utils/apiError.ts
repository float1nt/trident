import { AxiosError } from "axios";

/** 请求层已展示过 toast 的错误 */
export class ApiError extends Error {
  readonly toastShown: boolean;

  constructor(message: string, toastShown = true) {
    super(message);
    this.name = "ApiError";
    this.toastShown = toastShown;
  }
}

/** 从任意错误对象提取可展示文案 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof AxiosError) {
    const data = error.response?.data as
      | { message?: string; detail?: string | { message?: string }; data?: string | { message?: string } }
      | undefined;
    if (typeof data?.message === "string" && data.message) {
      return data.message;
    }
    if (typeof data?.detail === "string" && data.detail) {
      return data.detail;
    }
    if (data?.detail && typeof data.detail === "object" && data.detail.message) {
      return data.detail.message;
    }
    if (typeof data?.data === "string" && data.data) {
      return data.data;
    }
    if (data?.data && typeof data.data === "object" && "message" in data.data) {
      const msg = (data.data as { message?: string }).message;
      if (msg) return msg;
    }
    if (error.message) {
      return error.message;
    }
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "请求失败";
}

/** 全局拦截器或业务层已弹出错误 toast */
export function isErrorToastShown(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.toastShown;
  }
  return error instanceof AxiosError;
}
