"""Router źródeł dla lig bez CSV (NO_CSV): Liga Mistrzów -> football-data.org, Liga Europy -> TheSportsDB."""
from __future__ import annotations

from . import fdorg, sportsdb


def enabled(league: str) -> bool:
    return sportsdb.enabled(league) or fdorg.enabled()


def why_disabled(league: str) -> str:
    return "brak tokenu FOOTBALL_DATA_ORG_TOKEN - brak odświeżania"


def fetch_season(league: str, season: int) -> list[dict]:
    if sportsdb.enabled(league):
        return sportsdb.fetch_season(league, season)
    return fdorg.fetch_season(league, season)


def source_name(league: str) -> str:
    return "TheSportsDB" if sportsdb.enabled(league) else "football-data.org"


def partial() -> bool:
    """True, gdy ostatnie pobranie z TheSportsDB urwał limit zapytań (wynik niepełny - uruchom ponownie za minutę)."""
    return sportsdb.PARTIAL["flag"]
