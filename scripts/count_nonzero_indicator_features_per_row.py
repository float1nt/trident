#!/usr/bin/env python3
"""
对表格中每条记录（每条流），统计「有多少列取非零数值」：
  单列：若为有限数且绝对值大于 eps → 记 1，否则（含 NaN/Inf）→ 记 0；
  行：对上述 0/1 指示量按列求和，得到该行非零特征个数。

默认只统计「数值类型」列，并跳过常见标识列（如 Label、Timestamp）。

示例：
  python3 scripts/count_nonzero_indicator_features_per_row.py \\
    --input data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv \\
    --output outputs/eda/nonzero_feat_count.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Sequence

import numpy as np
import pandas as pd


DEFAULT_EXCLUDE = (
    "Label",
    "LabelNorm",
    "Timestamp",
    "Flow ID",  # 常为字符串，若读成数字可删去此项
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="按行统计非零数值特征列个数（列二值指示后求和）"
    )
    p.add_argument("--input", "-i", type=Path, required=True, help="输入 CSV 路径")
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="输出每行计数 CSV（含 row_index 与 nonzero_feature_count）",
    )
    p.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="可选：写入整体分布摘要 JSON",
    )
    p.add_argument(
        "--chunksize",
        type=int,
        default=200_000,
        help="分块读取行数",
    )
    p.add_argument(
        "--eps",
        type=float,
        default=0.0,
        help="|x| > eps 视为非零；默认 0",
    )
    p.add_argument(
        "--exclude",
        nargs="*",
        default=list(DEFAULT_EXCLUDE),
        help="排除的列名（不分块累加）；默认常见元数据列",
    )
    p.add_argument(
        "--all-columns-as-numeric",
        action="store_true",
        help=(
            "默认只统计当前为数值 dtype 的列；指定此项则对除 --exclude 外的所有列做 to_numeric（含原字符串列）"
        ),
    )
    p.add_argument(
        "--keep-label-column",
        type=str,
        default=None,
        help="若指定列名存在，一并写入输出 CSV 便于对齐标签",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="仅处理前 N 行，0 表示全表",
    )
    return p.parse_args()


def resolve_feature_columns(
    sample: pd.DataFrame,
    exclude: Sequence[str],
    numeric_only: bool,
    all_as_numeric: bool,
) -> List[str]:
    ex = {str(x) for x in exclude}
    cols = [c for c in sample.columns if c not in ex]
    if all_as_numeric:
        return cols
    if numeric_only:
        num = sample[cols].select_dtypes(include=[np.number]).columns.tolist()
        return num
    return cols


def main() -> None:
    args = parse_args()
    path = args.input
    if not path.is_file():
        raise SystemExit(f"输入文件不存在: {path}")

    head = pd.read_csv(path, nrows=4096, low_memory=False)
    feat_cols = resolve_feature_columns(
        head,
        exclude=args.exclude,
        numeric_only=not args.all_columns_as_numeric,
        all_as_numeric=args.all_columns_as_numeric,
    )
    if not feat_cols:
        raise SystemExit("没有可用特征列（请检查 --exclude / dtype）")

    extra_use = []
    if args.keep_label_column and args.keep_label_column in head.columns:
        extra_use.append(args.keep_label_column)

    usecols = list(dict.fromkeys(feat_cols + extra_use))

    out_path = args.output
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        header = ["row_index", "nonzero_feature_count"] + (
            [args.keep_label_column] if extra_use else []
        )
        with out_path.open("w", encoding="utf-8") as f:
            f.write(",".join(header) + "\n")

    global_sum = 0.0
    global_sum_sq = 0.0
    global_n = 0
    global_min = np.iinfo(np.int64).max
    global_max = -1
    hist = np.zeros(len(feat_cols) + 1, dtype=np.int64)

    reader = pd.read_csv(
        path,
        usecols=lambda c: c in set(usecols),
        chunksize=args.chunksize,
        low_memory=False,
    )

    row_base = 0
    rows_emitted = 0
    max_rows = int(args.max_rows) if args.max_rows and args.max_rows > 0 else None

    for chunk in reader:
        if max_rows is not None:
            need = max_rows - rows_emitted
            if need <= 0:
                break
            if len(chunk) > need:
                chunk = chunk.iloc[:need]

        block = chunk[feat_cols].apply(pd.to_numeric, errors="coerce")
        arr = block.to_numpy(dtype=np.float64, copy=False)
        finite = np.isfinite(arr)
        nz = finite & (np.abs(arr) > float(args.eps))
        counts = nz.sum(axis=1).astype(np.int64)

        if out_path is not None:
            out_df = pd.DataFrame(
                {
                    "row_index": np.arange(row_base, row_base + len(counts), dtype=np.int64),
                    "nonzero_feature_count": counts,
                }
            )
            if extra_use:
                out_df[args.keep_label_column] = chunk[args.keep_label_column].values
            out_df.to_csv(out_path, mode="a", header=False, index=False)

        # 更新摘要
        global_n += int(len(counts))
        c64 = counts.astype(np.float64)
        global_sum += float(c64.sum())
        global_sum_sq += float((c64 * c64).sum())
        global_min = int(min(global_min, int(counts.min()) if len(counts) else global_min))
        global_max = int(max(global_max, int(counts.max()) if len(counts) else global_max))
        bc = np.bincount(counts, minlength=len(hist)).astype(np.int64)
        if len(bc) > len(hist):
            hist = np.concatenate([hist, np.zeros(len(bc) - len(hist), dtype=np.int64)])
        hist[: len(bc)] += bc

        row_base += len(chunk)
        rows_emitted += len(chunk)
        if max_rows is not None and rows_emitted >= max_rows:
            break

    mean = global_sum / global_n if global_n else 0.0
    var = max(global_sum_sq / global_n - mean * mean, 0.0) if global_n else 0.0
    std = float(var**0.5)

    summary = {
        "input": str(path.resolve()),
        "rows": int(global_n),
        "feature_column_count": int(len(feat_cols)),
        "eps": float(args.eps),
        "excluded_columns": list(args.exclude),
        "nonzero_feature_count_min": int(global_min if global_n else 0),
        "nonzero_feature_count_max": int(global_max if global_n else 0),
        "nonzero_feature_count_mean": mean,
        "nonzero_feature_count_std": std,
        "histogram": {
            str(k): int(hist[k]) for k in range(len(hist)) if hist[k] > 0
        },
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        with args.summary_json.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"Wrote summary: {args.summary_json}", flush=True)
    if out_path:
        print(f"Wrote per-row counts: {out_path}", flush=True)


if __name__ == "__main__":
    main()
