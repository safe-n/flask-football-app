"""SQLite: mecze (historia), nadchodzące mecze (API / ręczne). Dziennik i zakłady mają własne moduły."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config
from .tdata import COLS, _from_norm, match_id

_LOCK = threading.RLock()

UP_COLS = ["id", "source", "tour", "tournament", "surface", "best_of", "date", "p1", "p2", "o1", "o2",
           "total_line", "o_over", "o_under", "hcp_line", "o_h1", "o_h2", "updated_at"]


def connect(path=None) -> sqlite3.Connection:
    p = path or config.DB_PATH
    if str(p) != ":memory:":
        from pathlib import Path
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL") if str(p) != ":memory:" else None
    init(conn)
    return conn


def init(conn) -> None:
    cols = ", ".join(f'"{c}"' for c in COLS)
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS matches (id TEXT PRIMARY KEY, {cols});
    CREATE TABLE IF NOT EXISTS upcoming (id TEXT PRIMARY KEY, source TEXT, tour TEXT, tournament TEXT, surface TEXT,
        best_of INTEGER, date TEXT, p1 TEXT, p2 TEXT, o1 REAL, o2 REAL, total_line REAL, o_over REAL, o_under REAL,
        hcp_line REAL, o_h1 REAL, o_h2 REAL, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.commit()


def upsert_matches(conn, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d.insert(0, "id", [match_id(t, dt, a, b) + f"|{tn}" for t, dt, a, b, tn in
                       zip(d.tour, d.date, d.winner, d.loser, d.tournament.fillna(""))])
    d = d[["id"] + COLS].astype(object).where(d[["id"] + COLS].notna(), None)
    q = f"INSERT OR REPLACE INTO matches (id, {', '.join(chr(34) + c + chr(34) for c in COLS)}) VALUES ({', '.join('?' * (len(COLS) + 1))})"
    with _LOCK:
        before = conn.total_changes
        conn.executemany(q, [tuple(r) for r in d.itertuples(index=False, name=None)])
        conn.commit()
        return conn.total_changes - before


def load_matches(conn) -> pd.DataFrame:
    with _LOCK:
        df = pd.read_sql_query("SELECT * FROM matches", conn)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df = _from_norm(df.drop(columns=["id"]))
    rord = {"1st Round": 1, "2nd Round": 2, "3rd Round": 3, "4th Round": 4, "Quarterfinals": 5, "Semifinals": 6,
            "The Final": 7, "Round Robin": 3}
    df["_r"] = df["round"].map(rord).fillna(2)
    return df.sort_values(["date", "_r"], kind="stable").drop(columns="_r").reset_index(drop=True)


def up_id(tour, date, p1, p2) -> str:
    return match_id(tour, date, p1, p2)


def upsert_upcoming(conn, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    with _LOCK:
        for r in rows:
            r = dict(r)
            r.setdefault("id", up_id(r["tour"], r["date"], r["p1"], r["p2"]))
            r["updated_at"] = now
            vals = [r.get(c) for c in UP_COLS]
            vals = [None if (isinstance(v, float) and v != v) else v for v in vals]
            conn.execute(f"INSERT OR REPLACE INTO upcoming ({', '.join(UP_COLS)}) VALUES ({', '.join('?' * len(UP_COLS))})", vals)
            n += 1
        conn.commit()
    return n


def load_upcoming(conn, include_past_days: int = 1) -> pd.DataFrame:
    with _LOCK:
        df = pd.read_sql_query("SELECT * FROM upcoming", conn)
    if df.empty:
        return df
    df["d"] = pd.to_datetime(df["date"].str[:10], errors="coerce")
    cut = pd.Timestamp.today().normalize() - pd.Timedelta(days=include_past_days)
    return df[df.d >= cut].sort_values(["date", "tour", "p1"]).drop(columns="d").reset_index(drop=True)


def delete_upcoming(conn, uid: str) -> None:
    with _LOCK:
        conn.execute("DELETE FROM upcoming WHERE id=?", (uid,))
        conn.commit()


def prune_upcoming(conn, played: set[str], older_than_days: int = 3) -> int:
    """Usuwa mecze, które już mają wynik w historii, oraz stare (> N dni po terminie)."""
    df = pd.read_sql_query("SELECT id, date FROM upcoming", conn)
    if df.empty:
        return 0
    cut = (pd.Timestamp.today().normalize() - pd.Timedelta(days=older_than_days)).strftime("%Y-%m-%d")
    drop = [i for i, d in zip(df.id, df.date) if i in played or str(d)[:10] < cut]
    with _LOCK:
        conn.executemany("DELETE FROM upcoming WHERE id=?", [(i,) for i in drop])
        conn.commit()
    return len(drop)


def meta_get(conn, k: str, default=None):
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(conn, k: str, v) -> None:
    with _LOCK:
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, str(v)))
        conn.commit()


def nan_none(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x
