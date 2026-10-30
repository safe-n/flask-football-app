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


def download(tour: str, year: int, timeout: int = 60) -> pd.DataFrame:
    """Pobiera rok; najpierw .xlsx, potem .xls (starsze lata)."""
    url = url_for(tour, year)
    errors = []
    for u in (url, url[:-1] if url.endswith(".xlsx") else url):
        try:
            r = requests.get(u, timeout=timeout, headers={"User-Agent": "tnpred"})
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


def load_history_dir(d: Path | None = None) -> pd.DataFrame:
    d = d or config.HISTORY_DIR
    files = sorted(Path(d).glob("*.csv")) if Path(d).exists() else []
    parts = [read_csv(f) for f in files if not f.name.startswith("DEMO")]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)


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
