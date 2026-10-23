"""Rynki remisowe: ranking nadchodzących meczów, uczciwe kursy i porównanie ze średnią ligi."""
from __future__ import annotations

import pandas as pd

MARKETS = {
    "ht_or_ft": ("Remis do przerwy LUB na koniec meczu", "draw_ht_or_ft"),
    "either": ("Remis w 1. LUB 2. połowie", "draw_either_half"),
    "ht": ("Remis do przerwy", "draw_ht"),
    "2h": ("Remis w 2. połowie", "draw_2h"),
    "ft": ("Remis na koniec meczu", "draw_ft"),
}


def base_rates(df: pd.DataFrame) -> dict[str, float]:
    """Jak często te remisy zdarzają się w historii ligi (punkt odniesienia dla prognoz)."""
    t = df.dropna(subset=["hg", "ag", "hg_ht", "ag_ht"])
    if t.empty:
        return {}
    ht, h2, ft = t.hg_ht == t.ag_ht, (t.hg - t.hg_ht) == (t.ag - t.ag_ht), t.hg == t.ag
    return {"ht": float(ht.mean()), "2h": float(h2.mean()), "either": float((ht | h2).mean()),
            "ht_or_ft": float((ht | ft).mean()), "ft": float(ft.mean())}


def draw_table(P, df: pd.DataFrame, upcoming: pd.DataFrame, market: str = "ht_or_ft", days: int = 7,
               top: int | None = None) -> pd.DataFrame:
    """Nadchodzące mecze z prawdopodobieństwami remisów, uczciwym kursem (1/p) i różnicą względem średniej ligi."""
    if market not in MARKETS:
        raise ValueError(f"Nieznany rynek '{market}'. Dostępne: {', '.join(MARKETS)}")
    key = MARKETS[market][1]
    horizon = pd.Timestamp.today().normalize() + pd.Timedelta(days=days)
    base = base_rates(df).get(market)
    rows = []
    for r in upcoming[upcoming["date"] <= horizon].to_dict("records"):
        if r["home"] not in P.teams or r["away"] not in P.teams:
            continue
        p = P.predict(r["home"], r["away"], r.get("referee"))
        if "halves" not in p:
            continue
        h = p["halves"]
        sel = h[key]
        rows.append({"data": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"), "mecz": f"{r['home']} – {r['away']}",
                     "xG": f"{p['xg']['home']}–{p['xg']['away']}",
                     "HT_%": 100 * h["draw_ht"], "2H_%": 100 * h["draw_2h"], "HT_lub_2H_%": 100 * h["draw_either_half"],
                     "HT_lub_FT_%": 100 * h["draw_ht_or_ft"], "FT_%": 100 * h["draw_ft"],
                     "kurs_fair": 1 / sel, "vs_liga_pp": (100 * (sel - base)) if base is not None else None, "_p": sel})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("_p", ascending=False).drop(columns="_p")
    out = out.head(top) if top else out
    return out.round(2).reset_index(drop=True)
