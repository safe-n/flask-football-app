"""Backtest walk-forward: Elo zna tylko mecze SPRZED danego meczu. Parametry s0 i waga rynku są strojone na całej historii,
więc wynik jest lekko optymistyczny (jak w fbpred). Porównanie: model (Elo) vs rynek (Pinnacle bez marży) vs mieszanka.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .model import TennisModel, final_tb
from .odds import blend
from .pointmodel import match_dist, serve_probs, summarize


def _ll(p, y):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(p, y):
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def rows(m: TennisModel, days: int | None = None, tour: str | None = None, limit: int | None = None,
         since=None, with_markets: bool = True) -> pd.DataFrame:
    """Mecze z prognozą sprzed meczu, zorientowane losowo-stabilnie (zawodnik 1 = alfabetycznie pierwszy)."""
    df = m.df[m.df.p_elo_w.notna()]
    if tour:
        df = df[df.tour == tour]
    if since is not None:
        df = df[df.date >= pd.Timestamp(since)]
    elif days:
        df = df[df.date >= df.date.max() - pd.Timedelta(days=days)]
    if limit:
        df = df.tail(limit)
    out = []
    for r in df.to_dict("records"):
        w_first = str(r["winner"]) <= str(r["loser"])
        p1, p2 = (r["winner"], r["loser"]) if w_first else (r["loser"], r["winner"])
        pe = r["p_elo_w"] if w_first else 1 - r["p_elo_w"]
        pm = r["p_mkt_w"] if w_first else (1 - r["p_mkt_w"] if r["p_mkt_w"] == r["p_mkt_w"] else np.nan)
        w = m.w.get(r["tour"], 0.35)
        p = blend(min(max(pe, 0.01), 0.99), min(max(pm, 0.01), 0.99), w) if pm == pm else pe
        rec = {"date": r["date"], "tour": r["tour"], "tournament": r["tournament"], "surface": r["surface"],
               "round": r["round"], "best_of": int(r["best_of"]), "p1": p1, "p2": p2, "y": 1.0 if w_first else 0.0,
               "p_elo": pe, "p_market": pm, "p": p, "completed": bool(r["completed"]),
               "total_games": r["total_games"], "tb": float(r["n_tb"] > 0), "straight": float(r["lsets"] == 0) if r["lsets"] == r["lsets"] else np.nan,
               "set1_tb": float(r["w1"] + r["l1"] == 13) if r["w1"] == r["w1"] else np.nan,
               "score": " ".join(f"{int(a)}-{int(b)}" if w_first else f"{int(b)}-{int(a)}"
                                 for a, b in ((r.get(f"w{i}"), r.get(f"l{i}")) for i in range(1, 6)) if a == a and b == b and a is not None),
               "comment": r["comment"],
               "o1": r["psw"] if w_first else r["psl"], "o2": r["psl"] if w_first else r["psw"]}
        if with_markets and rec["completed"]:
            s0 = m.s0.get(f"{r['tour']}|{r['surface']}", 0.62)
            pa, pb = serve_probs(round(p, 3), s0)
            sm = summarize(match_dist(pa, pb, rec["best_of"], final_tb(rec["best_of"], r.get("series"))), rec["best_of"])
            line = 22.5 if rec["best_of"] == 3 else 38.5
            rec.update(games_mean=sm["games_mean"], line=line, p_over=sum(v for k, v in sm["games_pmf"].items() if k > line),
                       p_tb=sm["p_tb"], p_straight=sm["straight"], p_set1_tb=sm["set1_tb"])
        out.append(rec)
    return pd.DataFrame(out)


def calibration(p, y, bins=(0, .2, .35, .5, .65, .8, 1.0001)) -> list[dict]:
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        k = (p >= lo) & (p < hi)
        if k.sum() >= 10:
            out.append({"przedzial": f"{100 * lo:.0f}–{min(100 * hi, 100):.0f}%", "n": int(k.sum()),
                        "model": float(p[k].mean()), "faktycznie": float(y[k].mean())})
    return out


def summary(bt: pd.DataFrame) -> dict:
    if bt.empty:
        return {}
    out = {"n": len(bt)}
    # zwycięzca: symetryzacja - trafność faworyta modelu
    out["acc_elo"] = float(((bt.p_elo >= 0.5) == (bt.y == 1)).mean())
    out["ll_elo"] = _ll(bt.p_elo, bt.y)
    mk = bt[bt.p_market.notna()]
    if len(mk):
        out.update(n_mkt=len(mk), ll_elo_mkt=_ll(mk.p_elo, mk.y), ll_market=_ll(mk.p_market, mk.y), ll_blend=_ll(mk.p, mk.y),
                   acc_market=float(((mk.p_market >= 0.5) == (mk.y == 1)).mean()),
                   acc_blend=float(((mk.p >= 0.5) == (mk.y == 1)).mean()),
                   brier_elo=_brier(mk.p_elo, mk.y), brier_market=_brier(mk.p_market, mk.y), brier_blend=_brier(mk.p, mk.y))
    c = bt[bt.completed & bt.get("games_mean", pd.Series(dtype=float)).notna()] if "games_mean" in bt else bt.iloc[0:0]
    if len(c):
        over_y = (c.total_games > c.line).astype(float)
        out.update(n_games=len(c), games_mean_pred=float(c.games_mean.mean()), games_mean_real=float(c.total_games.mean()),
                   games_mae=float((c.games_mean - c.total_games).abs().mean()),
                   over_pred=float(c.p_over.mean()), over_real=float(over_y.mean()), over_brier=_brier(c.p_over, over_y),
                   over_brier_base=_brier(np.full(len(c), over_y.mean()), over_y),
                   tb_pred=float(c.p_tb.mean()), tb_real=float(c.tb.mean()), tb_brier=_brier(c.p_tb, c.tb),
                   tb_brier_base=_brier(np.full(len(c), c.tb.mean()), c.tb),
                   straight_pred=float(c.p_straight.mean()), straight_real=float(c.straight.mean()))
    return out


def roi_value(bt: pd.DataFrame, min_edge: float = 0.03, use: str = "p") -> dict:
    """Symulacja „1 zł na zwycięzcę, gdy przewaga ≥ min_edge” po kursach Pinnacle (zamknięcia - najtrudniejszy rynek).

    Krecze: zakład liczony wg zwycięzcy w danych (u bukmacherów zasady się różnią). To NIE jest obietnica zysku.
    """
    d = bt[bt.o1.notna() & bt.o2.notna() & (bt.o1 > 1) & (bt.o2 > 1)]
    if d.empty:
        return {}
    p = d[use].to_numpy(dtype=float)
    e1, e2 = p * d.o1.to_numpy() - 1, (1 - p) * d.o2.to_numpy() - 1
    y = d.y.to_numpy()
    prof = []
    for a, b, o1, o2, yy in zip(e1, e2, d.o1.to_numpy(), d.o2.to_numpy(), y):
        if a >= min_edge and a >= b:
            prof.append(o1 - 1 if yy == 1 else -1.0)
        elif b >= min_edge:
            prof.append(o2 - 1 if yy == 0 else -1.0)
    if not prof:
        return {"n": 0}
    prof = np.array(prof)
    return {"n": int(len(prof)), "zysk": float(prof.sum()), "roi": float(prof.mean()),
            "se": float(prof.std(ddof=1) / np.sqrt(len(prof))) if len(prof) > 1 else None,
            "trafnosc": float((prof > 0).mean())}
