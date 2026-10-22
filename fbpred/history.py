"""Historia meczów w CSV (źródło prawdy) + archiwum kursów przedmeczowych.

Układ katalogu `history/`:
    E0_2024.csv, E0_2025.csv ...   zakończone mecze, jeden plik = liga + sezon (małe, czytelne diffy w gicie)
    odds/E0.csv                    archiwum kursów PRZED meczem (fixtures.csv pokazuje je tylko chwilowo)
    aliases.json                   opcjonalnie {"Nott'm Forest": "Nottm Forest"} - ujednolicanie nazw drużyn
    UPDATES.log                    dziennik aktualizacji (co, kiedy, ile dodano)

Zasady: dopisujemy i poprawiamy (upsert po fixture_id), nigdy nie kasujemy. Nowa niepusta wartość nadpisuje starą.
Każdy wiersz przechodzi walidację; błędne są odrzucane i raportowane, drobne usterki (np. HT > FT) naprawiane.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import config, csvdata, db
from .leagues import NO_CSV

INT_COLS = ["fixture_id", "season", "hg", "ag", "hg_ht", "ag_ht", "h_shots", "a_shots", "h_sot", "a_sot",
            "h_corners", "a_corners", "h_yellow", "a_yellow", "h_red", "a_red", "stats_done"]
REAL_COLS = ["o_home", "o_draw", "o_away", "o_over25", "o_under25", "o_btts_yes", "o_btts_no"]
STAT_COLS = ["h_shots", "a_shots", "h_sot", "a_sot", "h_corners", "a_corners", "h_yellow", "a_yellow", "h_red", "a_red"]
FILE_RE = re.compile(r"^(?P<league>[A-Za-z0-9]+)_(?P<season>\d{4})\.csv$")
ODDS_COLS = ["snapshot", "fixture_id", "league", "date", "home", "away"] + REAL_COLS


def hdir(p=None) -> Path:
    return Path(p) if p else Path(config.HISTORY_DIR)


def season_of(d) -> int:
    t = pd.Timestamp(d)
    return t.year if t.month >= 7 else t.year - 1


def discover_leagues(hist=None) -> list[str]:
    """Ligi, które mają pliki w history/ (bez sztucznej DEMO)."""
    hd = hdir(hist)
    found = {m["league"] for f in hd.glob("*.csv") if (m := FILE_RE.match(f.name))} if hd.exists() else set()
    return sorted(found - {"DEMO"})


def resolve_leagues(spec: str | None, hist=None) -> list[str]:
    """'auto' / puste = wszystkie ligi z history/ (albo domyślna), inaczej lista rozdzielona przecinkami."""
    if not spec or spec.strip().lower() == "auto":
        return discover_leagues(hist) or [config.DEFAULT_LEAGUE]
    return [x.strip() for x in spec.split(",") if x.strip()]


# ------------------------------------------------------------------ aliasy nazw
def load_aliases(hist=None) -> dict[str, str]:
    f = hdir(hist) / "aliases.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def apply_aliases(rows: list[dict], aliases: dict[str, str] | None = None) -> list[dict]:
    aliases = load_aliases() if aliases is None else aliases
    if not aliases:
        return rows
    for r in rows:
        r["home"] = aliases.get(r["home"], r["home"])
        r["away"] = aliases.get(r["away"], r["away"])
    return rows


# ------------------------------------------------------------------ walidacja
def _num(x):
    try:
        v = float(x)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


def validate_rows(rows: list[dict]) -> tuple[list[dict], list[tuple[dict, str]], int]:
    """Zwraca (poprawne, odrzucone z powodem, liczba naprawionych usterek)."""
    good, bad, fixed = [], [], 0
    for r in rows:
        r = dict(r)
        if not r.get("home") or not r.get("away") or r["home"] == r["away"]:
            bad.append((r, "nazwy drużyn"))
            continue
        if pd.isna(pd.to_datetime(r.get("date"), errors="coerce")):
            bad.append((r, "data"))
            continue
        hg, ag = _num(r.get("hg")), _num(r.get("ag"))
        if hg is None or ag is None or not (0 <= hg <= 20 and 0 <= ag <= 20) or hg != int(hg) or ag != int(ag):
            bad.append((r, "wynik"))
            continue
        h1, a1 = _num(r.get("hg_ht")), _num(r.get("ag_ht"))
        if (h1 is None) != (a1 is None) or (h1 is not None and not (0 <= h1 <= hg and 0 <= a1 <= ag)):
            r["hg_ht"] = r["ag_ht"] = None  # niespójny wynik do przerwy -> usuwamy tylko jego, mecz zostaje
            fixed += 1
        for c in STAT_COLS:
            v = _num(r.get(c))
            if v is not None and (v < 0 or v > 60):
                r[c] = None
                fixed += 1
        for c in REAL_COLS:
            v = _num(r.get(c))
            if v is not None and not (1.0 < v <= 1000):
                r[c] = None
                fixed += 1
        good.append(r)
    return good, bad, fixed


# ------------------------------------------------------------------ ramki i pliki
def frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).reindex(columns=db.COLUMNS)
    for c in INT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    for c in REAL_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def read_file(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        return frame([])
    return frame(pd.read_csv(path).to_dict("records"))


def to_rows(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Porównywalna postać tekstowa; braki oznaczone jawnie (w pandas 3 NaN != NaN po astype(str))."""
    return df.astype(object).where(df.notna(), "∅").astype(str)


def merge(old: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Upsert po fixture_id. Zwraca (scalone, dodane, zaktualizowane)."""
    new_i = new.drop_duplicates("fixture_id", keep="last").set_index("fixture_id")
    if old.empty:
        out = new_i.reset_index()[db.COLUMNS]
        return out.sort_values(["date", "fixture_id"]).reset_index(drop=True), len(new_i), 0
    old_i = old.drop_duplicates("fixture_id", keep="last").set_index("fixture_id")
    merged = frame(new_i.combine_first(old_i).reset_index().to_dict("records")).set_index("fixture_id")
    added = int(len(new_i.index.difference(old_i.index)))
    common = new_i.index.intersection(old_i.index)
    cols = [c for c in db.COLUMNS if c != "fixture_id"]
    changed = (_norm(old_i.loc[common, cols]) != _norm(merged.loc[common, cols])).any(axis=1)
    out = merged.reset_index()[db.COLUMNS].sort_values(["date", "fixture_id"]).reset_index(drop=True)
    return out, added, int(changed.sum())


def save_matches(rows: list[dict], hist=None) -> dict:
    """Waliduje i scala ZAKOŃCZONE mecze do plików liga_sezon.csv. Zwraca statystyki."""
    hd = hdir(hist)
    rows = [dict(r) for r in rows if r.get("hg") is not None and r.get("ag") is not None]
    rows = apply_aliases(rows, load_aliases(hd))
    good, bad, fixed = validate_rows(rows)
    result = {"files": {}, "rejected": [(r.get("date"), r.get("home"), r.get("away"), why) for r, why in bad],
              "sanitized": fixed}
    if not good:
        return result
    df = frame(good)
    df["season"] = df["season"].fillna(pd.Series([season_of(d) for d in df["date"]], index=df.index)).astype("Int64")
    hd.mkdir(parents=True, exist_ok=True)
    for (lg, season), grp in df.groupby(["league", "season"]):
        path = hd / f"{lg}_{int(season)}.csv"
        out, added, updated = merge(read_file(path), grp)
        if added or updated or not path.exists():
            out.to_csv(path, index=False, lineterminator="\n")
        result["files"][path.name] = {"dodane": added, "zmienione": updated, "razem": len(out)}
    return result


def load_into_db(conn, hist=None, leagues: list[str] | None = None) -> int:
    """Wczytuje historię z CSV do SQLite (offline, szybko). Zwraca liczbę wczytanych wierszy."""
    hd, n = hdir(hist), 0
    if not hd.exists():
        return 0
    aliases = load_aliases(hd)
    for f in sorted(hd.glob("*.csv")):
        m = FILE_RE.match(f.name)
        if not m or (leagues and m["league"] not in leagues):
            continue
        rows = apply_aliases(to_rows(read_file(f)), aliases)
        db.upsert_matches(conn, rows)
        n += len(rows)
    return n


def export_from_db(conn, hist=None, leagues: list[str] | None = None, include_demo: bool = False) -> dict:
    """Jednorazowa migracja: zapisuje zakończone mecze z bazy SQLite do plików historii (bez sztucznej ligi DEMO)."""
    df = db.load_matches(conn)
    if leagues:
        df = df[df["league"].isin(leagues)]
    elif not include_demo:
        df = df[df["league"] != "DEMO"]
    df = df.copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return save_matches(to_rows(df), hist)


def status(hist=None) -> pd.DataFrame:
    rows = []
    for f in sorted(hdir(hist).glob("*.csv")):
        m = FILE_RE.match(f.name)
        if not m:
            continue
        d = read_file(f)
        rows.append({"liga": m["league"], "sezon": int(m["season"]), "mecze": len(d), "od": d["date"].min(),
                     "do": d["date"].max(), "HT_%": round(100 * d["hg_ht"].notna().mean()),
                     "kartki_%": round(100 * d["h_yellow"].notna().mean()),
                     "sot_%": round(100 * d["h_sot"].notna().mean()), "kursy_%": round(100 * d["o_home"].notna().mean())})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ aktualizacja ze źródła
def update_from_source(leagues: list[str], seasons: list[int] | None = None, hist=None, log=print) -> list[dict]:
    """Pobiera sezony z football-data.co.uk i scala do historii (domyślnie bieżący + poprzedni sezon)."""
    hd = hdir(hist)
    cur = season_of(date.today())
    seasons = seasons or [cur, cur - 1]
    out = []
    for lg in leagues:
        for y in seasons:
            try:
                if lg in NO_CSV:                       # np. Liga Mistrzów: tylko football-data.org
                    from . import fdorg
                    rows = fdorg.fetch_season(lg, y)
                else:
                    rows = csvdata.parse_csv(csvdata.download(lg, y), lg, y)
                res = save_matches(rows, hd)
            except Exception as e:  # noqa: BLE001 - brak sezonu / sieci nie przerywa reszty
                log(f"  {lg} {y}: błąd ({e})")
                continue
            for name, st in res["files"].items():
                log(f"  {name}: +{st['dodane']} nowych, ~{st['zmienione']} zmienionych (razem {st['razem']})"
                    + (f", odrzucono {len(res['rejected'])}" if res["rejected"] else ""))
                out.append({"liga": lg, "sezon": y, **st, "odrzucone": len(res["rejected"])})
                _log_update(hd, lg, y, st, len(res["rejected"]))
            for rej in res["rejected"][:5]:
                log(f"    odrzucony: {rej}")
    return out


def _log_update(hd: Path, lg: str, y: int, st: dict, rejected: int) -> None:
    hd.mkdir(parents=True, exist_ok=True)
    with open(hd / "UPDATES.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} | {lg} {y} | +{st['dodane']} ~{st['zmienione']} "
                f"razem={st['razem']} odrzucone={rejected}\n")


# ------------------------------------------------------------------ archiwum kursów
def archive_odds(rows: list[dict], hist=None, snapshot: str | None = None) -> int:
    """Dopisuje kursy nadchodzących meczów (1 wiersz na mecz na dzień). Zwraca liczbę nowych wierszy."""
    hd = hdir(hist) / "odds"
    snapshot = snapshot or date.today().isoformat()
    by_league: dict[str, list[dict]] = {}
    for r in rows:
        if any(_num(r.get(c)) for c in ("o_home", "o_over25")):
            by_league.setdefault(r["league"], []).append(r)
    added = 0
    for lg, rs in by_league.items():
        path = hd / f"{lg}.csv"
        old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=ODDS_COLS)
        seen = set(zip(old["snapshot"].astype(str), old["fixture_id"].astype(int))) if len(old) else set()
        new = [{"snapshot": snapshot, "fixture_id": int(r["fixture_id"]), "league": lg,
                "date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"), "home": r["home"], "away": r["away"],
                **{c: r.get(c) for c in REAL_COLS}}
               for r in rs if (snapshot, int(r["fixture_id"])) not in seen]
        if new:
            hd.mkdir(parents=True, exist_ok=True)
            out = pd.concat([old, pd.DataFrame(new)], ignore_index=True)[ODDS_COLS]
            out.to_csv(path, index=False, lineterminator="\n")
            added += len(new)
    return added
