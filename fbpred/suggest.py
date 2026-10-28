"""Podpowiedzi modelu: najbardziej prawdopodobne typy wg Twoich kryteriów + automatyczny kupon."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from . import profile as prof
from .betmarkets import GROUPS, book_odds, catalogue, leg_id
from .odds import apply_blend, edge
from .stats import season_slice

PROFILES = {"": None, "balanced_away": [prof.GROUPS[0]], "balanced": [prof.GROUPS[0], prof.GROUPS[1]]}


@dataclass
class Criteria:
    min_p: float = 0.60
    max_p: float = 0.97
    groups: tuple = ("Remisy",)
    keys: tuple = ()                 # jeśli niepuste: tylko te rynki (np. d_either, d_htft)
    days: int = 3
    min_games: int = 12              # drużyny z mniejszą liczbą meczów (np. beniaminkowie) są odrzucane
    skip_short_rest: bool = False
    min_edge: float | None = None    # wymaga kursu bukmachera z bazy
    profile: str = ""                # "", "balanced_away", "balanced"
    balance: float = 0.10
    max_per_match: int = 1
    top: int = 20
    sort: str = "p"                  # "p" albo "edge"
    flags_hide: list = field(default_factory=list)


def team_games(df: pd.DataFrame, seasons: int = 2) -> Counter:
    d = season_slice(df, seasons)
    return Counter(list(d["home"]) + list(d["away"]))


def leg_flags(pred: dict, row: dict, games: Counter, min_games: int, p_edge: float | None = None) -> list[str]:
    """Ostrzeżenia o ryzyku dla jednego typu."""
    out = []
    for side in ("home", "away"):
        n = games.get(pred[side], 0)
        if n < min_games:
            out.append(f"mało danych: {pred[side]} ({n} meczów) - model słabo zna tę drużynę")
    rs = pred.get("rest")
    if rs and (rs["home_short"] or rs["away_short"]):
        who = [pred[s] for s in ("home", "away") if rs[f"{s}_short"]]
        out.append("krótka przerwa: " + ", ".join(who))
    mk = pred.get("market_1x2")
    if mk:
        gap = max(abs(pred["1x2"][k] - mk[k]) for k in "1X2")
        if gap > 0.12:
            out.append(f"model vs rynek: różnica {100 * gap:.0f} pp w 1X2")
    if p_edge is not None and p_edge > 0.15:
        out.append("przewaga >15% nad kursem - zwykle błąd modelu")
    return out


def suggestions(P, df: pd.DataFrame, up: pd.DataFrame, c: Criteria, blend_w=None, league: str = "") -> tuple[pd.DataFrame, dict]:
    """Zwraca (tabela podpowiedzi, statystyki odrzuceń)."""
    games = team_games(df)
    horizon = pd.Timestamp.today().normalize() + pd.Timedelta(days=c.days)
    rows, rej = [], Counter()
    for r in up[up["date"] <= horizon].to_dict("records"):
        if r["home"] not in P.teams or r["away"] not in P.teams:
            rej["nieznana drużyna"] += 1
            continue
        pred = apply_blend(P.predict(r["home"], r["away"], r.get("referee"), date=r["date"]), r, blend_w)
        if min(games.get(r["home"], 0), games.get(r["away"], 0)) < c.min_games:
            rej["za mało danych o drużynie"] += 1
            continue
        if c.skip_short_rest and pred.get("rest") and (pred["rest"]["home_short"] or pred["rest"]["away_short"]):
            rej["krótka przerwa"] += 1
            continue
        if PROFILES.get(c.profile):
            if not all(r.get(k) for k in ("o_home", "o_draw", "o_away")):
                rej["brak kursów do oceny profilu"] += 1
                continue
            m = prof.market_features(pd.DataFrame([{**r, "hg": 0, "ag": 0, "hg_ht": 0, "ag_ht": 0}]), c.balance)
            if m.empty or m.iloc[0]["grupa"] not in PROFILES[c.profile]:
                rej["inny profil kursów"] += 1
                continue
        for key, m in catalogue(pred).items():
            if c.keys and key not in c.keys:
                continue
            if not c.keys and c.groups and m["group"] not in c.groups:
                continue
            if not (c.min_p <= m["p"] <= c.max_p):
                continue
            odds = book_odds(r, key)
            e = edge(m["p"], odds) if odds else None
            if c.min_edge is not None and (e is None or e < c.min_edge):
                continue
            rows.append({"id": leg_id(league or r["league"], r["date"], r["home"], r["away"], key),
                         "data": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"), "mecz": f"{r['home']} – {r['away']}",
                         "rynek": m["label"], "key": key, "p_%": 100 * m["p"], "kurs_fair": 1 / m["p"],
                         "kurs_bukm": odds, "przewaga_%": None if e is None else 100 * e,
                         "ostrzeżenia": "; ".join(leg_flags(pred, r, games, c.min_games, e))})
    if not rows:
        return pd.DataFrame(), dict(rej)
    out = pd.DataFrame(rows)
    sort_col = "przewaga_%" if c.sort == "edge" else "p_%"
    out = out.sort_values(sort_col, ascending=False, na_position="last")
    out = out.groupby("mecz", sort=False).head(c.max_per_match).head(c.top).reset_index(drop=True)
    return out.round(2), dict(rej)


def auto_coupon(sugg: pd.DataFrame, legs: int = 3) -> pd.DataFrame:
    """Najlepsze `legs` typów z RÓŻNYCH meczów (z listy podpowiedzi posortowanej wg kryterium)."""
    if sugg.empty:
        return sugg
    return sugg.drop_duplicates("mecz").head(legs).reset_index(drop=True)


def combine(ps: list[float], odds: list[float | None] | None = None) -> dict:
    """Łączny kupon przy założeniu niezależności meczów (poprawne tylko dla typów z RÓŻNYCH meczów)."""
    p = 1.0
    for x in ps:
        p *= x
    out = {"p": p, "kurs_fair": 1 / p if p else None, "min_sensowny_kurs": 1.1 / p if p else None}
    if odds and all(o for o in odds):
        o = 1.0
        for x in odds:
            o *= x
        out.update(kurs_laczny=o, ev=p * o - 1)
    return out


def coupon_summary(legs: list[dict], combined: dict | None, warnings: list[str]) -> str:
    """Zwięzłe podsumowanie kuponu oparte na regułach (działa zawsze, za darmo, bez AI)."""
    ok = [l for l in legs if not l.get("blad")]
    if not ok:
        return "Brak poprawnych typów w zestawieniu."
    L = [f"Typów: {len(ok)}."]
    weakest = min(ok, key=lambda l: l["p"])
    L.append(f"Najsłabszy typ (noga): {weakest['mecz']} - {weakest['rynek']} ({100 * weakest['p']:.0f}%).")
    if combined:
        L.append(f"Szansa całego kuponu wg modelu: {100 * combined['p']:.1f}% (uczciwy kurs {combined['kurs_fair']:.2f}; "
                 f"sensowny dopiero od ok. {combined['min_sensowny_kurs']:.2f}).")
        if combined.get("ev") is not None:
            ev = 100 * combined["ev"]
            L.append(f"Przy kursie łącznym {combined['kurs_laczny']:.2f} oczekiwany zwrot wynosi {ev:+.0f}% - "
                     + ("poniżej zera: kupon wygląda na nieopłacalny wg modelu." if ev < 0 else
                        "dodatni tylko jeśli prawdopodobieństwa modelu są trafne; to właśnie najczęstsze źródło pomyłek."))
    flagged = sorted({w for l in ok for w in l.get("ostrzezenia", [])})
    if flagged:
        L.append("Ostrzeżenia: " + " | ".join(flagged[:6]) + ".")
    if any(l["key"].startswith("d_") for l in ok):
        L.append("Uwaga: dla rynków remisów w połowach źródło danych nie ma historycznych kursów, więc nie da się ich porównać z rynkiem; "
                 "sprawdź w backteście tabelę obciążenia.")
    L += warnings
    return "\n".join(L)
