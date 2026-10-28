"""Statystyki opisowe: sędziowie (kartki, rożne), drużyny (kartki, rożne, strzały) + mnożniki z modeli."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models.counts import to_long


def season_slice(df: pd.DataFrame, seasons: int = 1) -> pd.DataFrame:
    """Ostatnie `seasons` sezonów (po kolumnie season; bez niej cała historia)."""
    if "season" not in df or df["season"].isna().all():
        return df
    return df[df["season"] > df["season"].max() - seasons]


def active_teams(df: pd.DataFrame) -> list[str]:
    """Drużyny z najnowszego sezonu (odsiewa kluby, które już dawno wypadły z ligi)."""
    last = season_slice(df, 1)
    return sorted(set(last["home"]) | set(last["away"]))


def referee_table(df: pd.DataFrame, P=None, seasons: int = 2, min_matches: int = 8) -> pd.DataFrame:
    """Sędziowie: średnie kartek i rożnych na mecz, odchylenie od średniej ligi i mnożnik z modelu (shrinkage)."""
    need = ["referee", "h_yellow", "a_yellow"]
    if any(c not in df for c in need):
        return pd.DataFrame()
    d = season_slice(df, seasons).dropna(subset=need).copy()
    if d.empty:
        return pd.DataFrame()
    d["zolte"] = d["h_yellow"] + d["a_yellow"]
    cols = {"mecze": ("zolte", "size"), "zolte_sr": ("zolte", "mean")}
    if {"h_red", "a_red"} <= set(d.columns) and d["h_red"].notna().any():
        d["czerwone"] = d["h_red"].fillna(0) + d["a_red"].fillna(0)
        cols["czerwone_sr"] = ("czerwone", "mean")
    if {"h_corners", "a_corners"} <= set(d.columns) and d["h_corners"].notna().any():
        d["rozne"] = d["h_corners"] + d["a_corners"]
        cols["rozne_sr"] = ("rozne", "mean")
    t = d.groupby("referee").agg(**cols)
    t["vs_liga_%"] = (t["zolte_sr"] / d["zolte"].mean() - 1) * 100
    if P is not None and getattr(P, "yellow", None) is not None and P.yellow.r:
        t["mnoznik_model"] = [float(np.exp(P.yellow.r.get(r, 0.0))) for r in t.index]
    t = t[t["mecze"] >= min_matches].sort_values("zolte_sr", ascending=False)
    return t.round(2).reset_index()


def team_table(df: pd.DataFrame, P=None, seasons: int = 1) -> pd.DataFrame:
    """Drużyny aktywne w lidze: gole, żółte kartki, rożne i celne strzały (zdobyte / stracone na mecz)."""
    d = season_slice(df, seasons)
    teams = active_teams(df)
    out = to_long(d, "hg", "ag").groupby("team").agg(mecze=("y", "size"), gole_za=("y", "mean"))
    out["gole_przeciw"] = to_long(d, "hg", "ag").groupby("opp")["y"].mean()
    for label, h, a in (("zolte", "h_yellow", "a_yellow"), ("rozne", "h_corners", "a_corners"), ("sot", "h_sot", "a_sot")):
        if h in d and d[h].notna().any():
            lg = to_long(d, h, a)
            out[f"{label}_za"] = lg.groupby("team")["y"].mean()
            out[f"{label}_przeciw"] = lg.groupby("opp")["y"].mean()
    if P is not None:
        if getattr(P, "yellow", None) is not None:
            out["kartki_x"] = [float(np.exp(P.yellow.f.get(t, 0.0))) for t in out.index]
        if getattr(P, "corners", None) is not None:
            out["rozne_x"] = [float(np.exp(P.corners.f.get(t, 0.0))) for t in out.index]
    out = out.loc[[t for t in out.index if t in teams]]
    return out.sort_values("gole_za", ascending=False).round(2).reset_index().rename(columns={"team": "druzyna"})


HL_KEYS = ("btts", "draw_ht", "draw_2h", "draw_either_half", "draw_ht_or_ft", "draw_ft")


def base_rates(df: pd.DataFrame, seasons: int = 3) -> dict[str, float]:
    """Średnia częstość zdarzeń w lidze (ostatnie sezony) - punkt odniesienia dla wyróżnień na stronie Mecze."""
    d = season_slice(df[df["hg"].notna()], seasons)
    out: dict[str, float] = {}
    if d.empty:
        return out
    out["btts"] = float(((d["hg"] > 0) & (d["ag"] > 0)).mean())
    out["draw_ft"] = float((d["hg"] == d["ag"]).mean())
    h = d[d["hg_ht"].notna() & d["ag_ht"].notna()]
    if len(h) >= 100:
        ht = h["hg_ht"] == h["ag_ht"]
        h2 = (h["hg"] - h["hg_ht"]) == (h["ag"] - h["ag_ht"])
        ft = h["hg"] == h["ag"]
        out.update(draw_ht=float(ht.mean()), draw_2h=float(h2.mean()), draw_either_half=float((ht | h2).mean()),
                   draw_ht_or_ft=float((ht | ft).mean()))
    return out


def highlights(pred: dict, base: dict[str, float], margin: float = 0.08) -> dict[str, bool]:
    """Które wartości są 'godne uwagi': co najmniej `margin` (domyślnie 8 pp) powyżej średniej ligi dla danego rynku."""
    vals = {"btts": pred["goals"]["btts_yes"]}
    for k in ("draw_ht", "draw_2h", "draw_either_half", "draw_ht_or_ft", "draw_ft"):
        if pred.get("halves") and k in pred["halves"]:
            vals[k] = pred["halves"][k]
    return {k: (k in base and v >= base[k] + margin) for k, v in vals.items()}
