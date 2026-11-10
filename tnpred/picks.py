"""Moje typy: kafelki z procentami kliknięte na liście meczów, rozliczane po meczu (wszedł / nie wszedł).

Bez stawek - to dziennik skuteczności. Typ zapamiętuje szansę modelu i punkt odniesienia (rynek albo średnią touru)
z chwili kliknięcia, a kurs bukmachera tylko wtedy, gdy był w bazie. Ocena: trafione vs oczekiwane (suma szans modelu)
- jeśli trafiasz częściej, niż wynikałoby z procentów, Twoja selekcja coś dodaje; jeśli rzadziej, to tylko szum lub pech.
"""
from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import betmarkets as bm

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT, leg TEXT UNIQUE, tour TEXT, date TEXT, p1 TEXT, p2 TEXT, key TEXT, label TEXT, grp TEXT,
    p REAL, ref REAL, kurs REAL, status TEXT, settled_at TEXT
);
"""
COLS = ["id", "created_at", "leg", "tour", "date", "p1", "p2", "key", "label", "grp", "p", "ref", "kurs", "status", "settled_at"]
BUCKETS = [(0.0, 0.35, "< 35%"), (0.35, 0.5, "35–50%"), (0.5, 0.65, "50–65%"), (0.65, 0.8, "65–80%"), (0.8, 1.01, "≥ 80%")]


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def kind(key: str, p: float | None = None) -> str:
    """Rodzaj typu do zestawień."""
    if key in ("w1", "w2"):
        return "Zwycięzca – faworyt" if (p or 0) >= 0.5 else "Zwycięzca – underdog"
    if key[:1] == "o" and key[1:].replace(".", "", 1).isdigit():
        return "Over gemów"
    if key[:1] == "u" and key[1:].replace(".", "", 1).isdigit():
        return "Under gemów"
    if key in ("tb", "notb"):
        return "Tie-break"
    if key == "str":
        return "Bez straty seta"
    return "Inne"


def legs(conn) -> set[str]:
    ensure(conn)
    return {r[0] for r in conn.execute("SELECT leg FROM picks")}


def add(conn, leg: str, label: str, p: float, ref: float | None = None, kurs: float | None = None) -> int:
    ensure(conn)
    t, d, a, b, _s, _bo, key = bm.parse_leg(leg)
    cur = conn.execute(
        "INSERT OR IGNORE INTO picks (created_at, leg, tour, date, p1, p2, key, label, grp, p, ref, kurs, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), leg, t, d, a, b, key, label[:120], kind(key, p),
         float(p), None if ref is None else float(ref), None if not kurs else float(kurs), "open"))
    conn.commit()
    return int(cur.lastrowid or 0)


def remove(conn, leg: str | None = None, pick_id: int | None = None) -> None:
    ensure(conn)
    if pick_id is not None:
        conn.execute("DELETE FROM picks WHERE id=?", (int(pick_id),))
    else:
        conn.execute("DELETE FROM picks WHERE leg=?", (leg,))
    conn.commit()


def set_status(conn, pick_id: int, status: str) -> None:
    if status not in ("open", "hit", "miss", "void"):
        raise ValueError("zły status")
    conn.execute("UPDATE picks SET status=?, settled_at=? WHERE id=?",
                 (status, None if status == "open" else datetime.now(timezone.utc).isoformat(timespec="seconds"), int(pick_id)))
    conn.commit()


def set_kurs(conn, pick_id: int, kurs: float | None) -> None:
    conn.execute("UPDATE picks SET kurs=? WHERE id=?", (kurs if kurs and kurs > 1 else None, int(pick_id)))
    conn.commit()


def settle_open(conn, match_lookup) -> int:
    """match_lookup(tour, data, p1, p2) -> wiersz wyniku | None. Krecz/walkower = zwrot (nie liczy się do skuteczności)."""
    ensure(conn)
    n = 0
    for pid, leg in conn.execute("SELECT id, leg FROM picks WHERE status='open'").fetchall():
        try:
            t, d, a, b, _s, _bo, key = bm.parse_leg(leg)
        except ValueError:
            continue
        res = bm.leg_won(key, bm.oriented(match_lookup(t, d, a, b), a))
        if res is None:
            continue
        set_status(conn, pid, "void" if res == "void" else ("hit" if res else "miss"))
        n += 1
    return n


def load(conn) -> pd.DataFrame:
    ensure(conn)
    return pd.read_sql_query("SELECT * FROM picks ORDER BY date DESC, id DESC", conn)


def _line(g: pd.DataFrame, label: str) -> dict:
    n = len(g)
    hit = int((g.status == "hit").sum())
    exp = float(g.p.sum())
    k = g[g.kurs.notna()]
    profit = float(np.where(k.status == "hit", k.kurs - 1, -1.0).sum()) if len(k) else None
    return {"label": label, "n": n, "hit": hit, "rate": hit / n if n else None, "exp": exp / n if n else None,
            "diff": (hit - exp) / n if n else None, "n_kurs": len(k), "profit": profit,
            "roi": profit / len(k) if len(k) else None}


def summary(df: pd.DataFrame) -> dict:
    """Skuteczność rozliczonych typów: całość, wg rodzaju, wg przedziału szansy."""
    if df is None or df.empty:
        return {}
    done = df[df.status.isin(["hit", "miss"])]
    out = {"open": int((df.status == "open").sum()), "void": int((df.status == "void").sum()), "total": len(df)}
    if done.empty:
        return out
    out["all"] = _line(done, "Wszystkie")
    order = ["Zwycięzca – faworyt", "Zwycięzca – underdog", "Over gemów", "Under gemów", "Tie-break", "Bez straty seta", "Inne"]
    out["kinds"] = [_line(done[done.grp == k], k) for k in order if (done.grp == k).any()]
    out["buckets"] = [_line(done[(done.p >= lo) & (done.p < hi)], lab) for lo, hi, lab in BUCKETS
                      if ((done.p >= lo) & (done.p < hi)).any()]
    # Brier: średni kwadrat błędu szansy (0 = idealnie, 0.25 = rzut monetą przy 50%)
    y = (done.status == "hit").astype(float)
    out["brier"] = float(((done.p - y) ** 2).mean())
    out["strip"] = [(r.status == "hit", f"{r.date} {r.p1} – {r.p2}: {r.label} ({100 * r.p:.0f}%)")
                    for r in done.sort_values(["date", "id"]).tail(60).itertuples()]
    return out


def export_text(conn) -> tuple[str, int]:
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM picks ORDER BY id", conn)
    return df.to_csv(index=False), len(df)


def import_text(conn, text: str) -> int:
    ensure(conn)
    if not text or not text.strip():
        return 0
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return 0
    df = df.astype(object).where(df.notna(), None)
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO picks ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                     [tuple(r.get(c) for c in COLS) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before
