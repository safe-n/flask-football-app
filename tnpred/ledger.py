"""Dziennik prognoz: zapis prognozy PRZED meczem (zamrażana w dniu meczu), potem porównanie z wynikiem i z rynkiem."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY, logged_at TEXT, date TEXT, tour TEXT, tournament TEXT, surface TEXT, best_of INTEGER,
    p1 TEXT, p2 TEXT, p_model REAL, p_elo REAL, p_market REAL, o1 REAL, o2 REAL,
    games_mean REAL, total_line REAL, p_over REAL, p_tb REAL, p_straight REAL
);
"""
COLS = ["id", "logged_at", "date", "tour", "tournament", "surface", "best_of", "p1", "p2", "p_model", "p_elo", "p_market",
        "o1", "o2", "games_mean", "total_line", "p_over", "p_tb", "p_straight"]


def ensure(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def log(conn, rows: list[dict]) -> int:
    """Zapisuje/aktualizuje prognozy meczów, które się jeszcze nie zaczęły (data > dziś). Starsze = zamrożone."""
    ensure(conn)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for r in rows:
        if str(r["date"])[:10] < today:
            continue
        exists = conn.execute("SELECT date FROM predictions WHERE id=?", (r["id"],)).fetchone()
        if exists and str(exists[0])[:10] <= today:
            continue    # zamrożona w dniu meczu
        vals = {**r, "logged_at": now}
        conn.execute(f"INSERT OR REPLACE INTO predictions ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                     [None if (isinstance(vals.get(c), float) and vals.get(c) != vals.get(c)) else vals.get(c) for c in COLS])
        n += 1
    conn.commit()
    return n


def load(conn) -> pd.DataFrame:
    ensure(conn)
    return pd.read_sql_query("SELECT * FROM predictions ORDER BY date DESC, tour, p1", conn)


def evaluate(pred: pd.DataFrame, lookup) -> pd.DataFrame:
    """Dokleja wynik (lookup(tour, data, p1, p2) -> wiersz) i trafienia."""
    if pred.empty:
        return pred
    out = []
    for r in pred.to_dict("records"):
        m = lookup(r["tour"], r["date"], r["p1"], r["p2"])
        if m is None:
            continue
        c = str(m.get("comment") or "").lower()
        if not c.startswith("compl"):
            continue
        y = 1.0 if m["winner"] == r["p1"] else 0.0
        tg = float(m.get("total_games") or np.nan)
        out.append({**r, "y": y, "total_games": tg, "tb": float((m.get("n_tb") or 0) > 0),
                    "straight": float((m.get("lsets") or 0) == 0), "score": m.get("score", "")})
    return pd.DataFrame(out)


def scores(ev: pd.DataFrame) -> dict:
    if ev.empty:
        return {}
    y = ev.y.to_numpy()

    def ll(p):
        p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    out = {"n": len(ev), "ll_model": ll(ev.p_model), "acc_model": float(((ev.p_model >= 0.5) == (y == 1)).mean())}
    mk = ev[ev.p_market.notna()]
    if len(mk):
        ym = mk.y.to_numpy()
        pm = np.clip(mk.p_market.to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        pmod = np.clip(mk.p_model.to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        out["n_mkt"] = len(mk)
        out["ll_market"] = float(-np.mean(ym * np.log(pm) + (1 - ym) * np.log(1 - pm)))
        out["ll_model_same"] = float(-np.mean(ym * np.log(pmod) + (1 - ym) * np.log(1 - pmod)))
    g = ev[ev.total_games.notna() & ev.games_mean.notna()]
    if len(g):
        out["games_bias"] = float((g.games_mean - g.total_games).mean())
        out["games_mae"] = float((g.games_mean - g.total_games).abs().mean())
    return out


def export_text(conn) -> tuple[str, int]:
    df = load(conn)
    return df[COLS].sort_values("id").to_csv(index=False), len(df)


def import_text(conn, text: str) -> int:
    ensure(conn)
    if not text or not text.strip():
        return 0
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return 0
    df = df.astype(object).where(df.notna(), None)
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO predictions ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                     [tuple(r.get(c) for c in COLS) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before
