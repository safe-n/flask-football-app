"""Dostępność zawodników (kontuzje, zawieszenia) i składy z API-Football - tylko informacja pomocnicza.

Nie zmienia prognozy: pokazuje, kogo brakuje, żebyś mógł świadomie użyć korekty xG na stronie Mecz.
Oszczędność limitu: kontuzje to JEDNO zapytanie na ligę i dzień (cache 3 h, wspólne dla wszystkich meczów ligi tego dnia),
dopasowanie meczu do API - jedno zapytanie na ligę i dzień (cache 6 h), składy - zapytanie na mecz i tylko na życzenie.
Dzienny limit własny (AVAIL_DAILY_CAP) chroni resztę darmowych 100 zapytań.
"""
from __future__ import annotations

import json
from datetime import date as _date
from pathlib import Path

from . import config, names
from .fetch import ApiClient, QuotaExhausted

LEAGUE_IDS = {"E0": 39, "E1": 40, "D1": 78, "D2": 79, "SP1": 140, "SP2": 141, "I1": 135, "I2": 136, "F1": 61, "F2": 62,
              "N1": 88, "B1": 144, "P1": 94, "T1": 203, "G1": 197, "SC0": 179, "CL": 2}
TTL_FIXTURES, TTL_INJURIES, TTL_LINEUPS = 6 * 3600, 3 * 3600, 20 * 60


def enabled() -> bool:
    return bool(config.API_KEY) and config.AVAIL_ENABLED


def season_of(day: str) -> int:
    d = _date.fromisoformat(day[:10])
    return d.year if d.month >= 7 else d.year - 1


class Budget:
    """Dzienny licznik zapytań zużytych przez ten moduł (plik w katalogu cache)."""

    def __init__(self, cache_dir: Path | None = None, cap: int | None = None):
        self.file = Path(cache_dir or config.CACHE_DIR) / "avail_budget.json"
        self.cap = config.AVAIL_DAILY_CAP if cap is None else cap

    def used(self) -> int:
        try:
            d = json.loads(self.file.read_text())
            return int(d["n"]) if d.get("day") == _date.today().isoformat() else 0
        except Exception:  # noqa: BLE001
            return 0

    def add(self, n: int) -> None:
        if n:
            try:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                self.file.write_text(json.dumps({"day": _date.today().isoformat(), "n": self.used() + n}))
            except OSError:
                pass

    def left(self) -> int:
        return max(self.cap - self.used(), 0)


def _call(client, budget: Budget, path: str, params: dict, ttl: int):
    """Wywołanie z cache i limitem dziennym; z cache nic nie kosztuje."""
    if not client.cached(path, params, ttl) and budget.left() <= 0:
        raise QuotaExhausted(f"dzienny limit {budget.cap} zapytań dla kontuzji/składów wyczerpany (AVAIL_DAILY_CAP)")
    before = client.used
    try:
        return client.get(path, params, ttl=ttl)
    finally:
        budget.add(client.used - before)


def _side(team_name: str, home: str, away: str) -> str | None:
    r = names.resolve(team_name, [home, away])
    return "home" if r == home else "away" if r == away else None


def find_fixture(client, budget, league: str, home: str, away: str, day: str) -> int | None:
    resp = _call(client, budget, "/fixtures", {"league": LEAGUE_IDS[league], "season": season_of(day), "date": day[:10]}, TTL_FIXTURES)
    for it in resp:
        t = it.get("teams", {})
        if _side(t.get("home", {}).get("name", ""), home, away) == "home" and \
           _side(t.get("away", {}).get("name", ""), home, away) == "away":
            return it["fixture"]["id"]
    return None


def parse_injuries(resp: list, fixture_id: int, home: str, away: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"home": [], "away": []}
    for it in resp:
        if it.get("fixture", {}).get("id") != fixture_id:
            continue
        side = _side(it.get("team", {}).get("name", ""), home, away)
        pl = it.get("player", {})
        if side and pl.get("name"):
            out[side].append({"gracz": pl["name"], "status": pl.get("type") or "", "powod": pl.get("reason") or ""})
    return out


def parse_lineups(resp: list, home: str, away: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in resp:
        side = _side(it.get("team", {}).get("name", ""), home, away)
        if side:
            out[side] = {"formacja": it.get("formation") or "", "trener": (it.get("coach") or {}).get("name") or "",
                         "pierwsza_jedenastka": [p["player"]["name"] for p in it.get("startXI", []) if p.get("player")],
                         "rezerwa": [p["player"]["name"] for p in it.get("substitutes", []) if p.get("player")]}
    return out


def for_match(league: str, home: str, away: str, day: str, with_lineups: bool = False, client=None, budget: Budget | None = None) -> dict:
    """Kontuzje (+ opcjonalnie składy) dla jednego meczu. Nigdy nie rzuca wyjątku - błędy trafiają do `uwagi`."""
    res: dict = {"ok": False, "uwagi": [], "kontuzje": {"home": [], "away": []}, "sklady": None, "fixture_id": None}
    if league not in LEAGUE_IDS:
        res["uwagi"].append(f"Liga {league} nie ma przypisanego id w API-Football.")
        return res
    try:
        client = client or ApiClient()
        budget = budget or Budget()
        fid = find_fixture(client, budget, league, home, away, day)
        if fid is None:
            res["uwagi"].append("Nie znalazłem tego meczu w API-Football (inna nazwa drużyn albo inna data).")
            return res
        res["fixture_id"] = fid
        inj = _call(client, budget, "/injuries", {"league": LEAGUE_IDS[league], "season": season_of(day), "date": day[:10]}, TTL_INJURIES)
        res["kontuzje"] = parse_injuries(inj, fid, home, away)
        res["ok"] = True
        if with_lineups:
            lu = parse_lineups(_call(client, budget, "/lineups", {"fixture": fid}, TTL_LINEUPS), home, away)
            res["sklady"] = lu
            if not lu:
                res["uwagi"].append("Składy jeszcze nie są opublikowane (zwykle ok. godziny przed meczem).")
    except QuotaExhausted as e:
        res["uwagi"].append(str(e))
    except Exception as e:  # noqa: BLE001 - brak sieci, zły klucz itp. nie mogą psuć strony meczu
        res["uwagi"].append(f"API-Football: {e}")
    res["limit_dzis"] = f"{(budget.used() if budget else 0)}/{config.AVAIL_DAILY_CAP}"
    return res


# ------------------------------------------------------------------ diagnostyka (CLI: avail-probe)
def probe(league: str, client=None, out=print) -> None:
    """Sprawdza klucz i pokazuje, jakie rynki kursów i jakie dane faktycznie zwraca konto - do kalibracji kolejnych funkcji."""
    client = client or ApiClient()
    st = client.get("/status", {}, ttl=0)
    if isinstance(st, dict):
        req = st.get("requests", {})
        out(f"konto: plan={st.get('subscription', {}).get('plan')}, zapytań dziś: {req.get('current')}/{req.get('limit_day')}")
    bets = client.get("/odds/bets", {}, ttl=24 * 3600)
    kw = ("half", "1st", "2nd", "first", "second", "draw", "both teams", "double")
    out(f"rynków kursów w API: {len(bets)}; związane z połowami/remisem/BTTS:")
    for b in bets:
        if any(k in b["name"].lower() for k in kw):
            out(f"   {b['id']:>4}  {b['name']}")
    lid = LEAGUE_IDS.get(league)
    if not lid:
        out(f"liga {league} bez id w API-Football")
        return
    season = season_of(_date.today().isoformat())
    nxt = client.get("/fixtures", {"league": lid, "season": season, "next": 3}, ttl=3600)
    out(f"najbliższe mecze {league}: " + "; ".join(f"{i['teams']['home']['name']}–{i['teams']['away']['name']} ({i['fixture']['date'][:10]})" for i in nxt))
    if nxt:
        fx = nxt[0]["fixture"]["id"]
        o = client.get("/odds", {"fixture": fx, "bookmaker": config.ODDS_BOOKMAKER_ID}, ttl=3600)
        names_ = sorted({b["name"] for it in o for bm in it.get("bookmakers", []) for b in bm.get("bets", [])})
        out(f"rynki kursów dla pierwszego meczu (bukmacher {config.ODDS_BOOKMAKER_ID}): {len(names_)}")
        for n in names_:
            out(f"   {n}")
        d = nxt[0]["fixture"]["date"][:10]
        inj = client.get("/injuries", {"league": lid, "season": season, "date": d}, ttl=3600)
        out(f"kontuzje/zawieszenia w {league} na {d}: {len(inj)} wpisów")
    out(f"zużyto zapytań w tym uruchomieniu: {client.used}, zostało: {client.remaining}")
