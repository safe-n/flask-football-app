"""Rynki wyprowadzane z rozkładów prawdopodobieństwa (macierze wyników, pmf)."""
from __future__ import annotations

import numpy as np


def outcome_1x2(m: np.ndarray) -> dict[str, float]:
    return {"1": float(np.tril(m, -1).sum()), "X": float(np.trace(m)), "2": float(np.triu(m, 1).sum())}


def total_pmf(m: np.ndarray) -> np.ndarray:
    """Rozkład sumy goli z macierzy wyników."""
    n = m.shape[0]
    out = np.zeros(2 * n - 1)
    for s in range(2 * n - 1):
        out[s] = np.trace(m[:, ::-1], offset=n - 1 - s)
    return out


def over(pmf: np.ndarray, line: float) -> float:
    k = np.arange(len(pmf))
    return float(pmf[k > line].sum())


def btts(m: np.ndarray) -> float:
    return float(m[1:, 1:].sum())


def top_scores(m: np.ndarray, n: int = 5) -> list[tuple[str, float]]:
    flat = [(f"{i}-{j}", float(m[i, j])) for i in range(m.shape[0]) for j in range(m.shape[1])]
    return sorted(flat, key=lambda x: -x[1])[:n]


def convolve(p1: np.ndarray, p2: np.ndarray) -> np.ndarray:
    """Rozkład sumy dwóch niezależnych zmiennych (np. kartki gospodarzy + gości)."""
    return np.convolve(p1, p2)


def diff_dist(m: np.ndarray) -> dict[int, float]:
    """Rozkład różnicy bramek (gospodarze - goście)."""
    n = m.shape[0]
    return {d: float(np.trace(m, offset=-d)) for d in range(-(n - 1), n)}


def sign_label(d: int) -> str:
    return "1" if d > 0 else ("X" if d == 0 else "2")


def htft(m_ht: np.ndarray, m_2h: np.ndarray) -> dict[str, float]:
    """Połowa/mecz (9 kombinacji) przy niezależnych połowach."""
    d1, d2 = diff_dist(m_ht), diff_dist(m_2h)
    out = {f"{a}/{b}": 0.0 for a in "1X2" for b in "1X2"}
    for x, px in d1.items():
        for y, py in d2.items():
            out[f"{sign_label(x)}/{sign_label(x + y)}"] += px * py
    return out


# ----------------------------------------------------------------- rynki dodatkowe
def double_chance(m: np.ndarray) -> dict[str, float]:
    p = outcome_1x2(m)
    return {"1X": p["1"] + p["X"], "X2": p["X"] + p["2"], "12": p["1"] + p["2"]}


def draw_no_bet(m: np.ndarray) -> dict[str, float]:
    p = outcome_1x2(m)
    s = p["1"] + p["2"]
    return {"home": p["1"] / s, "away": p["2"] / s}


def asian(m: np.ndarray, line: float) -> dict[str, float]:
    """Handicap azjatycki (całe i połówkowe linie) dla gospodarzy: win / push / lose."""
    win = push = lose = 0.0
    for d, p in diff_dist(m).items():
        x = d + line
        if x > 1e-9:
            win += p
        elif abs(x) <= 1e-9:
            push += p
        else:
            lose += p
    return {"win": win, "push": push, "lose": lose}


def team_totals(m: np.ndarray) -> dict[str, dict[str, float]]:
    ph, pa = m.sum(axis=1), m.sum(axis=0)
    return {"home": {str(l): over(ph, l) for l in (0.5, 1.5, 2.5)},
            "away": {str(l): over(pa, l) for l in (0.5, 1.5, 2.5)}}


def clean_sheets(m: np.ndarray) -> dict[str, float]:
    return {"home_cs": float(m[:, 0].sum()), "away_cs": float(m[0, :].sum()),
            "home_win_to_nil": float(m[1:, 0].sum()), "away_win_to_nil": float(m[0, 1:].sum())}


def exact_total(tot: np.ndarray) -> dict[str, float]:
    out = {str(k): float(tot[k]) for k in range(5)}
    out["5+"] = float(tot[5:].sum())
    return out
