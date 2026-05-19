#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


TARGET_ALIASES = [
    "FWD Init Win Bytes",
    "Fwd Init Win Bytes",
    "fwd_init_win_bytes",
]

LABEL_ALIASES = ["label", "Label"]
YEAR_ALIASES = ["year_tag", "year", "Year", "yearTag"]


def resolve_column(columns: Iterable[str], aliases: list[str]) -> Optional[str]:
    col_list = [str(c) for c in columns]
    col_set = set(col_list)
    for alias in aliases:
        if alias in col_set:
            return alias
    norm_map = {str(c).strip().lower(): str(c) for c in col_list}
    for alias in aliases:
        key = alias.strip().lower()
        if key in norm_map:
            return norm_map[key]
    return None


@dataclass
class GroupStats:
    total_rows: int = 0
    replaced_neg1_rows: int = 0
    outlier_rows: int = 0
    non_numeric_rows: int = 0


def derive_paths(input_csv: Path, output_csv: Optional[Path], report_json: Optional[Path]) -> tuple[Path, Path]:
    if output_csv is None:
        output_csv = input_csv.with_name(f"{input_csv.stem}_clean_fwd_init_win.csv")
    if report_json is None:
        report_json = input_csv.with_name(f"{input_csv.stem}_fwd_init_win_outlier_report.json")
    return output_csv, report_json


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean FWD Init Win Bytes (-1->0) and analyze outliers."
    )
    parser.add_argument(
        "--input-csv",
        required=True,
        help="Path to input CSV.",
    )
    parser.add_argument(
        "--output-csv",
        default="",
        help="Path to cleaned CSV. Default: <input>_clean_fwd_init_win.csv",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="Path to outlier report JSON. Default: <input>_fwd_init_win_outlier_report.json",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=200000,
        help="CSV chunksize for streaming.",
    )
    args = parser.parse_args()

    input_csv = Path(args.input_csv).expanduser().resolve()
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    output_csv, report_json = derive_paths(
        input_csv=input_csv,
        output_csv=Path(args.output_csv).expanduser().resolve() if args.output_csv else None,
        report_json=Path(args.report_json).expanduser().resolve() if args.report_json else None,
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    header = pd.read_csv(input_csv, nrows=0)
    columns = [str(c) for c in header.columns]
    target_col = resolve_column(columns, TARGET_ALIASES)
    if target_col is None:
        raise KeyError(f"Cannot resolve target column from aliases={TARGET_ALIASES}")
    label_col = resolve_column(columns, LABEL_ALIASES)
    year_col = resolve_column(columns, YEAR_ALIASES)

    print(f"[1/4] Input: {input_csv}", flush=True)
    print(f"      target_col={target_col}, label_col={label_col}, year_col={year_col}", flush=True)

    total_rows = 0
    neg1_rows = 0
    non_numeric_rows = 0
    cleaned_values: list[np.ndarray] = []

    for chunk in pd.read_csv(input_csv, chunksize=args.chunksize, low_memory=False):
        total_rows += len(chunk)
        raw = pd.to_numeric(chunk[target_col], errors="coerce")
        non_numeric_rows += int(raw.isna().sum())
        neg1_rows += int((raw == -1).sum())
        cleaned = raw.mask(raw == -1, 0.0)
        cleaned_values.append(cleaned.fillna(0.0).to_numpy(dtype=np.float64))

    if total_rows == 0:
        raise ValueError("Input CSV has no rows.")

    values = np.concatenate(cleaned_values, axis=0)
    q1 = float(np.quantile(values, 0.25))
    q3 = float(np.quantile(values, 0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    overall_outlier_mask = (values < lower) | (values > upper)
    overall_outlier_rows = int(overall_outlier_mask.sum())
    overall_outlier_ratio = overall_outlier_rows / len(values)

    print("[2/4] Thresholds computed.", flush=True)
    print(
        f"      q1={q1:.6f}, q3={q3:.6f}, iqr={iqr:.6f}, lower={lower:.6f}, upper={upper:.6f}, outlier_ratio={overall_outlier_ratio:.4%}",
        flush=True,
    )

    if output_csv.exists():
        output_csv.unlink()

    by_label: Dict[str, GroupStats] = {}
    by_year: Dict[str, GroupStats] = {}
    by_label_year: Dict[str, GroupStats] = {}

    wrote_header = False
    for chunk in pd.read_csv(input_csv, chunksize=args.chunksize, low_memory=False):
        raw = pd.to_numeric(chunk[target_col], errors="coerce")
        clean = raw.mask(raw == -1, 0.0).fillna(0.0)
        outlier_mask = (clean < lower) | (clean > upper)

        local_non_numeric = raw.isna()
        local_replaced = raw == -1

        if label_col is not None:
            labels = chunk[label_col].astype(str).fillna("UNKNOWN_LABEL")
        else:
            labels = pd.Series(["ALL"] * len(chunk))
        if year_col is not None:
            years = chunk[year_col].astype(str).fillna("UNKNOWN_YEAR")
        else:
            years = pd.Series(["ALL"] * len(chunk))

        for label, year, rep, outl, nonn in zip(labels, years, local_replaced, outlier_mask, local_non_numeric):
            lbl = str(label)
            yr = str(year)
            key_ly = f"{yr}|{lbl}"

            s_lbl = by_label.setdefault(lbl, GroupStats())
            s_yr = by_year.setdefault(yr, GroupStats())
            s_ly = by_label_year.setdefault(key_ly, GroupStats())

            for s in (s_lbl, s_yr, s_ly):
                s.total_rows += 1
                if bool(rep):
                    s.replaced_neg1_rows += 1
                if bool(outl):
                    s.outlier_rows += 1
                if bool(nonn):
                    s.non_numeric_rows += 1

        out_chunk = chunk.copy()
        out_chunk[target_col] = clean
        out_chunk.to_csv(
            output_csv,
            mode="a",
            index=False,
            header=not wrote_header,
        )
        wrote_header = True

    def top_groups(stats_map: Dict[str, GroupStats], top_k: int = 30) -> list[dict]:
        rows = []
        for name, st in stats_map.items():
            total = max(1, st.total_rows)
            rows.append(
                {
                    "group": name,
                    "rows": st.total_rows,
                    "replaced_neg1_rows": st.replaced_neg1_rows,
                    "replaced_neg1_ratio": st.replaced_neg1_rows / total,
                    "outlier_rows": st.outlier_rows,
                    "outlier_ratio": st.outlier_rows / total,
                    "non_numeric_rows": st.non_numeric_rows,
                    "non_numeric_ratio": st.non_numeric_rows / total,
                }
            )
        rows.sort(key=lambda r: (r["outlier_ratio"], r["rows"]), reverse=True)
        return rows[:top_k]

    report = {
        "input_csv": str(input_csv),
        "output_csv": str(output_csv),
        "target_column": target_col,
        "label_column": label_col,
        "year_column": year_col,
        "cleaning_rule": "FWD Init Win Bytes == -1 -> 0; non-numeric -> 0",
        "outlier_rule": {
            "method": "IQR",
            "q1": q1,
            "q3": q3,
            "iqr": iqr,
            "lower_bound": lower,
            "upper_bound": upper,
        },
        "overall": {
            "rows": int(total_rows),
            "replaced_neg1_rows": int(neg1_rows),
            "replaced_neg1_ratio": float(neg1_rows / total_rows),
            "non_numeric_rows": int(non_numeric_rows),
            "non_numeric_ratio": float(non_numeric_rows / total_rows),
            "outlier_rows_after_clean": int(overall_outlier_rows),
            "outlier_ratio_after_clean": float(overall_outlier_ratio),
            "cleaned_value_min": float(values.min()),
            "cleaned_value_max": float(values.max()),
            "cleaned_value_mean": float(values.mean()),
            "cleaned_value_std": float(values.std()),
            "p50": float(np.quantile(values, 0.5)),
            "p90": float(np.quantile(values, 0.9)),
            "p95": float(np.quantile(values, 0.95)),
            "p99": float(np.quantile(values, 0.99)),
            "p999": float(np.quantile(values, 0.999)),
        },
        "top_label_outliers": top_groups(by_label, top_k=40),
        "top_year_outliers": top_groups(by_year, top_k=20),
        "top_year_label_outliers": top_groups(by_label_year, top_k=60),
    }

    with report_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[3/4] Cleaned CSV written.", flush=True)
    print(f"      {output_csv}", flush=True)
    print("[4/4] Outlier report written.", flush=True)
    print(f"      {report_json}", flush=True)


if __name__ == "__main__":
    main()
