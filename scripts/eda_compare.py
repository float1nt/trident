from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path("/home/sr/97/trident")
DOCS = ROOT / "docs"


@dataclass
class DatasetSummary:
    name: str
    total_rows: int
    columns: List[str]
    label_col: str
    top_labels: List[Tuple[str, int]]
    top_missing: List[Tuple[str, int]]
    total_size_gb: float


def _load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dataset(
    key: str,
    summary_path: Path,
    data_globs: List[str],
) -> DatasetSummary:
    data = _load_json(summary_path)
    all_files: List[Path] = []
    for glob_pattern in data_globs:
        all_files.extend(sorted(Path("/").glob(glob_pattern)))
    total_size = sum(f.stat().st_size for f in all_files)
    return DatasetSummary(
        name=key,
        total_rows=int(data["total_rows"]),
        columns=list(data["columns"]),
        label_col=str(data["label_col"]),
        top_labels=[(str(x[0]), int(x[1])) for x in data["top_labels"]],
        top_missing=[(str(x[0]), int(x[1])) for x in data["top_missing"]],
        total_size_gb=total_size / (1024**3),
    )


def _top1_ratio(s: DatasetSummary) -> float:
    if not s.top_labels:
        return 0.0
    return s.top_labels[0][1] / max(s.total_rows, 1)


def _benign_ratio(s: DatasetSummary) -> float:
    total_benign = 0
    for label, cnt in s.top_labels:
        label_l = label.lower()
        if "benign" in label_l:
            total_benign += cnt
    return total_benign / max(s.total_rows, 1)


def _missing_top_ratio(s: DatasetSummary) -> float:
    if not s.top_missing:
        return 0.0
    return s.top_missing[0][1] / max(s.total_rows, 1)


def build_compare_md(summaries: Dict[str, DatasetSummary]) -> str:
    names = ["CICIDS2017", "CICDDoS2019", "CICIDS2026"]
    cols_sets = {k: set(v.columns) for k, v in summaries.items()}
    common_cols = set.intersection(*(cols_sets[n] for n in names))
    union_cols = set.union(*(cols_sets[n] for n in names))

    lines: List[str] = []
    lines.append("# 2017 / 2019 / 2026 EDA 横向对比报告")
    lines.append("")
    lines.append("本报告基于三份独立 EDA 结果自动汇总，聚焦可用于建模与数据治理的横向差异。")
    lines.append("")
    lines.append("## 1) 核心规模对比")
    lines.append("")
    lines.append("| 数据集 | 样本数 | 列数 | 标签列名 | 文件体量(GB) |")
    lines.append("|---|---:|---:|---|---:|")
    for n in names:
        s = summaries[n]
        lines.append(
            f"| {n} | {s.total_rows:,} | {len(s.columns)} | `{s.label_col}` | {s.total_size_gb:.2f} |"
        )
    lines.append("")

    lines.append("## 2) 标签分布与不平衡程度")
    lines.append("")
    lines.append("| 数据集 | Top1 类别 | Top1 占比 | BENIGN 占比 | 标签类别数(TopN统计) |")
    lines.append("|---|---|---:|---:|---:|")
    for n in names:
        s = summaries[n]
        top1_name = s.top_labels[0][0] if s.top_labels else "N/A"
        lines.append(
            f"| {n} | {top1_name} | {_top1_ratio(s):.2%} | {_benign_ratio(s):.2%} | {len(s.top_labels)} |"
        )
    lines.append("")
    lines.append("- 2019 的类别高度集中（`TFTP`约 40%），长尾攻击类别多，需重点处理类别不平衡。")
    lines.append("- 2017 以 `BENIGN` 为主（约 75%），但攻击标签类型更碎片化。")
    lines.append("- 2026 类别相对更均衡，适合做多分类基线与迁移验证。")
    lines.append("")

    lines.append("## 3) 缺失值横向对比")
    lines.append("")
    lines.append("| 数据集 | 缺失最多列 | 缺失数 | 缺失率 |")
    lines.append("|---|---|---:|---:|")
    for n in names:
        s = summaries[n]
        c, m = s.top_missing[0]
        lines.append(f"| {n} | {c} | {m:,} | {_missing_top_ratio(s):.2%} |")
    lines.append("")
    lines.append("- 三个数据集整体缺失率都较低，主要关注 `Flow Bytes/s` 的少量异常缺失。")
    lines.append("")

    lines.append("## 4) 特征空间可对齐性")
    lines.append("")
    lines.append(f"- 三数据集特征并集数量: **{len(union_cols)}**")
    lines.append(f"- 三数据集共同特征数量: **{len(common_cols)}**")
    lines.append(
        "- 2019 存在大量带前导空格列名（如 ` Label`、` Source IP`），建模前建议统一列名规范。"
    )
    lines.append("- 2017 额外包含 `Attempted Category`、`ICMP Code/Type`、`Total TCP Flow Time` 等特征。")
    lines.append("- 2026 特征集合更接近 2017 的主干 CICFlowMeter 风格。")
    lines.append("")

    lines.append("## 5) 建模与实验建议（跨数据集）")
    lines.append("")
    lines.append("- **列名标准化**: 统一 trim 空格、大小写和别名映射，确保训练/推理特征对齐。")
    lines.append("- **标签体系映射**: 建议构建三级标签（Benign / DoS家族 / 细粒度攻击）用于跨年迁移。")
    lines.append("- **分层采样策略**: 2019 训练时建议按类别上限采样，避免 `TFTP` 主导模型。")
    lines.append("- **鲁棒预处理**: 对高偏态数值特征使用 `log1p + RobustScaler`，并保留零值语义。")
    lines.append("- **跨域评估**: 推荐做 `2017->2026` 与 `2019->2026` 的零样本/少样本迁移实验。")
    lines.append("")

    lines.append("## 6) 原始 EDA 文档索引")
    lines.append("")
    lines.append("- [CICIDS2017](./eda_2017/eda.md)")
    lines.append("- [CICDDoS2019](./eda_2019/eda.md)")
    lines.append("- [CICIDS2026](./eda_2026/eda.md)")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    summaries = {
        "CICIDS2017": _load_dataset(
            "CICIDS2017",
            DOCS / "eda_2017" / "eda_summary.json",
            ["home/data/2017/*.csv"],
        ),
        "CICDDoS2019": _load_dataset(
            "CICDDoS2019",
            DOCS / "eda_2019" / "eda_summary.json",
            ["home/data/2019/*.csv"],
        ),
        "CICIDS2026": _load_dataset(
            "CICIDS2026",
            DOCS / "eda_2026" / "eda_summary.json",
            ["home/data/cicids2026.csv"],
        ),
    }
    content = build_compare_md(summaries)
    out = DOCS / "eda_compare_2017_2019_2026.md"
    out.write_text(content, encoding="utf-8")
    print(f"Generated: {out}")


if __name__ == "__main__":
    main()
