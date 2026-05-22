#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


RENAME_2019_TO_2017: Dict[str, str] = {
    "Source IP": "Src IP",
    "Source Port": "Src Port",
    "Destination IP": "Dst IP",
    "Destination Port": "Dst Port",
    "Total Fwd Packets": "Total Fwd Packet",
    "Total Backward Packets": "Total Bwd packets",
    "Total Length of Fwd Packets": "Total Length of Fwd Packet",
    "Total Length of Bwd Packets": "Total Length of Bwd Packet",
    "Min Packet Length": "Packet Length Min",
    "Max Packet Length": "Packet Length Max",
    "CWE Flag Count": "CWR Flag Count",
    "Avg Fwd Segment Size": "Fwd Segment Size Avg",
    "Avg Bwd Segment Size": "Bwd Segment Size Avg",
    "Fwd Avg Bytes/Bulk": "Fwd Bytes/Bulk Avg",
    "Fwd Avg Packets/Bulk": "Fwd Packet/Bulk Avg",
    "Fwd Avg Bulk Rate": "Fwd Bulk Rate Avg",
    "Bwd Avg Bytes/Bulk": "Bwd Bytes/Bulk Avg",
    "Bwd Avg Packets/Bulk": "Bwd Packet/Bulk Avg",
    "Bwd Avg Bulk Rate": "Bwd Bulk Rate Avg",
    "Init_Win_bytes_forward": "FWD Init Win Bytes",
    "Init_Win_bytes_backward": "Bwd Init Win Bytes",
    "act_data_pkt_fwd": "Fwd Act Data Pkts",
    "min_seg_size_forward": "Fwd Seg Size Min",
}

FILES_2017 = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]
def _benign_label(year_tag: str, original_label: str) -> str:
    """Emit Trident-compatible year-prefixed labels (e.g. 2017|BENIGN)."""
    if year_tag == "2026":
        sub = str(original_label).strip()
        if sub and sub.upper() not in {"BENIGN", "BENIGN_TYPE"}:
            return f"{year_tag}|BENIGN|{sub.upper()}"
    return f"{year_tag}|BENIGN"


def detect_label_column(columns: List[str]) -> str:
    candidates = ["Label", "label", "Class", "class", "Attack", "attack", "Target", "target"]
    for c in candidates:
        if c in columns:
            return c
    raise ValueError(f"Unable to detect label column from headers: {columns[:10]} ...")


def standardize_columns(df: pd.DataFrame, year_tag: str) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    if year_tag == "2019":
        df = df.rename(columns=RENAME_2019_TO_2017)
    return df


def standardized_header(path: Path, year_tag: str) -> List[str]:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    header = [str(c).strip() for c in header]
    if year_tag == "2019":
        header = [RENAME_2019_TO_2017.get(c, c) for c in header]
    return header


def iter_files(dir_2017: Path, dir_2019: Path, file_2026: Path) -> List[tuple[str, Path]]:
    files: List[tuple[str, Path]] = []
    files.extend([("2017", dir_2017 / name) for name in FILES_2017 if (dir_2017 / name).exists()])
    files.extend([("2019", p) for p in sorted(dir_2019.glob("*.csv"))])
    files.append(("2026", file_2026))
    return files


def sample_subset(
    subset: pd.DataFrame,
    take_n: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    if take_n <= 0 or subset.empty:
        return subset.iloc[0:0]
    if len(subset) <= take_n:
        return subset
    picks = rng.choice(subset.index.to_numpy(), size=take_n, replace=False)
    return subset.loc[picks]


def write_rows(
    out_path: Path,
    rows: pd.DataFrame,
    first_write: bool,
    ordered_columns: List[str],
) -> bool:
    if rows.empty:
        return first_write
    rows = rows.reindex(columns=ordered_columns)
    rows.to_csv(out_path, index=False, mode="w" if first_write else "a", header=first_write)
    return False


def process_file(
    file_path: Path,
    year_tag: str,
    common_features: List[str],
    benign_cap: int,
    attack_cap: int,
    kept_benign: Dict[str, int],
    kept_attack: Counter,
    total_benign: Dict[str, int],
    total_attack: Counter,
    output_csv: Path,
    ordered_columns: List[str],
    first_write: bool,
    chunksize: int,
    rng: np.random.Generator,
    benign_multiplier: float,
) -> bool:
    for chunk in pd.read_csv(file_path, low_memory=False, chunksize=chunksize):
        chunk = standardize_columns(chunk, year_tag=year_tag)
        label_col = detect_label_column(list(chunk.columns))
        raw_label = chunk[label_col].astype(str).str.strip()
        upper_label = raw_label.str.upper()

        if year_tag == "2026":
            benign_mask = pd.Series(True, index=chunk.index)
        else:
            benign_mask = upper_label.eq("BENIGN")
        attack_mask = ~benign_mask

        total_benign[year_tag] += int(benign_mask.sum())

        attack_labels = raw_label[attack_mask].replace({"": "UNKNOWN_ATTACK"})
        if not attack_labels.empty:
            total_attack.update(attack_labels.value_counts().to_dict())

        benign_remaining = max(0, benign_cap - kept_benign[year_tag]) if benign_cap > 0 else -1
        if benign_cap <= 0 or benign_remaining > 0:
            benign_rows = chunk.loc[benign_mask, common_features].copy()
            benign_rows["Label"] = [
                _benign_label(year_tag, ol) for ol in raw_label.loc[benign_mask].to_numpy()
            ]
            benign_rows["year_tag"] = year_tag
            benign_rows["original_label"] = raw_label.loc[benign_mask].to_numpy()
            benign_rows["benign_type"] = np.where(
                year_tag == "2026",
                benign_rows["original_label"].astype(str),
                "",
            )
            if benign_cap <= 0:
                benign_sample = benign_rows
            else:
                benign_sample = sample_subset(benign_rows, benign_remaining, rng=rng)

            if benign_multiplier > 1.0 and not benign_sample.empty:
                extra_n = int(round((benign_multiplier - 1.0) * len(benign_sample)))
                if extra_n > 0:
                    picks = rng.choice(benign_sample.index.to_numpy(), size=extra_n, replace=True)
                    benign_extra = benign_sample.loc[picks].copy()
                    benign_sample = pd.concat([benign_sample, benign_extra], ignore_index=True)

            kept_benign[year_tag] += len(benign_sample)
            first_write = write_rows(output_csv, benign_sample, first_write, ordered_columns)

        attack_work = chunk.loc[attack_mask, common_features].copy()
        if not attack_work.empty:
            attack_work["raw_attack_label"] = raw_label.loc[attack_mask].replace({"": "UNKNOWN_ATTACK"}).to_numpy()
            for attack_label, group in attack_work.groupby("raw_attack_label", sort=False):
                if attack_cap <= 0:
                    picked = group.copy()
                else:
                    remaining = max(0, attack_cap - int(kept_attack[attack_label]))
                    if remaining <= 0:
                        continue
                    picked = sample_subset(group, remaining, rng=rng).copy()
                if picked.empty:
                    continue
                base = str(attack_label).strip().upper().replace(" ", "_")
                picked["Label"] = f"{year_tag}|{base}"
                picked["year_tag"] = year_tag
                picked["original_label"] = attack_label
                picked["benign_type"] = ""
                picked = picked.drop(columns=["raw_attack_label"], errors="ignore")
                kept_attack[attack_label] += len(picked)
                first_write = write_rows(output_csv, picked, first_write, ordered_columns)

    return first_write


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample and align CICIDS2017/2019/2026 into one dataset.")
    parser.add_argument("--dir-2017", default="data/cic2017")
    parser.add_argument("--dir-2019", default="data/cicids2019")
    parser.add_argument("--file-2026", default="data/cicids2026.csv")
    parser.add_argument("--output-csv", default="data/aligned_2017_2019_2026_sampled.csv")
    parser.add_argument("--report-json", default="data/aligned_2017_2019_2026_sampled.report.json")
    parser.add_argument("--benign-per-year", type=int, default=100000)
    parser.add_argument("--attack-per-type", type=int, default=10000)
    parser.add_argument(
        "--benign-multiplier",
        type=float,
        default=1.0,
        help="Multiplier for kept benign rows (e.g., 10 keeps attack unchanged and expands benign 10x).",
    )
    parser.add_argument("--chunksize", type=int, default=200000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dir_2017 = Path(args.dir_2017)
    dir_2019 = Path(args.dir_2019)
    file_2026 = Path(args.file_2026)
    output_csv = Path(args.output_csv)
    report_json = Path(args.report_json)

    files = iter_files(dir_2017=dir_2017, dir_2019=dir_2019, file_2026=file_2026)
    if not files:
        raise FileNotFoundError("No source files found.")

    header_2017 = standardized_header((dir_2017 / FILES_2017[0]), year_tag="2017")
    header_2019 = standardized_header(sorted(dir_2019.glob("*.csv"))[0], year_tag="2019")
    header_2026 = standardized_header(file_2026, year_tag="2026")

    label_2017 = detect_label_column(header_2017)
    label_2019 = detect_label_column(header_2019)
    label_2026 = detect_label_column(header_2026)

    feat_2017 = [c for c in header_2017 if c != label_2017 and c]
    feat_2019 = [c for c in header_2019 if c != label_2019 and c]
    feat_2026 = [c for c in header_2026 if c != label_2026 and c]

    set_2019 = set(feat_2019)
    set_2026 = set(feat_2026)
    common_features = [c for c in feat_2017 if c in set_2019 and c in set_2026]
    if "Timestamp" not in common_features:
        raise ValueError("Timestamp is not in aligned common features.")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        output_csv.unlink()

    rng = np.random.default_rng(args.seed)
    kept_benign = {"2017": 0, "2019": 0, "2026": 0}
    total_benign = {"2017": 0, "2019": 0, "2026": 0}
    kept_attack: Counter = Counter()
    total_attack: Counter = Counter()
    ordered_columns = common_features + ["Label", "year_tag", "original_label", "benign_type"]
    first_write = True

    for file_idx, (year_tag, file_path) in enumerate(files, start=1):
        print(f"[{file_idx}/{len(files)}] Processing {year_tag} -> {file_path}", flush=True)
        if not file_path.exists():
            print(f"  [SKIP] file not found: {file_path}", flush=True)
            continue
        first_write = process_file(
            file_path=file_path,
            year_tag=year_tag,
            common_features=common_features,
            benign_cap=args.benign_per_year,
            attack_cap=args.attack_per_type,
            kept_benign=kept_benign,
            kept_attack=kept_attack,
            total_benign=total_benign,
            total_attack=total_attack,
            output_csv=output_csv,
            ordered_columns=ordered_columns,
            first_write=first_write,
            chunksize=args.chunksize,
            rng=rng,
            benign_multiplier=float(args.benign_multiplier),
        )
        print(
            f"  kept_benign={kept_benign} kept_attack_types={len(kept_attack)}",
            flush=True,
        )

    report_json.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "output_csv": str(output_csv),
        "report_json": str(report_json),
        "source_files": [str(p) for _, p in files],
        "common_feature_count": len(common_features),
        "common_features": common_features,
        "sampling_rules": {
            "benign_per_year": args.benign_per_year,
            "attack_per_type": args.attack_per_type,
            "benign_multiplier": float(args.benign_multiplier),
            "benign_label_mapping": "year_tag|BENIGN",
        },
        "totals_before_sampling": {
            "benign_by_year": total_benign,
            "attack_by_type": dict(total_attack),
        },
        "totals_after_sampling": {
            "benign_by_year": kept_benign,
            "attack_by_type": dict(kept_attack),
        },
        "final_rows": int(sum(kept_benign.values()) + sum(kept_attack.values())),
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] output_csv={output_csv}", flush=True)
    print(f"[DONE] report_json={report_json}", flush=True)
    print(f"[DONE] final_rows={report['final_rows']}", flush=True)


if __name__ == "__main__":
    main()
