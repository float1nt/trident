import random
import re
from pathlib import Path
from typing import List, Optional

import numpy as np
import torch

YEAR_LABEL_RE = re.compile(r"^(20\d{2})\|(.*)$")


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def ordered_data_files(data_dir: Path, input_files: Optional[List[str]] = None) -> List[Path]:
    if input_files:
        order = input_files
    else:
        order = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]
    return [data_dir / name for name in order if (data_dir / name).exists()]


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


def has_year_prefix(raw_label: str) -> bool:
    return YEAR_LABEL_RE.match(str(raw_label).strip()) is not None


def split_year_label(raw_label: str) -> tuple[Optional[str], str]:
    s = str(raw_label).strip()
    m = YEAR_LABEL_RE.match(s)
    if not m:
        return None, s
    return m.group(1), m.group(2).strip()


def normalize_base_label(x: str) -> str:
    _, raw = split_year_label(x)
    s = str(raw).strip().upper()
    if s == "BENIGN" or s.startswith("BENIGN|"):
        return "BENIGN"
    return s


def normalize_label(x: str) -> str:
    year, raw = split_year_label(x)
    s = str(raw).strip()
    base = normalize_base_label(x)

    # Keep BENIGN subtype if present, e.g. 2026|BENIGN|DNS.
    if s.upper().startswith("BENIGN|"):
        subtype = s.split("|", 1)[1].strip()
        if subtype:
            if year:
                return f"{year}|BENIGN|{subtype.upper()}"
            return f"BENIGN|{subtype.upper()}"

    if year:
        return f"{year}|{base}"
    return base


def is_benign_label(x: str) -> bool:
    return normalize_base_label(x) == "BENIGN"

