"""Dziennik prognoz: zapisuj PRZED meczem, rozliczaj PO meczu - jedyny uczciwy test modelu na żywo."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .backtest import brier_bin, logloss_bin, logloss_multi
from .odds import edge, implied_probs, kelly

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    fixture_id INTEGER PRIMARY KEY,
    league TEXT, date TEXT, home TEXT, away TEXT, logged_at TEXT, model_version TEXT,
    p1 REAL, px REAL, p2 REAL, q1 REAL, qx REAL, q2 REAL,
    p_over25 REAL, p_btts REAL, p_draw_ht REAL, p_draw_2h REAL,
    o_home REAL, o_draw REAL, o_away REAL, o_over25 REAL, o_under25 REAL,
    payload TEXT
);
"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def log_predictions(conn, predictor, upcoming: pd.DataFrame, league: str, version: str = "0.2.0",
                    blend_w: float | None = None) -> int:
    """Zapisuje prognozy nadchodzących meczów (nadpisuje starsze, dopóki mecz się nie odbył)."""
    from .odds import apply_blend
    ensure(conn)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for r in upcoming.to_dict("records"):
        p = apply_blend(predictor.predict(r["home"], r["away"], r.get("referee")), r, blend_w)
        h = p.get("halves", {})
        q = p.get("1x2_blend") or {}
        conn.execute(
            "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (int(r["fixture_id"]), str(league), pd.Timestamp(r["date"]).strftime("%Y-%m-%d"), r["home"], r["away"],
             now, version, p["1x2"]["1"], p["1x2"]["X"], p["1x2"]["2"], q.get("1"), q.get("X"), q.get("2"),
             p["goals"]["over_2.5"], p["goals"]["btts_yes"], h.get("draw_ht"), h.get("draw_2h"),
             _f(r.get("o_home")), _f(r.get("o_draw")), _f(r.get("o_away")),
             _f(r.get("o_over25")), _f(r.get("o_under25")), json.dumps(p)))
        n += 1
    conn.commit()
    return n


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


def settled(conn, league: str | None = None) -> pd.DataFrame:
    """Prognozy, dla których mecz już się odbył (z wynikami)."""
    ensure(conn)
    q = ("SELECT p.*, m.hg, m.ag, m.hg_ht, m.ag_ht FROM predictions p JOIN matches m USING (fixture_id) "
         "WHERE m.hg IS NOT NULL")
    params: list = []
    if league:
        q += " AND p.league = ?"
        params.append(str(league))
    df = pd.read_sql_query(q + " ORDER BY p.date", conn, params=params)
    df["y"] = np.where(df.hg > df.ag, 0, np.where(df.hg == df.ag, 1, 2))
    return df


def pending(conn, league: str | None = None) -> int:
    ensure(conn)
    q = ("SELECT COUNT(*) FROM predictions p JOIN matches m USING (fixture_id) WHERE m.hg IS NULL")
    params: list = []
    if league:
        q += " AND p.league = ?"
        params.append(str(league))
    return conn.execute(q, params).fetchone()[0]


def league_base_rates(hist: pd.DataFrame) -> dict:
    """Częstości ligowe z historii (baseline do raportu na żywo)."""
    h = hist.dropna(subset=["hg", "ag"])
    out = {"x1x2": np.array([(h.hg > h.ag).mean(), (h.hg == h.ag).mean(), (h.hg < h.ag).mean()]),
           "over25": float((h.hg + h.ag > 2.5).mean()), "btts": float(((h.hg > 0) & (h.ag > 0)).mean())}
    t = h.dropna(subset=["hg_ht", "ag_ht"])
    if len(t):
        out["draw_ht"] = float((t.hg_ht == t.ag_ht).mean())
    return out


def track_summary(df: pd.DataFrame, min_edge: float = 0.03, base: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Podsumowanie na żywo: log-loss modelu / miksu / rynku + symulacja płaskiej stawki."""
    if df.empty:
        return pd.DataFrame(), {}
    y = df["y"].to_numpy(int)
    rows = []
    M = df[["p1", "px", "p2"]].to_numpy()
    b3 = base["x1x2"] if base else np.array([np.mean(y == 0), np.mean(y == 1), np.mean(y == 2)])
    r = {"rynek": "1X2", "n": len(df), "model": logloss_multi(M, y),
         "baseline": logloss_multi(np.tile(b3, (len(y), 1)), y)}
    has_o = df[["o_home", "o_draw", "o_away"]].notna().all(axis=1)
    if has_o.any():
        K = np.array([implied_probs(list(v)) for v in df.loc[has_o, ["o_home", "o_draw", "o_away"]].to_numpy()])
        r["rynek_ll"] = logloss_multi(K, y[has_o.to_numpy()])
        r["model_na_tych_samych"] = logloss_multi(M[has_o.to_numpy()], y[has_o.to_numpy()])
    if df["q1"].notna().all():
        r["mix"] = logloss_multi(df[["q1", "qx", "q2"]].to_numpy(), y)
    rows.append(r)
    for name, pc, yy, bk in (("Over 2.5", "p_over25", (df.hg + df.ag > 2.5).astype(float), "over25"),
                             ("BTTS", "p_btts", ((df.hg > 0) & (df.ag > 0)).astype(float), "btts"),
                             ("Remis do przerwy", "p_draw_ht", (df.hg_ht == df.ag_ht).astype(float), "draw_ht")):
        ok = df[pc].notna() & (df["hg_ht"].notna() if "ht" in name.lower() or "przerwy" in name else True)
        if ok.sum() == 0:
            continue
        p, t = df.loc[ok, pc].to_numpy(float), yy[ok].to_numpy(float)
        rows.append({"rynek": name, "n": int(ok.sum()), "model": logloss_bin(p, t),
                     "baseline": logloss_bin(np.full_like(p, (base or {}).get(bk, t.mean())), t),
                     "brier": brier_bin(p, t)})
    out = pd.DataFrame(rows).round(4)

    # symulacja płaskiej stawki 1j na typy z przewagą (kursy z chwili zapisu prognozy)
    bets = 0
    profit = 0.0
    kelly_pnl = 0.0
    for r_ in df.itertuples(index=False):
        use = [(r_.q1 if pd.notna(r_.q1) else r_.p1, r_.o_home, r_.y == 0),
               (r_.qx if pd.notna(r_.qx) else r_.px, r_.o_draw, r_.y == 1),
               (r_.q2 if pd.notna(r_.q2) else r_.p2, r_.o_away, r_.y == 2),
               (r_.p_over25, r_.o_over25, r_.hg + r_.ag > 2.5),
               (1 - r_.p_over25, r_.o_under25, r_.hg + r_.ag <= 2.5)]
        for p, o, won in use:
            if o is None or pd.isna(o) or o <= 1 or edge(p, o) < min_edge:
                continue
            bets += 1
            profit += (o - 1) if won else -1
            kelly_pnl += kelly(p, o) * ((o - 1) if won else -1)
    sim = {"zaklady": bets, "zysk_j": round(profit, 2), "ROI_%": round(100 * profit / bets, 2) if bets else 0.0,
           "zysk_kelly_%_bankrolla": round(100 * kelly_pnl, 2),
           "uwaga": "mała próba = wynik to głównie szum; patrz na log-loss i kalibrację"}
    return out, sim
