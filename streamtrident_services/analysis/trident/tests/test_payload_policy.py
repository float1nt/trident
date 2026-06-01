from __future__ import annotations

from dataclasses import replace

from app.config import TridentConfig
from app.runtime.online_engine import FlowAssignment
from app.worker import _should_keep_payload


class _TSieve:
    def __init__(self, benign_names: set[str] | None = None) -> None:
        self.benign_names = benign_names or set()

    def is_benign_learner(self, name: str) -> bool:
        return name in self.benign_names


class _Engine:
    def __init__(self, benign_names: set[str] | None = None) -> None:
        self.tsieve = _TSieve(benign_names)


def _assignment(*, learner: str = "NEW_1", is_unknown: bool = False) -> FlowAssignment:
    return FlowAssignment(
        flow_uid="flow-1",
        assigned_learner=learner,
        is_unknown=is_unknown,
        pred_loss=0.1,
        threshold=0.2,
        assignment_meta={},
    )


def test_payload_policy_never_keeps_payload_during_cold_start() -> None:
    cfg = replace(TridentConfig(), runtime_mode="cold_start")

    keep = _should_keep_payload(
        _assignment(is_unknown=True),
        cfg=cfg,
        engine=_Engine(),  # type: ignore[arg-type]
        cold_start_finalized=True,
    )

    assert keep is False


def test_payload_policy_drops_payload_before_cold_start_is_finalized() -> None:
    cfg = replace(TridentConfig(), runtime_mode="inference")

    keep = _should_keep_payload(
        _assignment(is_unknown=True),
        cfg=cfg,
        engine=_Engine(),  # type: ignore[arg-type]
        cold_start_finalized=False,
    )

    assert keep is False


def test_payload_policy_keeps_unknown_payload_after_cold_start() -> None:
    cfg = replace(TridentConfig(), runtime_mode="inference")

    keep = _should_keep_payload(
        _assignment(is_unknown=True),
        cfg=cfg,
        engine=_Engine(),  # type: ignore[arg-type]
        cold_start_finalized=True,
    )

    assert keep is True


def test_payload_policy_drops_benign_learner_payload() -> None:
    cfg = replace(TridentConfig(), runtime_mode="inference")

    keep = _should_keep_payload(
        _assignment(learner="NEW_1"),
        cfg=cfg,
        engine=_Engine({"NEW_1"}),  # type: ignore[arg-type]
        cold_start_finalized=True,
    )

    assert keep is False


def test_payload_policy_keeps_non_benign_learner_payload() -> None:
    cfg = replace(TridentConfig(), runtime_mode="inference")

    keep = _should_keep_payload(
        _assignment(learner="NEW_1"),
        cfg=cfg,
        engine=_Engine({"COLD_0|BENIGN"}),  # type: ignore[arg-type]
        cold_start_finalized=True,
    )

    assert keep is True
