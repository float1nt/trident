from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import load_config
from .logging_utils import configure_logging, emit_event, emit_exception
from .persistence.clickhouse_http import ClickHouseHTTPClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Trident database migrations")
    parser.add_argument("--config", default="config/trident.yaml")
    parser.add_argument("--migrations-dir", default="migrations")
    parser.add_argument("--target", choices=["all", "clickhouse", "postgres"], default="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_dir = Path(os.getenv("TRIDENT_LOG_DIR", "/var/log/trident"))
    log_file = os.getenv("TRIDENT_LOG_FILE", "migrate.log")
    configure_logging(service_name="trident-migrate", log_path=log_dir / log_file)
    cfg = load_config(args.config)
    root = Path(args.migrations_dir)
    emit_event(
        "migrate_started",
        clickhouse_dsn=cfg.clickhouse_dsn,
        postgres_dsn=cfg.postgres_dsn,
        target=args.target,
        migrations_dir=str(root),
    )
    if args.target in {"all", "clickhouse"}:
        try:
            applied = apply_clickhouse(root / "clickhouse", cfg.clickhouse_dsn)
            emit_event("migrate_clickhouse_finished", applied_count=len(applied), applied_files=applied)
        except Exception:
            emit_exception("migrate_clickhouse_failed", target=str(root / "clickhouse"))
            raise
    if args.target in {"all", "postgres"}:
        try:
            applied = apply_postgres(root / "postgres", cfg.postgres_dsn)
            emit_event("migrate_postgres_finished", applied_count=len(applied), applied_files=applied)
        except Exception:
            emit_exception("migrate_postgres_failed", target=str(root / "postgres"))
            raise
    emit_event("migrate_finished", target=args.target)
    return 0


def apply_clickhouse(path: Path, dsn: str) -> list[str]:
    client = ClickHouseHTTPClient(dsn)
    applied: list[str] = []
    for file in _sql_files(path):
        client.execute(file.read_text(encoding="utf-8"))
        applied.append(str(file))
    return applied


def apply_postgres(path: Path, dsn: str) -> list[str]:
    import psycopg

    applied: list[str] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for file in _sql_files(path):
                cur.execute(file.read_text(encoding="utf-8"))
                applied.append(str(file))
    return applied


def _sql_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(file for file in path.iterdir() if file.suffix == ".sql")


if __name__ == "__main__":
    raise SystemExit(main())
