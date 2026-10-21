"""Klient API-Football (RapidAPI lub api-sports) z cache na dysku i pilnowaniem limitu zapytań.

Zasady: każda odpowiedź jest zapisywana w CACHE_DIR, więc ponowne uruchomienie nie zużywa limitu.
Pobieranie statystyk jest wznawialne (tylko mecze bez stats_done). Klucz TYLKO z .env.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from . import config
from .db import update_fields, upsert_matches

BASE = {"rapidapi": "https://api-football-v1.p.rapidapi.com/v3",
        "apisports": "https://v3.football.api-sports.io"}
FINISHED = {"FT", "AET", "PEN"}
STAT_MAP = {"Shots on Goal": "sot", "Total Shots": "shots", "Corner Kicks": "corners",
            "Yellow Cards": "yellow", "Red Cards": "red"}


class QuotaExhausted(RuntimeError):
    pass


class ApiClient:
    def __init__(self, key: str | None = None, provider: str | None = None,
                 cache_dir: Path | None = None, reserve: int | None = None):
        self.key = key or config.API_KEY
        self.provider = provider or config.API_PROVIDER
        self.cache_dir = Path(cache_dir or config.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.reserve = config.REQUEST_RESERVE if reserve is None else reserve
        self.remaining: int | None = None
        self.used = 0
        if not self.key:
            raise RuntimeError("Brak API_KEY. Skopiuj .env.example do .env i wpisz NOWY klucz.")

    def _headers(self) -> dict:
        if self.provider == "apisports":
            return {"x-apisports-key": self.key}
        return {"x-rapidapi-key": self.key, "x-rapidapi-host": config.API_HOST}

    def get(self, path: str, params: dict, ttl: int | None = None) -> list:
        """Zwraca pole `response`. ttl=None -> cache bezterminowy; ttl=sekundy -> odświeżaj."""
        key = hashlib.sha1((path + json.dumps(params, sort_keys=True)).encode()).hexdigest()
        f = self.cache_dir / f"{key}.json"
        if f.exists() and (ttl is None or time.time() - f.stat().st_mtime < ttl):
            return json.loads(f.read_text())["response"]
        if self.remaining is not None and self.remaining <= self.reserve:
            raise QuotaExhausted(f"Zostało {self.remaining} zapytań (rezerwa {self.reserve}).")
        for attempt in range(2):
            r = requests.get(BASE[self.provider] + path, headers=self._headers(), params=params, timeout=30)
            if r.status_code == 429 and attempt == 0:
                time.sleep(61)  # limit na minutę
                continue
            break
        r.raise_for_status()
        self.used += 1
        rem = r.headers.get("x-ratelimit-requests-remaining")
        self.remaining = int(rem) if rem is not None and rem.isdigit() else self.remaining
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(f"API zwróciło błąd: {data['errors']}")
        f.write_text(json.dumps(data))
        return data["response"]


# ------------------------------------------------------------------ parsery
def _referee(s):
    return s.split(",")[0].strip() if s else None


def parse_fixture(item: dict, league: str) -> dict:
    fx, teams, goals = item["fixture"], item["teams"], item["goals"]
    ht = (item.get("score") or {}).get("halftime") or {}
    return dict(
        fixture_id=fx["id"], league=str(league), season=item["league"]["season"],
        date=fx["date"][:10], home=teams["home"]["name"], away=teams["away"]["name"],
        referee=_referee(fx.get("referee")), status=fx["status"]["short"],
        hg=goals["home"] if fx["status"]["short"] in FINISHED else None,
        ag=goals["away"] if fx["status"]["short"] in FINISHED else None,
        hg_ht=ht.get("home"), ag_ht=ht.get("away"),
    )


def parse_statistics(resp: list, home_name: str) -> dict:
    out: dict = {}
    for ts in resp:
        side = "h" if ts["team"]["name"] == home_name else "a"
        for s in ts.get("statistics", []):
            k = STAT_MAP.get(s["type"])
            if k:
                v = s["value"]
                out[f"{side}_{k}"] = 0 if v is None else (int(v) if str(v).isdigit() else None)
    return out


def parse_odds(resp: list, bookmaker_id: int) -> dict:
    out: dict = {}
    for item in resp:
        for bm in item.get("bookmakers", []):
            if bm["id"] != bookmaker_id:
                continue
            for bet in bm.get("bets", []):
                name = bet["name"].lower()
                vals = {v["value"]: float(v["odd"]) for v in bet["values"]}
                if name == "match winner":
                    out.update(o_home=vals.get("Home"), o_draw=vals.get("Draw"), o_away=vals.get("Away"))
                elif name == "goals over/under":
                    out.update(o_over25=vals.get("Over 2.5"), o_under25=vals.get("Under 2.5"))
                elif name == "both teams score":
                    out.update(o_btts_yes=vals.get("Yes"), o_btts_no=vals.get("No"))
    return out


# ------------------------------------------------------------------ zadania
def fetch_season(client: ApiClient, conn, league: str, season: int) -> int:
    """1 zapytanie: wszystkie mecze sezonu z wynikami i wynikiem do przerwy."""
    resp = client.get("/fixtures", {"league": league, "season": season})
    return upsert_matches(conn, [parse_fixture(i, league) for i in resp])


def fetch_missing_stats(client: ApiClient, conn, league: str, limit: int = 80) -> int:
    """Statystyki meczów (kartki, rożne, strzały). Wznawialne: bierze tylko stats_done=0."""
    rows = conn.execute(
        "SELECT fixture_id, home FROM matches WHERE league=? AND status IN ('FT','AET','PEN') "
        "AND stats_done=0 ORDER BY date DESC LIMIT ?", (str(league), limit)).fetchall()
    done = 0
    for fid, home in rows:
        try:
            resp = client.get("/fixtures/statistics", {"fixture": fid})
        except QuotaExhausted as e:
            print(f"  stop: {e}")
            break
        st = parse_statistics(resp, home)
        st["stats_done"] = 1 if "h_yellow" in st and "a_yellow" in st else 2  # 2 = brak danych
        update_fields(conn, fid, st)
        done += 1
    return done


def fetch_upcoming(client: ApiClient, conn, league: str, days: int = 7, with_odds: bool = True) -> int:
    today = date.today()
    season = today.year if today.month >= 7 else today.year - 1
    resp = client.get("/fixtures", {"league": league, "season": season, "from": today.isoformat(),
                                    "to": (today + timedelta(days=days)).isoformat()}, ttl=3600)
    rows = [parse_fixture(i, league) for i in resp]
    if with_odds:
        for r in rows:
            try:
                o = client.get("/odds", {"fixture": r["fixture_id"], "bookmaker": config.ODDS_BOOKMAKER_ID},
                               ttl=3 * 3600)
            except QuotaExhausted as e:
                print(f"  stop: {e}")
                break
            r.update(parse_odds(o, config.ODDS_BOOKMAKER_ID))
    return upsert_matches(conn, rows)
