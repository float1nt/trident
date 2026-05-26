from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp/mplconfig-trident").resolve()))

from trident_demo.pipeline.runner import PROFILE_DEFAULT_CONFIG, run_pipeline
from trident_demo.runtime.online_runner import DEFAULT_ONLINE_CONFIG, run_online


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trident demo: single entrypoint for batch / replay / benchmark / viz-demo pipelines.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run a demo pipeline profile end-to-end.")
    run_parser.add_argument(
        "--profile",
        choices=["batch", "replay", "benchmark", "viz-demo"],
        required=True,
        help="Pipeline profile (replaces main.py, benchmark script, and run_static shell).",
    )
    run_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="YAML config path (default per profile under trident_demo/configs/).",
    )
    run_parser.add_argument("--max-rows", type=int, default=0, help="Cap rows loaded/injected (0 = no cap).")
    run_parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Enable performance_benchmark (also default for profile=benchmark).",
    )
    run_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Base output directory (default: trident_demo/outputs).",
    )
    run_parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Replay: do not auto-start Redis via docker compose.",
    )
    run_parser.add_argument(
        "--no-inject",
        action="store_true",
        help="Replay/benchmark: skip CSV→Redis inject (stream must already contain data).",
    )

    online_parser = sub.add_parser("online", help="Run the deployable Redis streaming runtime path.")
    online_parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_ONLINE_CONFIG,
        help="Base YAML config path (default: trident_demo/configs/online.yaml).",
    )
    online_parser.add_argument("--max-rows", type=int, default=0, help="Cap Redis messages processed (0 = no cap).")
    online_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Base output directory (default from config paths.output_dir).",
    )
    online_parser.add_argument(
        "--redis-url",
        type=str,
        default=None,
        help="Override input.redis.url.",
    )
    online_parser.add_argument(
        "--redis-stream",
        type=str,
        default=None,
        help="Override input.redis.key / stream.",
    )
    online_parser.add_argument(
        "--window-size",
        type=int,
        default=0,
        help="Override stream.window_size (0 = keep config).",
    )
    online_parser.add_argument(
        "--start-redis",
        action="store_true",
        help="Start Redis via the demo docker compose preflight. By default online mode expects Redis to be an independent service.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]

    if args.command == "run":
        config_path = args.config or PROFILE_DEFAULT_CONFIG[args.profile]
        run_pipeline(
            repo_root=repo_root,
            profile=args.profile,
            config_path=config_path,
            max_rows=int(args.max_rows),
            benchmark=bool(args.benchmark or args.profile == "benchmark"),
            output_dir=args.output_dir,
            skip_docker=bool(args.skip_docker),
            no_inject=bool(args.no_inject),
        )
        return

    if args.command == "online":
        run_online(
            repo_root=repo_root,
            config_path=args.config,
            max_rows=int(args.max_rows),
            output_dir=args.output_dir,
            redis_url=args.redis_url,
            redis_stream=args.redis_stream,
            window_size=int(args.window_size),
            skip_docker=not bool(args.start_redis),
        )
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
