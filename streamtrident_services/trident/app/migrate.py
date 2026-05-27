from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .persistence.clickhouse_http import ClickHouseHTTPClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Trident database migrations")
    parser.add_argument("--config", default="config/trident.yaml")
    parser.add_argument("--migrations-dir", default="migrations")
    parser.add_argument("--target", choices=["all", "clickhouse", "postgres"], default="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    root = Path(args.migrations_dir)
    if args.target in {"all", "clickhouse"}:
        apply_clickhouse(root / "clickhouse", cfg.clickhouse_dsn)
    if args.target in {"all", "postgres"}:
        apply_postgres(root / "postgres", cfg.postgres_dsn)
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
