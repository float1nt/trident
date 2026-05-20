import argparse
import re
from datetime import datetime
from pathlib import Path

from trident_stream.config import build_logger, load_config
from trident_stream.experiment import TridentStreamingExperiment


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Streaming Trident-AE experiment entrypoint.")
    parser.add_argument("--config", type=str, default="configs/config.yaml", help="Path to YAML config.")
    return parser


def build_run_id(config_path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config_name = Path(config_path).name
    safe_config_name = re.sub(r"[^A-Za-z0-9._-]", "_", config_name)
    return f"{timestamp}_{safe_config_name}"


def main() -> None:
    args = build_argparser().parse_args()
    cfg = load_config(args.config)
    run_id = build_run_id(args.config)
    cfg.setdefault("runtime", {})["run_id"] = run_id
    base_output_dir = Path(cfg["paths"]["output_dir"])
    run_output_dir = (base_output_dir / "runs" / run_id).resolve()
    cfg["paths"]["output_dir"] = str(run_output_dir)
    cfg["paths"]["log_file"] = "run.log"
    logger = build_logger(output_dir=Path(cfg["paths"]["output_dir"]), log_file=cfg["paths"]["log_file"])
    TridentStreamingExperiment(cfg=cfg, logger=logger).run()


if __name__ == "__main__":
    main()
