#!/usr/bin/env python3
import argparse
import itertools
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def _safe_div(x: float, y: float) -> float:
    return float(x / y) if y else 0.0


def _normalize_dist(dist: Dict[str, int]) -> Dict[str, float]:
    total = float(sum(int(v) for v in dist.values()))
    if total <= 0:
        return {}
    return {str(k): float(int(v) / total) for k, v in dist.items()}


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _jsd(p: np.ndarray, q: np.ndarray) -> float:
    """
    Jensen-Shannon divergence with ln base.
    """
    m = 0.5 * (p + q)
    eps = 1e-12
    p = np.clip(p, eps, 1.0)
    q = np.clip(q, eps, 1.0)
    m = np.clip(m, eps, 1.0)
    kl_pm = np.sum(p * np.log(p / m))
    kl_qm = np.sum(q * np.log(q / m))
    return float(0.5 * (kl_pm + kl_qm))


def _build_vectors(
    dist_a: Dict[str, float], dist_b: Dict[str, float]
) -> Tuple[np.ndarray, np.ndarray]:
    keys = sorted(set(dist_a.keys()).union(dist_b.keys()))
    va = np.array([dist_a.get(k, 0.0) for k in keys], dtype=float)
    vb = np.array([dist_b.get(k, 0.0) for k in keys], dtype=float)
    return va, vb


def analyze_overlap(
    run_dir: Path,
    min_samples: int,
    candidate_score_threshold: float,
    candidate_js_sim_threshold: float,
    candidate_handoff_threshold: float,
) -> Dict[str, object]:
    profile_path = run_dir / "learner_label_distribution.csv"
    assign_path = run_dir / "sample_learner_assignments.csv"
    if not profile_path.exists():
        raise FileNotFoundError(f"Missing file: {profile_path}")
    if not assign_path.exists():
        raise FileNotFoundError(f"Missing file: {assign_path}")

    prof = pd.read_csv(profile_path)
    # UNKNOWN bucket is useful for metrics, but not for merge candidates.
    prof = prof[prof["learner_name"] != "UNKNOWN"].copy()
    prof = prof[prof["total_assigned_samples"] >= min_samples].copy()
    prof = prof.reset_index(drop=True)

    if prof.empty:
        return {
            "run_dir": str(run_dir),
            "message": f"No learners with total_assigned_samples >= {min_samples}",
            "pair_count": 0,
            "candidate_count": 0,
        }

    # Prepare per-learner metadata
    learner_meta: Dict[str, Dict[str, object]] = {}
    for _, row in prof.iterrows():
        name = str(row["learner_name"])
        dist_raw = json.loads(str(row["label_distribution_json"]))
        dist = {str(k): int(v) for k, v in dist_raw.items()}
        learner_meta[name] = {
            "total_assigned_samples": int(row["total_assigned_samples"]),
            "dominant_label": str(row["dominant_label"]),
            "dominant_ratio": float(row["dominant_ratio"]),
            "dist_raw": dist,
            "dist_norm": _normalize_dist(dist),
        }

    # Build temporal handoff counts
    assign = pd.read_csv(assign_path, usecols=["assigned_learner"])
    seq = assign["assigned_learner"].astype(str).tolist()
    learner_counts = assign["assigned_learner"].astype(str).value_counts().to_dict()
    handoff_counts: Dict[Tuple[str, str], int] = {}
    for i in range(1, len(seq)):
        a = seq[i - 1]
        b = seq[i]
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        handoff_counts[key] = handoff_counts.get(key, 0) + 1

    # Pairwise overlap metrics
    rows: List[Dict[str, object]] = []
    names = sorted(learner_meta.keys())
    for a, b in itertools.combinations(names, 2):
        ma = learner_meta[a]
        mb = learner_meta[b]
        va, vb = _build_vectors(ma["dist_norm"], mb["dist_norm"])  # type: ignore[arg-type]
        cosine_sim = _cosine_sim(va, vb)
        js_div = _jsd(va, vb)
        js_sim = float(max(0.0, 1.0 - js_div))
        dominant_same = int(ma["dominant_label"] == mb["dominant_label"])  # type: ignore[index]
        key = tuple(sorted((a, b)))
        handoff = int(handoff_counts.get(key, 0))
        min_count = min(int(learner_counts.get(a, 0)), int(learner_counts.get(b, 0)))
        handoff_rate = _safe_div(handoff, min_count)
        # Composite score: distribution similarity + temporal competition + dominant label match.
        overlap_score = (
            0.50 * js_sim
            + 0.25 * cosine_sim
            + 0.20 * min(1.0, handoff_rate)
            + 0.05 * dominant_same
        )
        rows.append(
            {
                "learner_a": a,
                "learner_b": b,
                "samples_a": int(ma["total_assigned_samples"]),  # type: ignore[index]
                "samples_b": int(mb["total_assigned_samples"]),  # type: ignore[index]
                "dominant_label_a": str(ma["dominant_label"]),  # type: ignore[index]
                "dominant_label_b": str(mb["dominant_label"]),  # type: ignore[index]
                "dominant_same": dominant_same,
                "dominant_ratio_a": float(ma["dominant_ratio"]),  # type: ignore[index]
                "dominant_ratio_b": float(mb["dominant_ratio"]),  # type: ignore[index]
                "js_similarity": js_sim,
                "cosine_similarity": cosine_sim,
                "handoff_count": handoff,
                "handoff_rate_min_count": handoff_rate,
                "overlap_score": overlap_score,
            }
        )

    pair_df = pd.DataFrame(rows).sort_values(
        by=["overlap_score", "js_similarity", "cosine_similarity"],
        ascending=False,
    )
    pair_csv = run_dir / "learner_overlap_pairs.csv"
    pair_df.to_csv(pair_csv, index=False)

    candidates_df = pair_df[
        (pair_df["overlap_score"] >= candidate_score_threshold)
        & (pair_df["js_similarity"] >= candidate_js_sim_threshold)
        & (pair_df["handoff_rate_min_count"] >= candidate_handoff_threshold)
    ].copy()
    candidates_csv = run_dir / "learner_overlap_candidates.csv"
    candidates_df.to_csv(candidates_csv, index=False)

    top_k = pair_df.head(20).to_dict(orient="records")
    summary = {
        "run_dir": str(run_dir),
        "analyzed_learner_count": int(len(names)),
        "pair_count": int(len(pair_df)),
        "candidate_count": int(len(candidates_df)),
        "thresholds": {
            "min_samples": min_samples,
            "candidate_score_threshold": candidate_score_threshold,
            "candidate_js_sim_threshold": candidate_js_sim_threshold,
            "candidate_handoff_threshold": candidate_handoff_threshold,
        },
        "output_files": {
            "pairs_csv": str(pair_csv),
            "candidates_csv": str(candidates_csv),
        },
        "top_pairs": top_k,
    }
    summary_path = run_dir / "learner_overlap_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["output_files"]["summary_json"] = str(summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze high-overlap learner pairs (no merge).")
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Run directory, e.g. outputs/runs/20260511_161649",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=300,
        help="Minimum samples per learner to include in pairwise analysis.",
    )
    parser.add_argument(
        "--candidate-score-threshold",
        type=float,
        default=0.80,
        help="Candidate overlap score threshold.",
    )
    parser.add_argument(
        "--candidate-js-sim-threshold",
        type=float,
        default=0.90,
        help="Candidate Jensen-Shannon similarity threshold.",
    )
    parser.add_argument(
        "--candidate-handoff-threshold",
        type=float,
        default=0.05,
        help="Candidate handoff-rate threshold (normalized by min sample count).",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    summary = analyze_overlap(
        run_dir=run_dir,
        min_samples=args.min_samples,
        candidate_score_threshold=args.candidate_score_threshold,
        candidate_js_sim_threshold=args.candidate_js_sim_threshold,
        candidate_handoff_threshold=args.candidate_handoff_threshold,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

