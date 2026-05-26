#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trident_stream.cic_align import RENAME_2019_TO_2017  # noqa: E402

FILES_2017 = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]


def _read_header(csv_path: Path) -> List[str]:
    with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
        line = f.readline().rstrip("\n").rstrip("\r")
    return [c.strip() for c in line.split(",")]


def _load_and_standardize(chunk: pd.DataFrame, rename_map: Dict[str, str]) -> pd.DataFrame:
    chunk.columns = [str(c).strip() for c in chunk.columns]
    return chunk.rename(columns=rename_map)


def _align_one_file(
    src_path: Path,
    dst_path: Path,
    keep_columns: List[str],
    rename_map: Dict[str, str],
    chunksize: int,
) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    first = True
    for chunk in pd.read_csv(src_path, chunksize=chunksize, low_memory=False):
        chunk = _load_and_standardize(chunk, rename_map=rename_map)
        aligned = chunk.reindex(columns=keep_columns)
        aligned.to_csv(dst_path, mode="w" if first else "a", header=first, index=False)
        first = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Align CIC2017 and CIC2019 by mapped same-name features.")
    parser.add_argument("--data-root", default="/home/data", help="Root data directory containing 2017/ and 2019/.")
    parser.add_argument(
        "--out-dir",
        default="outputs/aligned_2017_2019",
        help="Output directory for aligned csv files.",
    )
    parser.add_argument("--chunksize", type=int, default=200000, help="CSV chunk size.")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    dir_2017 = data_root / "2017"
    dir_2019 = data_root / "2019"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files_2017 = [dir_2017 / name for name in FILES_2017 if (dir_2017 / name).exists()]
    files_2019 = sorted(dir_2019.glob("*.csv"))
    if not files_2017:
        raise FileNotFoundError(f"No 2017 csv files found under {dir_2017}")
    if not files_2019:
        raise FileNotFoundError(f"No 2019 csv files found under {dir_2019}")

    header_2017 = _read_header(files_2017[0])
    header_2019_raw = _read_header(files_2019[0])
    header_2019 = [RENAME_2019_TO_2017.get(c, c) for c in header_2019_raw]

    set_2017 = set(header_2017)
    set_2019 = set(header_2019)

    # 保证 Trident 主流程所需字段存在
    essential = {"Timestamp", "Label"}
    common = [c for c in header_2017 if c in set_2019 and c != ""]
    missing_essential = [c for c in essential if c not in set(common)]
    if missing_essential:
        raise ValueError(f"Missing essential columns after alignment: {missing_essential}")

    # 2019 中可能会映射出重复列（例如 Fwd Header Length.1），去重时保留首次出现
    seen = set()
    keep_columns: List[str] = []
    for c in common:
        if c in seen:
            continue
        seen.add(c)
        keep_columns.append(c)

    out_files_2017: List[str] = []
    out_files_2019: List[str] = []

    for p in files_2017:
        out_name = f"2017_{p.name}"
        _align_one_file(
            src_path=p,
            dst_path=out_dir / out_name,
            keep_columns=keep_columns,
            rename_map={},
            chunksize=args.chunksize,
        )
        out_files_2017.append(out_name)

    for p in files_2019:
        out_name = f"2019_{p.name}"
        _align_one_file(
            src_path=p,
            dst_path=out_dir / out_name,
            keep_columns=keep_columns,
            rename_map=RENAME_2019_TO_2017,
            chunksize=args.chunksize,
        )
        out_files_2019.append(out_name)

    report = {
        "keep_columns_count": len(keep_columns),
        "keep_columns": keep_columns,
        "dropped_only_2017_columns": [c for c in header_2017 if c not in set_2019],
        "dropped_only_2019_columns_after_mapping": [c for c in header_2019 if c not in set_2017],
        "rename_2019_to_2017": RENAME_2019_TO_2017,
        "output_files_2017": out_files_2017,
        "output_files_2019": out_files_2019,
    }
    (out_dir / "alignment_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Aligned dataset generated at: {out_dir}")
    print(f"Kept columns: {len(keep_columns)}")
    print(f"Output files: {len(out_files_2017) + len(out_files_2019)}")


if __name__ == "__main__":
    main()

