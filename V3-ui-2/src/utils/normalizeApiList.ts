const LIST_KEYS = ["items", "risks", "list", "records", "data"] as const;

/** 将接口 data 规范为数组，兼容直接数组或 { items | risks | ... } 包裹 */
export function normalizeApiList<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (!value || typeof value !== "object") return [];

  const obj = value as Record<string, unknown>;
  for (const key of LIST_KEYS) {
    const nested = obj[key];
    if (Array.isArray(nested)) return nested as T[];
  }
  return [];
}
