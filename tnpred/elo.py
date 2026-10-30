"""Elo ogólne + Elo na nawierzchni (styl FiveThirtyEight: K maleje z liczbą meczów zawodnika).

Szansa = Elo „zmieszane”: (1-w)·ogólne + w·nawierzchnia. Każdy system aktualizuje się własnym oczekiwaniem.
Walk-forward: dla każdego meczu zapamiętujemy prognozę SPRZED meczu (do backtestu i zakładki Ostatnie).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SURFACES = ("Hard", "Clay", "Grass")


def surface_of(s) -> str:
    s = str(s or "").strip().capitalize()
    return s if s in SURFACES else "Hard"   # Carpet / brak -> twarda (hala)


def k_factor(n: int) -> float:
    return 250.0 / (n + 5) ** 0.4


def initial_rating(rank) -> float:
    """Debiutant w bazie: ocena z rankingu (lepsze niż 1500 dla każdego kwalifikanta)."""
    try:
        r = float(rank)
    except (TypeError, ValueError):
        r = float("nan")
    if not (r == r) or r <= 0:
        return 1380.0
    return float(min(max(1500.0 - 100.0 * math.log(r / 50.0), 1300.0), 1800.0))


def expect(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class Elo:
    def __init__(self, surface_weight: float = 0.5):
        self.w = surface_weight
        self.r: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.rs: dict[tuple[str, str], float] = {}
        self.ns: dict[tuple[str, str], int] = {}
        self.last: dict[str, pd.Timestamp] = {}
        self.rank: dict[str, float] = {}
        self.hist: dict[str, list[tuple]] = {}

    def _ensure(self, key: str, rank) -> None:
        if key not in self.r:
            self.r[key] = initial_rating(rank)
            self.n[key] = 0

    def rating(self, key: str, surface: str, rank=None) -> tuple[float, float, float]:
        """(ogólne, nawierzchnia, zmieszane) - dla nieznanego zawodnika z rankingu."""
        base = self.r.get(key, initial_rating(rank))
        rs = self.rs.get((key, surface), base)
        return base, rs, (1 - self.w) * base + self.w * rs

    def prob(self, a: str, b: str, surface: str, rank_a=None, rank_b=None) -> float:
        return expect(self.rating(a, surface, rank_a)[2], self.rating(b, surface, rank_b)[2])

    def update(self, w: str, l: str, surface: str, date, rank_w=None, rank_l=None) -> float:
        """Aktualizacja po meczu (w wygrał). Zwraca prognozę SPRZED meczu dla zwycięzcy."""
        self._ensure(w, rank_w)
        self._ensure(l, rank_l)
        for k, rk in ((w, rank_w), (l, rank_l)):
            if rk == rk and rk is not None:
                self.rank[k] = rk
        p = self.prob(w, l, surface)
        sw, sl = (w, surface), (l, surface)
        self.rs.setdefault(sw, self.r[w])     # pierwszy mecz na nawierzchni: start od oceny ogólnej
        self.rs.setdefault(sl, self.r[l])
        e = expect(self.r[w], self.r[l])
        kw, kl = k_factor(self.n[w]), k_factor(self.n[l])
        self.r[w] += kw * (1 - e)
        self.r[l] -= kl * (1 - e)
        self.ns.setdefault(sw, 0)
        self.ns.setdefault(sl, 0)
        es = expect(self.rs[sw], self.rs[sl])
        self.rs[sw] += k_factor(self.ns[sw]) * (1 - es)
        self.rs[sl] -= k_factor(self.ns[sl]) * (1 - es)
        self.n[w] += 1
        self.n[l] += 1
        self.ns[sw] += 1
        self.ns[sl] += 1
        self.last[w] = self.last[l] = date
        for k in (w, l):
            self.hist.setdefault(k, []).append((date, round(self.r[k], 1)))
        return p


def walk(df: pd.DataFrame, surface_weight: float = 0.5, use_retired: bool = False) -> tuple[Elo, np.ndarray]:
    """Przechodzi mecze chronologicznie. Zwraca (Elo po wszystkich meczach, prognozy sprzed meczu dla zwycięzcy)."""
    elo = Elo(surface_weight)
    out = np.full(len(df), np.nan)
    tours, ws, ls = df["tour"].to_numpy(), df["winner"].to_numpy(), df["loser"].to_numpy()
    surf, dates = df["surface"].to_numpy(), df["date"].to_numpy()
    wr, lr = df["wrank"].to_numpy(dtype=float), df["lrank"].to_numpy(dtype=float)
    comment = df["comment"].fillna("Completed").astype(str).to_numpy()
    for i in range(len(df)):
        a, b = f"{tours[i]}|{ws[i]}", f"{tours[i]}|{ls[i]}"
        c = comment[i].lower()
        if c.startswith("walk") or c.startswith("w/o") or c.startswith("disq"):
            continue
        if c.startswith("ret") and not use_retired:
            out[i] = elo.prob(a, b, surf[i], wr[i], lr[i])
            continue
        out[i] = elo.update(a, b, surf[i], pd.Timestamp(dates[i]), wr[i], lr[i])
    return elo, out
