import { useCallback, useState } from "react";
import { message } from "@/utils/message";
import { getErrorMessage, isErrorToastShown } from "@/utils/apiError";

export const API_SUCCESS_MESSAGE = "数据已更新！";

export interface UseApiOptions {
  /** 默认「数据已更新！」；传 false 关闭成功提示 */
  successMessage?: string | false;
  /** 初始 loading 状态 */
  initialLoading?: boolean;
}

function resolveSuccessMessage(options: UseApiOptions): string | false {
  if (options.successMessage === false) {
    return false;
  }
  if (typeof options.successMessage === "string") {
    return options.successMessage;
  }
  return API_SUCCESS_MESSAGE;
}

/**
 * 封装接口调用：区域 loading、成功 toast、失败 toast（与 request 拦截器配合，避免重复提示）
 */
export function useApi(options: UseApiOptions = {}) {
  const [loading, setLoading] = useState(options.initialLoading ?? false);
  const successMessage = resolveSuccessMessage(options);

  const run = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      setLoading(true);
      try {
        const result = await fn();
        if (successMessage !== false) {
          message.success(successMessage);
        }
        return result;
      } catch (error) {
        console.error(error);
        if (!isErrorToastShown(error)) {
          message.error(getErrorMessage(error));
        }
        return undefined;
      } finally {
        setLoading(false);
      }
    },
    [successMessage],
  );

  return { loading, setLoading, run };
}

/**
 * 无 loading 状态的单次调用（如后台静默拉取用户信息）
 */
export async function runApi<T>(
  fn: () => Promise<T>,
  options: UseApiOptions = {},
): Promise<T | undefined> {
  const successMessage = resolveSuccessMessage(options);
  try {
    const result = await fn();
    if (successMessage !== false) {
      message.success(successMessage);
    }
    return result;
  } catch (error) {
    console.error(error);
    if (!isErrorToastShown(error)) {
      message.error(getErrorMessage(error));
    }
    return undefined;
  }
}
