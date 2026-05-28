from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.runtime.learner_overlap import LearnerOverlapConfig, build_learner_overlap_snapshot


@dataclass
class FakeTSieve:
    learners: dict[str, object]

    def interval_sample_by_loss(self, _name: str, samples: np.ndarray, keep_count: int) -> np.ndarray:
        return samples[:keep_count]

    def classify_batch_details(self, samples: np.ndarray) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for sample in samples:
            value = int(sample[0])
            if value == 1:
                accepted = ["A", "B"]
            elif value == 2:
                accepted = ["A", "C"]
            elif value == 3:
                accepted = ["B", "C"]
            else:
                accepted = []
            rows.append({"accepted_names": accepted})
        return rows


def test_build_learner_overlap_snapshot_aggregates_connected_component() -> None:
    tsieve = FakeTSieve(learners={"A": object(), "B": object(), "C": object()})
    history = [
        np.asarray([1.0], dtype=np.float64),
        np.asarray([2.0], dtype=np.float64),
        np.asarray([3.0], dtype=np.float64),
    ]
    learner_histories = {"A": history, "B": history, "C": history}

    snapshot = build_learner_overlap_snapshot(
        tsieve=tsieve,
        learner_histories=learner_histories,
        config=LearnerOverlapConfig(
            min_jaccard=0.20,
            top_k_edges=10,
            max_edges=10,
            graph_algo="connected",
            mutual_top_k=2,
            sample_cap_per_learner=10,
        ),
    )

    assert snapshot.meta["aggregate_count"] == 1
    assert snapshot.meta["selected_edge_count"] == 3
    assert snapshot.mapping == {"A": "AGG_001", "B": "AGG_001", "C": "AGG_001"}
    assert snapshot.aggregates[0].member_count == 3
    assert snapshot.aggregates[0].internal_edge_count == 3
    assert 0.30 < snapshot.aggregates[0].avg_internal_jaccard < 0.34
    assert snapshot.accept_count["A"] > 0
    assert snapshot.accept_count["B"] > 0
    assert snapshot.accept_count["C"] > 0
