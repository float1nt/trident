from __future__ import annotations

from pathlib import Path

from app.migrate import _split_sql_statements, _sql_files


def test_sql_files_returns_sorted_sql_only(tmp_path: Path) -> None:
    (tmp_path / "002_b.sql").write_text("select 2", encoding="utf-8")
    (tmp_path / "001_a.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "note.txt").write_text("skip", encoding="utf-8")

    assert [path.name for path in _sql_files(tmp_path)] == ["001_a.sql", "002_b.sql"]


def test_split_sql_statements_splits_on_semicolons() -> None:
    sql = "SELECT 1;\n\nALTER TABLE t DROP PROJECTION IF EXISTS p;\n"
    assert _split_sql_statements(sql) == ["SELECT 1;", "ALTER TABLE t DROP PROJECTION IF EXISTS p;"]
