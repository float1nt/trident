from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

from .tscissors import TScissors
from .utils import is_benign_label


class AutoEncoder(nn.Module):
    """
    tSieve AE learner (paper-aligned).

    Based on Trident §4.1:
    - Encoder dims: d -> 256 -> 128 -> 64 -> 32
    - Decoder is symmetric with skip additions from encoder tiers,
      in a U-Net-like manner (addition, not concatenation).
    """

    def __init__(self, in_dim: int):
        super().__init__()
        self.enc1 = nn.Linear(in_dim, 256)  # E1
        self.enc2 = nn.Linear(256, 128)  # E2
        self.enc3 = nn.Linear(128, 64)  # E3
        self.enc4 = nn.Linear(64, 32)  # E4

        self.dec3 = nn.Linear(32, 64)  # D3
        self.dec2 = nn.Linear(64, 128)  # D2
        self.dec1 = nn.Linear(128, 256)  # D1
        self.reconstruct = nn.Linear(256, in_dim)

        self.act = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.act(self.enc1(x))
        e2 = self.act(self.enc2(e1))
        e3 = self.act(self.enc3(e2))
        e4 = self.act(self.enc4(e3))

        # U-Net-like skip additions following Trident §4.1
        d3 = self.act(self.dec3(e4) + e3)
        d2 = self.act(self.dec2(d3) + e2)
        d1 = self.act(self.dec1(d2) + e1)
        return self.reconstruct(d1)


@dataclass
class Learner:
    name: str
    scaler: StandardScaler
    model: AutoEncoder
    threshold: float
    device: torch.device
    batch_size: int
    lr: float

    def reconstruction_loss(self, x: np.ndarray) -> np.ndarray:
        x_scaled = self.scaler.transform(x)
        with torch.no_grad():
            t = torch.as_tensor(x_scaled, dtype=torch.float32, device=self.device)
            pred = self.model(t)
            return torch.mean((pred - t) ** 2, dim=1).detach().cpu().numpy()

    def fit_incremental(self, x: np.ndarray, epochs: int) -> None:
        if len(x) == 0:
            return
        x_scaled = self.scaler.transform(x)
        ds = TensorDataset(torch.as_tensor(x_scaled, dtype=torch.float32))
        dl = DataLoader(ds, batch_size=self.batch_size, shuffle=True, drop_last=False)
        self.model.train()
        optimizer = optim.Adam(self.model.parameters(), lr=self.lr)
        criterion = nn.MSELoss()
        for _ in range(epochs):
            for (batch,) in dl:
                batch = batch.to(self.device)
                out = self.model(batch)
                loss = criterion(out, batch)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
        self.model.eval()


class TSieve:
    """Manage one-class AE learners."""

    def __init__(
        self,
        device: torch.device,
        tscissors: TScissors,
        batch_size: int,
        lr: float,
        min_class_samples: int,
        max_train_per_class: int,
        benign_accept_scale: float = 1.0,
        prefer_non_benign_first: bool = True,
    ):
        self.device = device
        self.tscissors = tscissors
        self.batch_size = batch_size
        self.lr = lr
        self.min_class_samples = min_class_samples
        self.max_train_per_class = max_train_per_class
        self.benign_accept_scale = max(0.0, min(float(benign_accept_scale), 1.0))
        self.prefer_non_benign_first = bool(prefer_non_benign_first)
        self.learners: Dict[str, Learner] = {}

    def _batch_losses_and_thresholds(
        self, samples: np.ndarray
    ) -> Tuple[List[str], np.ndarray, np.ndarray]:
        """
        Compute per-learner losses for a whole window in batch mode.
        Returns:
          names: learner names in row order
          losses_matrix: shape [num_learners, num_samples]
          thresholds: shape [num_learners]
        """
        names: List[str] = []
        losses_rows: List[np.ndarray] = []
        thresholds: List[float] = []
        for name, learner in self.learners.items():
            losses = learner.reconstruction_loss(samples)
            threshold = learner.threshold
            if is_benign_label(name):
                threshold = threshold * self.benign_accept_scale
            names.append(name)
            losses_rows.append(losses.astype(np.float64, copy=False))
            thresholds.append(float(threshold))
        losses_matrix = np.vstack(losses_rows) if losses_rows else np.empty((0, len(samples)), dtype=np.float64)
        thresholds_np = np.asarray(thresholds, dtype=np.float64)
        return names, losses_matrix, thresholds_np

    def _select_prediction_from_accepted(
        self,
        names: List[str],
        losses_by_learner: np.ndarray,
        accepted_idx: np.ndarray,
    ) -> Optional[str]:
        if len(accepted_idx) == 0:
            return None

        if self.prefer_non_benign_first:
            non_benign = np.asarray(
                [idx for idx in accepted_idx if not is_benign_label(names[int(idx)])],
                dtype=int,
            )
            if len(non_benign) > 0:
                best = non_benign[np.argmin(losses_by_learner[non_benign])]
                return names[int(best)]

            benign_only = np.asarray(
                [idx for idx in accepted_idx if is_benign_label(names[int(idx)])],
                dtype=int,
            )
            if len(benign_only) == 0:
                return None
            best = benign_only[np.argmin(losses_by_learner[benign_only])]
            return names[int(best)]

        best = accepted_idx[np.argmin(losses_by_learner[accepted_idx])]
        return names[int(best)]

    def _train_ae(self, x_train: np.ndarray, epochs: int) -> Learner:
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(x_train)
        model = AutoEncoder(x_scaled.shape[1]).to(self.device)
        ds = TensorDataset(torch.as_tensor(x_scaled, dtype=torch.float32))
        dl = DataLoader(ds, batch_size=self.batch_size, shuffle=True, drop_last=False)
        optimizer = optim.Adam(model.parameters(), lr=self.lr)
        criterion = nn.MSELoss()
        model.train()
        for _ in range(epochs):
            for (batch,) in dl:
                batch = batch.to(self.device)
                out = model(batch)
                loss = criterion(out, batch)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
        model.eval()
        with torch.no_grad():
            t = torch.as_tensor(x_scaled, dtype=torch.float32, device=self.device)
            losses = torch.mean((model(t) - t) ** 2, dim=1).cpu().numpy()
        threshold = self.tscissors.fit_threshold(losses)
        return Learner(
            name="",
            scaler=scaler,
            model=model,
            threshold=threshold,
            device=self.device,
            batch_size=self.batch_size,
            lr=self.lr,
        )

    def add_learner(self, name: str, x_train: np.ndarray, epochs: int) -> bool:
        if len(x_train) < self.min_class_samples:
            return False
        if len(x_train) > self.max_train_per_class:
            idx = np.random.choice(len(x_train), size=self.max_train_per_class, replace=False)
            x_train = x_train[idx]
        learner = self._train_ae(x_train, epochs)
        learner.name = name
        self.learners[name] = learner
        return True

    def _classify_sample_with_details(self, sample: np.ndarray) -> Dict[str, object]:
        if not self.learners:
            return {"pred": None, "accepted_names": [], "losses": {}, "thresholds": {}}
        names: List[str] = []
        losses: List[float] = []
        ths: List[float] = []
        for name, learner in self.learners.items():
            loss = float(learner.reconstruction_loss(sample)[0])
            threshold = learner.threshold
            if is_benign_label(name):
                threshold = threshold * self.benign_accept_scale
            names.append(name)
            losses.append(loss)
            ths.append(threshold)
        losses_np = np.asarray(losses)
        ths_np = np.asarray(ths)
        accepted = np.where(losses_np <= ths_np)[0]
        losses_map = {names[i]: float(losses_np[i]) for i in range(len(names))}
        thresholds_map = {names[i]: float(ths_np[i]) for i in range(len(names))}
        accepted_names = [names[int(idx)] for idx in accepted]
        if len(accepted) == 0:
            return {
                "pred": None,
                "accepted_names": accepted_names,
                "losses": losses_map,
                "thresholds": thresholds_map,
            }

        if self.prefer_non_benign_first:
            # Prefer non-BENIGN learners first to reduce attack leakage into benign learners.
            non_benign = np.asarray(
                [idx for idx in accepted if not is_benign_label(names[int(idx)])],
                dtype=int,
            )
            if len(non_benign) > 0:
                best = non_benign[np.argmin(losses_np[non_benign])]
                return {
                    "pred": names[int(best)],
                    "accepted_names": accepted_names,
                    "losses": losses_map,
                    "thresholds": thresholds_map,
                }

            benign_only = np.asarray(
                [idx for idx in accepted if is_benign_label(names[int(idx)])],
                dtype=int,
            )
            if len(benign_only) == 0:
                return {
                    "pred": None,
                    "accepted_names": accepted_names,
                    "losses": losses_map,
                    "thresholds": thresholds_map,
                }
            best = benign_only[np.argmin(losses_np[benign_only])]
            return {
                "pred": names[int(best)],
                "accepted_names": accepted_names,
                "losses": losses_map,
                "thresholds": thresholds_map,
            }

        # Parallel competition: choose global minimum loss among all accepted learners.
        best = accepted[np.argmin(losses_np[accepted])]
        return {
            "pred": names[int(best)],
            "accepted_names": accepted_names,
            "losses": losses_map,
            "thresholds": thresholds_map,
        }

    def classify_sample(self, sample: np.ndarray) -> Optional[str]:
        details = self._classify_sample_with_details(sample)
        return details["pred"]  # type: ignore[return-value]

    def classify_sample_debug(self, sample: np.ndarray) -> Dict[str, object]:
        return self._classify_sample_with_details(sample)

    def classify_batch(self, samples: np.ndarray) -> List[Optional[str]]:
        if len(samples) == 0:
            return []
        if not self.learners:
            return [None] * len(samples)

        names, losses_matrix, thresholds = self._batch_losses_and_thresholds(samples)
        accepted_mask = losses_matrix <= thresholds[:, None]
        preds: List[Optional[str]] = []
        for i in range(len(samples)):
            accepted_idx = np.where(accepted_mask[:, i])[0]
            pred = self._select_prediction_from_accepted(names, losses_matrix[:, i], accepted_idx)
            preds.append(pred)
        return preds

    def classify_batch_debug(self, samples: np.ndarray) -> List[Dict[str, Any]]:
        if len(samples) == 0:
            return []
        if not self.learners:
            return [{"pred": None, "accepted_names": []} for _ in range(len(samples))]

        names, losses_matrix, thresholds = self._batch_losses_and_thresholds(samples)
        accepted_mask = losses_matrix <= thresholds[:, None]
        rows: List[Dict[str, Any]] = []
        for i in range(len(samples)):
            accepted_idx = np.where(accepted_mask[:, i])[0]
            accepted_names = [names[int(idx)] for idx in accepted_idx]
            pred = self._select_prediction_from_accepted(names, losses_matrix[:, i], accepted_idx)
            rows.append({"pred": pred, "accepted_names": accepted_names})
        return rows

    def refresh_threshold(self, name: str, x_samples: np.ndarray) -> None:
        losses = self.learners[name].reconstruction_loss(x_samples)
        self.learners[name].threshold = self.tscissors.fit_threshold(losses)

    @staticmethod
    def _interval_indices(sorted_len: int, keep_count: int) -> np.ndarray:
        if keep_count >= sorted_len:
            return np.arange(sorted_len, dtype=int)
        positions = np.linspace(0, sorted_len - 1, num=max(1, keep_count), dtype=int)
        return np.unique(positions).astype(int)

    def interval_sample_by_loss(self, name: str, x_samples: np.ndarray, keep_count: int) -> np.ndarray:
        """
        Interval sampling over reconstruction-loss sorted samples.
        Used to preserve historical loss distribution during incremental updates.
        """
        if len(x_samples) == 0 or keep_count <= 0:
            return x_samples[:0]
        if keep_count >= len(x_samples):
            return x_samples
        losses = self.learners[name].reconstruction_loss(x_samples)
        sorted_idx = np.argsort(losses)
        keep_pos = self._interval_indices(len(sorted_idx), keep_count)
        keep_idx = sorted_idx[keep_pos]
        return x_samples[keep_idx]

