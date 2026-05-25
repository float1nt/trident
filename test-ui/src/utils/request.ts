import axios, {
  AxiosInstance,
  InternalAxiosRequestConfig,
  AxiosResponse,
  AxiosError,
  AxiosRequestConfig,
} from "axios";
import { message } from "./message";

// 响应数据类型
export interface ResponseData<T = any> {
  code?: number;
  message?: string;
  data?: T;
}

/** vLLM 未就绪时的特殊错误码，前端展示 warning 而非 error */
const VLLM_NOT_READY_ERROR_CODE = "VLLM_NOT_READY";

/** 已有任务在跑时的特殊错误码，前端展示 warning 而非 error */
const TASK_ALREADY_RUNNING_ERROR_CODE = "TASK_ALREADY_RUNNING";

// 创建 axios 实例
const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
  timeout: 15000,
  headers: {
    "Content-Type": "application/json;charset=UTF-8",
  },
});

// 请求拦截器
service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 从 localStorage 读取 token
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    if (config.data instanceof FormData) {
      if (config.headers) {
        delete config.headers["Content-Type"];
      }
    }

    // 确保 timeout 配置被正确应用
    // 如果请求配置中指定了 timeout，则使用它（axios 会自动覆盖实例的默认 timeout）
    // 这里显式确保 timeout 被正确设置
    if (config.timeout === undefined || config.timeout === null) {
      // 如果没有指定 timeout，使用实例的默认值（15000ms）
      // 但这种情况不应该发生，因为我们在 request 函数中已经处理了
    }

    return config;
  },
  (error: AxiosError) => {
    console.error("请求错误:", error);
    return Promise.reject(error);
  }
);

// 响应拦截器
service.interceptors.response.use(
  (response: AxiosResponse<ResponseData | Blob>) => {
    if (response.data instanceof Blob) {
      return response.data;
    }

    const res = response.data as ResponseData;

    if (res.code && res.code !== 200 && res.code !== 201) {
      message.error(res.message || "请求失败");
      return Promise.reject(new Error(res.message || "请求失败"));
    }

    return res as any;
  },
  (error: AxiosError<ResponseData>) => {
    console.error("响应错误:", error);

    if (error.response) {
      const { status, data } = error.response;

      switch (status) {
        case 401:
          message.error("未授权，请重新登录");
          // 清除 token 并跳转到登录页
          localStorage.removeItem("token");
          localStorage.removeItem("userInfo");
          if (window.location.pathname !== "/login") {
            window.location.href = "/login";
          }
          break;
        case 403:
          message.error(data?.message || data?.data || "拒绝访问，权限不足");
          break;
        case 404:
          message.error("请求的资源不存在");
          break;
        case 400: {
          // 已有任务在跑：展示 warning 而非 error（参考 VLLM_NOT_READY）
          const dataAny = data as Record<string, any>;
          const taskAlreadyRunning =
            dataAny?.data?.errorCode === TASK_ALREADY_RUNNING_ERROR_CODE ||
            dataAny?.detail?.errorCode === TASK_ALREADY_RUNNING_ERROR_CODE;
          if (taskAlreadyRunning) {
            const msg =
              dataAny?.message ||
              dataAny?.detail?.message ||
              dataAny?.data?.message ||
              "检测到正在运行的任务，无法启动新任务";
            message.warning(msg);
          } else {
            message.error(
              dataAny?.message ||
                dataAny?.detail ||
                (typeof dataAny?.data === "string" ? dataAny.data : null) ||
                `请求失败: ${status}`
            );
          }
          break;
        }
        case 500:
          const errorMessage =
            data?.message ||
            (typeof data?.data === "string" ? data.data : null) ||
            data?.data?.message ||
            data?.data?.error ||
            "服务器内部错误";
          if (data?.data?.errors) {
            const errors = data.data.errors;
            const errorDetails: string[] = [];
            if (errors.classificationError) {
              errorDetails.push(`分类服务错误: ${errors.classificationError}`);
            }
            if (errors.clusterError) {
              errorDetails.push(`聚类服务错误: ${errors.clusterError}`);
            }
            if (errors.exportError) {
              errorDetails.push(`导出错误: ${errors.exportError}`);
            }
            if (errors.analyzeError) {
              errorDetails.push(`分析服务错误: ${errors.analyzeError}`);
            }
            if (errorDetails.length > 0) {
              message.error(`${errorMessage} - ${errorDetails.join("; ")}`);
            } else {
              message.error(errorMessage);
            }
          } else {
            message.error(errorMessage);
          }
          break;
        case 503:
          // vLLM 未就绪：展示 warning 而非 error
          if (data?.data?.errorCode === VLLM_NOT_READY_ERROR_CODE) {
            message.warning(data?.message || "vLLM 服务未就绪，请确保服务已启动");
          } else {
            message.error(data?.message || "服务暂时不可用");
          }
          break;
        default:
          message.error(data?.message || `请求失败: ${status}`);
      }
    } else if (error.request) {
      message.error("网络错误，请检查网络连接");
    } else {
      message.error(error.message || "请求失败");
    }

    return Promise.reject(error);
  }
);

export default service;

// 请求配置接口
interface RequestConfig {
  url: string;
  method?: "get" | "post" | "put" | "delete" | "patch";
  params?: any;
  data?: any;
  responseType?: "blob" | "arraybuffer" | "document" | "json" | "text" | "stream";
  headers?: Record<string, string>;
  timeout?: number; // 请求超时时间（毫秒）
}

/**
 * 通用请求方法
 */
export function request<T = any>(config: RequestConfig): Promise<T> {
  // 确保 timeout 配置被正确传递
  // axios 会自动使用请求配置中的 timeout 覆盖实例的默认 timeout
  const axiosConfig: AxiosRequestConfig = {
    ...config,
    // 如果指定了 timeout，则使用它；否则使用实例的默认值（15000ms）
    timeout: config.timeout !== undefined ? config.timeout : undefined,
  };
  return service(axiosConfig);
}

/** GET 请求的可选配置 */
export interface GetRequestConfig {
  timeout?: number;
}

/**
 * GET 请求
 * @param url 请求地址
 * @param params 查询参数
 * @param config 可选配置（如 timeout，用于后端繁忙时的轮询场景）
 * @returns Promise<ResponseData<T>>
 */
export function get<T = any>(
  url: string,
  params?: any,
  config?: GetRequestConfig
): Promise<ResponseData<T>> {
  return service({
    url,
    method: "get",
    params,
    ...config,
  });
}

/**
 * POST 请求（返回 Blob）
 */
export function post(
  url: string,
  data?: any,
  config?: { responseType: "blob" }
): Promise<Blob>;

/**
 * POST 请求（返回 ResponseData）
 */
export function post<T = any>(
  url: string,
  data?: any,
  config?: { responseType?: never }
): Promise<ResponseData<T>>;

/**
 * POST 请求实现
 */
export function post<T = any>(
  url: string,
  data?: any,
  config?: { responseType?: "blob" }
): Promise<ResponseData<T> | Blob> {
  return service({
    url,
    method: "post",
    data,
    ...config,
  });
}

/**
 * PUT 请求
 * @param url 请求地址
 * @param data 请求体数据
 * @returns Promise<ResponseData<T>>
 */
export function put<T = any>(
  url: string,
  data?: any
): Promise<ResponseData<T>> {
  return service({
    url,
    method: "put",
    data,
  });
}

/**
 * DELETE 请求
 * @param url 请求地址
 * @param data 请求体数据（可选）
 * @returns Promise<ResponseData<T>>
 */
export function del<T = any>(
  url: string,
  data?: any
): Promise<ResponseData<T>> {
  return service({
    url,
    method: "delete",
    data,
  });
}


