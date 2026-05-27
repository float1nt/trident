from __future__ import annotations

from pathlib import Path

from app.config import load_config


def test_redis_output_is_disabled_by_default() -> None:
    assert load_config(None).redis_output_enabled is False


def test_best_effort_consumer_is_default() -> None:
    cfg = load_config(None)

    assert cfg.consumer_mode == "best_effort"
    assert cfg.best_effort_start_id == "$"


def test_redis_output_can_be_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "trident.yaml"
    config_path.write_text("redis_output_enabled: true\n", encoding="utf-8")

    assert load_config(config_path).redis_output_enabled is True
