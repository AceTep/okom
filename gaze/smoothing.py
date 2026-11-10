"""One Euro filter (Casiez, Roussel, Vogel, CHI 2012) for a feature vector.

Low-pass filter whose cutoff rises with speed: strong smoothing while the
signal is steady (removes jitter), little smoothing during fast movement
(keeps latency low). Applied per dimension.
"""

from __future__ import annotations

import math

import numpy as np


def _alpha(cutoff_hz: float, dt: float) -> float:
    tau = 1.0 / (2 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    def __init__(
        self, min_cutoff_hz: float, beta: float, d_cutoff_hz: float, reset_after_s: float = 0.5
    ) -> None:
        self.min_cutoff = min_cutoff_hz
        self.beta = beta
        self.d_cutoff = d_cutoff_hz
        self.reset_after = reset_after_s
        self._t: float | None = None
        self._x: np.ndarray | None = None
        self._dx: np.ndarray | None = None

    def reset(self) -> None:
        self._t = self._x = self._dx = None

    def __call__(self, t: float, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if self._t is None or t - self._t > self.reset_after or t <= self._t:
            # first sample, a long gap (face lost) or time going backwards: start over
            self._t, self._x, self._dx = t, x.copy(), np.zeros_like(x)
            return x.copy()
        dt = t - self._t
        dx = (x - self._x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * np.abs(self._dx)
        tau = 1.0 / (2 * math.pi * cutoff)
        a = 1.0 / (1.0 + tau / dt)
        self._x = a * x + (1 - a) * self._x
        self._t = t
        return self._x.copy()
