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
from .odds import blend, market_pair, market_pair_vec
from .pointmodel import mixture_dist, serve_probs, summarize
from .tdata import add_derived

S0_DEFAULT = {"ATP|Hard": 0.645, "ATP|Clay": 0.625, "ATP|Grass": 0.670,
              "WTA|Hard": 0.565, "WTA|Clay": 0.555, "WTA|Grass": 0.575}
W_DEFAULT = {"ATP": 0.35, "WTA": 0.35}
SIGMA_DEFAULT: dict = {}           # forma dnia (tour|nawierzchnia); brak = 0 do czasu strojenia


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


KEEP = ["date", "tour", "tournament", "series", "surface", "round", "best_of", "winner", "loser", "wrank", "lrank",
        "w1", "l1", "w2", "l2", "w3", "l3", "w4", "l4", "w5", "l5", "lsets", "comment", "psw", "psl",
        "games_w", "games_l", "total_games", "n_tb", "completed", "retired", "p_elo_w", "p_mkt_w"]
CATS = ["tour", "tournament", "series", "surface", "round", "winner", "loser", "comment"]


def slim(df: pd.DataFrame) -> pd.DataFrame:
    """Tylko potrzebne kolumny; teksty jako kategorie, liczby jako float32 - kilka razy mniej pamięci (Render: 512 MB)."""
    df = df[[c for c in KEEP if c in df.columns]].copy()
    for c in CATS:
        if c in df.columns:
            df[c] = df[c].astype(str).astype("category")
    for c in df.columns:
        if c not in CATS and c not in ("date", "completed", "retired", "p_elo_w", "p_mkt_w") and df[c].dtype.kind == "f":
            df[c] = df[c].astype("float32")
    return df.reset_index(drop=True)


class TennisModel:
    def __init__(self, matches: pd.DataFrame, params: dict | None = None):
        self.params = params if params is not None else load_params()
        df = add_derived(matches) if len(matches) else matches.assign(total_games=[], n_tb=[], completed=[], retired=[])
        self.elo, pre = walk(df, config.ELO_SURFACE_WEIGHT, config.ELO_USE_RETIRED) if len(df) else (Elo(), np.array([]))
        df = df.copy()
        df["p_elo_w"] = pre
        if len(df):
            p_ps = market_pair_vec(df["psw"], df["psl"])
            p_avg = market_pair_vec(df["avgw"], df["avgl"])
            df["p_mkt_w"] = np.where(np.isnan(p_ps), p_avg, p_ps)
        else:
            df["p_mkt_w"] = []
        self.df = slim(df)
        self.s0 = {**S0_DEFAULT, **self.params.get("s0", {})}
        self.w = {**W_DEFAULT, **self.params.get("blend_w", {})}
        self.sigma = {**SIGMA_DEFAULT, **self.params.get("sigma", {})}
        from . import style as _style
        self.style = _style.load()            # styl TB zawodników (tennis_params/style.json, liczony na Twoim komputerze)
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
        sg = self.sigma.get(f"{tour}|{surface}", 0.0)
        pa, pb = serve_probs(p, s0, sg)
        dist = mixture_dist(pa, pb, sg, best_of, final_tb(best_of, series))
        m = summarize(dist, best_of)
        from . import style as _style
        p_tb_base = m["p_tb"]
        p_tb_adj, style_info = _style.adjust(self.style, tour, n1, n2, p_tb_base)
        if style_info:
            m = {**m, "p_tb": p_tb_adj}
        warn = []
        for i in (i1, i2):
            if not i["known"]:
                warn.append(f"{i['name']}: brak w historii - ocena z rankingu/domyślna, prognoza mało pewna")
            elif i["n"] < 15:
                warn.append(f"{i['name']}: tylko {i['n']} meczów w bazie")
        return {"tour": tour, "surface": surface, "best_of": best_of, "p1": n1, "p2": n2, "info": [i1, i2],
                "p_elo": p_elo, "p_market": mk[0] if mk else None, "p": p, "w": w_used if mk else None,
                "s0": s0, "sigma": sg, "serve": (pa, pb), "m": m, "base": self.base_for(tour, surface, best_of),
                "o1": o1, "o2": o2, "warn": warn,
                "style": style_info, "p_tb_base": p_tb_base}

    # ---------------------------------------------------------------- strojenie
    def fit_s0(self, years: float = 3, sample: int = 1500, verbose=False, with_sigma: bool = True) -> dict:
        """Dobiera s0 (serwis bazowy) i sigma (forma dnia) dla touru+nawierzchni tak, by na historii meczów do 2 setów zgadzały się:
        tie-break w 1. secie, gemy w 1. secie, odsetek meczów bez straty seta i średnia gemów w meczu.
        Zwraca {"tour|naw": s0}; sigma zapisuje w self.fitted_sigma (fit_all zapisuje oba)."""
        out, self.fitted_sigma = {}, {}
        df = self.df
        cut = df.date.max() - pd.Timedelta(days=int(365 * years))
        d = df[(df.date >= cut) & df.completed & (df.best_of == 3) & df.p_elo_w.notna() & df.w1.notna()].copy()
        d["p_fit"] = d.p_mkt_w.fillna(d.p_elo_w)      # szansa z kursów (ostrzejsza niż samo Elo)
        s0_grid = [round(x, 2) for x in np.arange(0.50, 0.7201, 0.02)]
        sg_grid = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10] if with_sigma else [0.0]
        for (t, s), g in d.groupby(["tour", "surface"], observed=True):
            if len(g) < 60:
                continue
            g = g.tail(sample)
            obs = {"tb1": float((((g.w1 == 7) & (g.l1 == 6)) | ((g.w1 == 6) & (g.l1 == 7))).mean()),
                   "g1": float((g.w1 + g.l1).mean()), "st": float((g.lsets == 0).mean()), "gm": float(g.total_games.mean())}
            ps = np.round((np.abs(g.p_fit.to_numpy() - 0.5) + 0.5) / 0.05) * 0.05
            vals, cnt = np.unique(np.clip(ps, 0.5, 0.95), return_counts=True)
            best = None
            for s0 in s0_grid:
                for sg in sg_grid:
                    acc = {"tb1": 0.0, "g1": 0.0, "st": 0.0, "gm": 0.0}
                    for v, c in zip(vals, cnt):
                        pa, pb = serve_probs(float(v), s0, sg)
                        sm = summarize(mixture_dist(pa, pb, sg, 3, 7), 3)
                        g1 = 0.0
                        dist1 = mixture_dist(pa, pb, sg, 3, 7)["set1"]
                        g1 = sum((a_ + b_) * pr for (a_, b_), pr in dist1.items())
                        acc["tb1"] += c * sm["set1_tb"]
                        acc["g1"] += c * g1
                        acc["st"] += c * sm["straight"]
                        acc["gm"] += c * sm["games_mean"]
                    n = cnt.sum()
                    pred = {k: v / n for k, v in acc.items()}
                    loss = (((pred["tb1"] - obs["tb1"]) / 0.02) ** 2 + ((pred["g1"] - obs["g1"]) / 0.25) ** 2
                            + ((pred["st"] - obs["st"]) / 0.03) ** 2 + ((pred["gm"] - obs["gm"]) / 0.4) ** 2)
                    if best is None or loss < best[0]:
                        best = (loss, s0, sg, pred)
            key = f"{t}|{s}"
            ok = best[1] < s0_grid[-1]
            out[key] = best[1] if ok else S0_DEFAULT.get(key, 0.62)
            self.fitted_sigma[key] = best[2] if ok else 0.0
            if verbose:
                pr = best[3]
                print(f"{t} {s}: s0={out[key]} forma dnia={self.fitted_sigma[key]}{'' if ok else ' (górny brzeg - domyślne)'} | "
                      f"TB 1. set {100 * obs['tb1']:.1f}% (model {100 * pr['tb1']:.1f}%), gemy 1. set {obs['g1']:.2f} ({pr['g1']:.2f}), "
                      f"bez straty seta {100 * obs['st']:.0f}% ({100 * pr['st']:.0f}%), gemy w meczu {obs['gm']:.1f} ({pr['gm']:.1f}), n={len(g)}")
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
