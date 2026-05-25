from __future__ import annotations

from pathlib import Path

from trident_demo.orchestration.data_prep import main as data_prep_main


def run_viz_demo_data_prep(repo_root: Path, logger) -> None:
    aligned_csv = repo_root / "data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv"
    report_json = repo_root / "data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.report.json"
    logger.info("[1/2] prepare_threeway_sampled_dataset (x5 benign) ...")
    argv = [
        "data_prep",
        "--dir-2017",
        str(repo_root / "data/cic2017"),
        "--dir-2019",
        str(repo_root / "data/cicids2019"),
        "--file-2026",
        str(repo_root / "data/cicids2026.csv"),
        "--benign-multiplier",
        "5",
        "--benign-per-year",
        "100000",
        "--attack-per-type",
        "10000",
        "--output-csv",
        str(aligned_csv),
        "--report-json",
        str(report_json),
    ]
    data_prep_main(argv=argv)
