#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import yaml

from trident_stream.utils import has_year_prefix, is_benign_label, normalize_label, ordered_data_files


def infer_year_tag(path: Path) -> str:
    name = path.name
    if name.startswith("2017_"):
        return "2017"
    if name.startswith("2019_"):
        return "2019"
    parts = [p.lower() for p in path.parts]
    if "2017" in parts:
        return "2017"
    if "2019" in parts:
        return "2019"
    return "0000"


def add_year_to_label(df: pd.DataFrame, year_tag: str) -> pd.DataFrame:
    if "Label" not in df.columns:
        raise ValueError("Input file missing required column: Label")
    out = df.copy()
    raw = out["Label"].astype(str).str.strip()
    has_year = raw.map(has_year_prefix)
    if year_tag == "0000":
        # Unknown source year: keep labels untouched to avoid creating fake prefixes.
        out["Label"] = raw
        return out
    out["Label"] = raw
    out.loc[~has_year, "Label"] = year_tag + "|" + raw[~has_year]
    return out


def apply_sampling(data: pd.DataFrame, sampling_cfg: Dict[str, Any]) -> pd.DataFrame:
    attack_sample_per_type = int(sampling_cfg.get("attack_sample_per_type", 0))
    benign_sample_max_rows = int(sampling_cfg.get("benign_sample_max_rows", 0))
    benign_sample_per_day = int(sampling_cfg.get("benign_sample_per_day", 0))
    if attack_sample_per_type <= 0 and benign_sample_max_rows <= 0 and benign_sample_per_day <= 0:
        return data

    benign_mask = data["LabelNorm"].map(is_benign_label)
    benign_df = data[benign_mask]
    attack_df = data[~benign_mask]
    rng_seed = int(sampling_cfg.get("seed", 42))
    sampled_frames: List[pd.DataFrame] = []

    if benign_sample_per_day > 0:
        benign_df = benign_df.copy()
        benign_df["__day__"] = benign_df["Timestamp"].dt.strftime("%Y-%m-%d")
        per_day_frames: List[pd.DataFrame] = []
        for _, group in benign_df.groupby("__day__", sort=True):
            if len(group) > benign_sample_per_day:
                picked = group.sample(n=benign_sample_per_day, random_state=rng_seed)
            else:
                picked = group
            per_day_frames.append(picked.drop(columns=["__day__"], errors="ignore"))
        benign_df = (
            pd.concat(per_day_frames, ignore_index=True)
            if per_day_frames
            else benign_df.drop(columns=["__day__"], errors="ignore")
        )
    elif benign_sample_max_rows > 0 and len(benign_df) > benign_sample_max_rows:
        benign_df = benign_df.sample(n=benign_sample_max_rows, random_state=rng_seed)
    sampled_frames.append(benign_df)

    if attack_sample_per_type > 0:
        for _, group in attack_df.groupby("LabelNorm", sort=True):
            if len(group) > attack_sample_per_type:
                sampled_group = group.sample(n=attack_sample_per_type, random_state=rng_seed)
            else:
                sampled_group = group
            sampled_frames.append(sampled_group)
    else:
        sampled_frames.append(attack_df)

    sampled = pd.concat(sampled_frames, ignore_index=True)
    sampled = sampled.sort_values("Timestamp").reset_index(drop=True)
    return sampled


def load_cfg(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _stream_sample_with_chunks(
    files: List[Path],
    sampling_cfg: Dict[str, Any],
    chunksize: int,
) -> tuple[pd.DataFrame, int]:
    attack_sample_per_type = int(sampling_cfg.get("attack_sample_per_type", 0))
    benign_sample_max_rows = int(sampling_cfg.get("benign_sample_max_rows", 0))
    benign_sample_per_day = int(sampling_cfg.get("benign_sample_per_day", 0))

    benign_pool_parts: List[pd.DataFrame] = []
    attack_pool_parts_by_label: Dict[str, List[pd.DataFrame]] = {}
    attack_count_by_label: Dict[str, int] = {}
    benign_kept = 0
    benign_kept_by_day: Dict[str, int] = {}
    rows_before_sampling = 0

    total_files = len(files)
    for f_idx, f in enumerate(files, start=1):
        year_tag = infer_year_tag(f)
        print(
            f"[2/5] Loading file {f_idx}/{total_files}: {f} | year_tag={year_tag} | chunksize={chunksize}",
            flush=True,
        )
        chunk_iter = pd.read_csv(f, low_memory=False, chunksize=chunksize)
        for c_idx, chunk in enumerate(chunk_iter, start=1):
            chunk = add_year_to_label(chunk, year_tag=year_tag)
            chunk["Timestamp"] = pd.to_datetime(chunk["Timestamp"], errors="coerce")
            chunk = chunk.dropna(subset=["Timestamp"])
            chunk["LabelNorm"] = chunk["Label"].map(normalize_label)
            rows_before_sampling += len(chunk)
            print(
                f"       chunk={c_idx} valid_rows={len(chunk)} cumulative_rows={rows_before_sampling}",
                flush=True,
            )

            benign_mask = chunk["LabelNorm"].map(is_benign_label)
            benign_chunk = chunk[benign_mask]
            attack_chunk = chunk[~benign_mask]

            if benign_sample_per_day > 0:
                if not benign_chunk.empty:
                    benign_chunk = benign_chunk.copy()
                    benign_chunk["__day__"] = benign_chunk["Timestamp"].dt.strftime("%Y-%m-%d")
                    per_day_take: List[pd.DataFrame] = []
                    for day_key, g in benign_chunk.groupby("__day__", sort=False):
                        kept = benign_kept_by_day.get(str(day_key), 0)
                        remain = benign_sample_per_day - kept
                        if remain <= 0:
                            continue
                        take = g.iloc[:remain].drop(columns=["__day__"], errors="ignore")
                        if not take.empty:
                            per_day_take.append(take.copy())
                            benign_kept_by_day[str(day_key)] = kept + len(take)
                    if per_day_take:
                        benign_pool_parts.append(pd.concat(per_day_take, ignore_index=True))
            elif benign_sample_max_rows > 0:
                remain = benign_sample_max_rows - benign_kept
                if remain > 0 and not benign_chunk.empty:
                    take = benign_chunk.iloc[:remain].copy()
                    benign_pool_parts.append(take)
                    benign_kept += len(take)
            else:
                if not benign_chunk.empty:
                    benign_pool_parts.append(benign_chunk.copy())

            if attack_sample_per_type > 0:
                for label, g in attack_chunk.groupby("LabelNorm", sort=False):
                    key = str(label)
                    kept = attack_count_by_label.get(key, 0)
                    remain = attack_sample_per_type - kept
                    if remain <= 0:
                        continue
                    take = g.iloc[:remain].copy()
                    if not take.empty:
                        attack_pool_parts_by_label.setdefault(key, []).append(take)
                        attack_count_by_label[key] = kept + len(take)
            else:
                if not attack_chunk.empty:
                    attack_pool_parts_by_label.setdefault("__ALL_ATTACK__", []).append(attack_chunk.copy())

    sampled_frames: List[pd.DataFrame] = []
    if benign_pool_parts:
        sampled_frames.append(pd.concat(benign_pool_parts, ignore_index=True))
    for parts in attack_pool_parts_by_label.values():
        if parts:
            sampled_frames.append(pd.concat(parts, ignore_index=True))

    if not sampled_frames:
        return pd.DataFrame(), rows_before_sampling

    sampled = pd.concat(sampled_frames, ignore_index=True)
    sampled = sampled.sort_values("Timestamp").reset_index(drop=True)
    return sampled, rows_before_sampling


def _stream_passthrough_to_csv(
    files: List[Path],
    output_csv: Path,
    chunksize: int,
) -> tuple[int, int, int, Dict[str, int]]:
    rows_before_sampling = 0
    benign_after = 0
    attack_after = 0
    label_counts_after: Dict[str, int] = {}
    wrote_header = False

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        output_csv.unlink()

    total_files = len(files)
    for f_idx, f in enumerate(files, start=1):
        year_tag = infer_year_tag(f)
        print(
            f"[2/5] Loading file {f_idx}/{total_files}: {f} | year_tag={year_tag} | chunksize={chunksize}",
            flush=True,
        )
        chunk_iter = pd.read_csv(f, low_memory=False, chunksize=chunksize)
        for c_idx, chunk in enumerate(chunk_iter, start=1):
            chunk = add_year_to_label(chunk, year_tag=year_tag)
            chunk["Timestamp"] = pd.to_datetime(chunk["Timestamp"], errors="coerce")
            chunk = chunk.dropna(subset=["Timestamp"])
            chunk["LabelNorm"] = chunk["Label"].map(normalize_label)
            rows_before_sampling += len(chunk)
            benign_n = int(chunk["LabelNorm"].map(is_benign_label).sum())
            benign_after += benign_n
            attack_after += int(len(chunk) - benign_n)
            for label, n in chunk["LabelNorm"].value_counts().to_dict().items():
                k = str(label)
                label_counts_after[k] = int(label_counts_after.get(k, 0) + int(n))
            print(
                f"       chunk={c_idx} valid_rows={len(chunk)} cumulative_rows={rows_before_sampling}",
                flush=True,
            )
            chunk.drop(columns=["LabelNorm"], errors="ignore").to_csv(
                output_csv,
                index=False,
                mode="a",
                header=not wrote_header,
            )
            wrote_header = True

    return rows_before_sampling, benign_after, attack_after, label_counts_after


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prebuild sampled aligned dataset with year-tagged labels for faster reruns.",
    )
    parser.add_argument("--config", default="configs/config.yaml", help="Config path.")
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Override output sampled CSV path.",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Override output report JSON path.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=None,
        help="Override rows per chunk for streaming read; <=0 means full-file read.",
    )
    args = parser.parse_args()

    cfg = load_cfg(Path(args.config))
    sampling_cfg = cfg.get("sampling", {})
    if not isinstance(sampling_cfg, dict):
        raise ValueError("Config field 'sampling' must be a mapping/object when provided.")

    data_dir = Path(sampling_cfg.get("data_dir", cfg["paths"]["data_dir"]))
    input_files = sampling_cfg.get("input_files", cfg["paths"].get("input_files"))
    output_csv = Path(
        args.output_csv
        or sampling_cfg.get("output_csv")
        or "data/aligned_2017_2019_sampled_year_tagged.csv"
    )
    report_json = Path(
        args.report_json
        or sampling_cfg.get("report_json")
        or "data/aligned_2017_2019_sampled_year_tagged.report.json"
    )
    chunksize = int(
        args.chunksize
        if args.chunksize is not None
        else sampling_cfg.get("chunksize", 200000)
    )
    effective_sampling_cfg: Dict[str, Any] = {
        "seed": int(sampling_cfg.get("seed", cfg.get("runtime", {}).get("seed", 42))),
        "attack_sample_per_type": int(
            sampling_cfg.get(
                "attack_sample_per_type",
                cfg.get("runtime", {}).get("attack_sample_per_type", 0),
            )
        ),
        "benign_sample_max_rows": int(
            sampling_cfg.get(
                "benign_sample_max_rows",
                cfg.get("runtime", {}).get("benign_sample_max_rows", 0),
            )
        ),
        "benign_sample_per_day": int(sampling_cfg.get("benign_sample_per_day", 0)),
    }
    files = ordered_data_files(data_dir, input_files=input_files)
    if not files:
        raise FileNotFoundError(f"No input files found in {data_dir}")

    t0 = time.perf_counter()
    print(
        f"[1/5] Start preparing sampled dataset | files={len(files)} | config={args.config}",
        flush=True,
    )

    no_sampling = (
        int(effective_sampling_cfg["attack_sample_per_type"]) <= 0
        and int(effective_sampling_cfg["benign_sample_max_rows"]) <= 0
        and int(effective_sampling_cfg["benign_sample_per_day"]) <= 0
    )

    if chunksize > 0 and no_sampling:
        print("[3/5] Streaming passthrough mode (no sampling)...", flush=True)
        print(f"[5/5] Writing sampled csv: {output_csv}", flush=True)
        rows_before_sampling, benign_after, attack_after, label_counts_after = _stream_passthrough_to_csv(
            files=files,
            output_csv=output_csv,
            chunksize=chunksize,
        )
        data_rows_for_report = rows_before_sampling
        rows_after_sampling = rows_before_sampling
    elif chunksize > 0:
        print("[3/5] Streaming read + sampling...", flush=True)
        sampled, rows_before_sampling = _stream_sample_with_chunks(
            files=files,
            sampling_cfg=effective_sampling_cfg,
            chunksize=chunksize,
        )
        data_rows_for_report = rows_before_sampling
        rows_after_sampling = int(len(sampled))
        benign_after = int(sampled["LabelNorm"].map(is_benign_label).sum())
        attack_after = int((~sampled["LabelNorm"].map(is_benign_label)).sum())
        label_counts_after = {
            str(k): int(v) for k, v in sampled["LabelNorm"].value_counts().to_dict().items()
        }
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        print(f"[5/5] Writing sampled csv: {output_csv}", flush=True)
        sampled.drop(columns=["LabelNorm"], errors="ignore").to_csv(output_csv, index=False)
    else:
        print("[3/5] Full-file read mode...", flush=True)
        frames: List[pd.DataFrame] = []
        cumulative_rows = 0
        for idx, f in enumerate(files, start=1):
            year_tag = infer_year_tag(f)
            print(
                f"[2/5] Loading file {idx}/{len(files)}: {f} | year_tag={year_tag}",
                flush=True,
            )
            chunk = pd.read_csv(f, low_memory=False)
            chunk = add_year_to_label(chunk, year_tag=year_tag)
            frames.append(chunk)
            cumulative_rows += len(chunk)
            print(
                f"       loaded_rows={len(chunk)} | cumulative_rows={cumulative_rows}",
                flush=True,
            )

        print("[4/5] Applying sampling strategy...", flush=True)
        data = pd.concat(frames, ignore_index=True)
        data["Timestamp"] = pd.to_datetime(data["Timestamp"], errors="coerce")
        data = data.dropna(subset=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
        data["LabelNorm"] = data["Label"].map(normalize_label)
        sampled = apply_sampling(data, sampling_cfg=effective_sampling_cfg)
        data_rows_for_report = int(len(data))
        rows_after_sampling = int(len(sampled))
        benign_after = int(sampled["LabelNorm"].map(is_benign_label).sum())
        attack_after = int((~sampled["LabelNorm"].map(is_benign_label)).sum())
        label_counts_after = {
            str(k): int(v) for k, v in sampled["LabelNorm"].value_counts().to_dict().items()
        }
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        print(f"[5/5] Writing sampled csv: {output_csv}", flush=True)
        sampled.drop(columns=["LabelNorm"], errors="ignore").to_csv(output_csv, index=False)

    report = {
        "config": str(Path(args.config)),
        "source_data_dir": str(data_dir),
        "source_files": [str(x) for x in files],
        "rows_before_sampling": int(data_rows_for_report),
        "rows_after_sampling": int(rows_after_sampling),
        "benign_after_sampling": int(benign_after),
        "attack_after_sampling": int(attack_after),
        "label_counts_after_sampling": label_counts_after,
        "output_csv": str(output_csv),
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = time.perf_counter() - t0
    print(f"Sampled dataset saved: {output_csv}", flush=True)
    print(f"Report saved: {report_json}", flush=True)
    print(f"Rows before sampling: {data_rows_for_report}", flush=True)
    print(f"Rows after sampling: {rows_after_sampling}", flush=True)
    print(f"Elapsed: {elapsed:.2f}s", flush=True)


if __name__ == "__main__":
    main()
