"""Kursy: usuwanie marży (metoda potęgowa / proporcjonalna), mieszanie z modelem, edge, Kelly (jak w fbpred)."""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq


def valid(*odds) -> bool:
    for o in odds:
        try:
            if o is None or not (float(o) > 1.0) or math.isnan(float(o)):
                return False
        except (TypeError, ValueError):
            return False
    return True


def implied_probs(odds: list[float], method: str = "power") -> list[float]:
    inv = np.array([1.0 / float(o) for o in odds])
    s = inv.sum()
    if method == "power" and s > 1 + 1e-9:
        k = brentq(lambda k: (inv ** k).sum() - 1.0, 1.0, 60.0)
        return [float(x) for x in inv ** k]
    return [float(x) for x in inv / s]


def overround(odds: list[float]) -> float:
    return float(sum(1.0 / float(o) for o in odds) - 1.0)


def edge(p: float, odds: float) -> float:
    return p * float(odds) - 1.0


def kelly(p: float, odds: float, fraction: float = 0.25, cap: float = 0.03) -> float:
    b = float(odds) - 1.0
    if b <= 0:
        return 0.0
    f = (p * b - (1 - p)) / b
    return float(min(max(f * fraction, 0.0), cap))


def blend(p_model: float, p_market: float, w: float) -> float:
    """w = waga modelu (0 = sam rynek, 1 = sam model). Mieszanie w skali logitów - stabilniejsze przy skrajnych kursach."""
    lm = math.log(p_model / (1 - p_model))
    lk = math.log(p_market / (1 - p_market))
    x = w * lm + (1 - w) * lk
    return 1 / (1 + math.exp(-x))


def market_pair(o1, o2) -> tuple[float, float] | None:
    if not valid(o1, o2):
        return None
    a, b = implied_probs([o1, o2])
    return a, b
