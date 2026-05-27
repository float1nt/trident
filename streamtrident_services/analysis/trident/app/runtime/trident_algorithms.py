from __future__ import annotations

import base64
import io
import math
import pickle
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from scipy.stats import genpareto
from sklearn.cluster import DBSCAN
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset


class AutoEncoder(nn.Module):
    """tSieve autoencoder: d -> 256 -> 128 -> 64 -> 32 -> 64 -> 128 -> 256 -> d."""

    def __init__(self, in_dim: int):
        super().__init__()
        self.enc1 = nn.Linear(in_dim, 256)
        self.enc2 = nn.Linear(256, 128)
        self.enc3 = nn.Linear(128, 64)
        self.enc4 = nn.Linear(64, 32)
        self.dec3 = nn.Linear(32, 64)
        self.dec2 = nn.Linear(64, 128)
        self.dec1 = nn.Linear(128, 256)
        self.reconstruct = nn.Linear(256, in_dim)
        self.act = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.act(self.enc1(x))
        e2 = self.act(self.enc2(e1))
        e3 = self.act(self.enc3(e2))
        e4 = self.act(self.enc4(e3))
        d3 = self.act(self.dec3(e4) + e3)
        d2 = self.act(self.dec2(d3) + e2)
        d1 = self.act(self.dec1(d2) + e1)
        return self.reconstruct(d1)


class TScissors:
    """POT/EVT threshold estimator from Trident's tScissors component."""

    def __init__(self, evt_quantile: float = 0.97, evt_risk: float = 0.0015, fallback_quantile: float = 0.99):
        self.evt_quantile = evt_quantile
        self.evt_risk = evt_risk
        self.fallback_quantile = fallback_quantile

    def fit_threshold(self, losses: np.ndarray) -> float:
        losses = losses[np.isfinite(losses)]
        if len(losses) == 0:
            return 1.0
        if len(losses) < 100:
            return float(np.quantile(losses, min(0.99, self.evt_quantile)))
        u = float(np.quantile(losses, self.evt_quantile))
        peaks = losses[losses > u] - u
        if len(peaks) < 30:
            return float(np.quantile(losses, self.fallback_quantile))
        try:
            c, _loc, scale = genpareto.fit(peaks, floc=0)
            n = len(losses)
            npk = len(peaks)
            if abs(c) > 1e-6:
                val = u + (scale / c) * (((n * self.evt_risk / npk) ** (-c)) - 1)
            else:
                val = u - scale * math.log(self.evt_risk * n / npk)
            if not np.isfinite(val):
                raise ValueError("invalid evt threshold")
            return float(max(val, np.quantile(losses, 0.99)))
        except Exception:
            return float(np.quantile(losses, self.fallback_quantile))


@dataclass
class Learner:
    name: str
    scaler: StandardScaler
    model: Any
    threshold: float
    device: torch.device
    batch_size: int
    lr: float
    classifier_backend: str
    train_sample_count: int = 0

    def reconstruction_loss(self, x: np.ndarray) -> np.ndarray:
        x_scaled = self.scaler.transform(x)
        if self.classifier_backend == "iforest":
            return (-self.model.score_samples(x_scaled)).astype(np.float64, copy=False)
        with torch.no_grad():
            t = torch.as_tensor(x_scaled, dtype=torch.float32, device=self.device)
            pred = self.model(t)
            return torch.mean((pred - t) ** 2, dim=1).detach().cpu().numpy()

    def fit_incremental(self, x: np.ndarray, epochs: int) -> dict[str, list[float]]:
        if len(x) == 0:
            return {"train": [], "val": []}
        self.train_sample_count += int(len(x))
        if self.classifier_backend == "iforest":
            x_scaled = self.scaler.fit_transform(x)
            self.model.fit(x_scaled)
            return {"train": [], "val": []}
        x_scaled = self.scaler.transform(x)
        n = len(x_scaled)
        val_count = int(max(0, round(n * 0.1)))
        val_count = min(val_count, max(0, n - 32))
        if n >= 512:
            val_count = max(val_count, 64)
        x_val = x_scaled[np.linspace(0, n - 1, num=val_count, dtype=int)] if val_count > 0 else np.empty((0, x_scaled.shape[1]))
        ds = TensorDataset(torch.as_tensor(x_scaled, dtype=torch.float32))
        dl = DataLoader(ds, batch_size=self.batch_size, shuffle=True, drop_last=False)
        self.model.train()
        optimizer = optim.Adam(self.model.parameters(), lr=self.lr)
        criterion = nn.MSELoss()
        epoch_losses: list[float] = []
        epoch_val_losses: list[float] = []
        for _ in range(max(0, int(epochs))):
            batch_losses: list[float] = []
            for (batch,) in dl:
                batch = batch.to(self.device)
                out = self.model(batch)
                loss = criterion(out, batch)
                batch_losses.append(float(loss.item()))
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            epoch_losses.append(float(np.mean(batch_losses)) if batch_losses else float("nan"))
            if len(x_val) > 0:
                with torch.no_grad():
                    tv = torch.as_tensor(x_val, dtype=torch.float32, device=self.device)
                    pv = self.model(tv)
                    epoch_val_losses.append(float(torch.mean((pv - tv) ** 2).detach().cpu().item()))
            else:
                epoch_val_losses.append(float("nan"))
        self.model.eval()
        return {"train": epoch_losses, "val": epoch_val_losses}

    def serialize(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "threshold": float(self.threshold),
            "classifier_backend": self.classifier_backend,
            "batch_size": int(self.batch_size),
            "lr": float(self.lr),
            "train_sample_count": int(self.train_sample_count),
            "scaler": _b64_pickle(self.scaler),
        }
        if self.classifier_backend == "iforest":
            payload["iforest"] = _b64_pickle(self.model)
        else:
            buf = io.BytesIO()
            torch.save({"in_dim": int(self.model.reconstruct.out_features), "state_dict": self.model.state_dict()}, buf)
            payload["autoencoder"] = base64.b64encode(buf.getvalue()).decode("ascii")
        return payload

    @classmethod
    def deserialize(cls, payload: dict[str, Any], *, device: torch.device) -> "Learner":
        scaler = _unb64_pickle(str(payload["scaler"]))
        backend = str(payload.get("classifier_backend", "ae"))
        if backend == "iforest":
            model = _unb64_pickle(str(payload["iforest"]))
        else:
            raw = base64.b64decode(str(payload["autoencoder"]).encode("ascii"))
            loaded = torch.load(io.BytesIO(raw), map_location=device, weights_only=False)
            model = AutoEncoder(int(loaded["in_dim"])).to(device)
            model.load_state_dict(loaded["state_dict"])
            model.eval()
        return cls(
            name=str(payload.get("name") or ""),
            scaler=scaler,
            model=model,
            threshold=float(payload.get("threshold", 1.0)),
            device=device,
            batch_size=int(payload.get("batch_size", 256)),
            lr=float(payload.get("lr", 0.001)),
            classifier_backend=backend,
            train_sample_count=int(payload.get("train_sample_count", 0)),
        )


class TSieve:
    """Trident one-class learner manager."""

    def __init__(
        self,
        *,
        device: torch.device,
        tscissors: TScissors,
        batch_size: int,
        lr: float,
        min_class_samples: int,
        max_train_per_class: int,
        benign_accept_scale: float = 1.0,
        prefer_non_benign_first: bool = True,
        classifier_backend: str = "ae",
        iforest_n_estimators: int = 200,
        seed: int = 42,
        uniform_learner_treatment: bool = False,
    ) -> None:
        self.device = device
        self.tscissors = tscissors
        self.batch_size = batch_size
        self.lr = lr
        self.min_class_samples = min_class_samples
        self.max_train_per_class = max_train_per_class
        self.benign_accept_scale = max(0.0, min(float(benign_accept_scale), 1.0))
        self.prefer_non_benign_first = bool(prefer_non_benign_first)
        self.uniform_learner_treatment = bool(uniform_learner_treatment)
        self.classifier_backend = str(classifier_backend).strip().lower()
        if self.classifier_backend not in {"ae", "iforest"}:
            raise ValueError(f"Unsupported tsieve classifier_backend: {classifier_backend}")
        self.iforest_n_estimators = int(iforest_n_estimators)
        self.seed = int(seed)
        self.learners: dict[str, Learner] = {}
        self.last_add_train_trace: dict[str, Any] = {}

    def is_benign_learner(self, name: str) -> bool:
        return "BENIGN" in str(name).upper()

    def add_learner(self, name: str, x_train: np.ndarray, epochs: int) -> bool:
        if len(x_train) < self.min_class_samples:
            return False
        if len(x_train) > self.max_train_per_class:
            rng = np.random.default_rng(self.seed)
            idx = rng.choice(len(x_train), size=self.max_train_per_class, replace=False)
            x_train = x_train[idx]
        learner, epoch_losses = self._train_iforest(x_train) if self.classifier_backend == "iforest" else self._train_ae(x_train, epochs)
        learner.name = name
        learner.train_sample_count = int(len(x_train))
        self.learners[name] = learner
        self.last_add_train_trace = {
            "learner_name": str(name),
            "train_sample_count": int(len(x_train)),
            "epochs": int(epochs),
            "epoch_losses": [float(x) for x in epoch_losses.get("train", [])],
            "epoch_val_losses": [float(x) for x in epoch_losses.get("val", [])],
            "threshold": float(learner.threshold),
            "backend": str(self.classifier_backend),
        }
        return True

    def classify_batch(self, samples: np.ndarray) -> list[str | None]:
        if len(samples) == 0:
            return []
        if not self.learners:
            return [None] * len(samples)
        names, losses_matrix, thresholds = self._batch_losses_and_thresholds(samples)
        accepted_mask = losses_matrix <= thresholds[:, None]
        preds: list[str | None] = []
        for i in range(len(samples)):
            accepted_idx = np.where(accepted_mask[:, i])[0]
            preds.append(self._select_prediction_from_accepted(names, losses_matrix[:, i], accepted_idx))
        return preds

    def classify_batch_details(self, samples: np.ndarray) -> list[dict[str, Any]]:
        if len(samples) == 0:
            return []
        if not self.learners:
            return [{"pred": None, "accepted_names": [], "losses": {}, "thresholds": {}} for _ in range(len(samples))]
        names, losses_matrix, thresholds = self._batch_losses_and_thresholds(samples)
        accepted_mask = losses_matrix <= thresholds[:, None]
        rows: list[dict[str, Any]] = []
        for i in range(len(samples)):
            accepted_idx = np.where(accepted_mask[:, i])[0]
            pred = self._select_prediction_from_accepted(names, losses_matrix[:, i], accepted_idx)
            rows.append(
                {
                    "pred": pred,
                    "accepted_names": [names[int(idx)] for idx in accepted_idx],
                    "losses": {names[j]: float(losses_matrix[j, i]) for j in range(len(names))},
                    "thresholds": {names[j]: float(thresholds[j]) for j in range(len(names))},
                }
            )
        return rows

    def refresh_threshold(self, name: str, x_samples: np.ndarray) -> None:
        losses = self.learners[name].reconstruction_loss(x_samples)
        self.learners[name].threshold = self.tscissors.fit_threshold(losses)

    def interval_sample_by_loss(self, name: str, x_samples: np.ndarray, keep_count: int) -> np.ndarray:
        if len(x_samples) == 0 or keep_count <= 0:
            return x_samples[:0]
        if keep_count >= len(x_samples):
            return x_samples
        losses = self.learners[name].reconstruction_loss(x_samples)
        sorted_idx = np.argsort(losses)
        keep_pos = np.unique(np.linspace(0, len(sorted_idx) - 1, num=max(1, keep_count), dtype=int))
        return x_samples[sorted_idx[keep_pos]]

    def _batch_losses_and_thresholds(self, samples: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
        names: list[str] = []
        losses_rows: list[np.ndarray] = []
        thresholds: list[float] = []
        for name, learner in self.learners.items():
            losses = learner.reconstruction_loss(samples)
            threshold = learner.threshold
            if (not self.uniform_learner_treatment) and self.is_benign_learner(name):
                threshold = threshold * self.benign_accept_scale
            names.append(name)
            losses_rows.append(losses.astype(np.float64, copy=False))
            thresholds.append(float(threshold))
        return names, np.vstack(losses_rows) if losses_rows else np.empty((0, len(samples))), np.asarray(thresholds, dtype=np.float64)

    def _select_prediction_from_accepted(self, names: list[str], losses_by_learner: np.ndarray, accepted_idx: np.ndarray) -> str | None:
        if len(accepted_idx) == 0:
            return None
        if self.prefer_non_benign_first and (not self.uniform_learner_treatment):
            non_benign = np.asarray([idx for idx in accepted_idx if not self.is_benign_learner(names[int(idx)])], dtype=int)
            if len(non_benign) > 0:
                return names[int(non_benign[np.argmin(losses_by_learner[non_benign])])]
            benign_only = np.asarray([idx for idx in accepted_idx if self.is_benign_learner(names[int(idx)])], dtype=int)
            if len(benign_only) == 0:
                return None
            return names[int(benign_only[np.argmin(losses_by_learner[benign_only])])]
        return names[int(accepted_idx[np.argmin(losses_by_learner[accepted_idx])])]

    def _train_ae(self, x_train: np.ndarray, epochs: int) -> tuple[Learner, dict[str, list[float]]]:
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(x_train)
        n = len(x_scaled)
        val_count = int(max(0, round(n * 0.1)))
        val_count = min(val_count, max(0, n - 64))
        if n >= 1024:
            val_count = max(val_count, 128)
        x_val = x_scaled[np.linspace(0, n - 1, num=val_count, dtype=int)] if val_count > 0 else np.empty((0, x_scaled.shape[1]))
        model = AutoEncoder(x_scaled.shape[1]).to(self.device)
        ds = TensorDataset(torch.as_tensor(x_scaled, dtype=torch.float32))
        dl = DataLoader(ds, batch_size=self.batch_size, shuffle=True, drop_last=False)
        optimizer = optim.Adam(model.parameters(), lr=self.lr)
        criterion = nn.MSELoss()
        model.train()
        epoch_losses: list[float] = []
        epoch_val_losses: list[float] = []
        for _ in range(max(0, int(epochs))):
            batch_losses: list[float] = []
            for (batch,) in dl:
                batch = batch.to(self.device)
                out = model(batch)
                loss = criterion(out, batch)
                batch_losses.append(float(loss.item()))
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            epoch_losses.append(float(np.mean(batch_losses)) if batch_losses else float("nan"))
            if len(x_val) > 0:
                with torch.no_grad():
                    tv = torch.as_tensor(x_val, dtype=torch.float32, device=self.device)
                    pv = model(tv)
                    epoch_val_losses.append(float(torch.mean((pv - tv) ** 2).detach().cpu().item()))
            else:
                epoch_val_losses.append(float("nan"))
        model.eval()
        with torch.no_grad():
            t = torch.as_tensor(x_scaled, dtype=torch.float32, device=self.device)
            losses = torch.mean((model(t) - t) ** 2, dim=1).cpu().numpy()
        learner = Learner("", scaler, model, self.tscissors.fit_threshold(losses), self.device, self.batch_size, self.lr, "ae")
        return learner, {"train": epoch_losses, "val": epoch_val_losses}

    def _train_iforest(self, x_train: np.ndarray) -> tuple[Learner, dict[str, list[float]]]:
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(x_train)
        model = IsolationForest(n_estimators=self.iforest_n_estimators, contamination="auto", random_state=self.seed, n_jobs=-1)
        model.fit(x_scaled)
        losses = (-model.score_samples(x_scaled)).astype(np.float64, copy=False)
        learner = Learner("", scaler, model, self.tscissors.fit_threshold(losses), self.device, self.batch_size, self.lr, "iforest")
        return learner, {"train": [], "val": []}


class TMagnifier:
    """DBSCAN unknown buffer clustering from Trident's tMagnifier component."""

    def __init__(
        self,
        *,
        cluster_trigger_size: int,
        max_unknown_buffer: int,
        dbscan_eps: float,
        dbscan_min_samples: int,
        new_class_min_size: int,
    ) -> None:
        self.cluster_trigger_size = cluster_trigger_size
        self.max_unknown_buffer = max_unknown_buffer
        self.dbscan_eps = dbscan_eps
        self.dbscan_min_samples = dbscan_min_samples
        self.new_class_min_size = new_class_min_size
        self.unknown_buffer: list[np.ndarray] = []
        self.unknown_labels: list[str] = []
        self.unknown_meta: list[dict[str, Any]] = []
        self.dropped_unknown_label_counts: dict[str, int] = {}

    def add_unknown(self, sample: np.ndarray, label: str, meta: dict[str, Any] | None = None) -> None:
        self.unknown_buffer.append(sample)
        self.unknown_labels.append(label)
        self.unknown_meta.append(dict(meta) if meta else {})
        if len(self.unknown_buffer) > self.max_unknown_buffer:
            overflow = len(self.unknown_buffer) - self.max_unknown_buffer
            for old_label in self.unknown_labels[:overflow]:
                self.dropped_unknown_label_counts[old_label] = int(self.dropped_unknown_label_counts.get(old_label, 0) + 1)
            self.unknown_buffer = self.unknown_buffer[-self.max_unknown_buffer :]
            self.unknown_labels = self.unknown_labels[-self.max_unknown_buffer :]
            self.unknown_meta = self.unknown_meta[-self.max_unknown_buffer :]

    def pop_new_class_clusters(self) -> list[tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]]:
        if len(self.unknown_buffer) < self.cluster_trigger_size:
            return []
        ub = np.stack(self.unknown_buffer, axis=0)
        ubz = StandardScaler().fit_transform(ub)
        labels = DBSCAN(eps=self.dbscan_eps, min_samples=self.dbscan_min_samples).fit(ubz).labels_
        consumed = np.zeros(len(ub), dtype=bool)
        clusters: list[tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]] = []
        for c in np.unique(labels):
            if c == -1:
                continue
            idx = np.where(labels == c)[0]
            if len(idx) < self.new_class_min_size:
                continue
            cluster_labels = np.asarray([self.unknown_labels[i] for i in idx], dtype=object)
            cluster_metas = [dict(self.unknown_meta[int(i)]) for i in idx]
            clusters.append((ub[idx], cluster_labels, cluster_metas))
            consumed[idx] = True
        keep_idx = [i for i in range(len(self.unknown_buffer)) if not consumed[i]]
        self.unknown_buffer = [self.unknown_buffer[i] for i in keep_idx]
        self.unknown_labels = [self.unknown_labels[i] for i in keep_idx]
        self.unknown_meta = [self.unknown_meta[i] for i in keep_idx]
        return clusters


def _b64_pickle(value: Any) -> str:
    return base64.b64encode(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).decode("ascii")


def _unb64_pickle(value: str) -> Any:
    return pickle.loads(base64.b64decode(value.encode("ascii")))
