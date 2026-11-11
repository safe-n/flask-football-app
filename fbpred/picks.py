"""Moje typy: kafelki z procentami kliknięte na liście meczów, rozliczane po meczu (wszedł / nie wszedł), składane w kupony.

Bez stawek - to dziennik skuteczności (nie zastępuje „Moich zakładów”). Typ zapamiętuje szansę modelu i punkt odniesienia
(rynek dla 1X2, średnią ligi dla pozostałych) z chwili kliknięcia, a kurs bukmachera tylko wtedy, gdy był w bazie.
Ocena: trafione vs oczekiwane (średnia z klikniętych procentów). Wzorzec: tnpred/picks.py, opis w docs/WZORZEC-MOJE-TYPY.md.
"""
from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import betmarkets as bm
from .bets import leg_won

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT, leg TEXT UNIQUE, league TEXT, date TEXT, home TEXT, away TEXT, key TEXT, label TEXT, grp TEXT,
    p REAL, ref REAL, kurs REAL, status TEXT, settled_at TEXT, coupon INTEGER
);
CREATE TABLE IF NOT EXISTS pick_coupons (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, note TEXT);
"""
COLS = ["id", "created_at", "leg", "league", "date", "home", "away", "key", "label", "grp", "p", "ref", "kurs", "status",
        "settled_at", "coupon"]
CCOLS = ["id", "created_at", "note"]
BUCKETS = [(0.0, 0.35, "< 35%"), (0.35, 0.5, "35–50%"), (0.5, 0.65, "50–65%"), (0.65, 0.8, "65–80%"), (0.8, 1.01, "≥ 80%")]
KINDS = ["Zwycięzca – faworyt", "Zwycięzca – underdog", "Remis (koniec meczu)", "Podwójna szansa", "Over goli", "Under goli",
         "BTTS", "Remisy w połowach", "Kartki", "Rożne", "Inne"]

# klucz typu (jak w Zestawieniu) -> nazwa kafelka w stats.tiles / średniej ligi w stats.base_rates
TILE_OF = {"o2.5": "over25", "btts": "btts", "d_ht": "draw_ht", "d_2h": "draw_2h", "d_either": "draw_either_half",
           "d_htft": "draw_ht_or_ft", "d_ft": "draw_ft", "y3.5": "yellow35", "c9.5": "corners95"}
X12 = ("1", "X", "2")


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class Locked(ValueError):
    """Typ jest na zatwierdzonym kuponie - nie można go usunąć ani zmienić kursu."""


def _locked(conn, leg=None, pick_id=None) -> bool:
    q, a = ("leg=?", leg) if pick_id is None else ("id=?", int(pick_id))
    r = conn.execute(f"SELECT coupon FROM picks WHERE {q}", (a,)).fetchone()
    return bool(r and r[0] is not None)


def _is_line(key: str, prefix: str) -> bool:
    return key[:1] == prefix and key[1:].replace(".", "", 1).isdigit()


def kind(key: str, fav: bool | None = None) -> str:
    """Rodzaj typu do zestawień. `fav`: czy 1/2 było najwyższą z szans 1X2 w chwili kliknięcia."""
    if key in ("1", "2"):
        return "Zwycięzca – faworyt" if fav else "Zwycięzca – underdog"
    if key in ("X", "d_ft"):
        return "Remis (koniec meczu)"
    if key in ("1X", "X2", "12"):
        return "Podwójna szansa"
    if _is_line(key, "o"):
        return "Over goli"
    if _is_line(key, "u"):
        return "Under goli"
    if key in ("btts", "nobtts"):
        return "BTTS"
    if key.startswith("d_"):
        return "Remisy w połowach"
    if _is_line(key, "y"):
        return "Kartki"
    if _is_line(key, "c"):
        return "Rożne"
    return "Inne"


def tile_specs(pred: dict, base: dict | None = None) -> dict[str, dict]:
    """Klikalne kafelki meczu: klucz -> {label, p, ref, rl, fav}. Te same liczby, które rysuje strona Mecze
    (katalog rynków z Zestawienia), więc procent zapisany = procent widziany."""
    base = base or {}
    cat = bm.catalogue(pred)
    mk = pred.get("market_1x2") or {}
    best = max((cat[k]["p"] for k in X12 if k in cat), default=None)
    out: dict[str, dict] = {}
    for k in X12:
        if k not in cat:
            continue
        ref, rl = (mk.get(k), "rynek") if mk.get(k) is not None else ((base.get("draw_ft"), "liga") if k == "X" else (None, ""))
        out[k] = {"label": cat[k]["label"], "p": cat[k]["p"], "ref": ref, "rl": rl, "fav": cat[k]["p"] == best}
    for k, tname in TILE_OF.items():
        if k in cat:
            out[k] = {"label": cat[k]["label"], "p": cat[k]["p"], "ref": base.get(tname), "rl": "liga", "fav": None}
    return out


def legs(conn) -> set[str]:
    ensure(conn)
    return {r[0] for r in conn.execute("SELECT leg FROM picks")}


def add(conn, leg: str, label: str, p: float, ref: float | None = None, kurs: float | None = None, fav: bool | None = None) -> int:
    ensure(conn)
    lg, d, h, a, key = bm.parse_leg(leg)
    cur = conn.execute(
        "INSERT OR IGNORE INTO picks (created_at, leg, league, date, home, away, key, label, grp, p, ref, kurs, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), leg, lg, d, h, a, key, label[:120], kind(key, fav),
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
    cur = conn.execute("INSERT INTO pick_coupons (created_at, note) VALUES (?, ?)",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), (note or "")[:200]))
    cid = int(cur.lastrowid)
    conn.execute(f"UPDATE picks SET coupon=? WHERE id IN ({','.join('?' * len(ids))})", (cid, *ids))
    conn.commit()
    return cid


def independent(legs_df: pd.DataFrame) -> bool:
    """Czy każdy typ jest z innego meczu (tylko wtedy iloczyn szans ma sens)."""
    return not legs_df.duplicated(["league", "date", "home", "away"]).any()


def joint(legs_df: pd.DataFrame) -> tuple[float | None, float | None]:
    """(szansa wszystkich wg modelu, kurs łączny). Szansa = None, gdy są dwa typy z jednego meczu; kurs = None, gdy brakuje kursu."""
    if legs_df.empty:
        return None, None
    p = float(np.prod(legs_df.p)) if independent(legs_df) else None
    odds = float(np.prod(legs_df.kurs)) if legs_df.kurs.notna().all() else None
    return p, odds


def coupon_status(legs_df: pd.DataFrame) -> str:
    st = set(legs_df.status)
    if "miss" in st:
        return "lost"
    if "open" in st:
        return "open"
    if st <= {"void"}:
        return "void"
    return "won"


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records") if len(df) else []


def coupons(conn) -> list[dict]:
    """Zatwierdzone kupony (najnowsze pierwsze): typy, status, szansa całości wg modelu, kurs AKO (gdy każdy typ ma kurs)."""
    ensure(conn)
    cs = pd.read_sql_query("SELECT * FROM pick_coupons ORDER BY id DESC", conn)
    pk = pd.read_sql_query("SELECT * FROM picks WHERE coupon IS NOT NULL ORDER BY date, id", conn)
    out = []
    for c in cs.to_dict("records"):
        lg = pk[pk.coupon == c["id"]]
        if lg.empty:
            continue
        live = lg[lg.status != "void"]                      # zwroty wypadają z kursu AKO i z iloczynu szans
        p_all, odds = joint(live)
        status = coupon_status(lg)
        profit = None
        if odds and status in ("won", "lost"):
            profit = odds - 1 if status == "won" else -1.0
        out.append({**c, "legs": _records(lg), "n": len(lg), "status": status, "odds": odds, "p": p_all, "profit": profit,
                    "kind": ("AKO" if len(lg) > 1 else "Pojedynczy") if odds else "bez kursów"})
    return out


def coupon_summary(cps: list[dict]) -> dict:
    done = [c for c in cps if c["status"] in ("won", "lost")]
    if not done:
        return {}
    won = sum(c["status"] == "won" for c in done)
    k = [c for c in done if c["profit"] is not None]
    pr = sum(c["profit"] for c in k)
    ps = [c["p"] for c in done if c["p"] is not None]
    return {"n": len(done), "won": won, "rate": won / len(done), "exp": float(np.mean(ps)) if ps else None,
            "n_kurs": len(k), "profit": pr if k else None, "roi": pr / len(k) if k else None}


def db_lookup(conn):
    """-> funkcja (liga, data, gospodarz, gość) -> wiersz meczu z bazy | None (kolejność jak w identyfikatorze typu)."""
    def look(lg, d, h, a):
        q = pd.read_sql_query("SELECT * FROM matches WHERE league=? AND home=? AND away=? AND date=?", conn, params=[lg, h, a, d])
        return q.to_dict("records")[0] if len(q) else None
    return look


def settle_open(conn, match_lookup) -> int:
    """match_lookup(liga, data, gospodarz, gość) -> wiersz wyniku | None. Rozlicza otwarte typy, gdy jest wynik (i dane rynku)."""
    ensure(conn)
    n = 0
    for pid, leg in conn.execute("SELECT id, leg FROM picks WHERE status='open'").fetchall():
        try:
            lg, d, h, a, key = bm.parse_leg(leg)
        except ValueError:
            continue
        row = match_lookup(lg, d, h, a)
        res = None if row is None else leg_won(key, row)
        if res is None:
            continue
        set_status(conn, pid, "hit" if res else "miss")
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
    out["kinds"] = [_line(done[done.grp == k], k) for k in KINDS if (done.grp == k).any()]
    out["buckets"] = [_line(done[(done.p >= lo) & (done.p < hi)], lab) for lo, hi, lab in BUCKETS
                      if ((done.p >= lo) & (done.p < hi)).any()]
    y = (done.status == "hit").astype(float)                 # Brier: 0 = idealnie, 0.25 = rzut monetą przy 50%
    out["brier"] = float(((done.p - y) ** 2).mean())
    out["strip"] = [(r.status == "hit", f"{r.date} {r.home} – {r.away}: {r.label} ({100 * r.p:.0f}%)")
                    for r in done.sort_values(["date", "id"]).tail(60).itertuples()]
    return out


def export_text(conn) -> tuple[str, int]:
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM picks ORDER BY id", conn)
    return df.to_csv(index=False), len(df)


def export_coupons(conn) -> tuple[str, int]:
    ensure(conn)
    df = pd.read_sql_query(f"SELECT {', '.join(CCOLS)} FROM pick_coupons ORDER BY id", conn)
    return df.to_csv(index=False), len(df)


def _import(conn, text: str | None, table: str, cols: list[str]) -> int:
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
    conn.executemany(f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [tuple(r.get(c) for c in cols) for r in df.to_dict("records")])
    conn.commit()
    return conn.total_changes - before


def import_text(conn, text: str | None) -> int:
    return _import(conn, text, "picks", COLS)


def import_coupons(conn, text: str | None) -> int:
    return _import(conn, text, "pick_coupons", CCOLS)
