"""Katalog lig: kod football-data.co.uk -> nazwa, kraj, kod w football-data.org (jeśli darmowy plan go obejmuje)."""
from __future__ import annotations

CATALOG: dict[str, tuple[str, str, str | None]] = {
    # kod:  (nazwa,               kraj,  kod football-data.org)
    "E0": ("Premier League", "ENG", "PL"),
    "E1": ("Championship", "ENG", "ELC"),
    "D1": ("Bundesliga", "GER", "BL1"),
    "D2": ("2. Bundesliga", "GER", None),
    "SP1": ("La Liga", "ESP", "PD"),
    "SP2": ("La Liga 2", "ESP", None),
    "I1": ("Serie A", "ITA", "SA"),
    "I2": ("Serie B", "ITA", None),
    "F1": ("Ligue 1", "FRA", "FL1"),
    "F2": ("Ligue 2", "FRA", None),
    "N1": ("Eredivisie", "NED", "DED"),
    "B1": ("Jupiler Pro League", "BEL", None),
    "P1": ("Primeira Liga", "POR", "PPL"),
    "T1": ("Süper Lig", "TUR", None),
    "G1": ("Super League", "GRE", None),
    "SC0": ("Scottish Premiership", "SCO", None),
    "CL": ("Liga Mistrzów", "EUR", "CL"),
}

# ligi, których NIE ma w football-data.co.uk (dane tylko z football-data.org, wymaga darmowego tokenu)
NO_CSV = {"CL"}


def name(code: str) -> str:
    return CATALOG[code][0] if code in CATALOG else code


def label(code: str) -> str:
    return f"{code} · {CATALOG[code][0]}" if code in CATALOG else code


def fdorg_code(code: str) -> str | None:
    return CATALOG[code][2] if code in CATALOG else None


def season_label(season) -> str:
    try:
        y = int(season)
    except (TypeError, ValueError):
        return str(season)
    return f"{y}/{str(y + 1)[-2:]}"
