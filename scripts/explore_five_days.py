import argparse
from pathlib import Path
from typing import List, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_FILES = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Descriptive EDA for CICIDS2017 five-day CSV files.")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing day-level CSV files.")
    parser.add_argument(
        "--input-files",
        nargs="+",
        default=DEFAULT_FILES,
        help="Ordered input file list. Defaults to monday->friday.",
    )
    parser.add_argument("--output-dir", type=str, default="outputs/eda_five_days", help="EDA output directory.")
    parser.add_argument("--sample-size-corr", type=int, default=50000, help="Sample size for correlation analysis.")
    return parser.parse_args()


def normalize_label(x: str) -> str:
    s = str(x).strip().upper()
    return "BENIGN" if s == "BENIGN" else s


def sanitize_filename(x: str) -> str:
    out = []
    for ch in x:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")


def save_plot(fig: plt.Figure, out_dir: Path, name: str) -> None:
    out_path = out_dir / f"{name}.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def load_data(data_dir: Path, input_files: Sequence[str]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for fn in input_files:
        fp = data_dir / fn
        if not fp.exists():
            continue
        df = pd.read_csv(fp, low_memory=False)
        day_name = Path(fn).stem.capitalize()
        df["DayFile"] = fn
        df["Day"] = day_name
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No input files found in {data_dir} from: {list(input_files)}")

    data = pd.concat(frames, ignore_index=True)
    if "Timestamp" in data.columns:
        data["TimestampParsed"] = pd.to_datetime(data["Timestamp"], errors="coerce")
    else:
        data["TimestampParsed"] = pd.NaT

    if "Label" in data.columns:
        data["LabelNorm"] = data["Label"].map(normalize_label)
    else:
        data["LabelNorm"] = "UNKNOWN"
    data["IsAttack"] = (data["LabelNorm"] != "BENIGN").astype(int)
    return data


def plot_row_counts_by_day(data: pd.DataFrame, out_dir: Path) -> pd.Series:
    daily_counts = data["Day"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(10, 4))
    daily_counts.plot(kind="bar", ax=ax, color="#4C78A8")
    ax.set_title("Rows per Day")
    ax.set_xlabel("Day")
    ax.set_ylabel("Rows")
    for i, v in enumerate(daily_counts.values):
        ax.text(i, v, f"{int(v)}", ha="center", va="bottom", fontsize=9)
    save_plot(fig, out_dir, "01_rows_per_day")
    return daily_counts


def plot_overall_label_distribution(data: pd.DataFrame, out_dir: Path, top_k: int = 20) -> pd.Series:
    label_counts = data["LabelNorm"].value_counts()
    top = label_counts.head(top_k).sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(11, 7))
    top.plot(kind="barh", ax=ax, color="#59A14F")
    ax.set_title(f"Top {top_k} Labels by Count (Overall)")
    ax.set_xlabel("Rows")
    ax.set_ylabel("Label")
    save_plot(fig, out_dir, "02_top_labels_overall")
    return label_counts


def plot_day_label_heatmap(data: pd.DataFrame, out_dir: Path, top_k: int = 15) -> pd.DataFrame:
    top_labels = data["LabelNorm"].value_counts().head(top_k).index.tolist()
    sub = data[data["LabelNorm"].isin(top_labels)]
    pivot = pd.crosstab(sub["Day"], sub["LabelNorm"])
    pivot = pivot.reindex(sorted(pivot.index), axis=0)
    pivot = pivot.reindex(top_labels, axis=1, fill_value=0)
    log_pivot = np.log1p(pivot.values)

    fig, ax = plt.subplots(figsize=(13, 5))
    im = ax.imshow(log_pivot, aspect="auto", cmap="viridis")
    ax.set_title("Day x Label Count Heatmap (log1p scale, top labels)")
    ax.set_xlabel("Label")
    ax.set_ylabel("Day")
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("log1p(count)")
    save_plot(fig, out_dir, "03_day_label_heatmap_log")
    return pivot


def plot_attack_ratio_by_day(data: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    ratio = data.groupby("Day")["IsAttack"].agg(["count", "sum"]).rename(columns={"count": "Total", "sum": "Attack"})
    ratio["Benign"] = ratio["Total"] - ratio["Attack"]
    ratio["AttackRatio"] = ratio["Attack"] / ratio["Total"]
    ratio = ratio.sort_index()

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(ratio.index, ratio["Benign"], label="Benign", color="#4E79A7")
    ax.bar(ratio.index, ratio["Attack"], bottom=ratio["Benign"], label="Attack", color="#E15759")
    ax.set_title("Benign vs Attack Rows by Day")
    ax.set_xlabel("Day")
    ax.set_ylabel("Rows")
    ax.legend(loc="upper right")
    save_plot(fig, out_dir, "04_benign_vs_attack_stacked")

    fig2, ax2 = plt.subplots(figsize=(10, 4))
    ax2.plot(ratio.index, ratio["AttackRatio"], marker="o", linewidth=2, color="#F28E2B")
    ax2.set_ylim(0, 1)
    ax2.set_title("Attack Ratio by Day")
    ax2.set_xlabel("Day")
    ax2.set_ylabel("Attack Ratio")
    ax2.grid(alpha=0.3)
    save_plot(fig2, out_dir, "05_attack_ratio_by_day")
    return ratio


def plot_hourly_traffic(data: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    valid = data.dropna(subset=["TimestampParsed"]).copy()
    valid["Hour"] = valid["TimestampParsed"].dt.floor("h")
    hourly = valid.groupby(["Day", "Hour"]).size().rename("Rows").reset_index()

    fig, ax = plt.subplots(figsize=(13, 5))
    for day, grp in hourly.groupby("Day"):
        ax.plot(grp["Hour"], grp["Rows"], marker=".", linewidth=1.5, label=day)
    ax.set_title("Hourly Traffic Volume by Day")
    ax.set_xlabel("Hour")
    ax.set_ylabel("Rows")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", ncol=2)
    save_plot(fig, out_dir, "06_hourly_volume_by_day")
    return hourly


def plot_missingness(data: pd.DataFrame, out_dir: Path, top_k: int = 25) -> pd.Series:
    missing_ratio = data.isna().mean().sort_values(ascending=False)
    top = missing_ratio.head(top_k)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(np.arange(len(top)), top.values, color="#B07AA1")
    ax.set_title(f"Top {top_k} Missing-Value Ratios")
    ax.set_xlabel("Column")
    ax.set_ylabel("Missing Ratio")
    ax.set_xticks(np.arange(len(top)))
    ax.set_xticklabels(top.index, rotation=75, ha="right", fontsize=8)
    ax.set_ylim(0, min(1.0, max(0.05, top.max() * 1.15)))
    save_plot(fig, out_dir, "07_top_missing_ratio_columns")
    return missing_ratio


def pick_numeric_features(data: pd.DataFrame, max_features: int = 8) -> List[str]:
    preferred = [
        "Flow Duration",
        "Total Fwd Packets",
        "Total Backward Packets",
        "Total Length of Fwd Packets",
        "Total Length of Bwd Packets",
        "Flow Bytes/s",
        "Flow Packets/s",
        "Packet Length Mean",
        "Fwd Packet Length Mean",
        "Bwd Packet Length Mean",
    ]
    numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
    picked = [c for c in preferred if c in numeric_cols]
    if len(picked) < max_features:
        extras = [c for c in numeric_cols if c not in picked and c not in ("IsAttack",)]
        variances = data[extras].var(numeric_only=True).sort_values(ascending=False)
        picked += variances.head(max_features - len(picked)).index.tolist()
    return picked[:max_features]


def plot_feature_boxplots_by_day(data: pd.DataFrame, out_dir: Path, features: Sequence[str]) -> None:
    if not features:
        return
    for feat in features:
        if feat not in data.columns:
            continue
        sub = data[["Day", feat]].dropna()
        if sub.empty:
            continue
        # Clip to reduce extreme tail impact and make boxplots readable.
        lo, hi = sub[feat].quantile([0.01, 0.99]).tolist()
        sub = sub[(sub[feat] >= lo) & (sub[feat] <= hi)]
        if sub.empty:
            continue

        days = sorted(sub["Day"].unique().tolist())
        arrays = [sub.loc[sub["Day"] == d, feat].values for d in days]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.boxplot(arrays, tick_labels=days, showfliers=False)
        ax.set_title(f"Feature Distribution by Day (clipped 1%-99%): {feat}")
        ax.set_xlabel("Day")
        ax.set_ylabel(feat)
        save_plot(fig, out_dir, f"08_box_{sanitize_filename(feat)}")


def plot_correlation_heatmap(data: pd.DataFrame, out_dir: Path, sample_size: int = 50000, top_k: int = 20) -> List[str]:
    numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
    numeric_cols = [c for c in numeric_cols if c not in ("IsAttack",)]
    if len(numeric_cols) < 2:
        return []

    safe_numeric = data[numeric_cols].replace([np.inf, -np.inf], np.nan)
    variances = safe_numeric.var(numeric_only=True).sort_values(ascending=False)
    selected = variances.head(top_k).index.tolist()
    frame = data[selected].replace([np.inf, -np.inf], np.nan).dropna()
    if frame.empty:
        return selected
    if len(frame) > sample_size:
        frame = frame.sample(n=sample_size, random_state=42)
    corr = frame.corr().fillna(0.0)

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
    ax.set_title("Correlation Heatmap (top-variance numeric features)")
    ax.set_xticks(np.arange(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=75, ha="right", fontsize=7)
    ax.set_yticks(np.arange(len(corr.index)))
    ax.set_yticklabels(corr.index, fontsize=7)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Correlation")
    save_plot(fig, out_dir, "09_correlation_heatmap_top_variance")
    return selected


def plot_feature_drift_heatmap(data: pd.DataFrame, out_dir: Path, top_k: int = 15) -> pd.DataFrame:
    numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
    numeric_cols = [c for c in numeric_cols if c not in ("IsAttack",)]
    if not numeric_cols:
        return pd.DataFrame()

    safe_numeric = data[numeric_cols].replace([np.inf, -np.inf], np.nan)
    variances = safe_numeric.var(numeric_only=True).sort_values(ascending=False)
    selected = variances.head(top_k).index.tolist()

    safe_selected = data[selected].replace([np.inf, -np.inf], np.nan)
    day_mean = pd.concat([data[["Day"]], safe_selected], axis=1).groupby("Day")[selected].mean(numeric_only=True)
    global_mean = safe_selected.mean(numeric_only=True)
    global_std = safe_selected.std(numeric_only=True).replace(0, np.nan)
    z = (day_mean - global_mean) / global_std
    z = z.fillna(0.0)

    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(z.values, aspect="auto", cmap="RdBu_r")
    ax.set_title("Feature Drift by Day (z-score of day mean)")
    ax.set_xlabel("Feature")
    ax.set_ylabel("Day")
    ax.set_xticks(np.arange(len(z.columns)))
    ax.set_xticklabels(z.columns, rotation=65, ha="right", fontsize=8)
    ax.set_yticks(np.arange(len(z.index)))
    ax.set_yticklabels(z.index)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("z-score")
    save_plot(fig, out_dir, "10_feature_drift_heatmap")
    return z


def build_summary_markdown(
    out_dir: Path,
    data: pd.DataFrame,
    daily_counts: pd.Series,
    label_counts: pd.Series,
    attack_ratio: pd.DataFrame,
    missing_ratio: pd.Series,
) -> None:
    total_rows = len(data)
    n_days = data["Day"].nunique()
    n_labels = data["LabelNorm"].nunique()
    valid_ts = int(data["TimestampParsed"].notna().sum())
    attack_rows = int(data["IsAttack"].sum())
    attack_share = attack_rows / max(total_rows, 1)

    lines = [
        "# Five-Day Descriptive EDA Summary",
        "",
        "## Dataset Overview",
        f"- Total rows: {total_rows}",
        f"- Distinct days loaded: {n_days}",
        f"- Distinct normalized labels: {n_labels}",
        f"- Rows with valid timestamp: {valid_ts}",
        f"- Attack rows: {attack_rows} ({attack_share:.2%})",
        "",
        "## Rows per Day",
    ]
    for day, count in daily_counts.items():
        lines.append(f"- {day}: {int(count)}")

    lines += [
        "",
        "## Top 10 Labels",
    ]
    for label, count in label_counts.head(10).items():
        lines.append(f"- {label}: {int(count)}")

    lines += [
        "",
        "## Attack Ratio per Day",
    ]
    for day, row in attack_ratio.sort_index().iterrows():
        lines.append(f"- {day}: {row['AttackRatio']:.2%} ({int(row['Attack'])}/{int(row['Total'])})")

    lines += [
        "",
        "## Top 10 Missing-Value Columns",
    ]
    for col, ratio in missing_ratio.head(10).items():
        lines.append(f"- {col}: {ratio:.2%}")

    (out_dir / "EDA_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_data(Path(args.data_dir), args.input_files)
    data.to_csv(out_dir / "all_days_with_basic_tags.csv", index=False)

    daily_counts = plot_row_counts_by_day(data, out_dir)
    label_counts = plot_overall_label_distribution(data, out_dir)
    day_label = plot_day_label_heatmap(data, out_dir)
    attack_ratio = plot_attack_ratio_by_day(data, out_dir)
    hourly = plot_hourly_traffic(data, out_dir)
    missing_ratio = plot_missingness(data, out_dir)

    features = pick_numeric_features(data)
    plot_feature_boxplots_by_day(data, out_dir, features)
    corr_selected = plot_correlation_heatmap(data, out_dir, sample_size=args.sample_size_corr)
    drift = plot_feature_drift_heatmap(data, out_dir)

    daily_counts.rename("rows").to_csv(out_dir / "daily_row_counts.csv")
    label_counts.rename("rows").to_csv(out_dir / "label_counts_overall.csv")
    day_label.to_csv(out_dir / "day_label_counts_top.csv")
    attack_ratio.to_csv(out_dir / "attack_ratio_by_day.csv")
    hourly.to_csv(out_dir / "hourly_volume_by_day.csv", index=False)
    missing_ratio.rename("missing_ratio").to_csv(out_dir / "missing_ratio_by_column.csv")
    if corr_selected:
        pd.Series(corr_selected, name="feature").to_csv(out_dir / "correlation_selected_features.csv", index=False)
    if not drift.empty:
        drift.to_csv(out_dir / "feature_drift_zscore_by_day.csv")

    safe_numeric_all = data.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan)
    numeric_desc = safe_numeric_all.describe(percentiles=[0.5, 0.9, 0.99]).T
    numeric_desc.to_csv(out_dir / "numeric_feature_describe.csv")

    build_summary_markdown(out_dir, data, daily_counts, label_counts, attack_ratio, missing_ratio)
    print(f"EDA done. Outputs in: {out_dir}")
    print(f"Generated figures and tables for {len(data)} rows across {data['Day'].nunique()} days.")


if __name__ == "__main__":
    main()
