"""Kursy: usuwanie marży (proporcjonalnie / metoda potęgowa), mieszanie z modelem, edge, Kelly."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq


def implied_probs(odds: list[float], method: str = "power") -> list[float]:
    """Prawdopodobieństwa z kursów bez marży.

    'power' (domyślnie) koryguje też "longshot bias" (marża jest większa na outsiderach),
    'proportional' skaluje wszystko równo.
    """
    inv = np.array([1.0 / o for o in odds])
    s = inv.sum()
    if method == "power" and s > 1 + 1e-9:
        k = brentq(lambda k: (inv ** k).sum() - 1.0, 1.0, 60.0)
        return list(inv ** k)
    return list(inv / s)


def overround(odds: list[float]) -> float:
    return float(sum(1.0 / o for o in odds) - 1.0)


def blend_probs(model: list[float], market: list[float], w: float) -> list[float]:
    """w = waga modelu (0 = sam rynek, 1 = sam model)."""
    b = w * np.asarray(model) + (1 - w) * np.asarray(market)
    return list(b / b.sum())


def edge(p_model: float, odds: float) -> float:
    """Oczekiwany zwrot z 1 jednostki: p*kurs - 1."""
    return p_model * odds - 1.0


def kelly(p_model: float, odds: float, fraction: float = 0.25, cap: float = 0.03) -> float:
    """Ułamkowy Kelly (domyślnie 1/4) z twardym limitem na bankroll."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (p_model * b - (1 - p_model)) / b
    return float(min(max(f * fraction, 0.0), cap))


def _valid(*odds) -> bool:
    return all(o is not None and pd.notna(o) and o > 1.0 for o in odds)


def market_1x2(row: dict) -> list[float] | None:
    o = [row.get("o_home"), row.get("o_draw"), row.get("o_away")]
    return implied_probs(o) if _valid(*o) else None


def apply_blend(pred: dict, row: dict, w: float | None) -> dict:
    """Dodaje do prognozy `market_1x2` i `1x2_blend` (jeśli są kursy i znana waga)."""
    q = market_1x2(row)
    if q is None:
        return pred
    pred["market_1x2"] = {k: round(float(v), 4) for k, v in zip("1X2", q)}
    if w is not None:
        b = blend_probs([pred["1x2"][k] for k in "1X2"], q, w)
        pred["1x2_blend"] = {k: round(float(v), 4) for k, v in zip("1X2", b)}
    return pred


def value_picks(pred: dict, row: dict, min_edge: float = 0.03) -> list[dict]:
    """Typy z przewagą nad kursem. Dla 1X2 używa wersji zmieszanej z rynkiem, jeśli dostępna."""
    picks = []

    def add(name, p, o):
        if _valid(o):
            e = edge(p, o)
            if e >= min_edge:
                picks.append({"rynek": name, "p_model": round(p, 3), "kurs": o,
                              "edge": round(e, 3), "kelly_1/4": round(kelly(p, o), 4)})

    x = pred.get("1x2_blend") or pred["1x2"]
    add("1", x["1"], row.get("o_home"))
    add("X", x["X"], row.get("o_draw"))
    add("2", x["2"], row.get("o_away"))
    add("Over 2.5", pred["goals"]["over_2.5"], row.get("o_over25"))
    add("Under 2.5", pred["goals"]["under_2.5"], row.get("o_under25"))
    add("BTTS tak", pred["goals"]["btts_yes"], row.get("o_btts_yes"))
    add("BTTS nie", pred["goals"]["btts_no"], row.get("o_btts_no"))
    return sorted(picks, key=lambda d: -d["edge"])
