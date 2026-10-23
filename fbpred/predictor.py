"""MatchPredictor: składa wszystkie modele i zwraca prognozy dla pojedynczego meczu."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models import markets as mk
from .models.counts import CountModel, to_long
from .models.goals import DixonColes, score_matrix

GOAL_LINES = (1.5, 2.5, 3.5)
YELLOW_LINES = (2.5, 3.5, 4.5, 5.5)
CORNER_LINES = (8.5, 9.5, 10.5, 11.5)


def _r(x: float, n: int = 4) -> float:
    return round(float(x), n)


DRAW_KEYS = ("draw_ht", "draw_2h", "draw_either_half", "draw_ht_or_ft")


def shift_prob(p: float, s: float) -> float:
    """Przesunięcie prawdopodobieństwa na skali logitów (kalibracja obciążenia modelu)."""
    if not s:
        return p
    p = min(max(p, 1e-6), 1 - 1e-6)
    return float(1.0 / (1.0 + np.exp(-(np.log(p / (1 - p)) + s))))


class MatchPredictor:
    """Trenuje modele na `df` (zakończone mecze jednej ligi).

    Wymagane kolumny: date, home, away, hg, ag.
    Opcjonalne (włączają kolejne rynki): hg_ht/ag_ht, h_yellow/a_yellow, h_corners/a_corners, referee.
    """

    def __init__(self, df: pd.DataFrame, as_of=None, min_rows: int = 80,
                 xi: float = 0.0019, ridge: float = 10.0, shot_weight: float = 0.0,
                 calib: dict | None = None):
        self.as_of = pd.Timestamp(as_of) if as_of is not None else df["date"].max()
        self.n_matches = len(df)
        self.goals = DixonColes(xi=xi, ridge=ridge).fit(df, self.as_of)
        self.ht = self.h2 = self.yellow = self.corners = self.sot = None
        self.shot_weight = float(shot_weight)
        self.calib = calib or {}          # {'draw_ht': +0.05, ...} - przesunięcia logitów z `tune`
        self.conv = (0.3, 0.3)

        def ok(cols):
            return all(c in df.columns for c in cols) and df[cols].notna().all(axis=1).sum() >= min_rows

        if self.shot_weight > 0 and ok(["h_sot", "a_sot"]):
            # drugi, mniej zaszumiony sygnał siły: celne strzały -> gole przez ligową skuteczność
            self.sot = CountModel(xi=xi, ridge=ridge, kmax=30).fit(to_long(df, "h_sot", "a_sot"), self.as_of)
            d = df.dropna(subset=["h_sot", "a_sot"])
            self.conv = (float(d["hg"].sum() / max(d["h_sot"].sum(), 1)), float(d["ag"].sum() / max(d["a_sot"].sum(), 1)))
        if ok(["hg_ht", "ag_ht"]):
            d = df.copy()
            d["hg_2h"] = d["hg"] - d["hg_ht"]
            d["ag_2h"] = d["ag"] - d["ag_ht"]
            d = d[(d["hg_2h"] >= 0) & (d["ag_2h"] >= 0)]
            self.ht = CountModel(xi=xi, ridge=ridge, kmax=10).fit(to_long(d, "hg_ht", "ag_ht"), self.as_of)
            self.h2 = CountModel(xi=xi, ridge=ridge, kmax=10).fit(to_long(d, "hg_2h", "ag_2h"), self.as_of)
        if ok(["h_yellow", "a_yellow"]):
            self.yellow = CountModel(xi=xi, ridge=ridge, use_ref=True, kmax=15).fit(
                to_long(df, "h_yellow", "a_yellow"), self.as_of)
        if ok(["h_corners", "a_corners"]):
            self.corners = CountModel(xi=xi, ridge=ridge, kmax=30).fit(
                to_long(df, "h_corners", "a_corners"), self.as_of)

    @property
    def teams(self) -> list[str]:
        return self.goals.teams

    # ------------------------------------------------------------ lambdy i macierz wyników
    def lambdas(self, home: str, away: str) -> tuple[float, float]:
        """Oczekiwane gole; z celnymi strzałami: średnia geometryczna (1-w)*gole + w*strzały."""
        lh, la = self.goals.lambdas(home, away)
        if self.sot is not None:
            b = self.shot_weight
            sh = max(self.sot.mean(home, away, 1) * self.conv[0], 0.05)
            sa = max(self.sot.mean(away, home, 0) * self.conv[1], 0.05)
            lh = float(np.exp((1 - b) * np.log(lh) + b * np.log(sh)))
            la = float(np.exp((1 - b) * np.log(la) + b * np.log(sa)))
        return lh, la

    def matrix(self, home: str, away: str) -> np.ndarray:
        lh, la = self.lambdas(home, away)
        return score_matrix(lh, la, self.goals.rho)

    # ------------------------------------------------------------ predict
    def predict(self, home: str, away: str, referee: str | None = None) -> dict:
        g = self.goals
        lh, la = self.lambdas(home, away)
        m = self.matrix(home, away)
        tot = mk.total_pmf(m)
        out: dict = {
            "home": home, "away": away, "referee": referee,
            "unknown_teams": [t for t in (home, away) if not g.knows(t)],
            "xg": {"home": _r(lh, 2), "away": _r(la, 2)},
            "1x2": {k: _r(v) for k, v in mk.outcome_1x2(m).items()},
            "goals": {
                **{f"over_{l}": _r(mk.over(tot, l)) for l in GOAL_LINES},
                **{f"under_{l}": _r(1 - mk.over(tot, l)) for l in GOAL_LINES},
                "btts_yes": _r(mk.btts(m)), "btts_no": _r(1 - mk.btts(m)),
                "top_scores": [(s, _r(p)) for s, p in mk.top_scores(m, 5)],
            },
        }
        out["extra"] = {
            "double_chance": {k: _r(v) for k, v in mk.double_chance(m).items()},
            "dnb": {k: _r(v) for k, v in mk.draw_no_bet(m).items()},
            "asian": {str(l): {k: _r(v) for k, v in mk.asian(m, l).items()}
                      for l in (-1.5, -1.0, -0.5, 0.5, 1.0, 1.5)},
            "team_totals": {t: {l: _r(v) for l, v in d.items()} for t, d in mk.team_totals(m).items()},
            "clean_sheets": {k: _r(v) for k, v in mk.clean_sheets(m).items()},
            "exact_total": {k: _r(v) for k, v in mk.exact_total(tot).items()},
        }
        if self.ht and self.h2:
            out["halves"] = self._halves(home, away, out["1x2"]["X"])
        if self.yellow:
            out["yellow"] = self._count(self.yellow, home, away, referee, YELLOW_LINES, 15)
        if self.corners:
            out["corners"] = self._count(self.corners, home, away, None, CORNER_LINES, 30)
        return out

    def _halves(self, home: str, away: str, ft_draw: float) -> dict:
        def mat(model):
            ph = model.pmf(model.mean(home, away, 1), 10)
            pa = model.pmf(model.mean(away, home, 0), 10)
            return np.outer(ph, pa), model.mean(home, away, 1), model.mean(away, home, 0)

        m1, h1, a1 = mat(self.ht)
        m2, h2, a2 = mat(self.h2)
        d1, d2 = float(np.trace(m1)), float(np.trace(m2))
        t1, t2 = mk.total_pmf(m1), mk.total_pmf(m2)
        htft = mk.htft(m1, m2)
        both = htft["X/X"]                                   # remis do przerwy ORAZ na koniec
        # P(HT lub FT) = P(HT) + P(FT) - P(oba); FT z głównego modelu (z korektą niskich wyników), granice Frécheta
        ht_or_ft = min(1.0, max(d1, ft_draw, d1 + ft_draw - both))
        either = 1 - (1 - d1) * (1 - d2)
        sh = lambda k, v: shift_prob(v, self.calib.get(k, 0.0))  # noqa: E731
        return {
            "xg_ht": {"home": _r(h1, 2), "away": _r(a1, 2)},
            "xg_2h": {"home": _r(h2, 2), "away": _r(a2, 2)},
            "ht_1x2": {k: _r(v) for k, v in mk.outcome_1x2(m1).items()},
            "2h_1x2": {k: _r(v) for k, v in mk.outcome_1x2(m2).items()},
            "draw_ht": _r(sh("draw_ht", d1)),
            "draw_2h": _r(sh("draw_2h", d2)),
            "draw_either_half": _r(sh("draw_either_half", either)),       # remis w 1. LUB 2. połowie
            "draw_ht_or_ft": _r(sh("draw_ht_or_ft", ht_or_ft)),           # remis do przerwy LUB na koniec meczu
            "draw_ft": _r(ft_draw),
            "draw_both_halves": _r(d1 * d2),
            "over_0.5_ht": _r(mk.over(t1, 0.5)),
            "over_1.5_2h": _r(mk.over(t2, 1.5)),
            "htft": {k: _r(v) for k, v in htft.items()},
        }

    def _count(self, model: CountModel, home, away, ref, lines, kmax) -> dict:
        mh = model.mean(home, away, 1, ref)
        ma = model.mean(away, home, 0, ref)
        ph, pa = model.pmf(mh, kmax), model.pmf(ma, kmax)
        tot = mk.convolve(ph, pa)
        return {
            "home_mean": _r(mh, 2), "away_mean": _r(ma, 2), "total_mean": _r(mh + ma, 2),
            "over": {str(l): _r(mk.over(tot, l)) for l in lines},
            "home_over": {str(l): _r(mk.over(ph, l)) for l in (0.5, 1.5, 2.5)},
            "away_over": {str(l): _r(mk.over(pa, l)) for l in (0.5, 1.5, 2.5)},
            "more_than_opponent": {
                "home": _r(sum(ph[i] * pa[:i].sum() for i in range(len(ph)))),
                "away": _r(sum(pa[i] * ph[:i].sum() for i in range(len(pa)))),
            },
        }


def format_prediction(p: dict) -> str:
    """Czytelny wydruk tekstowy prognozy (CLI)."""
    pct = lambda x: f"{100 * x:5.1f}%"  # noqa: E731
    L = [f"\n{p['home']}  vs  {p['away']}" + (f"   (sędzia: {p['referee']})" if p.get("referee") else "")]
    if p["unknown_teams"]:
        L.append(f"! Brak historii dla: {', '.join(p['unknown_teams'])} (użyto średniej ligowej)")
    L.append(f"Oczekiwane gole: {p['xg']['home']} - {p['xg']['away']}")
    x = p["1x2"]
    L.append(f"\n1X2:   1 {pct(x['1'])}   X {pct(x['X'])}   2 {pct(x['2'])}")
    g = p["goals"]
    L.append(f"Gole:  O1.5 {pct(g['over_1.5'])}  O2.5 {pct(g['over_2.5'])}  O3.5 {pct(g['over_3.5'])}  "
             f"BTTS {pct(g['btts_yes'])}")
    L.append("Wyniki: " + ", ".join(f"{s} ({100 * q:.1f}%)" for s, q in g["top_scores"]))
    if "1x2_blend" in p:
        b, q = p["1x2_blend"], p["market_1x2"]
        L.append(f"Rynek: 1 {pct(q['1'])}   X {pct(q['X'])}   2 {pct(q['2'])}   (po usunięciu marży)")
        L.append(f"Mix:   1 {pct(b['1'])}   X {pct(b['X'])}   2 {pct(b['2'])}   (model + rynek)")
    elif "market_1x2" in p:
        q = p["market_1x2"]
        L.append(f"Rynek: 1 {pct(q['1'])}   X {pct(q['X'])}   2 {pct(q['2'])}   (po usunięciu marży)")
    e = p.get("extra")
    if e:
        dc, dnb, cs = e["double_chance"], e["dnb"], e["clean_sheets"]
        L.append(f"Podwójna szansa: 1X {pct(dc['1X'])}  X2 {pct(dc['X2'])}  12 {pct(dc['12'])}")
        L.append(f"DNB: 1 {pct(dnb['home'])}  2 {pct(dnb['away'])}   |   Czyste konto: gosp. {pct(cs['home_cs'])}  goście {pct(cs['away_cs'])}")
        a = e["asian"]
        L.append(f"AH gosp.: -1.5 {pct(a['-1.5']['win'])}  -0.5 {pct(a['-0.5']['win'])}  +0.5 {pct(a['0.5']['win'])}  +1.5 {pct(a['1.5']['win'])}")
    if "halves" in p:
        h = p["halves"]
        L.append(f"\nPołowy: remis do przerwy {pct(h['draw_ht'])} | remis w 2. poł. {pct(h['draw_2h'])} | "
                 f"remis w którejkolwiek {pct(h['draw_either_half'])} | w obu {pct(h['draw_both_halves'])}")
        L.append(f"Do przerwy 1X2: 1 {pct(h['ht_1x2']['1'])}  X {pct(h['ht_1x2']['X'])}  2 {pct(h['ht_1x2']['2'])}")
        best = sorted(h["htft"].items(), key=lambda kv: -kv[1])[:3]
        L.append("Połowa/mecz top3: " + ", ".join(f"{k} {100 * v:.1f}%" for k, v in best))
    for key, name in (("yellow", "Żółte kartki"), ("corners", "Rzuty rożne")):
        if key in p:
            c = p[key]
            ov = "  ".join(f"O{l} {pct(v)}" for l, v in c["over"].items())
            L.append(f"\n{name}: średnio {c['home_mean']} + {c['away_mean']} = {c['total_mean']}")
            L.append(f"   {ov}")
    return "\n".join(L)
