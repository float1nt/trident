from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


CHUNKSIZE = 200_000
MAX_SAMPLE_ROWS = 200_000
TOP_K = 15


@dataclass
class NumericAgg:
    count: int = 0
    missing: int = 0
    sum_v: float = 0.0
    sum_sq_v: float = 0.0
    min_v: float = math.inf
    max_v: float = -math.inf
    zero_count: int = 0

    def update(self, series: pd.Series) -> None:
        values = pd.to_numeric(series, errors="coerce")
        missing = int(values.isna().sum())
        valid = values.dropna()
        n = int(valid.shape[0])
        self.count += n
        self.missing += missing
        if n == 0:
            return
        arr = valid.to_numpy(dtype=np.float64, copy=False)
        self.sum_v += float(arr.sum())
        self.sum_sq_v += float(np.square(arr).sum())
        self.min_v = min(self.min_v, float(arr.min()))
        self.max_v = max(self.max_v, float(arr.max()))
        self.zero_count += int((arr == 0).sum())

    def summary(self) -> Dict[str, float]:
        if self.count == 0:
            return {
                "count": 0,
                "mean": np.nan,
                "std": np.nan,
                "min": np.nan,
                "max": np.nan,
                "zero_ratio": np.nan,
            }
        mean = self.sum_v / self.count
        var = max(self.sum_sq_v / self.count - mean * mean, 0.0)
        std = math.sqrt(var)
        return {
            "count": self.count,
            "mean": mean,
            "std": std,
            "min": self.min_v,
            "max": self.max_v,
            "zero_ratio": self.zero_count / self.count,
        }


@dataclass
class DatasetAgg:
    name: str
    files: List[Path]
    total_rows: int = 0
    total_cols: int = 0
    columns: List[str] = field(default_factory=list)
    missing_counts: Dict[str, int] = field(default_factory=dict)
    numeric_aggs: Dict[str, NumericAgg] = field(default_factory=dict)
    label_counter: Counter = field(default_factory=Counter)
    label_col: Optional[str] = None
    sample_frames: List[pd.DataFrame] = field(default_factory=list)
    sample_rows: int = 0
    parse_errors: List[str] = field(default_factory=list)

    def add_chunk(self, chunk: pd.DataFrame) -> None:
        if not self.columns:
            self.columns = list(chunk.columns)
            self.total_cols = len(self.columns)
            for col in self.columns:
                self.missing_counts[col] = 0
        self.total_rows += len(chunk)

        for col in self.columns:
            if col in chunk.columns:
                self.missing_counts[col] += int(chunk[col].isna().sum())

        if self.label_col is None:
            self.label_col = detect_label_column(chunk)

        if self.label_col and self.label_col in chunk.columns:
            labels = (
                chunk[self.label_col]
                .astype(str)
                .str.strip()
                .replace({"": "MISSING", "nan": "MISSING", "None": "MISSING"})
            )
            self.label_counter.update(labels.value_counts(dropna=False).to_dict())

        # Determine numeric candidates once based on first chunk.
        if not self.numeric_aggs:
            for col in self.columns:
                converted = pd.to_numeric(chunk[col], errors="coerce")
                valid_ratio = 1.0 - float(converted.isna().mean())
                if valid_ratio >= 0.95:
                    self.numeric_aggs[col] = NumericAgg()

        for col, agg in self.numeric_aggs.items():
            if col in chunk.columns:
                agg.update(chunk[col])

        if self.sample_rows < MAX_SAMPLE_ROWS:
            remaining = MAX_SAMPLE_ROWS - self.sample_rows
            sampled = chunk.head(remaining)
            self.sample_frames.append(sampled.copy())
            self.sample_rows += len(sampled)

    def merged_sample(self) -> pd.DataFrame:
        if not self.sample_frames:
            return pd.DataFrame()
        return pd.concat(self.sample_frames, ignore_index=True)


def detect_label_column(df: pd.DataFrame) -> Optional[str]:
    candidates = [
        "label",
        "Label",
        "class",
        "Class",
        "attack",
        "Attack",
        "attack_cat",
        "target",
        "Target",
    ]
    for c in candidates:
        if c in df.columns:
            return c

    # Fallback: last column with low distinct ratio.
    for col in reversed(df.columns.tolist()):
        nunique = df[col].nunique(dropna=True)
        if 1 < nunique <= 100:
            return col
    return None


def iter_csv_chunks(path: Path) -> Iterable[pd.DataFrame]:
    kwargs = {
        "chunksize": CHUNKSIZE,
        "low_memory": False,
        "on_bad_lines": "skip",
    }
    # Some files may contain huge fields.
    yield from pd.read_csv(path, **kwargs)


def scan_dataset(name: str, files: List[Path]) -> DatasetAgg:
    agg = DatasetAgg(name=name, files=files)
    for file in files:
        try:
            for chunk in iter_csv_chunks(file):
                agg.add_chunk(chunk)
        except Exception as exc:  # pragma: no cover
            agg.parse_errors.append(f"{file.name}: {exc}")
    return agg


def format_pct(x: float) -> str:
    if pd.isna(x):
        return "NaN"
    return f"{x * 100:.2f}%"


def render_dataset_section(agg: DatasetAgg) -> str:
    lines: List[str] = []
    lines.append(f"## {agg.name}")
    lines.append("")
    lines.append("### 1) 数据规模与文件构成")
    lines.append("")
    lines.append(f"- 文件数: {len(agg.files)}")
    lines.append(f"- 总样本数: {agg.total_rows:,}")
    lines.append(f"- 特征列数: {agg.total_cols}")
    lines.append(
        f"- 标签列识别结果: `{agg.label_col}`" if agg.label_col else "- 标签列识别结果: 未识别"
    )
    total_size = sum(f.stat().st_size for f in agg.files)
    lines.append(f"- 文件总大小: {total_size / (1024**3):.2f} GB")
    lines.append("")
    lines.append("| 文件 | 大小(GB) |")
    lines.append("|---|---:|")
    for f in agg.files:
        lines.append(f"| {f.name} | {f.stat().st_size / (1024**3):.3f} |")
    lines.append("")

    lines.append("### 2) 缺失值分析（Top 15）")
    lines.append("")
    miss = sorted(
        ((col, cnt, cnt / max(agg.total_rows, 1)) for col, cnt in agg.missing_counts.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:TOP_K]
    lines.append("| 列名 | 缺失数量 | 缺失率 |")
    lines.append("|---|---:|---:|")
    for col, cnt, ratio in miss:
        lines.append(f"| {col} | {cnt:,} | {format_pct(ratio)} |")
    lines.append("")

    lines.append("### 3) 标签分布（Top 15）")
    lines.append("")
    if agg.label_counter:
        lines.append("| 标签 | 数量 | 占比 |")
        lines.append("|---|---:|---:|")
        total = sum(agg.label_counter.values())
        for label, cnt in agg.label_counter.most_common(TOP_K):
            lines.append(f"| {label} | {cnt:,} | {format_pct(cnt / total)} |")
    else:
        lines.append("- 未识别可用标签列，无法统计标签分布。")
    lines.append("")

    lines.append("### 4) 数值特征统计（Top 15 by std）")
    lines.append("")
    numeric_rows = []
    for col, nagg in agg.numeric_aggs.items():
        s = nagg.summary()
        numeric_rows.append((col, s["std"], s))
    numeric_rows.sort(key=lambda x: (np.nan_to_num(x[1], nan=-1.0)), reverse=True)
    lines.append("| 列名 | count | mean | std | min | max | zero_ratio |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for col, _, s in numeric_rows[:TOP_K]:
        lines.append(
            f"| {col} | {int(s['count']):,} | {s['mean']:.4g} | {s['std']:.4g} | "
            f"{s['min']:.4g} | {s['max']:.4g} | {format_pct(s['zero_ratio'])} |"
        )
    lines.append("")

    sample = agg.merged_sample()
    lines.append("### 5) 相关性与异常值（基于采样）")
    lines.append("")
    if sample.empty:
        lines.append("- 无可用采样数据。")
        lines.append("")
    else:
        numeric_sample = sample.apply(pd.to_numeric, errors="coerce")
        numeric_sample = numeric_sample.select_dtypes(include=["number"])
        # 保留非全空列
        numeric_sample = numeric_sample.loc[:, numeric_sample.notna().sum() > 0]
        if numeric_sample.shape[1] >= 2:
            corr = numeric_sample.corr(numeric_only=True).abs()
            pairs = []
            cols = corr.columns.tolist()
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    val = corr.iloc[i, j]
                    if pd.notna(val):
                        pairs.append((cols[i], cols[j], float(val)))
            pairs.sort(key=lambda x: x[2], reverse=True)
            lines.append("**高相关特征对（Top 10）**")
            lines.append("")
            lines.append("| 特征1 | 特征2 | |corr| |")
            lines.append("|---|---|---:|")
            for a, b, c in pairs[:10]:
                lines.append(f"| {a} | {b} | {c:.4f} |")
        else:
            lines.append("- 可用于相关性分析的数值列不足。")
        lines.append("")

        # IQR outlier ratio on top-variance numeric columns.
        candidate_cols = []
        for col in numeric_sample.columns:
            std = float(numeric_sample[col].std(skipna=True))
            if not pd.isna(std):
                candidate_cols.append((col, std))
        candidate_cols.sort(key=lambda x: x[1], reverse=True)
        lines.append("**异常值比例（IQR，Top 10 by std）**")
        lines.append("")
        lines.append("| 列名 | Q1 | Q3 | IQR | 异常值占比 |")
        lines.append("|---|---:|---:|---:|---:|")
        for col, _ in candidate_cols[:10]:
            s = numeric_sample[col].dropna()
            if s.empty:
                continue
            q1 = float(s.quantile(0.25))
            q3 = float(s.quantile(0.75))
            iqr = q3 - q1
            if iqr == 0:
                out_ratio = 0.0
            else:
                low = q1 - 1.5 * iqr
                high = q3 + 1.5 * iqr
                out_ratio = float(((s < low) | (s > high)).mean())
            lines.append(
                f"| {col} | {q1:.4g} | {q3:.4g} | {iqr:.4g} | {format_pct(out_ratio)} |"
            )
        lines.append("")

        if agg.label_col and agg.label_col in sample.columns:
            label_series = sample[agg.label_col].astype(str)
            lines.append("**采样标签熵（类别均匀度）**")
            vc = label_series.value_counts(normalize=True)
            entropy = float(-(vc * np.log2(vc + 1e-12)).sum())
            lines.append("")
            lines.append(f"- 采样标签熵: {entropy:.4f} bits")
            lines.append(f"- 采样标签类别数: {vc.shape[0]}")
            lines.append("")

    lines.append("### 6) 数据质量与建模建议")
    lines.append("")
    lines.append("- 建议先对极端长尾特征做 `log1p` 或分位数裁剪，再进行标准化。")
    lines.append("- 对高缺失列（缺失率 > 30%）建议评估删除或专门缺失值编码。")
    lines.append("- 对标签分布明显不均衡的数据集建议使用分层采样 + 类别权重或重采样。")
    lines.append("- 对高度相关特征可做降维或相关阈值筛选，减少冗余。")
    if agg.parse_errors:
        lines.append("- 解析告警:")
        for e in agg.parse_errors:
            lines.append(f"  - {e}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    data_root = Path("/home/data")
    datasets = {
        "CICIDS2017": sorted((data_root / "2017").glob("*.csv")),
        "CICDDoS2019": sorted((data_root / "2019").glob("*.csv")),
        "CICIDS2026": [data_root / "cicids2026.csv"],
    }

    report_parts: List[str] = []
    report_parts.append("# 2017 / 2019 / 2026 数据集 EDA 报告")
    report_parts.append("")
    report_parts.append("本报告基于分块扫描（chunked reading）与采样统计生成，兼顾大规模 CSV 的可执行性与分析细节。")
    report_parts.append("")
    report_parts.append("## 分析方法")
    report_parts.append("")
    report_parts.append(f"- 分块大小: {CHUNKSIZE:,} 行")
    report_parts.append(f"- 采样上限: {MAX_SAMPLE_ROWS:,} 行/数据集")
    report_parts.append("- 对全量数据统计: 样本规模、缺失率、标签分布、数值列一阶/二阶矩统计")
    report_parts.append("- 对采样数据统计: 相关性、IQR 异常值比例、标签熵")
    report_parts.append("")

    for name, files in datasets.items():
        agg = scan_dataset(name, files)
        report_parts.append(render_dataset_section(agg))

    output = Path("/home/sr/97/trident/docs/dataset_eda_2017_2019_2026.md")
    output.write_text("\n".join(report_parts), encoding="utf-8")
    print(f"EDA report generated at: {output}")


if __name__ == "__main__":
    main()
