import type { PaginationProps } from "antd";
import type { TablePaginationConfig } from "antd/es/table";

export const TABLE_PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

export const DEFAULT_TABLE_PAGE_SIZE = 10;

export const EVENT_TOPOLOGY_PAGE_SIZE_OPTIONS = [6, 10, 20, 50] as const;

export const DEFAULT_EVENT_TOPOLOGY_PAGE_SIZE = 6;

export function formatPaginationTotal(total: number): string {
  return `共 ${total} 条`;
}

/** Table / Pagination 统一分页 UI（条数切换、快速跳转、总数、尺寸） */
export const sharedPaginationProps: Pick<
  PaginationProps,
  "showSizeChanger" | "showQuickJumper" | "pageSizeOptions" | "showTotal" | "size"
> = {
  showSizeChanger: true,
  showQuickJumper: true,
  pageSizeOptions: TABLE_PAGE_SIZE_OPTIONS.map(String),
  showTotal: formatPaginationTotal,
  size: "small",
};

type TablePaginationParams = {
  current: number;
  pageSize: number;
  total: number;
  onChange: (page: number, pageSize: number) => void;
  pageSizeOptions?: readonly string[];
};

export function createTablePagination({
  current,
  pageSize,
  total,
  onChange,
}: TablePaginationParams): TablePaginationConfig {
  return {
    ...sharedPaginationProps,
    current,
    pageSize,
    total,
    onChange,
  };
}

export function createPaginationProps({
  current,
  pageSize,
  total,
  onChange,
  pageSizeOptions,
}: TablePaginationParams): PaginationProps {
  return {
    ...sharedPaginationProps,
    ...(pageSizeOptions ? { pageSizeOptions: [...pageSizeOptions] } : {}),
    current,
    pageSize,
    total,
    onChange,
  };
}
