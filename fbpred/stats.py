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
    out["over25"] = float(((d["hg"] + d["ag"]) > 2.5).mean())
    for col_h, col_a, mean_k, share_k, line in (("h_yellow", "a_yellow", "yellow_mean", "yellow35", 3.5),
                                                ("h_corners", "a_corners", "corners_mean", "corners95", 9.5)):
        if col_h in d and col_a in d:
            c = d[d[col_h].notna() & d[col_a].notna()]
            if len(c) >= 100:
                tot = c[col_h] + c[col_a]
                out[mean_k], out[share_k] = float(tot.mean()), float((tot > line).mean())
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


def grade(diff: float, big: float, small: float) -> str:
    """Klasa koloru: up2/up1 = wyraźnie/lekko powyżej średniej, dn2/dn1 = poniżej, '' = blisko średniej."""
    if diff >= big:
        return "up2"
    if diff >= small:
        return "up1"
    if diff <= -big:
        return "dn2"
    if diff <= -small:
        return "dn1"
    return ""


def tiles(pred: dict, base: dict[str, float], margin: float = 0.08) -> dict[str, dict]:
    """Kafelki do listy Mecze: wartość, średnia ligi i klasa koloru (zielone = ponad średnią, czerwone = poniżej).

    Progi: dla szans w punktach procentowych (duży = `margin`, mały = min(3 pp, margin/2)); dla średnich liczb (kartki, rożne)
    względnie: duży = 12%, mały = 5%."""
    small = min(0.03, margin / 2)
    out: dict[str, dict] = {}

    def pct(key, label, p, b):
        if p is None:
            return
        d = {"label": label, "txt": f"{100 * p:.0f}%", "cls": "", "base_txt": "", "d_txt": "", "short": ""}
        if b is not None:
            diff = p - b
            dd = round(100 * diff)
            d.update(cls=grade(diff, margin, small), base_txt=f"liga {100 * b:.0f}%", d_txt=f"{dd:+d} pp" if dd else "0 pp",
                     short=f"{dd:+d}" if dd else "0")
        out[key] = d

    def mean(key, label, v, b):
        if v is None:
            return
        d = {"label": label, "txt": f"{v:.1f}", "cls": "", "base_txt": "", "d_txt": "", "short": ""}
        if b:
            rel = v / b - 1
            dd = round(100 * rel)
            d.update(cls=grade(rel, 0.12, 0.05), base_txt=f"liga {b:.1f}", d_txt=f"{dd:+d}%" if dd else "0%",
                     short=f"{dd:+d}%" if dd else "0")
        out[key] = d

    g, h = pred.get("goals", {}), pred.get("halves") or {}
    pct("over25", "O2.5", g.get("over_2.5"), base.get("over25"))
    pct("btts", "BTTS", g.get("btts_yes"), base.get("btts"))
    for k, label in (("draw_ht", "Remis HT"), ("draw_2h", "Remis 2H"), ("draw_either_half", "HT lub 2H"),
                     ("draw_ht_or_ft", "HT lub FT"), ("draw_ft", "Remis FT")):
        pct(k, label, h.get(k), base.get(k))
    y, c = pred.get("yellow") or {}, pred.get("corners") or {}
    pct("yellow35", "Żółte O3.5", (y.get("over") or {}).get("3.5"), base.get("yellow35"))
    mean("yellow_mean", "Żółte śr.", y.get("total_mean"), base.get("yellow_mean"))
    pct("corners95", "Rożne O9.5", (c.get("over") or {}).get("9.5"), base.get("corners95"))
    mean("corners_mean", "Rożne śr.", c.get("total_mean"), base.get("corners_mean"))
    return out
