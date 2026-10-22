"""Klient football-data.org v4 (darmowy token): Liga Mistrzów + zapasowe źródło terminarza lig krajowych.

Darmowy plan: 10 zapytań/min, wyniki + terminarze (z wynikiem do przerwy), BEZ kursów i BEZ statystyk
(kartki/rożne) - dla Ligi Mistrzów model liczy więc 1X2, gole, BTTS i remis do przerwy, ale nie kartki/rożne.
Token: https://www.football-data.org/client/register -> zmienna FOOTBALL_DATA_ORG_TOKEN (sekret, nigdy w kodzie).
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Callable

import requests

from . import config
from .leagues import fdorg_code

BASE = "https://api.football-data.org/v4"
ID_OFFSET = 5_000_000_000      # żeby id z tego źródła nie kolidowały z crc32 z football-data.co.uk
NS_STATUSES = {"SCHEDULED", "TIMED"}


class FdOrgError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.FDORG_TOKEN)


def supports(league: str) -> bool:
    return fdorg_code(league) is not None


def _get(path: str, params: dict | None = None, token: str | None = None) -> dict:
    token = token or config.FDORG_TOKEN
    if not token:
        raise FdOrgError("brak FOOTBALL_DATA_ORG_TOKEN (darmowy token: football-data.org/client/register)")
    r = None
    for attempt in range(2):
        r = requests.get(BASE + path, headers={"X-Auth-Token": token}, params=params, timeout=30)
        if r.status_code == 429 and attempt == 0:
            time.sleep(61)  # limit na minutę
            continue
        break
    if r.status_code in (401, 403):
        raise FdOrgError(f"{r.status_code}: token nieprawidłowy albo darmowy plan nie obejmuje tych danych")
    r.raise_for_status()
    time.sleep(config.FDORG_PAUSE)
    return r.json()


def _team(t: dict, resolver: Callable | None) -> str:
    short, full = t.get("shortName") or "", t.get("name") or ""
    if resolver:
        hit = resolver([x for x in (short, full, t.get("tla")) if x])
        if hit:
            return hit
    return short or full


def parse_match(m: dict, league: str, season: int, resolver: Callable | None = None) -> dict | None:
    """Mecz z API -> wiersz bazy. None dla meczów, których nie umiemy uczciwie wykorzystać."""
    status = m.get("status")
    if status == "FINISHED":
        st = "FT"
    elif status in NS_STATUSES:
        st = "NS"
    else:
        return None  # w trakcie, przełożony, odwołany...
    score = m.get("score") or {}
    hg = ag = hg_ht = ag_ht = None
    if st == "FT":
        dur = score.get("duration", "REGULAR")
        ft = score.get("fullTime") if dur == "REGULAR" else score.get("regularTime")
        if not ft or ft.get("home") is None or ft.get("away") is None:
            return None  # dogrywka/karne bez wyniku z 90 minut - pomijamy zamiast zgadywać
        hg, ag = ft["home"], ft["away"]
        ht = score.get("halfTime") or {}
        hg_ht, ag_ht = ht.get("home"), ht.get("away")
    refs = m.get("referees") or []
    ref = next((r.get("name") for r in refs if r.get("type") in (None, "REFEREE") and r.get("name")), None)
    return dict(fixture_id=ID_OFFSET + int(m["id"]), league=league, season=season, date=str(m["utcDate"])[:10],
                home=_team(m["homeTeam"], resolver), away=_team(m["awayTeam"], resolver), referee=ref, status=st,
                hg=hg, ag=ag, hg_ht=hg_ht, ag_ht=ag_ht)


def fetch_season(league: str, season: int, resolver: Callable | None = None, token: str | None = None) -> list[dict]:
    """Wszystkie mecze sezonu (zakończone i zaplanowane) - 1 zapytanie."""
    code = fdorg_code(league)
    if not code:
        raise FdOrgError(f"liga {league} nie jest dostępna w football-data.org (darmowy plan)")
    data = _get(f"/competitions/{code}/matches", {"season": season}, token)
    rows = [parse_match(m, league, season, resolver) for m in data.get("matches", [])]
    return [r for r in rows if r]


def upcoming(league: str, resolver: Callable | None = None, days: int | None = None,
             token: str | None = None) -> list[dict]:
    """Nadchodzące mecze (cały pozostały terminarz albo najbliższe `days` dni) - 1 zapytanie."""
    code = fdorg_code(league)
    if not code:
        raise FdOrgError(f"liga {league} nie jest dostępna w football-data.org (darmowy plan)")
    params = {"status": "SCHEDULED,TIMED"}
    if days:
        params.update(dateFrom=date.today().isoformat(), dateTo=(date.today() + timedelta(days=days)).isoformat())
    data = _get(f"/competitions/{code}/matches", params, token)
    season = None
    out = []
    for m in data.get("matches", []):
        season = int(str((m.get("season") or {}).get("startDate", ""))[:4] or 0) or (date.today().year if date.today().month >= 7 else date.today().year - 1)
        row = parse_match(m, league, season, resolver)
        if row:
            out.append(row)
    return out
