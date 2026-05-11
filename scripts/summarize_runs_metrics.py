#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


def parse_run_summary(path: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        value = v.strip()
        if value.isdigit():
            data[key] = int(value)
            continue
        try:
            data[key] = float(value)
        except ValueError:
            data[key] = value
    return data


def parse_simple_yaml(path: Path) -> Dict[str, Any]:
    """
    Minimal parser for this project's 2-level YAML snapshots.
    """
    if not path.exists():
        return {}
    root: Dict[str, Any] = {}
    current_section: Optional[str] = None
    current_list_key: Optional[str] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()

        if indent == 0 and line.endswith(":"):
            current_section = line[:-1]
            root[current_section] = {}
            current_list_key = None
            continue

        if current_section is None:
            continue

        section = root[current_section]

        if line.startswith("- "):
            if current_list_key is not None and isinstance(section.get(current_list_key), list):
                section[current_list_key].append(line[2:].strip())
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            section[key] = []
            current_list_key = key
            continue

        current_list_key = None
        if value.lower() in {"true", "false"}:
            section[key] = value.lower() == "true"
        else:
            try:
                if "." in value:
                    section[key] = float(value)
                else:
                    section[key] = int(value)
            except ValueError:
                section[key] = value.strip("'\"")
    return root


def parse_label_distribution(path: Path) -> Tuple[List[Dict[str, Any]], Counter]:
    rows: List[Dict[str, Any]] = []
    label_counter: Counter = Counter()
    if not path.exists():
        return rows, label_counter

    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            learner_name = (row.get("learner_name") or "").strip()
            if not learner_name:
                continue
            dist_raw = row.get("label_distribution_json") or "{}"
            dist = json.loads(dist_raw)
            total = int(row.get("total_assigned_samples") or 0)
            dominant_count = int(row.get("dominant_count") or 0)
            dominant_ratio = float(row.get("dominant_ratio") or 0.0)

            norm_dist = {str(k): int(v) for k, v in dist.items()}
            label_counter.update(norm_dist)
            rows.append(
                {
                    "learner_name": learner_name,
                    "total_assigned_samples": total,
                    "dominant_label": row.get("dominant_label"),
                    "dominant_count": dominant_count,
                    "dominant_ratio": dominant_ratio,
                    "label_distribution": norm_dist,
                }
            )
    return rows, label_counter


def compute_binary_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_samples = sum(r["total_assigned_samples"] for r in rows)
    actual_benign = sum(r["label_distribution"].get("BENIGN", 0) for r in rows)
    actual_non_benign = total_samples - actual_benign

    benign_row = next((r for r in rows if r["learner_name"] == "BENIGN"), None)
    pred_benign = benign_row["total_assigned_samples"] if benign_row else 0
    pred_non_benign = total_samples - pred_benign

    tp = benign_row["label_distribution"].get("BENIGN", 0) if benign_row else 0
    fp = pred_benign - tp
    fn = actual_benign - tp
    tn = total_samples - tp - fp - fn

    def safe_div(x: float, y: float) -> float:
        return x / y if y else 0.0

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    specificity = safe_div(tn, tn + fp)
    accuracy = safe_div(tp + tn, total_samples)
    f1 = safe_div(2 * precision * recall, precision + recall)

    benign_false_positive_rate = safe_div(fn, actual_benign)
    risk_false_negative_rate = safe_div(fp, actual_non_benign)

    return {
        "totals": {
            "total_assigned_samples": total_samples,
            "actual_benign": actual_benign,
            "actual_non_benign": actual_non_benign,
            "pred_benign": pred_benign,
            "pred_non_benign": pred_non_benign,
        },
        "confusion_matrix_benign_positive": {
            "tp_benign_to_benign": tp,
            "fp_nonbenign_to_benign": fp,
            "fn_benign_to_nonbenign": fn,
            "tn_nonbenign_to_nonbenign": tn,
        },
        "rates": {
            "benign_false_positive_rate": benign_false_positive_rate,
            "risk_false_negative_rate": risk_false_negative_rate,
            "benign_precision": precision,
            "benign_recall": recall,
            "specificity_nonbenign": specificity,
            "accuracy": accuracy,
            "f1_benign": f1,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize run metrics into one JSON.")
    parser.add_argument("--runs-dir", default="outputs/runs", help="Runs directory")
    parser.add_argument(
        "--output-json",
        default="outputs/final_metrics_summary.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_dirs = sorted([p for p in runs_dir.iterdir() if p.is_dir()])
    run_results: List[Dict[str, Any]] = []

    observed_labels_global: Counter = Counter()
    rows_used_vals: List[int] = []
    feature_dim_vals: List[int] = []
    input_files_set = set()
    data_dirs = set()

    print("=== Final Run Metrics (BENIGN-centric) ===")
    for run_dir in run_dirs:
        run_id = run_dir.name
        summary = parse_run_summary(run_dir / "run_summary.txt")
        cfg = parse_simple_yaml(run_dir / "config_snapshot.yaml")
        rows, observed_labels = parse_label_distribution(run_dir / "learner_label_distribution.csv")
        if not rows:
            continue

        metrics = compute_binary_metrics(rows)
        observed_labels_global.update(observed_labels)

        if isinstance(summary.get("rows_used"), int):
            rows_used_vals.append(summary["rows_used"])
        if isinstance(summary.get("feature_dim"), int):
            feature_dim_vals.append(summary["feature_dim"])

        paths_cfg = cfg.get("paths", {})
        if isinstance(paths_cfg, dict):
            data_dir = paths_cfg.get("data_dir")
            if data_dir:
                data_dirs.add(str(data_dir))
            input_files = paths_cfg.get("input_files", [])
            if isinstance(input_files, list):
                for f in input_files:
                    input_files_set.add(str(f))

        rates = metrics["rates"]
        print(
            f"[{run_id}] "
            f"benign_false_positive_rate={rates['benign_false_positive_rate']:.4%}, "
            f"risk_false_negative_rate={rates['risk_false_negative_rate']:.4%}, "
            f"precision={rates['benign_precision']:.4%}, "
            f"recall={rates['benign_recall']:.4%}, "
            f"accuracy={rates['accuracy']:.4%}"
        )

        run_results.append(
            {
                "run_id": run_id,
                "summary": summary,
                "config_key_params": {
                    "stream": cfg.get("stream", {}),
                    "runtime": cfg.get("runtime", {}),
                    "tmagnifier": cfg.get("tmagnifier", {}),
                    "tsieve": cfg.get("tsieve", {}),
                    "tscissors": cfg.get("tscissors", {}),
                },
                "metrics": metrics,
                "learner_stats": {
                    "learner_count_in_distribution_file": len(rows),
                    "low_purity_learners_count_dominant_ratio_lt_0_8": sum(
                        1 for r in rows if r["dominant_ratio"] < 0.8
                    ),
                    "mean_dominant_ratio": (
                        mean([r["dominant_ratio"] for r in rows]) if rows else 0.0
                    ),
                },
                "observed_label_counts_in_assigned_samples": dict(observed_labels),
            }
        )

    overall = {}
    if run_results:
        overall = {
            "run_count": len(run_results),
            "best_run_by_lowest_risk_false_negative_rate": min(
                run_results, key=lambda x: x["metrics"]["rates"]["risk_false_negative_rate"]
            )["run_id"],
            "best_run_by_lowest_benign_false_positive_rate": min(
                run_results, key=lambda x: x["metrics"]["rates"]["benign_false_positive_rate"]
            )["run_id"],
            "average_benign_false_positive_rate": mean(
                [x["metrics"]["rates"]["benign_false_positive_rate"] for x in run_results]
            ),
            "average_risk_false_negative_rate": mean(
                [x["metrics"]["rates"]["risk_false_negative_rate"] for x in run_results]
            ),
        }

    output = {
        "dataset_description": {
            "name": "CICIDS2017 (project stream dataset)",
            "data_directories": sorted(data_dirs),
            "input_files_observed": sorted(input_files_set),
            "rows_used_observed": {
                "min": min(rows_used_vals) if rows_used_vals else None,
                "max": max(rows_used_vals) if rows_used_vals else None,
                "values": sorted(set(rows_used_vals)),
            },
            "feature_dim_observed": sorted(set(feature_dim_vals)),
            "labels_observed_in_assigned_samples_union": sorted(observed_labels_global.keys()),
        },
        "metric_definition": {
            "benign_false_positive_rate": "BENIGN -> non-BENIGN / actual_BENIGN",
            "risk_false_negative_rate": "non-BENIGN -> BENIGN / actual_non_BENIGN",
            "benign_precision": "tp_benign_to_benign / pred_benign",
            "benign_recall": "tp_benign_to_benign / actual_benign",
            "f1_benign": "harmonic_mean(precision, recall)",
        },
        "overall_summary": overall,
        "runs": run_results,
    }

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote JSON summary to: {out_path}")


if __name__ == "__main__":
    main()
