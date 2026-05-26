import type { Categories } from "@/api/types";

/** 是否为分类叶子节点 */
function isCategoryLeaf(
  node: { children?: unknown[] } | null | undefined
): boolean {
  return !node?.children || node.children.length === 0;
}

function getCategoryOriginalOrName(node: {
  name?: string;
  originalName?: string;
} | null | undefined): string {
  if (!node) return "";
  const original =
    (typeof node.originalName === "string" ? node.originalName : "").trim();
  if (original) return original;
  return (node.name ?? "").trim();
}

function getCategoryPathSegment(
  node: {
    name?: string;
    originalName?: string;
    grading?: string;
    children?: unknown[];
  } | null | undefined,
  includeGrading: boolean
): string {
  const displayName = getCategoryOriginalOrName(node);
  if (!displayName) return "";
  if (includeGrading && node?.grading?.trim()) {
    return `${displayName}-${node.grading.trim()}`;
  }
  return displayName;
}

/** 分类分级名称列展示 */
export function getCategoryDisplayName(node: {
  name?: string;
  originalName?: string;
  grading?: string;
  children?: unknown[];
} | null | undefined): string {
  return getCategoryPathSegment(node, isCategoryLeaf(node));
}

export type { Categories };
