"""Liga Europy (i inne rozgrywki bez darmowych CSV) z TheSportsDB - darmowe API v1 (klucz publiczny "123").

Ograniczenia darmowego API: brak wyników do przerwy, kartek i rożnych (model liczy tylko gole, bez rynków połówkowych z danych EL),
limit zapytań (~30/min), a lista sezonu bywa ucięta - dlatego łączymy kilka endpointów i deduplikujemy po idEvent.
Nic tu nie jest zgadywane po cichu: komenda `sportsdb-probe` pokazuje, co faktycznie zwróciło API.
"""
from __future__ import annotations

import time
import zlib
from datetime import date

import pandas as pd
import requests

from . import config

BASE = "https://www.thesportsdb.com/api/v1/json/{key}/"
LEAGUE_IDS = {"EL": 4481}                     # TheSportsDB: UEFA Europa League
FIRST_MONTH = 9                               # faza ligowa od września (eliminacje lipiec-sierpień pomijamy)
FINISHED = {"match finished", "ft", "finished", "full time"}
NOT_STARTED = {"not started", "ns", "scheduled", "time to be defined", "tbd", ""}
EXTRA = {"aet", "after extra time", "pen", "after penalty", "penalties", "ap"}   # wynik po 90 min nieznany -> pomijamy


class SportsDbError(RuntimeError):
    pass


def enabled(league: str) -> bool:
    return league in LEAGUE_IDS


def _get(path: str, params: dict | None = None) -> list[dict]:
    url = BASE.format(key=config.SPORTSDB_KEY) + path
    for attempt in range(3):
        r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "fbpred"})
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise SportsDbError(f"TheSportsDB HTTP {r.status_code} dla {path}")
        try:
            data = r.json()
        except ValueError as e:
            raise SportsDbError(f"TheSportsDB zwróciło nie-JSON dla {path}") from e
        return (data or {}).get("events") or []
    raise SportsDbError(f"TheSportsDB: limit zapytań ({path})")


def season_label(year: int) -> str:
    return f"{year}-{year + 1}"


def kickoff_of(e: dict) -> str | None:
    """Godzina startu w UTC: strTimestamp ('2026-09-24T19:45:00'), a w razie braku dateEvent + strTime."""
    ts = str(e.get("strTimestamp") or "")
    if len(ts) >= 16 and "T" in ts:
        return ts[:16].replace("T", " ")
    d, t = str(e.get("dateEvent") or ""), str(e.get("strTime") or "")
    return f"{d} {t[:5]}" if len(d) == 10 and len(t) >= 5 and t[:5] != "00:00" else None


def parse_event(e: dict, league: str, season: int) -> dict | None:
    """Zdarzenie API -> wiersz bazy; None, gdy nie umiemy go uczciwie wykorzystać (eliminacje, dogrywka, przełożony...)."""
    lname = str(e.get("strLeague") or "").lower()
    if lname and ("europa league" not in lname or "conference" in lname):       # zabezpieczenie przed pomyłką id ligi
        return None
    day = str(e.get("dateEvent") or "")[:10]
    home, away = (e.get("strHomeTeam") or "").strip(), (e.get("strAwayTeam") or "").strip()
    if len(day) != 10 or not home or not away:
        return None
    if day < f"{season}-{FIRST_MONTH:02d}-01":
        return None
    if str(e.get("strPostponed") or "no").lower() == "yes":
        return None
    status = str(e.get("strStatus") or "").strip().lower()
    if status in EXTRA:
        return None
    hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
    has_score = hs not in (None, "") and as_ not in (None, "")
    if status in FINISHED and has_score:
        st, hg, ag = "FT", int(hs), int(as_)
    elif status in NOT_STARTED and not has_score:
        st, hg, ag = "NS", None, None
    else:
        return None                          # trwa, przerwany, niespójny
    fid = zlib.crc32(f"{league}|{day}|{home}|{away}".encode()) & 0x7FFFFFFF
    return dict(fixture_id=fid, league=league, season=season, date=day, home=home, away=away, status=st,
                hg=hg, ag=ag, kickoff=kickoff_of(e))


ROUND_PAUSE = 2.2                              # darmowy limit ~30 zapytań/min
EXTRA_ROUNDS = (16, 32, 125, 150, 200)         # numeracja TheSportsDB dla fazy pucharowej bywa nietypowa


def fetch_events(league: str, season: int, rounds: bool = True) -> list[dict]:
    """Surowe zdarzenia sezonu. Darmowe API ucina listę sezonu do 15 zdarzeń, więc pobieramy kolejka po kolejce
    (+ ostatnie/następne) i deduplikujemy po idEvent."""
    lid, label = LEAGUE_IDS[league], season_label(season)
    ev = {str(e.get("idEvent")): e for e in _get("eventsseason.php", {"id": lid, "s": label})}
    if rounds:
        empty = 0
        for r in list(range(1, 15)) + list(EXTRA_ROUNDS):
            if r < 15 and empty >= 3:                  # 3 puste kolejki z rzędu: reszta numerów ligowych pusta, idziemy do pucharowych
                continue
            time.sleep(ROUND_PAUSE)
            got = _get("eventsround.php", {"id": lid, "r": r, "s": label})
            empty = empty + 1 if not got else 0
            for e in got:
                ev.setdefault(str(e.get("idEvent")), e)
    if season == (date.today().year if date.today().month >= 7 else date.today().year - 1):
        for path in ("eventspastleague.php", "eventsnextleague.php"):
            try:
                for e in _get(path, {"id": lid}):
                    ev.setdefault(str(e.get("idEvent")), e)
            except SportsDbError:
                pass
    return list(ev.values())


def fetch_season(league: str, season: int) -> list[dict]:
    rows = [parse_event(e, league, season) for e in fetch_events(league, season)]
    out = {r["fixture_id"]: r for r in rows if r}
    return list(out.values())


def probe(league: str = "EL", season: int | None = None, out=print) -> None:
    """Co faktycznie zwraca API: nazwy lig, liczby zdarzeń na kolejkę, statusy, daty - do jednorazowej weryfikacji."""
    season = season or (date.today().year if date.today().month >= 7 else date.today().year - 1)
    lid, label = LEAGUE_IDS[league], season_label(season)
    out(f"TheSportsDB, liga {league} (id {lid}), sezon {label}, klucz {'publiczny 123' if config.SPORTSDB_KEY == '123' else 'własny'}")
    seen: dict[str, dict] = {}
    for name, path, params in (("sezon", "eventsseason.php", {"id": lid, "s": label}), ("ostatnie", "eventspastleague.php", {"id": lid}),
                               ("następne", "eventsnextleague.php", {"id": lid})):
        try:
            got = _get(path, params)
        except Exception as e:  # noqa: BLE001
            out(f"  {name}: BŁĄD {e}")
            continue
        out(f"  {name}: {len(got)} zdarzeń; liga w danych: {sorted({str(x.get('strLeague')) for x in got})}")
        for x in got:
            seen.setdefault(str(x.get("idEvent")), x)
    out("  kolejki (liczba zdarzeń | daty | statusy | liga):")
    empty = 0
    for r in list(range(1, 15)) + list(EXTRA_ROUNDS):
        if r < 15 and empty >= 3:
            continue
        time.sleep(ROUND_PAUSE)
        try:
            got = _get("eventsround.php", {"id": lid, "r": r, "s": label})
        except Exception as e:  # noqa: BLE001
            out(f"    r={r}: BŁĄD {e}")
            continue
        empty = empty + 1 if not got else 0
        if got:
            days = sorted(str(x.get("dateEvent")) for x in got)
            st: dict[str, int] = {}
            for x in got:
                st[str(x.get("strStatus"))] = st.get(str(x.get("strStatus")), 0) + 1
            out(f"    r={r}: {len(got)} | {days[0]} .. {days[-1]} | {st} | {sorted({str(x.get('strLeague')) for x in got})}")
            late = [x for x in got if str(x.get("dateEvent")) >= f"{season}-09-01"][:2]
            for x in late:
                out(f"        {x.get('dateEvent')} ts={x.get('strTimestamp')} {x.get('strHomeTeam')} {x.get('intHomeScore')}-{x.get('intAwayScore')} {x.get('strAwayTeam')} [{x.get('strStatus')}]")
        for x in got:
            seen.setdefault(str(x.get("idEvent")), x)
    rows = [parse_event(e, league, season) for e in seen.values()]
    rows = [r for r in rows if r]
    fin = [r for r in rows if r["status"] == "FT"]
    out(f"Po filtrach (od {season}-{FIRST_MONTH:02d}-01, tylko Europa League, bez dogrywek): {len(rows)} meczów, w tym {len(fin)} z wynikiem, "
        f"{len(rows) - len(fin)} nadchodzących, {sum(1 for r in rows if r.get('kickoff'))} z godziną. "
        f"Drużyn: {len({r['home'] for r in rows} | {r['away'] for r in rows})}.")
