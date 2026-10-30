"""tennis-data.co.uk: wyniki ATP/WTA po setach + kursy (Pinnacle, Bet365, średnia, maks.). Darmowe pliki XLSX, 1 plik = rok.

Dane są aktualizowane przez autora strony zwykle co kilka dni - to źródło historii, nie wyników na żywo.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import config
from .elo import surface_of

COLS = ["date", "tour", "tournament", "location", "series", "court", "surface", "round", "best_of",
        "winner", "loser", "wrank", "lrank", "w1", "l1", "w2", "l2", "w3", "l3", "w4", "l4", "w5", "l5",
        "wsets", "lsets", "comment", "psw", "psl", "b365w", "b365l", "avgw", "avgl", "maxw", "maxl"]
_MAP = {"Date": "date", "Tournament": "tournament", "Location": "location", "Series": "series", "Tier": "series",
        "Court": "court", "Surface": "surface", "Round": "round", "Best of": "best_of", "Winner": "winner", "Loser": "loser",
        "WRank": "wrank", "LRank": "lrank", "Wsets": "wsets", "Lsets": "lsets", "Comment": "comment",
        "PSW": "psw", "PSL": "psl", "B365W": "b365w", "B365L": "b365l", "AvgW": "avgw", "AvgL": "avgl",
        "MaxW": "maxw", "MaxL": "maxl"}
for _i in range(1, 6):
    _MAP[f"W{_i}"] = f"w{_i}"
    _MAP[f"L{_i}"] = f"l{_i}"
NUM = ["best_of", "wrank", "lrank", "wsets", "lsets", "psw", "psl", "b365w", "b365l", "avgw", "avgl", "maxw", "maxl"] + \
      [f"{s}{i}" for i in range(1, 6) for s in "wl"]


def normalize(raw: pd.DataFrame, tour: str) -> pd.DataFrame:
    df = raw.rename(columns={c: _MAP.get(str(c).strip(), str(c).strip()) for c in raw.columns})
    df["tour"] = tour
    for c in COLS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[COLS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=False)
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("winner", "loser", "tournament", "location", "series", "court", "round", "comment"):
        df[c] = df[c].astype("string").str.strip()
    df["surface"] = df["surface"].map(surface_of)
    df["best_of"] = df["best_of"].fillna(3).astype(int)
    df["comment"] = df["comment"].fillna("Completed")
    df = df.dropna(subset=["date", "winner", "loser"])
    df = df[(df.winner != "") & (df.loser != "")]
    return df.reset_index(drop=True)


def url_for(tour: str, year: int) -> str:
    tpl = config.TDATA_WTA_URL if tour == "WTA" else config.TDATA_ATP_URL
    return tpl.format(year=year)


UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "*/*"}


def download(tour: str, year: int, timeout: int = 60) -> pd.DataFrame:
    """Pobiera rok; najpierw .xlsx, potem .xls (starsze lata)."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise RuntimeError("brak biblioteki openpyxl - dopisz linię 'openpyxl>=3.1' do requirements.txt") from None
    url = url_for(tour, year)
    errors = []
    for u in (url, url[:-1] if url.endswith(".xlsx") else url):
        try:
            r = requests.get(u, timeout=timeout, headers=UA)
            if r.status_code != 200 or len(r.content) < 1000:
                errors.append(f"{u}: HTTP {r.status_code}")
                continue
            raw = pd.read_excel(io.BytesIO(r.content))
            return normalize(raw, tour)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{u}: {e}")
    raise RuntimeError("; ".join(errors))


def history_file(tour: str, year: int) -> Path:
    return config.HISTORY_DIR / f"{tour}_{year}.csv"


def save_history(df: pd.DataFrame, tour: str, year: int) -> Path:
    p = history_file(tour, year)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(p, index=False)
    return p


def read_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    tour = str(df["tour"].iloc[0]) if "tour" in df.columns and len(df) else Path(path).stem.split("_")[0]
    return normalize(df.rename(columns=str), tour) if "Winner" in df.columns else _from_norm(df)


def _from_norm(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[COLS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["best_of"] = df["best_of"].fillna(3).astype(int)
    df["surface"] = df["surface"].map(surface_of)
    df["comment"] = df["comment"].fillna("Completed")
    for c in ("winner", "loser", "tournament", "round", "comment", "tour", "series"):
        df[c] = df[c].astype("string")
    return df.dropna(subset=["date", "winner", "loser"]).reset_index(drop=True)


def read_xlsx(path, tour: str) -> pd.DataFrame:
    """Plik pobrany ręcznie z tennis-data.co.uk (bez zmiany nazwy), np. tennis_history/WTA/2025.xlsx."""
    return normalize(pd.read_excel(path), tour)


def load_history_dir(d: Path | None = None, report: list | None = None) -> pd.DataFrame:
    """CSV w tennis_history/ + ręcznie pobrane XLSX w tennis_history/ATP/ i tennis_history/WTA/ (nazwy plików bez zmian)."""
    d = Path(d or config.HISTORY_DIR)
    parts = []
    if d.exists():
        for f in sorted(d.glob("*.csv")):
            if not f.name.startswith("DEMO"):
                parts.append(read_csv(f))
        for tour in ("ATP", "WTA"):
            for f in sorted((d / tour).glob("*.xls*")) if (d / tour).exists() else []:
                try:
                    x = read_xlsx(f, tour)
                    parts.append(x)
                    if report is not None:
                        report.append(f"{tour}/{f.name}: {len(x)} meczów")
                except Exception as e:  # noqa: BLE001
                    if report is not None:
                        report.append(f"{tour}/{f.name}: BŁĄD {e}")
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts, ignore_index=True)
    return df.drop_duplicates(subset=["tour", "date", "winner", "loser", "tournament"], keep="last").reset_index(drop=True)


# ---------------------------------------------------------------- zapasowe źródło: Jeff Sackmann (GitHub, bez kursów)
SACK_URL = {"ATP": "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv",
            "WTA": "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv"}
_ROUND = {"R128": ("1st Round", 0), "R64": ("2nd Round", 2), "R32": ("3rd Round", 4), "R16": ("4th Round", 5),
          "QF": ("Quarterfinals", 6), "SF": ("Semifinals", 7), "F": ("The Final", 8), "RR": ("Round Robin", 3),
          "BR": ("Bronze", 7), "ER": ("1st Round", 0)}
_LEVEL = {"G": "Grand Slam", "M": "Masters 1000", "A": "ATP", "F": "Masters Cup", "P": "Premier", "PM": "Premier Mandatory",
          "I": "International", "O": "Olympics"}


def from_sackmann(raw: pd.DataFrame, tour: str) -> pd.DataFrame:
    from .names import to_td
    raw = raw[~raw.get("tourney_level", pd.Series("", index=raw.index)).astype(str).isin(["D", "C"])]
    rows = []
    for r in raw.to_dict("records"):
        score = str(r.get("score") or "")
        comment = "Completed"
        up = score.upper()
        if "W/O" in up or "WALK" in up:
            comment = "Walkover"
        elif "RET" in up or "ABD" in up or "DEF" in up:
            comment = "Retired"
        sets = []
        for tok in score.split():
            tok = tok.split("(")[0]
            if "-" in tok:
                a, _, b = tok.partition("-")
                if a.isdigit() and b.isdigit():
                    sets.append((int(a), int(b)))
        rname, off = _ROUND.get(str(r.get("round")), ("2nd Round", 2))
        try:
            d = pd.Timestamp(str(int(r["tourney_date"]))) + pd.Timedelta(days=off)
        except (TypeError, ValueError, KeyError):
            continue
        row = {"date": d, "tournament": r.get("tourney_name"), "location": r.get("tourney_name"),
               "series": _LEVEL.get(str(r.get("tourney_level")), str(r.get("tourney_level"))), "court": "",
               "surface": r.get("surface"), "round": rname, "best_of": r.get("best_of") or 3,
               "winner": to_td(r.get("winner_name")), "loser": to_td(r.get("loser_name")),
               "wrank": r.get("winner_rank"), "lrank": r.get("loser_rank"), "comment": comment,
               "wsets": sum(a > b for a, b in sets), "lsets": sum(b > a for a, b in sets)}
        for i, (a, b) in enumerate(sets[:5], 1):
            row[f"w{i}"], row[f"l{i}"] = a, b
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["tour"] = tour
    return _from_norm(df)


def download_sackmann(tour: str, year: int, timeout: int = 60) -> pd.DataFrame:
    u = SACK_URL[tour].format(year=year)
    r = requests.get(u, timeout=timeout, headers=UA)
    if r.status_code != 200:
        raise RuntimeError(f"{u}: HTTP {r.status_code}")
    return from_sackmann(pd.read_csv(io.StringIO(r.text)), tour)


def download_any(tour: str, year: int) -> tuple[pd.DataFrame, str]:
    """Najpierw tennis-data.co.uk (z kursami), gdy blokuje - Sackmann (GitHub, bez kursów)."""
    try:
        return download(tour, year), "tennis-data.co.uk"
    except Exception as e1:  # noqa: BLE001
        try:
            df = download_sackmann(tour, year)
            if df.empty:
                raise RuntimeError("pusty plik")
            return df, "GitHub JeffSackmann (bez kursów)"
        except Exception as e2:  # noqa: BLE001
            raise RuntimeError(f"tennis-data: {str(e1)[:160]} | Sackmann: {str(e2)[:160]}") from None


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Gemy, tie-breaki, czy mecz ukończony. Sety bez wyniku (NaN) pomijane."""
    df = df.copy()
    gw = sum(df[f"w{i}"].fillna(0) for i in range(1, 6))
    gl = sum(df[f"l{i}"].fillna(0) for i in range(1, 6))
    df["games_w"], df["games_l"] = gw, gl
    df["total_games"] = gw + gl
    tb = 0
    for i in range(1, 6):
        a, b = df[f"w{i}"], df[f"l{i}"]
        tb = tb + (((a == 7) & (b == 6)) | ((a == 6) & (b == 7))).astype(int)
    df["n_tb"] = tb
    c = df["comment"].fillna("Completed").astype(str).str.lower()
    df["completed"] = c.str.startswith("compl")
    df["retired"] = c.str.startswith("ret") | c.str.startswith("walk") | c.str.startswith("w/o") | c.str.startswith("disq")
    df["set1_w"] = df["w1"] > df["l1"]
    return df


def match_id(tour, date, a, b) -> str:
    x, y = sorted([str(a), str(b)])
    return f"{tour}|{pd.Timestamp(date).strftime('%Y-%m-%d')}|{x}|{y}"
