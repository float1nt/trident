import argparse
from datetime import datetime
from pathlib import Path

from trident_stream.config import build_logger, load_config
from trident_stream.experiment import TridentStreamingExperiment


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Streaming Trident-AE experiment entrypoint.")
    parser.add_argument("--config", type=str, default="configs/config.yaml", help="Path to YAML config.")
    return parser


def main() -> None:
    args = build_argparser().parse_args()
    cfg = load_config(args.config)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg.setdefault("runtime", {})["run_id"] = run_id
    base_output_dir = Path(cfg["paths"]["output_dir"])
    run_output_dir = base_output_dir / "runs" / run_id
    cfg["paths"]["output_dir"] = str(run_output_dir)
    cfg["paths"]["log_file"] = "run.log"
    logger = build_logger(output_dir=Path(cfg["paths"]["output_dir"]), log_file=cfg["paths"]["log_file"])
    TridentStreamingExperiment(cfg=cfg, logger=logger).run()


if __name__ == "__main__":
    main()
