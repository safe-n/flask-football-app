"""Backtest walk-forward: model trenowany wyłącznie na przeszłości, ocena na kolejnych blokach."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .odds import implied_probs
from .predictor import MatchPredictor

EPS = 1e-12
YELLOW_LINE = 3.5
CORNER_LINE = 9.5
OPTIONAL = ["referee", "hg_ht", "ag_ht", "h_yellow", "a_yellow", "h_corners", "a_corners",
            "o_home", "o_draw", "o_away", "o_over25", "o_under25"]


# ---------------------------------------------------------------- metryki
def logloss_multi(P: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], EPS, 1))))


def brier_multi(P: np.ndarray, y: np.ndarray) -> float:
    onehot = np.eye(P.shape[1])[y]
    return float(np.mean(np.sum((P - onehot) ** 2, axis=1)))


def rps(P: np.ndarray, y: np.ndarray) -> float:
    """Ranked Probability Score dla uporządkowanych wyników 1 < X < 2."""
    onehot = np.eye(P.shape[1])[y]
    cp, co = np.cumsum(P, axis=1)[:, :-1], np.cumsum(onehot, axis=1)[:, :-1]
    return float(np.mean(np.sum((cp - co) ** 2, axis=1) / (P.shape[1] - 1)))


def logloss_bin(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier_bin(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


# ---------------------------------------------------------------- pętla
def walk_forward(df: pd.DataFrame, min_train: int = 300, step_days: int = 14,
                 progress: bool = True, **model_kw) -> pd.DataFrame:
    fin = df.dropna(subset=["hg", "ag"]).sort_values("date").reset_index(drop=True)
    for c in OPTIONAL:  # brakujące kolumny opcjonalne -> NaN (rynki zostaną pominięte)
        if c not in fin.columns:
            fin[c] = np.nan
    if len(fin) <= min_train + 20:
        raise ValueError(f"Za mało meczów ({len(fin)}) na backtest przy min_train={min_train}.")
    block = fin["date"].iloc[min_train]
    end = fin["date"].max()
    rows = []
    while block <= end:
        nxt = block + pd.Timedelta(days=step_days)
        train = fin[fin["date"] < block]
        test = fin[(fin["date"] >= block) & (fin["date"] < nxt)]
        if len(test):
            P = MatchPredictor(train, as_of=block, **model_kw)
            base = _baselines(train)
            for r in test.itertuples(index=False):
                rows.append(_record(P, r, base))
            if progress:
                print(f"\r  backtest: {len(rows)}/{len(fin) - min_train}", end="", flush=True)
        block = nxt
    if progress:
        print()
    return pd.DataFrame(rows)


def _baselines(train: pd.DataFrame) -> dict:
    tg = train["hg"] + train["ag"]
    b = {
        "b1": (train.hg > train.ag).mean(), "bx": (train.hg == train.ag).mean(),
        "b2": (train.hg < train.ag).mean(),
        "b_over25": (tg > 2.5).mean(), "b_btts": ((train.hg > 0) & (train.ag > 0)).mean(),
    }
    if train["hg_ht"].notna().any():
        t = train.dropna(subset=["hg_ht", "ag_ht"])
        b["b_draw_ht"] = (t.hg_ht == t.ag_ht).mean()
        b["b_draw_2h"] = ((t.hg - t.hg_ht) == (t.ag - t.ag_ht)).mean()
        b["b_draw_either"] = ((t.hg_ht == t.ag_ht) | ((t.hg - t.hg_ht) == (t.ag - t.ag_ht))).mean()
        b["b_draw_htft"] = ((t.hg_ht == t.ag_ht) | (t.hg == t.ag)).mean()
    if train["h_yellow"].notna().any():
        t = train.dropna(subset=["h_yellow", "a_yellow"])
        b["b_yel"] = ((t.h_yellow + t.a_yellow) > YELLOW_LINE).mean()
    if train["h_corners"].notna().any():
        t = train.dropna(subset=["h_corners", "a_corners"])
        b["b_cor"] = ((t.h_corners + t.a_corners) > CORNER_LINE).mean()
    return b


def _record(P: MatchPredictor, r, base: dict) -> dict:
    p = P.predict(r.home, r.away, r.referee)
    y = 0 if r.hg > r.ag else (1 if r.hg == r.ag else 2)
    rec = {
        "date": r.date, "home": r.home, "away": r.away, "y": y,
        "p1": p["1x2"]["1"], "px": p["1x2"]["X"], "p2": p["1x2"]["2"],
        "b1": base["b1"], "bx": base["bx"], "b2": base["b2"],
        "y_over25": int(r.hg + r.ag > 2.5), "p_over25": p["goals"]["over_2.5"], "b_over25": base["b_over25"],
        "y_btts": int(r.hg > 0 and r.ag > 0), "p_btts": p["goals"]["btts_yes"], "b_btts": base["b_btts"],
    }
    odds = [r.o_home, r.o_draw, r.o_away]
    if all(pd.notna(o) and o > 1 for o in odds):
        q = implied_probs(odds)
        rec.update(k1=q[0], kx=q[1], k2=q[2], o_home=r.o_home, o_draw=r.o_draw, o_away=r.o_away)
    if pd.notna(r.o_over25) and pd.notna(r.o_under25):
        rec["k_over25"] = implied_probs([r.o_over25, r.o_under25])[0]
    if "halves" in p and pd.notna(r.hg_ht):
        rec.update(y_draw_ht=int(r.hg_ht == r.ag_ht), p_draw_ht=p["halves"]["draw_ht"],
                   b_draw_ht=base.get("b_draw_ht"),
                   y_draw_2h=int((r.hg - r.hg_ht) == (r.ag - r.ag_ht)),
                   p_draw_2h=p["halves"]["draw_2h"], b_draw_2h=base.get("b_draw_2h"),
                   y_draw_either=int(r.hg_ht == r.ag_ht or (r.hg - r.hg_ht) == (r.ag - r.ag_ht)),
                   p_draw_either=p["halves"]["draw_either_half"], b_draw_either=base.get("b_draw_either"),
                   y_draw_htft=int(r.hg_ht == r.ag_ht or r.hg == r.ag),
                   p_draw_htft=p["halves"]["draw_ht_or_ft"], b_draw_htft=base.get("b_draw_htft"))
    if "yellow" in p and pd.notna(r.h_yellow):
        rec.update(y_yel=int(r.h_yellow + r.a_yellow > YELLOW_LINE),
                   p_yel=p["yellow"]["over"][str(YELLOW_LINE)], b_yel=base.get("b_yel"))
    if "corners" in p and pd.notna(r.h_corners):
        rec.update(y_cor=int(r.h_corners + r.a_corners > CORNER_LINE),
                   p_cor=p["corners"]["over"][str(CORNER_LINE)], b_cor=base.get("b_cor"))
    return rec


# ---------------------------------------------------------------- podsumowanie
def summarize(res: pd.DataFrame) -> pd.DataFrame:
    """Tabela: log-loss (mniej = lepiej) dla modelu, baseline'u (średnia ligowa) i bukmachera."""
    out = []
    y = res["y"].to_numpy(int)
    M = res[["p1", "px", "p2"]].to_numpy()
    B = res[["b1", "bx", "b2"]].to_numpy()
    row = {"rynek": "1X2", "n": len(res), "model": logloss_multi(M, y), "baseline": logloss_multi(B, y),
           "bukmacher": np.nan, "brier_model": brier_multi(M, y), "rps_model": rps(M, y)}
    if "k1" in res and res["k1"].notna().all():
        row["bukmacher"] = logloss_multi(res[["k1", "kx", "k2"]].to_numpy(), y)
    out.append(row)

    def binrow(name, yc, pc, bc, kc=None):
        if yc not in res:
            return
        s = res.dropna(subset=[yc, pc, bc])
        if s.empty:
            return
        yy = s[yc].to_numpy(float)
        r = {"rynek": name, "n": len(s), "model": logloss_bin(s[pc].to_numpy(float), yy),
             "baseline": logloss_bin(s[bc].to_numpy(float), yy), "bukmacher": np.nan,
             "brier_model": brier_bin(s[pc].to_numpy(float), yy), "rps_model": np.nan}
        if kc and kc in s and s[kc].notna().all():
            r["bukmacher"] = logloss_bin(s[kc].to_numpy(float), yy)
        out.append(r)

    binrow("Over 2.5", "y_over25", "p_over25", "b_over25", "k_over25")
    binrow("BTTS", "y_btts", "p_btts", "b_btts")
    binrow("Remis do przerwy", "y_draw_ht", "p_draw_ht", "b_draw_ht")
    binrow("Remis 2. połowa", "y_draw_2h", "p_draw_2h", "b_draw_2h")
    binrow("Remis HT lub 2H", "y_draw_either", "p_draw_either", "b_draw_either")
    binrow("Remis HT lub FT", "y_draw_htft", "p_draw_htft", "b_draw_htft")
    binrow(f"Żółte >{YELLOW_LINE}", "y_yel", "p_yel", "b_yel")
    binrow(f"Rożne >{CORNER_LINE}", "y_cor", "p_cor", "b_cor")
    t = pd.DataFrame(out)
    t["vs_baseline_%"] = (1 - t["model"] / t["baseline"]) * 100
    return t.round(4)


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Tabela kalibracji: przewidziane vs faktyczne częstości w przedziałach."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum():
            rows.append({"przedzial": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(m.sum()),
                         "przewidziane": round(float(p[m].mean()), 3), "faktyczne": round(float(y[m].mean()), 3)})
    return pd.DataFrame(rows)


def betting_sim(res: pd.DataFrame, min_edge: float = 0.05) -> dict:
    """Płaska stawka 1j na typy 1X2 z przewagą >= min_edge względem PRAWDZIWYCH kursów (z marżą bukmachera)."""
    if "o_home" not in res:
        return {}
    bets, profit, n = 0, 0.0, 0
    for r in res.itertuples(index=False):
        if pd.isna(getattr(r, "o_home", np.nan)):
            continue
        n += 1
        for j, (p, o) in enumerate(((r.p1, r.o_home), (r.px, r.o_draw), (r.p2, r.o_away))):
            if p * o - 1 >= min_edge:
                bets += 1
                profit += (o - 1) if r.y == j else -1
    return {"mecze": n, "zaklady": bets, "zysk_j": round(profit, 2),
            "ROI_%": round(100 * profit / bets, 2) if bets else 0.0,
            "uwaga": "kursy z marżą; mała próba = głównie szum"}


# ---------------------------------------------------------------- istotność i miks z rynkiem
def _loss_multi(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(P[np.arange(len(y)), y], EPS, 1))


def paired_ci(loss_a: np.ndarray, loss_b: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Średnia różnica strat (a - b) z 95% przedziałem bootstrap. Ujemna = a lepsze od b."""
    d = np.asarray(loss_a) - np.asarray(loss_b)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def best_blend(res: pd.DataFrame, step: float = 0.05) -> dict | None:
    """Waga modelu w miksie model+rynek minimalizująca log-loss 1X2 (tylko mecze z kursami)."""
    if "k1" not in res:
        return None
    s = res.dropna(subset=["k1", "kx", "k2"])
    if len(s) < 50:
        return None
    y = s["y"].to_numpy(int)
    M = s[["p1", "px", "p2"]].to_numpy()
    K = s[["k1", "kx", "k2"]].to_numpy()
    best = None
    for w in np.arange(0, 1 + 1e-9, step):
        ll = logloss_multi(w * M + (1 - w) * K, y)
        if best is None or ll < best["logloss"]:
            best = {"w": round(float(w), 2), "logloss": ll}
    best.update(n=len(s), model=logloss_multi(M, y), rynek=logloss_multi(K, y))
    return best


def compare_report(res: pd.DataFrame) -> list[str]:
    """Czytelne wnioski: czy różnice 1X2 są istotne, czy to szum (bootstrap 95%)."""
    y = res["y"].to_numpy(int)
    lm = _loss_multi(res[["p1", "px", "p2"]].to_numpy(), y)
    lb = _loss_multi(res[["b1", "bx", "b2"]].to_numpy(), y)
    lines = []

    def verdict(lo, hi, a, b):
        if hi < 0:
            return f"{a} istotnie LEPSZY od {b}"
        if lo > 0:
            return f"{a} istotnie GORSZY od {b}"
        return "różnica nieistotna (w granicach szumu)"

    d, lo, hi = paired_ci(lm, lb)
    lines.append(f"Model vs średnia ligowa: Δ log-loss {d:+.4f}  [95%: {lo:+.4f}, {hi:+.4f}] → {verdict(lo, hi, 'model', 'baseline')}")
    if "k1" in res and res["k1"].notna().all():
        lk = _loss_multi(res[["k1", "kx", "k2"]].to_numpy(), y)
        d, lo, hi = paired_ci(lm, lk)
        lines.append(f"Model vs rynek:          Δ log-loss {d:+.4f}  [95%: {lo:+.4f}, {hi:+.4f}] → {verdict(lo, hi, 'model', 'rynek')}")
    bl = best_blend(res)
    if bl:
        gain = 100 * (1 - bl["logloss"] / bl["rynek"])
        lines.append(f"Optymalny miks: {int(bl['w'] * 100)}% model + {int(100 - bl['w'] * 100)}% rynek → log-loss "
                     f"{bl['logloss']:.4f} (sam rynek {bl['rynek']:.4f}, zysk {gain:+.2f}%)")
    return lines


# ---------------------------------------------------------------- obciążenie (czy model zawyża/zaniża?)
BIAS_MARKETS = [("Over 2.5", "y_over25", "p_over25"), ("BTTS", "y_btts", "p_btts"),
                ("Remis do przerwy", "y_draw_ht", "p_draw_ht"), ("Remis 2. połowa", "y_draw_2h", "p_draw_2h"),
                ("Remis HT lub 2H", "y_draw_either", "p_draw_either"), ("Remis HT lub FT", "y_draw_htft", "p_draw_htft"),
                (f"Żółte >{YELLOW_LINE}", "y_yel", "p_yel"), (f"Rożne >{CORNER_LINE}", "y_cor", "p_cor")]


def bias_table(res: pd.DataFrame) -> pd.DataFrame:
    """Średnia prognoza vs faktyczna częstość. 'wniosek' ostrzega, gdy różnica wykracza poza ~2 błędy standardowe."""
    rows = []
    for name, yc, pc in BIAS_MARKETS:
        if yc not in res or pc not in res:
            continue
        s = res.dropna(subset=[yc, pc])
        if len(s) < 50:
            continue
        avg_p, freq = float(s[pc].mean()), float(s[yc].mean())
        se = float(np.sqrt(max(freq * (1 - freq), 1e-9) / len(s)))
        diff = avg_p - freq
        rows.append({"rynek": name, "n": len(s), "srednia_prognoza_%": 100 * avg_p, "faktycznie_%": 100 * freq,
                     "roznica_pp": 100 * diff,
                     "wniosek": "ok" if abs(diff) <= 2 * se else ("model ZAWYŻA" if diff > 0 else "model ZANIŻA")})
    return pd.DataFrame(rows).round(2)


def bias_shift(res: pd.DataFrame, ycol: str, pcol: str, min_n: int = 200) -> float:
    """Przesunięcie logitów s tak, by średnia skorygowana prognoza = faktycznej częstości (0 przy małej próbie)."""
    from scipy.optimize import brentq
    if ycol not in res or pcol not in res:
        return 0.0
    s = res.dropna(subset=[ycol, pcol])
    if len(s) < min_n:
        return 0.0
    p = np.clip(s[pcol].to_numpy(float), 1e-6, 1 - 1e-6)
    target = float(s[ycol].mean())
    se = float(np.sqrt(max(target * (1 - target), 1e-9) / len(s)))
    if abs(float(p.mean()) - target) <= 3 * se:   # różnica nieodróżnialna od szumu (3 SE) -> nie korygujemy
        return 0.0
    z = np.log(p / (1 - p))
    f = lambda sh: float(np.mean(1 / (1 + np.exp(-(z + sh)))) - target)  # noqa: E731
    if f(-3) * f(3) > 0:
        return 0.0
    return round(float(brentq(f, -3, 3)), 3)


# klucz w prognozie -> (kolumna faktów, kolumna prognoz) w wynikach backtestu
DRAW_CALIB = {"draw_ht": ("y_draw_ht", "p_draw_ht"), "draw_2h": ("y_draw_2h", "p_draw_2h"),
              "draw_either_half": ("y_draw_either", "p_draw_either"), "draw_ht_or_ft": ("y_draw_htft", "p_draw_htft")}
