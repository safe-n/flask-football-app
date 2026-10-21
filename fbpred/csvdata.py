"""Import darmowych danych z football-data.co.uk (wyniki, połowy, kartki, rożne, sędziowie, kursy).

Kody lig: E0 (Premier League), E1 (Championship), D1 (Bundesliga), SP1 (La Liga), I1 (Serie A),
F1 (Ligue 1), N1 (Eredivisie), P1 (Portugalia), SC0, T1, G1, B1.
Sezon = rok startu, np. 2024 -> sezon 2024/25 (plik mmz4281/2425/E0.csv).
UWAGA: nazwy drużyn z tego źródła nie pasują do API-Football - nie mieszaj źródeł w jednej lidze.
"""
from __future__ import annotations

import io
import zlib

import pandas as pd
import requests

URL = "https://www.football-data.co.uk/mmz4281/{code}/{league}.csv"

# preferencja: kursy zamknięcia Pinnacle > Bet365 zamknięcia > Bet365 > średnia rynku
ODDS_1X2 = [("PSCH", "PSCD", "PSCA"), ("B365CH", "B365CD", "B365CA"), ("AvgCH", "AvgCD", "AvgCA"),
            ("PSH", "PSD", "PSA"), ("B365H", "B365D", "B365A"), ("AvgH", "AvgD", "AvgA")]
ODDS_OU = [("PC>2.5", "PC<2.5"), ("B365C>2.5", "B365C<2.5"), ("AvgC>2.5", "AvgC<2.5"),
           ("P>2.5", "P<2.5"), ("B365>2.5", "B365<2.5"), ("Avg>2.5", "Avg<2.5")]


def season_code(year: int) -> str:
    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def download(league: str, year: int, timeout: int = 30) -> str:
    r = requests.get(URL.format(code=season_code(year), league=league), timeout=timeout)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")


def _num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _int(v):
    f = _num(v)
    return None if f is None else int(f)


def _first(row, groups):
    for g in groups:
        vals = [_num(row.get(c)) for c in g]
        if all(v is not None and v > 1.0 for v in vals):
            return vals
    return [None] * len(groups[0])


FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


def download_fixtures(timeout: int = 30) -> str:
    r = requests.get(FIXTURES_URL, timeout=timeout)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")


def parse_csv(text: str, league: str, year: int | None = None, only_div: bool = False) -> list[dict]:
    """year=None -> sezon wyliczany z daty (lipiec+ = nowy sezon). only_div: filtruj kolumnę Div == league."""
    df = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
    if only_div and "Div" in df:
        df = df[df["Div"] == league]
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "Date"])
    df["_d"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["_d"])
    rows = []
    for r in df.to_dict("records"):
        date = r["_d"].strftime("%Y-%m-%d")
        yr = year if year is not None else (r["_d"].year if r["_d"].month >= 7 else r["_d"].year - 1)
        h, a = str(r["HomeTeam"]).strip(), str(r["AwayTeam"]).strip()
        o = _first(r, ODDS_1X2)
        ou = _first(r, ODDS_OU)
        fid = zlib.crc32(f"{league}|{date}|{h}|{a}".encode()) & 0x7FFFFFFF
        has_stats = _int(r.get("HY")) is not None
        rows.append(dict(
            fixture_id=fid, league=league, season=yr, date=date, home=h, away=a,
            referee=(str(r["Referee"]).strip() if pd.notna(r.get("Referee")) else None),
            status="FT" if _int(r.get("FTHG")) is not None else "NS",
            hg=_int(r.get("FTHG")), ag=_int(r.get("FTAG")),
            hg_ht=_int(r.get("HTHG")), ag_ht=_int(r.get("HTAG")),
            h_shots=_int(r.get("HS")), a_shots=_int(r.get("AS")),
            h_sot=_int(r.get("HST")), a_sot=_int(r.get("AST")),
            h_corners=_int(r.get("HC")), a_corners=_int(r.get("AC")),
            h_yellow=_int(r.get("HY")), a_yellow=_int(r.get("AY")),
            h_red=_int(r.get("HR")), a_red=_int(r.get("AR")),
            stats_done=1 if has_stats else 0,
            o_home=o[0], o_draw=o[1], o_away=o[2], o_over25=ou[0], o_under25=ou[1],
        ))
    return rows
