from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ModelStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, *, session_id: str, learner_name: str, payload: dict[str, Any]) -> str:
        path = self._path(session_id=session_id, learner_name=learner_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        return str(path)

    def load(self, path: str | Path) -> dict[str, Any] | None:
        p = Path(path)
        if not p.exists():
            return None
        parsed = json.loads(p.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else None

    def _path(self, *, session_id: str, learner_name: str) -> Path:
        return self.root / _safe(session_id) / f"{_safe(learner_name)}.json"


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
