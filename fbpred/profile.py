"""Czy metoda "wyrównane kursy, lekka przewaga gości => remis w 1. lub 2. połowie" działa? Test na historii (kursy + wyniki).

Dla każdego rozegranego meczu z kursami 1X2 liczymy prawdopodobieństwa rynku (bez marży), dzielimy mecze na profile kursów
i porównujemy, jak często w danym profilu padał remis do przerwy / w 2. połowie / w którejś z nich / do przerwy lub na koniec.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .odds import implied_probs

GROUPS = ["wyrównane, gość lekko faworytem", "wyrównane, gospodarz lekko faworytem",
          "gość wyraźnym faworytem", "gospodarz wyraźnym faworytem"]
USER_GROUP = GROUPS[0]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Przedział Wilsona dla częstości k/n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def classify(diff: float, balance: float) -> str:
    """diff = P(gość) - P(gospodarz) wg rynku."""
    if diff > balance:
        return GROUPS[2]
    if diff < -balance:
        return GROUPS[3]
    return GROUPS[0] if diff > 0 else GROUPS[1]


def market_features(df: pd.DataFrame, balance: float = 0.10) -> pd.DataFrame:
    """Dodaje do ramki: ph, px, pa (rynek), diff, grupa i flagi remisów (tylko mecze z kursami i wynikiem do przerwy)."""
    need = ["o_home", "o_draw", "o_away", "hg", "ag", "hg_ht", "ag_ht"]
    d = df.dropna(subset=need).copy()
    d = d[(d["o_home"] > 1) & (d["o_draw"] > 1) & (d["o_away"] > 1)]
    if d.empty:
        return d
    pr = np.array([implied_probs([a, b, c]) for a, b, c in zip(d.o_home, d.o_draw, d.o_away)])
    d["ph"], d["px"], d["pa"] = pr[:, 0], pr[:, 1], pr[:, 2]
    d["diff"] = d["pa"] - d["ph"]
    d["grupa"] = [classify(x, balance) for x in d["diff"]]
    d["d_ht"] = d["hg_ht"] == d["ag_ht"]
    d["d_2h"] = (d["hg"] - d["hg_ht"]) == (d["ag"] - d["ag_ht"])
    d["d_either"] = d["d_ht"] | d["d_2h"]
    d["d_htft"] = d["d_ht"] | (d["hg"] == d["ag"])
    d["d_ft"] = d["hg"] == d["ag"]
    d["gole"] = d["hg"] + d["ag"]
    if {"o_over25", "o_under25"} <= set(d.columns):
        ou = d.dropna(subset=["o_over25", "o_under25"])
        d["p_over25"] = np.nan
        d.loc[ou.index, "p_over25"] = [implied_probs([a, b])[0] for a, b in zip(ou.o_over25, ou.o_under25)]
    return d


def _row(name: str, g: pd.DataFrame, rest: pd.DataFrame | None = None) -> dict:
    n = len(g)
    k = int(g["d_either"].sum())
    lo, hi = wilson(k, n)
    row = {"profil": name, "mecze": n, "remis_1H_lub_2H_%": 100 * k / n if n else np.nan,
           "przedzial_95_%": f"{100 * lo:.0f}–{100 * hi:.0f}" if n else "–",
           "remis_HT_%": 100 * g["d_ht"].mean() if n else np.nan, "remis_2H_%": 100 * g["d_2h"].mean() if n else np.nan,
           "HT_lub_FT_%": 100 * g["d_htft"].mean() if n else np.nan, "gole_śr": g["gole"].mean() if n else np.nan}
    if rest is not None and n and len(rest):
        p1, p2 = k / n, rest["d_either"].mean()
        se = np.sqrt(p1 * (1 - p1) / n + p2 * (1 - p2) / len(rest))
        row["vs_reszta_pp"] = 100 * (p1 - p2)
        row["różnica_95%"] = f"{100 * (p1 - p2 - 1.96 * se):+.1f} … {100 * (p1 - p2 + 1.96 * se):+.1f}"
    return row


def odds_profile(df: pd.DataFrame, balance: float = 0.10) -> dict:
    """Tabele: częstość remisów wg profilu kursów oraz wg profilu i oczekiwanej liczby goli. Plus werdykt dla Twojej metody."""
    d = market_features(df, balance)
    if d.empty:
        return {"n": 0}
    rows = [_row("WSZYSTKIE MECZE", d)]
    for g in GROUPS:
        sub = d[d["grupa"] == g]
        rows.append(_row(g + (" ← Twoja metoda" if g == USER_GROUP else ""), sub, d[d["grupa"] != g]))
    main = pd.DataFrame(rows).round(2)
    split = pd.DataFrame()
    if "p_over25" in d and d["p_over25"].notna().sum() > 100:
        e = d.dropna(subset=["p_over25"]).copy()
        e["gole_oczek"] = np.where(e["p_over25"] < 0.5, "mało goli (O2.5 < 50%)", "dużo goli (O2.5 ≥ 50%)")
        r2 = []
        for g in GROUPS[:2] + GROUPS[2:]:
            for lab in ("mało goli (O2.5 < 50%)", "dużo goli (O2.5 ≥ 50%)"):
                sub = e[(e["grupa"] == g) & (e["gole_oczek"] == lab)]
                if len(sub):
                    r = _row(f"{g} | {lab}", sub)
                    r2.append({k: r[k] for k in ("profil", "mecze", "remis_1H_lub_2H_%", "przedzial_95_%", "gole_śr")})
        split = pd.DataFrame(r2).round(2)
    mine = d[d["grupa"] == USER_GROUP]
    rest = d[d["grupa"] != USER_GROUP]
    verdict = "za mało meczów w tej grupie, by cokolwiek stwierdzić"
    if len(mine) >= 30 and len(rest) >= 30:
        p1, p2 = mine["d_either"].mean(), rest["d_either"].mean()
        se = np.sqrt(p1 * (1 - p1) / len(mine) + p2 * (1 - p2) / len(rest))
        lo, hi = p1 - p2 - 1.96 * se, p1 - p2 + 1.96 * se
        verdict = (f"Twoja grupa: {100 * p1:.1f}% vs reszta {100 * p2:.1f}% (różnica {100 * (p1 - p2):+.1f} pp, 95%: {100 * lo:+.1f} … {100 * hi:+.1f}). "
                   + ("To różnica istotna statystycznie." if lo > 0 or hi < 0 else
                      "To różnica w granicach szumu - dane nie potwierdzają przewagi tej grupy."))
    return {"n": len(d), "tabela": main, "podzial_goli": split, "werdykt": verdict}
