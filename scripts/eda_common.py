from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


plt.switch_backend("Agg")


def log_line(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(message + "\n")
    print(message, flush=True)


def detect_label_column(columns: List[str]) -> Optional[str]:
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
    for col in candidates:
        if col in columns:
            return col
    return columns[-1] if columns else None


@dataclass
class NumericStats:
    count: int = 0
    missing: int = 0
    sum_v: float = 0.0
    sum_sq_v: float = 0.0
    min_v: float = np.inf
    max_v: float = -np.inf
    zero_count: int = 0

    def update(self, series: pd.Series) -> None:
        values = pd.to_numeric(series, errors="coerce")
        self.missing += int(values.isna().sum())
        valid = values.dropna()
        n = int(valid.shape[0])
        self.count += n
        if n == 0:
            return
        arr = valid.to_numpy(dtype=np.float64, copy=False)
        self.sum_v += float(arr.sum())
        self.sum_sq_v += float(np.square(arr).sum())
        self.min_v = min(self.min_v, float(np.min(arr)))
        self.max_v = max(self.max_v, float(np.max(arr)))
        self.zero_count += int(np.sum(arr == 0))

    def to_dict(self) -> Dict[str, float]:
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
        return {
            "count": self.count,
            "mean": mean,
            "std": float(np.sqrt(var)),
            "min": self.min_v,
            "max": self.max_v,
            "zero_ratio": self.zero_count / self.count,
        }


@dataclass
class EdaState:
    dataset_name: str
    files: List[Path]
    output_dir: Path
    chunk_size: int = 200_000
    sample_cap: int = 250_000
    total_rows: int = 0
    columns: List[str] = field(default_factory=list)
    missing_counts: Dict[str, int] = field(default_factory=dict)
    numeric_stats: Dict[str, NumericStats] = field(default_factory=dict)
    label_col: Optional[str] = None
    label_counts: Counter = field(default_factory=Counter)
    sample_frames: List[pd.DataFrame] = field(default_factory=list)
    sample_rows: int = 0
    parse_warnings: List[str] = field(default_factory=list)

    @property
    def log_path(self) -> Path:
        return self.output_dir / "progress.log"

    def init_columns(self, chunk: pd.DataFrame) -> None:
        if self.columns:
            return
        self.columns = list(chunk.columns)
        self.missing_counts = {c: 0 for c in self.columns}
        self.label_col = detect_label_column(self.columns)
        for col in self.columns:
            converted = pd.to_numeric(chunk[col], errors="coerce")
            valid_ratio = 1.0 - float(converted.isna().mean())
            if valid_ratio >= 0.95:
                self.numeric_stats[col] = NumericStats()

    def update(self, chunk: pd.DataFrame) -> None:
        self.init_columns(chunk)
        self.total_rows += len(chunk)
        for col in self.columns:
            self.missing_counts[col] += int(chunk[col].isna().sum())
        for col, stats in self.numeric_stats.items():
            stats.update(chunk[col])
        if self.label_col and self.label_col in chunk.columns:
            s = (
                chunk[self.label_col]
                .astype(str)
                .str.strip()
                .replace({"": "MISSING", "nan": "MISSING", "None": "MISSING"})
            )
            self.label_counts.update(s.value_counts(dropna=False).to_dict())
        if self.sample_rows < self.sample_cap:
            remain = self.sample_cap - self.sample_rows
            sampled = chunk.head(remain)
            self.sample_frames.append(sampled.copy())
            self.sample_rows += len(sampled)

    def sample_df(self) -> pd.DataFrame:
        if not self.sample_frames:
            return pd.DataFrame()
        return pd.concat(self.sample_frames, ignore_index=True)


def _save_fig(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()


def _plot_label_distribution(state: EdaState, top_k: int = 20) -> Optional[Path]:
    if not state.label_counts:
        return None
    out = state.output_dir / "label_distribution_top20.png"
    top = state.label_counts.most_common(top_k)
    labels = [x[0] for x in top]
    values = [x[1] for x in top]
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(labels)), values)
    plt.xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=8)
    plt.title(f"{state.dataset_name} Label Distribution (Top {top_k})")
    plt.ylabel("Count")
    _save_fig(out)
    return out


def _plot_missing_top(state: EdaState, top_k: int = 20) -> Path:
    out = state.output_dir / "missing_top20.png"
    pairs = sorted(
        ((k, v, v / max(state.total_rows, 1)) for k, v in state.missing_counts.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]
    labels = [x[0] for x in pairs]
    values = [x[2] for x in pairs]
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(labels)), values)
    plt.xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=8)
    plt.title(f"{state.dataset_name} Missing Ratio (Top {top_k})")
    plt.ylabel("Missing ratio")
    _save_fig(out)
    return out


def _plot_numeric_summary(state: EdaState, top_k: int = 20) -> Path:
    out = state.output_dir / "numeric_std_top20.png"
    rows = []
    for col, st in state.numeric_stats.items():
        d = st.to_dict()
        rows.append((col, d["std"]))
    rows.sort(key=lambda x: np.nan_to_num(x[1], nan=-1.0), reverse=True)
    rows = rows[:top_k]
    labels = [x[0] for x in rows]
    vals = [x[1] for x in rows]
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(labels)), vals)
    plt.xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=8)
    plt.title(f"{state.dataset_name} Numeric Std (Top {top_k})")
    plt.ylabel("Std")
    _save_fig(out)
    return out


def _plot_corr_heatmap(sample: pd.DataFrame, state: EdaState, top_k: int = 20) -> Optional[Path]:
    numeric = sample.apply(pd.to_numeric, errors="coerce").select_dtypes(include=["number"])
    numeric = numeric.loc[:, numeric.notna().sum() > 0]
    if numeric.shape[1] < 2:
        return None
    variances = numeric.var(skipna=True).sort_values(ascending=False).head(top_k)
    num_top = numeric[variances.index.tolist()]
    corr = num_top.corr(numeric_only=True)
    out = state.output_dir / "correlation_heatmap_top20.png"
    plt.figure(figsize=(10, 8))
    im = plt.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    plt.colorbar(im, fraction=0.046, pad=0.04)
    plt.xticks(range(len(corr.columns)), corr.columns, rotation=45, ha="right", fontsize=7)
    plt.yticks(range(len(corr.index)), corr.index, fontsize=7)
    plt.title(f"{state.dataset_name} Correlation Heatmap (Top Variance Features)")
    _save_fig(out)
    return out


def _plot_histograms(sample: pd.DataFrame, state: EdaState, top_k: int = 6) -> Optional[Path]:
    numeric = sample.apply(pd.to_numeric, errors="coerce").select_dtypes(include=["number"])
    numeric = numeric.loc[:, numeric.notna().sum() > 0]
    if numeric.empty:
        return None
    stds = numeric.std(skipna=True).sort_values(ascending=False).head(top_k)
    out = state.output_dir / "histograms_top6.png"
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    axes = axes.flatten()
    for idx, col in enumerate(stds.index):
        s = numeric[col].dropna().head(60_000)
        axes[idx].hist(s, bins=60)
        axes[idx].set_title(col, fontsize=8)
    for i in range(len(stds.index), len(axes)):
        axes[i].axis("off")
    fig.suptitle(f"{state.dataset_name} Histograms (Top 6 by std)")
    _save_fig(out)
    return out


def _plot_boxplots(sample: pd.DataFrame, state: EdaState, top_k: int = 6) -> Optional[Path]:
    numeric = sample.apply(pd.to_numeric, errors="coerce").select_dtypes(include=["number"])
    numeric = numeric.loc[:, numeric.notna().sum() > 0]
    if numeric.empty:
        return None
    stds = numeric.std(skipna=True).sort_values(ascending=False).head(top_k)
    out = state.output_dir / "boxplots_top6.png"
    cols = stds.index.tolist()
    data = [numeric[c].dropna().head(80_000) for c in cols]
    plt.figure(figsize=(14, 6))
    plt.boxplot(data, labels=cols, showfliers=False)
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.title(f"{state.dataset_name} Boxplots (Top 6 by std)")
    _save_fig(out)
    return out


def _render_markdown(state: EdaState, figures: Dict[str, Optional[Path]]) -> str:
    total_size = sum(f.stat().st_size for f in state.files)
    lines: List[str] = []
    lines.append(f"# {state.dataset_name} EDA")
    lines.append("")
    lines.append("## 数据概览")
    lines.append("")
    lines.append(f"- 文件数: {len(state.files)}")
    lines.append(f"- 总样本数: {state.total_rows:,}")
    lines.append(f"- 列数: {len(state.columns)}")
    lines.append(f"- 标签列: `{state.label_col}`")
    lines.append(f"- 总文件大小: {total_size / (1024**3):.2f} GB")
    lines.append("")
    lines.append("| 文件 | 大小(GB) |")
    lines.append("|---|---:|")
    for f in state.files:
        lines.append(f"| {f.name} | {f.stat().st_size / (1024**3):.3f} |")
    lines.append("")
    lines.append("## 缺失值 Top 20")
    lines.append("")
    lines.append("| 列名 | 缺失数量 | 缺失率 |")
    lines.append("|---|---:|---:|")
    for col, miss in sorted(state.missing_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        lines.append(f"| {col} | {miss:,} | {miss / max(state.total_rows, 1):.2%} |")
    lines.append("")
    lines.append("## 标签分布 Top 20")
    lines.append("")
    if state.label_counts:
        total = sum(state.label_counts.values())
        lines.append("| 标签 | 数量 | 占比 |")
        lines.append("|---|---:|---:|")
        for label, cnt in state.label_counts.most_common(20):
            lines.append(f"| {label} | {cnt:,} | {cnt / total:.2%} |")
    else:
        lines.append("- 无标签分布可展示。")
    lines.append("")
    lines.append("## 数值特征统计 Top 20（按标准差）")
    lines.append("")
    rows = []
    for col, st in state.numeric_stats.items():
        d = st.to_dict()
        rows.append((col, d))
    rows.sort(key=lambda x: np.nan_to_num(x[1]["std"], nan=-1.0), reverse=True)
    lines.append("| 列名 | count | mean | std | min | max | zero_ratio |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for col, d in rows[:20]:
        lines.append(
            f"| {col} | {int(d['count']):,} | {d['mean']:.4g} | {d['std']:.4g} | "
            f"{d['min']:.4g} | {d['max']:.4g} | {d['zero_ratio']:.2%} |"
        )
    lines.append("")
    lines.append("## 可视化")
    lines.append("")
    for title, fig in figures.items():
        if fig is None:
            continue
        rel = fig.name
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"![{title}]({rel})")
        lines.append("")
    lines.append("## 结论与建议")
    lines.append("")
    lines.append("- 优先处理类别不平衡：训练时建议分层采样并使用类别权重。")
    lines.append("- 高缺失率列需评估删除或独立缺失编码。")
    lines.append("- 高相关特征可做相关阈值筛除，降低冗余。")
    lines.append("- 数值长尾较重时建议采用 `log1p` 或分位数截断。")
    if state.parse_warnings:
        lines.append("- 解析告警：")
        for msg in state.parse_warnings:
            lines.append(f"  - {msg}")
    lines.append("")
    lines.append("## 产物说明")
    lines.append("")
    lines.append("- `progress.log`: 实时进度日志。")
    lines.append("- `*.png`: 各类可视化图。")
    lines.append("- `eda.md`: 本数据集 EDA 文档。")
    lines.append("")
    return "\n".join(lines)


def run_eda(dataset_name: str, files: List[Path], output_dir: Path, chunk_size: int = 200_000) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "progress.log"
    if log_path.exists():
        log_path.unlink()

    state = EdaState(dataset_name=dataset_name, files=files, output_dir=output_dir, chunk_size=chunk_size)
    log_line(log_path, f"[START] dataset={dataset_name}, files={len(files)}, chunk_size={chunk_size}")
    for file_idx, file in enumerate(files, start=1):
        log_line(log_path, f"[FILE-START] {file_idx}/{len(files)} {file}")
        chunk_count = 0
        try:
            for chunk in pd.read_csv(
                file,
                chunksize=chunk_size,
                low_memory=False,
                on_bad_lines="skip",
            ):
                chunk_count += 1
                state.update(chunk)
                if chunk_count % 10 == 0:
                    log_line(
                        log_path,
                        f"[PROGRESS] file={file.name} chunk={chunk_count} total_rows={state.total_rows:,} sample_rows={state.sample_rows:,}",
                    )
        except Exception as exc:  # pragma: no cover
            warn = f"{file.name}: {exc}"
            state.parse_warnings.append(warn)
            log_line(log_path, f"[WARN] {warn}")
        log_line(
            log_path,
            f"[FILE-END] {file.name} chunks={chunk_count} cumulative_rows={state.total_rows:,}",
        )

    log_line(log_path, "[VIS] building plots")
    sample = state.sample_df()
    figs = {
        "标签分布 Top20": _plot_label_distribution(state),
        "缺失率 Top20": _plot_missing_top(state),
        "标准差 Top20": _plot_numeric_summary(state),
        "相关性热力图 Top20": _plot_corr_heatmap(sample, state),
        "直方图 Top6": _plot_histograms(sample, state),
        "箱线图 Top6": _plot_boxplots(sample, state),
    }
    log_line(log_path, "[DOC] writing markdown")
    md = _render_markdown(state, figs)
    (output_dir / "eda.md").write_text(md, encoding="utf-8")

    machine_summary = {
        "dataset": dataset_name,
        "total_rows": state.total_rows,
        "columns": state.columns,
        "label_col": state.label_col,
        "top_labels": state.label_counts.most_common(20),
        "top_missing": sorted(state.missing_counts.items(), key=lambda x: x[1], reverse=True)[:20],
    }
    (output_dir / "eda_summary.json").write_text(
        json.dumps(machine_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log_line(log_path, f"[DONE] report={output_dir / 'eda.md'}")
