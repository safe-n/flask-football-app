"""Dziennik własnych zakładów: co postawiłeś, po jakim kursie, jak się skończyło - i czy model miał rację.

Zakład to jeden typ albo AKO (kilka typów); każdy typ ma identyfikator jak w Zestawieniu (liga~data~gospodarz~gość~rynek).
Zakłady rozlicza się same, gdy w bazie pojawią się wyniki meczów (można też ręcznie: wygrany / przegrany / zwrot).
Zapis trwały: CSV w gałęzi ledger-data na GitHubie (tak jak dziennik prognoz).
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


def leg_won(key: str, r: dict) -> bool | None:
    """Czy typ `key` zaszedł w meczu z wynikiem `r` (hg, ag, hg_ht, ag_ht, h_yellow..). None = brak danych do rozliczenia."""
    def num(c):
        v = r.get(c)
        return None if v is None or v != v else float(v)
    hg, ag = num("hg"), num("ag")
    if hg is None or ag is None:
        return None
    ht_h, ht_a = num("hg_ht"), num("ag_ht")
    tot = hg + ag
    simple = {"1": hg > ag, "X": hg == ag, "2": hg < ag, "1X": hg >= ag, "X2": hg <= ag, "12": hg != ag,
              "btts": hg > 0 and ag > 0, "nobtts": not (hg > 0 and ag > 0), "d_ft": hg == ag}
    if key in simple:
        return bool(simple[key])
    if key[:1] in ("o", "u") and key[1:].replace(".", "", 1).isdigit():
        line = float(key[1:])
        return bool(tot > line) if key[0] == "o" else bool(tot < line)
    if key.startswith("d_"):
        if ht_h is None or ht_a is None:
            return None
        h1 = ht_h == ht_a
        h2 = (hg - ht_h) == (ag - ht_a)
        return bool({"d_ht": h1, "d_2h": h2, "d_either": h1 or h2, "d_htft": h1 or hg == ag}.get(key))
    for pre, a, b in (("y", "h_yellow", "a_yellow"), ("c", "h_corners", "a_corners")):
        if key.startswith(pre) and key[1:].replace(".", "", 1).isdigit():
            x, y = num(a), num(b)
            return None if x is None or y is None else bool(x + y > float(key[1:]))
    return None


def add_bet(conn, legs: list[dict], odds: float, stake: float, note: str = "") -> int:
    """legs: [{id, mecz, rynek, p}]. p_model = iloczyn szans (zakłada niezależność typów z różnych meczów)."""
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


def set_status(conn, bet_id: int, status: str) -> None:
    if status not in ("open", "won", "lost", "void"):
        raise ValueError("zły status")
    conn.execute("UPDATE bets SET status=? WHERE id=?", (status, int(bet_id)))
    conn.commit()


def delete(conn, bet_id: int) -> None:
    conn.execute("DELETE FROM bets WHERE id=?", (int(bet_id),))
    conn.commit()


def settle_open(conn, match_lookup) -> int:
    """Rozlicza otwarte zakłady, gdy znamy wyniki wszystkich meczów. match_lookup(liga, data, dom, gość) -> dict wyniku | None."""
    ensure(conn)
    n = 0
    for bid, legs_json in conn.execute("SELECT id, legs FROM bets WHERE status='open'").fetchall():
        outcomes = []
        for l in json.loads(legs_json):
            try:
                lg, d, h, a, key = bm.parse_leg(l["id"])
            except ValueError:
                outcomes.append(None)
                continue
            row = match_lookup(lg, d, h, a)
            outcomes.append(None if row is None else leg_won(key, row))
        if outcomes and any(o is False for o in outcomes):
            set_status(conn, bid, "lost")      # jeden przegrany typ przesądza o AKO, nawet gdy reszta jeszcze się nie odbyła
            n += 1
        elif outcomes and all(o is True for o in outcomes):
            set_status(conn, bid, "won")
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
    """Wyniki rozliczonych zakładów (zwroty pomijamy w trafności, ale liczymy jako 0 zysku)."""
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
    """Skumulowany zysk w kolejności stawiania (do wykresu)."""
    done = df[df.status.isin(["won", "lost", "void"])].sort_values("id") if len(df) else df
    return [] if done.empty else [float(x) for x in done.profit.cumsum()]


def sparkline(vals: list[float], w: int = 320, h: int = 90) -> str:
    """Inline SVG skumulowanego zysku: zielony ponad zerem, czerwony pod zerem."""
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


def export_csv(conn, path) -> int:
    from pathlib import Path
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM bets ORDER BY id", conn)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def import_csv(conn, path) -> int:
    from pathlib import Path
    ensure(conn)
    if not Path(path).exists():
        return 0
    df = pd.read_csv(path)
    if df.empty:
        return 0
    df = df.astype(object).where(df.notna(), None)
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO bets ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                     [tuple(r.get(c) for c in COLS) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before
