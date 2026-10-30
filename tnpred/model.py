"""TennisModel: Elo (walk-forward) + parametry serwisu + mieszanie z rynkiem -> pełna prognoza meczu."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config
from .elo import Elo, surface_of, walk
from .names import NameIndex
from .odds import blend, market_pair
from .pointmodel import match_dist, serve_probs, summarize
from .tdata import add_derived

S0_DEFAULT = {"ATP|Hard": 0.645, "ATP|Clay": 0.625, "ATP|Grass": 0.670,
              "WTA|Hard": 0.565, "WTA|Clay": 0.555, "WTA|Grass": 0.575}
W_DEFAULT = {"ATP": 0.35, "WTA": 0.35}


def params_path():
    return config.PARAMS_DIR / "model.json"


def load_params() -> dict:
    p = params_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def save_params(d: dict) -> None:
    p = params_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def final_tb(best_of: int, series: str | None = None) -> int:
    """Od 2022 w Wielkim Szlemie decydujący set kończy tie-break do 10. Upraszczamy: Bo5 -> do 10."""
    return 10 if best_of == 5 or (series or "").lower().startswith("grand") else 7


class TennisModel:
    def __init__(self, matches: pd.DataFrame, params: dict | None = None):
        self.params = params if params is not None else load_params()
        df = add_derived(matches) if len(matches) else matches.assign(total_games=[], n_tb=[], completed=[], retired=[])
        self.elo, pre = walk(df, config.ELO_SURFACE_WEIGHT, config.ELO_USE_RETIRED) if len(df) else (Elo(), np.array([]))
        df = df.copy()
        df["p_elo_w"] = pre
        mk = [market_pair(a, b) for a, b in zip(df.get("psw", []), df.get("psl", []))]
        mk2 = [market_pair(a, b) for a, b in zip(df.get("avgw", []), df.get("avgl", []))]
        df["p_mkt_w"] = [m[0] if m else (m2[0] if m2 else np.nan) for m, m2 in zip(mk, mk2)]
        self.df = df
        self.s0 = {**S0_DEFAULT, **self.params.get("s0", {})}
        self.w = {**W_DEFAULT, **self.params.get("blend_w", {})}
        self.names = {t: NameIndex(pd.concat([df[df.tour == t].winner, df[df.tour == t].loser]).astype(str).tolist())
                      for t in (df.tour.unique() if len(df) else [])}
        self.base = self._base_rates()
        self.built_at = datetime.now(timezone.utc)

    # ---------------------------------------------------------------- dane pomocnicze
    def _base_rates(self) -> dict:
        """Średnie „turnieju” (tour + nawierzchnia + do ilu setów) z ostatnich 3 lat - odpowiednik średniej ligi."""
        out = {}
        df = self.df
        if df.empty:
            return out
        cut = df.date.max() - pd.Timedelta(days=3 * 365)
        d = df[(df.date >= cut) & df.completed]
        for (t, s, bo), g in d.groupby(["tour", "surface", "best_of"]):
            if len(g) < 20:
                continue
            lines = [18.5, 19.5, 20.5, 21.5, 22.5, 23.5, 24.5] if bo == 3 else [33.5, 35.5, 36.5, 37.5, 38.5, 39.5, 41.5]
            need = bo // 2 + 1
            fav_w = g.p_mkt_w >= 0.5
            out[f"{t}|{s}|{bo}"] = {
                "n": int(len(g)), "games_mean": float(g.total_games.mean()),
                "over": {f"{x}": float((g.total_games > x).mean()) for x in lines},
                "p_tb": float((g.n_tb > 0).mean()), "straight": float((g.lsets == 0).mean()),
                "set1_tb": float((((g.w1 == 7) & (g.l1 == 6)) | ((g.w1 == 6) & (g.l1 == 7))).mean()),
                "set1_over9.5": float(((g.w1 + g.l1) > 9.5).mean()),
                "fav_win": float(fav_w[g.p_mkt_w.notna()].mean()) if g.p_mkt_w.notna().any() else None,
                "need": need,
            }
        return out

    def base_for(self, tour, surface, bo) -> dict:
        return self.base.get(f"{tour}|{surface}|{bo}") or self.base.get(f"{tour}|Hard|{bo}") or {}

    def resolve(self, tour: str, name: str) -> str | None:
        idx = self.names.get(tour)
        return idx.resolve(name) if idx else None

    def players(self, tour: str) -> list[str]:
        idx = self.names.get(tour)
        return sorted(idx.exact.values()) if idx else []

    def info(self, tour: str, name: str, surface: str) -> dict:
        k = f"{tour}|{name}"
        o, s, b = self.elo.rating(k, surface, self.elo.rank.get(k))
        return {"name": name, "known": k in self.elo.r, "elo": o, "elo_surface": s, "elo_mix": b,
                "n": self.elo.n.get(k, 0), "n_surface": self.elo.ns.get((k, surface), 0),
                "rank": self.elo.rank.get(k), "last": self.elo.last.get(k)}

    # ---------------------------------------------------------------- prognoza
    def predict(self, tour: str, surface: str, best_of: int, p1: str, p2: str, o1=None, o2=None,
                series: str | None = None, w: float | None = None) -> dict:
        tour = (tour or "ATP").upper()
        surface = surface_of(surface)
        best_of = 5 if int(best_of or 3) == 5 else 3
        n1 = self.resolve(tour, p1) or p1
        n2 = self.resolve(tour, p2) or p2
        i1, i2 = self.info(tour, n1, surface), self.info(tour, n2, surface)
        p_elo = 1.0 / (1.0 + 10 ** ((i2["elo_mix"] - i1["elo_mix"]) / 400.0))
        mk = market_pair(o1, o2)
        w_used = self.w.get(tour, 0.35) if w is None else w
        p = blend(p_elo, mk[0], w_used) if mk else p_elo
        s0 = self.s0.get(f"{tour}|{surface}", 0.62)
        pa, pb = serve_probs(p, s0)
        dist = match_dist(pa, pb, best_of, final_tb(best_of, series))
        m = summarize(dist, best_of)
        warn = []
        for i in (i1, i2):
            if not i["known"]:
                warn.append(f"{i['name']}: brak w historii - ocena z rankingu/domyślna, prognoza mało pewna")
            elif i["n"] < 15:
                warn.append(f"{i['name']}: tylko {i['n']} meczów w bazie")
        return {"tour": tour, "surface": surface, "best_of": best_of, "p1": n1, "p2": n2, "info": [i1, i2],
                "p_elo": p_elo, "p_market": mk[0] if mk else None, "p": p, "w": w_used if mk else None,
                "s0": s0, "serve": (pa, pb), "m": m, "base": self.base_for(tour, surface, best_of),
                "o1": o1, "o2": o2, "warn": warn}

    # ---------------------------------------------------------------- strojenie
    def fit_s0(self, years: float = 3, sample: int = 1500, verbose=False) -> dict:
        """Dobiera s0 (tour+nawierzchnia), by częstość tie-breaka w 1. secie zgadzała się z historią (mecze do 2 setów)."""
        out = {}
        df = self.df
        cut = df.date.max() - pd.Timedelta(days=int(365 * years))
        d = df[(df.date >= cut) & df.completed & (df.best_of == 3) & df.p_elo_w.notna()].copy()
        # szansa z kursów (ostrzejsza niż samo Elo) - inaczej spłaszczone Elo zawyża liczbę gemów i zaniża s0
        d["p_fit"] = d.p_mkt_w.fillna(d.p_elo_w)
        for (t, s), g in d.groupby(["tour", "surface"]):
            if len(g) < 60:
                continue
            g = g.tail(sample)
            # cel: częstość tie-breaka w 1. secie (bardzo czuła na s0, niezależna od długości meczu)
            obs = float((((g.w1 == 7) & (g.l1 == 6)) | ((g.w1 == 6) & (g.l1 == 7))).mean())
            ps = np.round(np.abs(g.p_fit.to_numpy() - 0.5) + 0.5, 2)
            vals, cnt = np.unique(ps, return_counts=True)

            def mean_games(s0):
                tot = 0.0
                for v, c in zip(vals, cnt):
                    pa, pb = serve_probs(float(v), s0)
                    tot += c * summarize(match_dist(pa, pb, 3, 7), 3)["set1_tb"]
                return tot / cnt.sum()

            lo, hi = 0.45, 0.78
            for _ in range(9):
                mid = round((lo + hi) / 2, 4)
                if mean_games(mid) < obs:
                    lo = mid
                else:
                    hi = mid
            out[f"{t}|{s}"] = round((lo + hi) / 2, 3)
            if verbose:
                print(f"s0 {t} {s}: {out[f'{t}|{s}']} (tie-break w 1. secie {100 * obs:.1f}%, n={len(g)})")
        return out

    def fit_blend(self, verbose=False) -> dict:
        """Waga modelu w mieszance z rynkiem (min. log-loss na meczach z kursami Pinnacle/średnimi)."""
        out = {}
        d = self.df[self.df.p_elo_w.notna() & self.df.p_mkt_w.notna()]
        for t, g in d.groupby("tour"):
            if len(g) < 200:
                continue
            pe = np.clip(g.p_elo_w.to_numpy(), 0.01, 0.99)
            pm = np.clip(g.p_mkt_w.to_numpy(), 0.01, 0.99)
            le, lm = np.log(pe / (1 - pe)), np.log(pm / (1 - pm))
            best = None
            for w in np.arange(0, 1.0001, 0.05):
                p = 1 / (1 + np.exp(-(w * le + (1 - w) * lm)))
                ll = float(-np.mean(np.log(p)))
                if best is None or ll < best[1]:
                    best = (round(float(w), 2), ll)
            out[t] = best[0]
            if verbose:
                print(f"waga modelu {t}: {best[0]} (log-loss {best[1]:.4f}, n={len(g)})")
        return out


def logloss(p) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(-np.mean(np.log(p)))


def pct(x) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.0f}%"
