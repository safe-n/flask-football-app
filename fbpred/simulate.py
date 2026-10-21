"""Symulacja Monte Carlo reszty sezonu: szanse na mistrzostwo, puchary, spadek, oczekiwane punkty."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models.goals import MAX_GOALS
from .predictor import MatchPredictor


def simulate_table(df: pd.DataFrame, P: MatchPredictor, upcoming: pd.DataFrame | None = None,
                   n: int = 5000, seed: int = 1, n_european: int = 4, n_relegated: int = 3):
    """Zwraca (tabela_prawdopodobieństw, info).

    Pozostałe mecze: jeśli w bazie są nierozegrane mecze bieżącego sezonu (`upcoming`) - bierzemy je,
    w przeciwnym razie zakładamy ligę kółko-i-kółko i dogrywamy brakujące pary.
    """
    cur = df["season"].max() if df["season"].notna().any() else None
    d = df if cur is None else df[df["season"] == cur]
    teams = sorted(set(d["home"]) | set(d["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)

    pts0, gd0, gf0, played = np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T)
    done = set()
    for r in d.itertuples(index=False):
        h, a = idx[r.home], idx[r.away]
        done.add((r.home, r.away))
        played[h] += 1
        played[a] += 1
        gf0[h] += r.hg
        gf0[a] += r.ag
        gd0[h] += r.hg - r.ag
        gd0[a] += r.ag - r.hg
        if r.hg > r.ag:
            pts0[h] += 3
        elif r.hg < r.ag:
            pts0[a] += 3
        else:
            pts0[h] += 1
            pts0[a] += 1

    method = "kalendarz z bazy"
    rem = []
    if upcoming is not None and not upcoming.empty:
        u = upcoming if cur is None else upcoming[upcoming["season"] == cur]
        rem = [(r.home, r.away) for r in u.itertuples(index=False) if r.home in idx and r.away in idx]
    if not rem:
        method = "dogrywka brakujących par (kółko i kółko)"
        rem = [(h, a) for h in teams for a in teams if h != a and (h, a) not in done]

    rng = np.random.default_rng(seed)
    pts = np.tile(pts0, (n, 1))
    gd = np.tile(gd0, (n, 1))
    gf = np.tile(gf0, (n, 1))
    G = MAX_GOALS + 1
    for h, a in rem:
        cdf = np.cumsum(P.goals.matrix(h, a).ravel())
        cdf[-1] = 1.0
        k = np.searchsorted(cdf, rng.random(n))
        i, j = np.divmod(k, G)
        hi, ai = idx[h], idx[a]
        pts[:, hi] += 3 * (i > j) + (i == j)
        pts[:, ai] += 3 * (i < j) + (i == j)
        gd[:, hi] += i - j
        gd[:, ai] += j - i
        gf[:, hi] += i
        gf[:, ai] += j

    score = pts * 1e6 + gd * 1e3 + gf + rng.random((n, T)) * 0.5  # losowy remis końcowy
    order = np.argsort(-score, axis=1)
    rank = np.argsort(order, axis=1) + 1
    out = pd.DataFrame({
        "druzyna": teams, "mecze": played.astype(int), "pkt_teraz": pts0.astype(int),
        "pkt_oczek": pts.mean(axis=0).round(1), "miejsce_oczek": rank.mean(axis=0).round(1),
        "mistrz_%": (rank == 1).mean(axis=0) * 100,
        f"top{n_european}_%": (rank <= n_european).mean(axis=0) * 100,
        f"spadek_%": (rank > T - n_relegated).mean(axis=0) * 100,
    })
    out = out.sort_values(["pkt_oczek"], ascending=False).reset_index(drop=True)
    for c in out.columns:
        if c.endswith("_%"):
            out[c] = out[c].round(1)
    info = {"sezon": None if cur is None else int(cur), "pozostalo_meczow": len(rem), "metoda": method, "symulacji": n}
    return out, info
