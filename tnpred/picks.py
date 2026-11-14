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
    p REAL, ref REAL, kurs REAL, status TEXT, settled_at TEXT, coupon INTEGER
);
CREATE TABLE IF NOT EXISTS coupons (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, note TEXT);
"""
COLS = ["id", "created_at", "leg", "tour", "date", "p1", "p2", "key", "label", "grp", "p", "ref", "kurs", "status", "settled_at",
        "coupon"]
CCOLS = ["id", "created_at", "note"]
BUCKETS = [(0.0, 0.35, "< 35%"), (0.35, 0.5, "35–50%"), (0.5, 0.65, "50–65%"), (0.65, 0.8, "65–80%"), (0.8, 1.01, "≥ 80%")]


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if "coupon" not in {r[1] for r in conn.execute("PRAGMA table_info(picks)")}:      # baza z 0.3.12
        conn.execute("ALTER TABLE picks ADD COLUMN coupon INTEGER")
    conn.commit()


class Locked(ValueError):
    """Typ jest na zatwierdzonym kuponie - nie można go usunąć ani zmienić kursu."""


def _locked(conn, leg=None, pick_id=None) -> bool:
    q, a = ("leg=?", leg) if pick_id is None else ("id=?", int(pick_id))
    r = conn.execute(f"SELECT coupon FROM picks WHERE {q}", (a,)).fetchone()
    return bool(r and r[0] is not None)


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
    if key == "nstr":
        return "Over setów"
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
    if _locked(conn, leg, pick_id):
        raise Locked("ten typ jest na zatwierdzonym kuponie - zostaje na stałe")
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
    if _locked(conn, pick_id=pick_id):
        raise Locked("kupon jest zatwierdzony - kursu nie można już zmienić")
    conn.execute("UPDATE picks SET kurs=? WHERE id=?", (kurs if kurs and kurs > 1 else None, int(pick_id)))
    conn.commit()


def draft(conn) -> pd.DataFrame:
    """Szkic kuponu: typy kliknięte od ostatniego zatwierdzenia."""
    ensure(conn)
    return pd.read_sql_query("SELECT * FROM picks WHERE coupon IS NULL ORDER BY date, id", conn)


def confirm(conn, note: str = "") -> int:
    """Zatwierdza szkic jako kupon (na stałe). -> numer kuponu."""
    ensure(conn)
    ids = [r[0] for r in conn.execute("SELECT id FROM picks WHERE coupon IS NULL")]
    if not ids:
        raise ValueError("szkic jest pusty - najpierw kliknij kafelki z procentami")
    cur = conn.execute("INSERT INTO coupons (created_at, note) VALUES (?, ?)",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), (note or "")[:200]))
    cid = int(cur.lastrowid)
    conn.execute(f"UPDATE picks SET coupon=? WHERE id IN ({','.join('?' * len(ids))})", (cid, *ids))
    conn.commit()
    return cid


def coupon_status(legs: pd.DataFrame) -> str:
    st = set(legs.status)
    if "miss" in st:
        return "lost"
    if "open" in st:
        return "open"
    if st <= {"void"}:
        return "void"
    return "won"


def coupons(conn) -> list[dict]:
    """Zatwierdzone kupony (najnowsze pierwsze): typy, status, szansa całości wg modelu, kurs AKO (gdy każdy typ ma kurs)."""
    ensure(conn)
    cs = pd.read_sql_query("SELECT * FROM coupons ORDER BY id DESC", conn)
    pk = pd.read_sql_query("SELECT * FROM picks WHERE coupon IS NOT NULL ORDER BY date, id", conn)
    out = []
    for c in cs.to_dict("records"):
        legs = pk[pk.coupon == c["id"]]
        if legs.empty:
            continue
        live = legs[legs.status != "void"]
        has_odds = len(live) > 0 and live.kurs.notna().all()
        odds = float(np.prod(live.kurs)) if has_odds else None
        status = coupon_status(legs)
        p_all = float(np.prod(live.p)) if len(live) else None
        profit = None
        if odds and status in ("won", "lost"):
            profit = odds - 1 if status == "won" else -1.0
        out.append({**c, "legs": legs.astype(object).where(legs.notna(), None).to_dict("records"), "n": len(legs),
                    "status": status, "odds": odds, "p": p_all, "profit": profit,
                    "kind": ("AKO" if len(legs) > 1 else "Pojedynczy") if has_odds else "bez kursów"})
    return out


def coupon_summary(cps: list[dict]) -> dict:
    done = [c for c in cps if c["status"] in ("won", "lost")]
    if not done:
        return {}
    won = sum(c["status"] == "won" for c in done)
    k = [c for c in done if c["profit"] is not None]
    pr = sum(c["profit"] for c in k)
    return {"n": len(done), "won": won, "rate": won / len(done), "exp": float(np.mean([c["p"] for c in done if c["p"] is not None] or [np.nan])),
            "n_kurs": len(k), "profit": pr if k else None, "roi": pr / len(k) if k else None}


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
    order = ["Zwycięzca – faworyt", "Zwycięzca – underdog", "Over gemów", "Under gemów", "Tie-break", "Over setów", "Bez straty seta", "Inne"]
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


def export_coupons(conn) -> tuple[str, int]:
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(CCOLS)} FROM coupons ORDER BY id", conn)
    return df.to_csv(index=False), len(df)


def import_coupons(conn, text: str) -> int:
    ensure(conn)
    if not text or not text.strip():
        return 0
    df = pd.read_csv(io.StringIO(text))
    df = df.astype(object).where(df.notna(), None)
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO coupons ({', '.join(CCOLS)}) VALUES (?,?,?)",
                     [tuple(r.get(c) for c in CCOLS) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before


def import_text(conn, text: str) -> int:
    ensure(conn)
    if not text or not text.strip():
        return 0
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return 0
    if "coupon" in df.columns:
        df["coupon"] = df["coupon"].astype("Int64")
    df = df.astype(object).where(df.notna(), None)
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO picks ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                     [tuple(r.get(c) for c in COLS) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before
