"""Retrospektywa ostatnich meczów: co model przewidziałby PRZED każdym z nich (trening tylko na meczach sprzed kolejki).

To NIE jest dziennik na żywo (ten zapisuje prognozy w chwili ich wydania), ale uczciwy podgląd bez zaglądania w przyszłość,
dostępny od ręki. Parametry modelu (ridge, xi) są jednak dobrane na całej historii, więc to nieco optymistyczne oszacowanie.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import _baselines, _record, brier_multi, logloss_multi
from .predictor import MatchPredictor


def recent_predictions(df: pd.DataFrame, days: int = 10, gap_days: int = 3, min_train: int = 100, **model_kw) -> pd.DataFrame:
    """Prognozy walk-forward dla meczów z ostatnich `days` dni danych (jeden model na kolejkę)."""
    fin = df.dropna(subset=["hg", "ag"]).sort_values("date").reset_index(drop=True)
    for c in ("referee", "hg_ht", "ag_ht", "h_yellow", "a_yellow", "h_corners", "a_corners",
              "o_home", "o_draw", "o_away", "o_over25", "o_under25"):
        if c not in fin.columns:
            fin[c] = np.nan
    if fin.empty:
        return pd.DataFrame()
    window = fin[fin["date"] > fin["date"].max() - pd.Timedelta(days=days)]
    dates = sorted(window["date"].unique())
    clusters, cur = [], [dates[0]] if dates else []
    for d in dates[1:]:
        if (d - cur[-1]) / np.timedelta64(1, "D") > gap_days:
            clusters.append(cur)
            cur = []
        cur.append(d)
    if cur:
        clusters.append(cur)
    rows = []
    for cl in clusters:
        start = cl[0]
        train = fin[fin["date"] < start]            # tylko mecze sprzed kolejki - żadnego zaglądania w przyszłość
        if len(train) < min_train:
            continue
        P = MatchPredictor(train, as_of=start, **model_kw)
        base = _baselines(train)
        for r in window[window["date"].isin(cl)].itertuples(index=False):
            rows.append(_record(P, r, base))
    return pd.DataFrame(rows)


def show_table(res: pd.DataFrame) -> pd.DataFrame:
    """Czytelna tabela: prognoza vs wynik."""
    if res.empty:
        return pd.DataFrame()
    pct = lambda x: f"{100 * x:.0f}"  # noqa: E731
    out = pd.DataFrame({
        "data": pd.to_datetime(res["date"]).dt.strftime("%Y-%m-%d"),
        "mecz": res["home"] + " – " + res["away"],
        "wynik": res["hg"].astype(int).astype(str) + "–" + res["ag"].astype(int).astype(str),
        "xG": res["xg_h"].round(2).astype(str) + "–" + res["xg_a"].round(2).astype(str),
        "model_1/X/2_%": [f"{pct(a)}/{pct(b)}/{pct(c)}" for a, b, c in zip(res.p1, res.px, res.p2)],
    })
    if "k1" in res and res["k1"].notna().any():
        out["rynek_1/X/2_%"] = [f"{pct(a)}/{pct(b)}/{pct(c)}" if pd.notna(a) else "–" for a, b, c in zip(res.k1, res.kx, res.k2)]
    pick = res[["p1", "px", "p2"]].to_numpy().argmax(axis=1)
    out["typ_modelu"] = [("1", "X", "2")[i] for i in pick]
    out["trafiony"] = np.where(pick == res["y"].to_numpy(), "TAK", "nie")
    if "p_draw_ht" in res:
        yn = {1: "TAK", 0: "nie"}
        out["remis_HT_%"] = (100 * res["p_draw_ht"]).round(0).astype("Int64")
        out["był_remis_HT"] = res["y_draw_ht"].map(yn)
        out["remis_2H_%"] = (100 * res["p_draw_2h"]).round(0).astype("Int64")
        out["był_remis_2H"] = res["y_draw_2h"].map(yn)
        out["HT_lub_2H_%"] = (100 * res["p_draw_either"]).round(0).astype("Int64")      # rynek „remis w dowolnej połowie”
        out["był_HT_lub_2H"] = res["y_draw_either"].map(yn)
        out["HT_lub_FT_%"] = (100 * res["p_draw_htft"]).round(0).astype("Int64")
        out["był_HT_lub_FT"] = res["y_draw_htft"].map(yn)
    return out


def summary(res: pd.DataFrame) -> str:
    """Jedno zdanie: log-loss modelu vs średnia ligi (i rynek) na tych meczach - z ostrzeżeniem o małej próbie."""
    if res.empty:
        return "Brak meczów w wybranym oknie."
    y = res["y"].to_numpy(int)
    m = logloss_multi(res[["p1", "px", "p2"]].to_numpy(), y)
    b = logloss_multi(res[["b1", "bx", "b2"]].to_numpy(), y)
    txt = f"{len(res)} meczów | log-loss modelu {m:.3f} vs średnia ligi {b:.3f}"
    if "k1" in res and res["k1"].notna().all():
        txt += f" vs rynek {logloss_multi(res[['k1', 'kx', 'k2']].to_numpy(), y):.3f}"
    hit = float((res[["p1", "px", "p2"]].to_numpy().argmax(axis=1) == y).mean())
    txt += f" | trafione typy 1X2: {100 * hit:.0f}% | Brier {brier_multi(res[['p1', 'px', 'p2']].to_numpy(), y):.3f}. "
    parts = []
    for label, pc, yc in (("remis HT", "p_draw_ht", "y_draw_ht"), ("remis 2H", "p_draw_2h", "y_draw_2h"),
                          ("HT lub 2H", "p_draw_either", "y_draw_either"), ("HT lub FT", "p_draw_htft", "y_draw_htft")):
        if pc in res and yc in res and res[yc].notna().any():
            ok = res[res[yc].notna()]
            parts.append(f"{label}: zaszło {int(ok[yc].sum())}/{len(ok)} (średnio wg modelu {100 * ok[pc].mean():.0f}%)")
    if parts:
        txt += "Remisy w połowach - " + "; ".join(parts) + ". "
    return txt + "To mała próba - o jakości modelu mówi dopiero backtest na tysiącach meczów."
