from typing import Dict, List, Tuple

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler


class TMagnifier:
    """Cluster unknown samples and propose emerging classes."""

    def __init__(
        self,
        cluster_trigger_size: int,
        max_unknown_buffer: int,
        dbscan_eps: float,
        dbscan_min_samples: int,
        new_class_min_size: int,
    ):
        self.cluster_trigger_size = cluster_trigger_size
        self.max_unknown_buffer = max_unknown_buffer
        self.dbscan_eps = dbscan_eps
        self.dbscan_min_samples = dbscan_min_samples
        self.new_class_min_size = new_class_min_size
        self.unknown_buffer: List[np.ndarray] = []
        self.unknown_labels: List[str] = []
        self.dropped_unknown_label_counts: Dict[str, int] = {}

    def add_unknown(self, sample: np.ndarray, label: str) -> None:
        self.unknown_buffer.append(sample)
        self.unknown_labels.append(label)
        if len(self.unknown_buffer) > self.max_unknown_buffer:
            overflow = len(self.unknown_buffer) - self.max_unknown_buffer
            for old_label in self.unknown_labels[:overflow]:
                self.dropped_unknown_label_counts[old_label] = (
                    int(self.dropped_unknown_label_counts.get(old_label, 0)) + 1
                )
            self.unknown_buffer = self.unknown_buffer[-self.max_unknown_buffer :]
            self.unknown_labels = self.unknown_labels[-self.max_unknown_buffer :]

    def pop_new_class_clusters(self) -> List[Tuple[np.ndarray, np.ndarray]]:
        if len(self.unknown_buffer) < self.cluster_trigger_size:
            return []
        ub = np.stack(self.unknown_buffer, axis=0)
        ubz = StandardScaler().fit_transform(ub)
        clus = DBSCAN(eps=self.dbscan_eps, min_samples=self.dbscan_min_samples).fit(ubz)
        labels = clus.labels_
        consumed = np.zeros(len(ub), dtype=bool)
        clusters: List[Tuple[np.ndarray, np.ndarray]] = []
        for c in np.unique(labels):
            if c == -1:
                continue
            idx = np.where(labels == c)[0]
            if len(idx) < self.new_class_min_size:
                continue
            cluster_labels = np.asarray([self.unknown_labels[i] for i in idx], dtype=object)
            clusters.append((ub[idx], cluster_labels))
            consumed[idx] = True
        self.unknown_buffer = [self.unknown_buffer[i] for i in range(len(self.unknown_buffer)) if not consumed[i]]
        self.unknown_labels = [self.unknown_labels[i] for i in range(len(self.unknown_labels)) if not consumed[i]]
        return clusters

