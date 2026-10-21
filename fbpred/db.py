"""Warstwa bazy (SQLite). Jedna tabela `matches`, upsert bez nadpisywania danych nullami."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

COLUMNS = [
    "fixture_id", "league", "season", "date", "home", "away", "referee", "status",
    "hg", "ag", "hg_ht", "ag_ht",
    "h_shots", "a_shots", "h_sot", "a_sot", "h_corners", "a_corners",
    "h_yellow", "a_yellow", "h_red", "a_red", "stats_done",
    "o_home", "o_draw", "o_away", "o_over25", "o_under25", "o_btts_yes", "o_btts_no",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    fixture_id INTEGER PRIMARY KEY,
    league TEXT NOT NULL,
    season INTEGER,
    date TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    referee TEXT,
    status TEXT,
    hg INTEGER, ag INTEGER, hg_ht INTEGER, ag_ht INTEGER,
    h_shots INTEGER, a_shots INTEGER, h_sot INTEGER, a_sot INTEGER,
    h_corners INTEGER, a_corners INTEGER,
    h_yellow INTEGER, a_yellow INTEGER, h_red INTEGER, a_red INTEGER,
    stats_done INTEGER DEFAULT 0,
    o_home REAL, o_draw REAL, o_away REAL,
    o_over25 REAL, o_under25 REAL, o_btts_yes REAL, o_btts_no REAL
);
CREATE INDEX IF NOT EXISTS idx_matches_league_date ON matches (league, date);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_matches(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Wstawia/aktualizuje mecze. Wartość None NIE kasuje istniejących danych."""
    if not rows:
        return 0
    updates = ", ".join(
        f"{c}=COALESCE(excluded.{c}, matches.{c})" for c in COLUMNS if c != "fixture_id"
    )
    sql = (
        f"INSERT INTO matches ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))}) "
        f"ON CONFLICT(fixture_id) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, [tuple(r.get(c) for c in COLUMNS) for r in rows])
    conn.commit()
    return len(rows)


def load_matches(conn: sqlite3.Connection, league: str | None = None,
                 finished_only: bool = True) -> pd.DataFrame:
    q = "SELECT * FROM matches"
    cond, params = [], []
    if league:
        cond.append("league = ?")
        params.append(str(league))
    if finished_only:
        cond.append("hg IS NOT NULL AND ag IS NOT NULL")
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY date, fixture_id"
    df = pd.read_sql_query(q, conn, params=params)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_upcoming(conn: sqlite3.Connection, league: str | None = None) -> pd.DataFrame:
    q = "SELECT * FROM matches WHERE hg IS NULL"
    params: list = []
    if league:
        q += " AND league = ?"
        params.append(str(league))
    q += " ORDER BY date, fixture_id"
    df = pd.read_sql_query(q, conn, params=params)
    df["date"] = pd.to_datetime(df["date"])
    return df


def update_fields(conn: sqlite3.Connection, fixture_id: int, fields: dict) -> None:
    """Aktualizuje wybrane kolumny jednego meczu (bez ruszania reszty)."""
    bad = set(fields) - set(COLUMNS)
    if bad:
        raise ValueError(f"Nieznane kolumny: {bad}")
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE matches SET {sets} WHERE fixture_id=?", (*fields.values(), fixture_id))
    conn.commit()


def purge_stale_upcoming(conn: sqlite3.Connection, days: int = 3) -> int:
    """Usuwa mecze bez wyniku, których data minęła (np. przełożone - zmieniły datę/id)."""
    cur = conn.execute("DELETE FROM matches WHERE hg IS NULL AND date < date('now', ?)", (f"-{days} day",))
    conn.commit()
    return cur.rowcount
