"""Dziennik własnych zakładów (jak w fbpred): co postawiłeś, po jakim kursie, jak się skończyło - i czy model miał rację.

Rozliczanie automatyczne po pojawieniu się wyniku w bazie (tennis-data aktualizuje się co kilka dni - można rozliczyć ręcznie).
Krecz/walkower: typ = zwrot (kurs tego typu = 1.00 w AKO).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import betmarkets as bm

SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placed_at TEXT, stake REAL, odds REAL, p_model REAL, status TEXT, legs TEXT, note TEXT
);
"""
COLS = ["id", "placed_at", "stake", "odds", "p_model", "status", "legs", "note"]


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def add_bet(conn, legs: list[dict], odds: float, stake: float, note: str = "") -> int:
    ensure(conn)
    if not legs:
        raise ValueError("brak typów")
    if not (odds and odds > 1.0) or not (stake and stake > 0):
        raise ValueError("podaj kurs > 1 i stawkę > 0")
    p = float(np.prod([float(l["p"]) for l in legs if l.get("p")] or [np.nan]))
    cur = conn.execute("INSERT INTO bets (placed_at, stake, odds, p_model, status, legs, note) VALUES (?,?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), float(stake), float(odds),
                        None if p != p else p, "open", json.dumps(legs, ensure_ascii=False), note[:200]))
    conn.commit()
    return int(cur.lastrowid)


def set_status(conn, bet_id: int, status: str, odds: float | None = None) -> None:
    if status not in ("open", "won", "lost", "void"):
        raise ValueError("zły status")
    if odds:
        conn.execute("UPDATE bets SET status=?, odds=? WHERE id=?", (status, float(odds), int(bet_id)))
    else:
        conn.execute("UPDATE bets SET status=? WHERE id=?", (status, int(bet_id)))
    conn.commit()


def delete(conn, bet_id: int) -> None:
    conn.execute("DELETE FROM bets WHERE id=?", (int(bet_id),))
    conn.commit()


def settle_open(conn, match_lookup) -> int:
    """match_lookup(tour, data, p1, p2) -> wiersz wyniku | None."""
    ensure(conn)
    n = 0
    for bid, legs_json, odds in conn.execute("SELECT id, legs, odds FROM bets WHERE status='open'").fetchall():
        legs = json.loads(legs_json)
        outcomes = []
        for l in legs:
            try:
                t, d, a, b, _s, _bo, key = bm.parse_leg(l["id"])
            except ValueError:
                outcomes.append(None)
                continue
            outcomes.append(bm.leg_won(key, bm.oriented(match_lookup(t, d, a, b), a)))
        if any(o is False for o in outcomes):
            set_status(conn, bid, "lost")
            n += 1
        elif outcomes and all(o is True or o == "void" for o in outcomes):
            if all(o == "void" for o in outcomes):
                set_status(conn, bid, "void")
            else:
                new_odds = odds
                if any(o == "void" for o in outcomes) and all(l.get("kurs") for l in legs):
                    new_odds = float(np.prod([float(l["kurs"]) for l, o in zip(legs, outcomes) if o is True]))
                set_status(conn, bid, "won", new_odds)
            n += 1
    return n


def load(conn) -> pd.DataFrame:
    ensure(conn)
    df = pd.read_sql_query("SELECT * FROM bets ORDER BY id DESC", conn)
    if df.empty:
        return df
    df["profit"] = np.where(df.status == "won", df.stake * (df.odds - 1), np.where(df.status == "lost", -df.stake, 0.0))
    df["profit"] = np.where(df.status == "open", np.nan, df["profit"])
    return df


def summary(df: pd.DataFrame) -> dict:
    done = df[df.status.isin(["won", "lost", "void"])] if len(df) else df
    if done.empty:
        return {}
    real = done[done.status != "void"]
    staked = float(done.stake[done.status != "void"].sum())
    profit = float(done.profit.sum())
    out = {"zakladow": len(done), "otwartych": int((df.status == "open").sum()), "wygranych": int((real.status == "won").sum()),
           "przegranych": int((real.status == "lost").sum()), "obstawiono": staked, "zysk": profit,
           "roi": profit / staked if staked > 0 else None,
           "sredni_kurs": float(real.odds.mean()) if len(real) else None,
           "trafnosc": float((real.status == "won").mean()) if len(real) else None}
    m = real[real.p_model.notna()]
    if len(m):
        out["trafnosc_wg_modelu"] = float(m.p_model.mean())
        out["zysk_wg_modelu"] = float((m.stake * (m.p_model * m.odds - 1)).sum())
        out["kurs_break_even"] = float(1 / m.p_model.mean())
    return out


def cumulative(df: pd.DataFrame) -> list[float]:
    done = df[df.status.isin(["won", "lost", "void"])].sort_values("id") if len(df) else df
    return [] if done.empty else [float(x) for x in done.profit.cumsum()]


def sparkline(vals: list[float], w: int = 320, h: int = 90) -> str:
    if len(vals) < 2:
        return ""
    pts = [0.0] + vals
    lo, hi = min(pts + [0.0]), max(pts + [0.0])
    span = (hi - lo) or 1.0
    xs = [i * (w - 8) / (len(pts) - 1) + 4 for i in range(len(pts))]
    ys = [h - 4 - (v - lo) / span * (h - 8) for v in pts]
    y0 = h - 4 - (0 - lo) / span * (h - 8)
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    col = "var(--up)" if pts[-1] >= 0 else "var(--dn)"
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none" role="img" aria-label="skumulowany zysk">'
            f'<line x1="0" x2="{w}" y1="{y0:.1f}" y2="{y0:.1f}" stroke="var(--mut)" stroke-dasharray="3 3" stroke-width="1"/>'
            f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round"/></svg>')


def export_text(conn) -> tuple[str, int]:
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM bets ORDER BY id", conn)
    return df.to_csv(index=False), len(df)


def import_text(conn, text: str) -> int:
    import io
    ensure(conn)
    if not text or not text.strip():
        return 0
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return 0
    df = df.astype(object).where(df.notna(), None)
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO bets ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                     [tuple(r.get(c) for c in COLS) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before
