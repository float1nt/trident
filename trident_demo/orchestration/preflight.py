from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from trident_demo.pipeline.context import RunContext


def preflight_stage(ctx: RunContext, *, skip_docker: bool = False) -> None:
    redis_cfg = ctx.cfg.get("input", {}).get("redis", {})
    url = str(redis_cfg.get("url", "redis://127.0.0.1:6379/0"))
    ctx.logger.info("Preflight: Redis URL=%s skip_docker=%s", url, skip_docker)

    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise SystemExit("Install redis: pip install redis") from exc

    client = redis.Redis.from_url(url, decode_responses=True)
    try:
        client.ping()
        ctx.logger.info("Preflight: Redis already reachable.")
        return
    except Exception:
        ctx.logger.info("Preflight: Redis not reachable yet.")

    if skip_docker:
        raise SystemExit(
            "Redis is not reachable and --skip-docker was set. Start Redis manually or remove --skip-docker."
        )

    compose_dir = ctx.repo_root / "suricata-cic-redis-live"
    compose_file = compose_dir / "docker-compose.yml"
    if not compose_file.exists():
        raise SystemExit(f"docker-compose.yml not found: {compose_file}")

    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("docker not found in PATH; start Redis manually or install Docker.")

    ctx.logger.info("Preflight: starting Redis via docker compose ...")
    subprocess.run(
        [docker, "compose", "-f", str(compose_file), "up", "-d", "redis"],
        cwd=str(compose_dir),
        check=True,
    )

    for _ in range(30):
        try:
            client.ping()
            ctx.logger.info("Preflight: Redis is up.")
            return
        except Exception:
            import time

            time.sleep(0.5)

    raise SystemExit("Redis did not become reachable after docker compose up.")
