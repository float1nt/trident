import math

import numpy as np
from scipy.stats import genpareto


class TScissors:
    """EVT-based threshold estimator (POT)."""

    def __init__(self, evt_quantile: float = 0.95, evt_risk: float = 1e-3, fallback_quantile: float = 0.995):
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

