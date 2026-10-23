"""Dziennik prognoz: zapisuj PRZED meczem, rozliczaj PO meczu - jedyny uczciwy test modelu na żywo."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from .backtest import brier_bin, logloss_bin, logloss_multi
from .odds import edge, implied_probs, kelly

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    fixture_id INTEGER PRIMARY KEY,
    league TEXT, date TEXT, home TEXT, away TEXT, logged_at TEXT, model_version TEXT,
    p1 REAL, px REAL, p2 REAL, q1 REAL, qx REAL, q2 REAL,
    p_over25 REAL, p_btts REAL, p_draw_ht REAL, p_draw_2h REAL, p_draw_either REAL, p_draw_htft REAL,
    o_home REAL, o_draw REAL, o_away REAL, o_over25 REAL, o_under25 REAL,
    payload TEXT
);
"""


NEW_COLS = ("p_draw_either", "p_draw_htft")  # dodane w 0.4.1 - migracja starych baz/dzienników


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
    for c in NEW_COLS:
        if c not in have:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {c} REAL")
    conn.commit()


def log_predictions(conn, predictor, upcoming: pd.DataFrame, league: str, version: str = "0.2.0",
                    blend_w: float | None = None) -> int:
    """Zapisuje prognozy nadchodzących meczów (nadpisuje starsze, dopóki mecz się nie odbył)."""
    from .odds import apply_blend
    ensure(conn)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.today().isoformat()
    n = 0
    for r in upcoming.to_dict("records"):
        mdate = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
        # zamrożenie: w dniu meczu (i później) nie nadpisujemy istniejącej prognozy - zero podglądania
        if mdate <= today and conn.execute("SELECT 1 FROM predictions WHERE fixture_id=?",
                                           (int(r["fixture_id"]),)).fetchone():
            continue
        p = apply_blend(predictor.predict(r["home"], r["away"], r.get("referee"), date=r["date"]), r, blend_w)
        h = p.get("halves", {})
        q = p.get("1x2_blend") or {}
        vals = {"fixture_id": int(r["fixture_id"]), "league": str(league), "date": mdate, "home": r["home"], "away": r["away"],
                "logged_at": now, "model_version": version, "p1": p["1x2"]["1"], "px": p["1x2"]["X"], "p2": p["1x2"]["2"],
                "q1": q.get("1"), "qx": q.get("X"), "q2": q.get("2"), "p_over25": p["goals"]["over_2.5"],
                "p_btts": p["goals"]["btts_yes"], "p_draw_ht": h.get("draw_ht"), "p_draw_2h": h.get("draw_2h"),
                "p_draw_either": h.get("draw_either_half"), "p_draw_htft": h.get("draw_ht_or_ft"),
                "o_home": _f(r.get("o_home")), "o_draw": _f(r.get("o_draw")), "o_away": _f(r.get("o_away")),
                "o_over25": _f(r.get("o_over25")), "o_under25": _f(r.get("o_under25")), "payload": json.dumps(p)}
        conn.execute(f"INSERT OR REPLACE INTO predictions ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                     tuple(vals.values()))
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
        out["draw_either"] = float(((t.hg_ht == t.ag_ht) | ((t.hg - t.hg_ht) == (t.ag - t.ag_ht))).mean())
        out["draw_htft"] = float(((t.hg_ht == t.ag_ht) | (t.hg == t.ag)).mean())
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
    ht_eq = df.hg_ht == df.ag_ht
    for name, pc, yy, bk, needs_ht in (
            ("Over 2.5", "p_over25", (df.hg + df.ag > 2.5).astype(float), "over25", False),
            ("BTTS", "p_btts", ((df.hg > 0) & (df.ag > 0)).astype(float), "btts", False),
            ("Remis do przerwy", "p_draw_ht", ht_eq.astype(float), "draw_ht", True),
            ("Remis HT lub 2H", "p_draw_either", (ht_eq | ((df.hg - df.hg_ht) == (df.ag - df.ag_ht))).astype(float), "draw_either", True),
            ("Remis HT lub FT", "p_draw_htft", (ht_eq | (df.hg == df.ag)).astype(float), "draw_htft", True)):
        if pc not in df:
            continue
        ok = df[pc].notna() & (df["hg_ht"].notna() if needs_ht else True)
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


# ------------------------------------------------------------------ trwałość w repo (CSV)
EXPORT_COLS = ["fixture_id", "league", "date", "home", "away", "logged_at", "model_version",
               "p1", "px", "p2", "q1", "qx", "q2", "p_over25", "p_btts", "p_draw_ht", "p_draw_2h", "p_draw_either", "p_draw_htft",
               "o_home", "o_draw", "o_away", "o_over25", "o_under25"]


def export_csv(conn, path) -> int:
    """Zapisuje dziennik do CSV (bez ciężkiego payloadu) - plik trzymamy w repo."""
    from pathlib import Path
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(EXPORT_COLS)} FROM predictions ORDER BY date, fixture_id", conn)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def import_csv(conn, path) -> int:
    """Wczytuje dziennik z CSV. Istniejące wiersze mają pierwszeństwo (INSERT OR IGNORE)."""
    from pathlib import Path
    ensure(conn)
    if not Path(path).exists():
        return 0
    df = pd.read_csv(path)
    if df.empty:
        return 0
    df = df.astype(object).where(df.notna(), None)
    cols = [c for c in EXPORT_COLS if c in df.columns]
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO predictions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [tuple(r[c] for c in cols) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before
