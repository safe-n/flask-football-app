"""The Odds API (the-odds-api.com) - nadchodzące mecze ATP/WTA z kursami. Opcjonalne: bez ODDS_API_KEY moduł jest wyłączony.

Darmowy plan: ok. 500 kredytów/mies. Lista sportów nic nie kosztuje; kursy = (liczba rynków × liczba regionów) za turniej.
Domyślnie tylko „h2h” w regionie „eu” = 1 kredyt na turniej. Odświeżanie co TN_ODDS_REFRESH_HOURS (domyślnie 12 h).
"""
from __future__ import annotations

import statistics
from collections import Counter

import requests

from . import config
from .names import to_td

BASE = "https://api.the-odds-api.com/v4"
SLAMS = ("australian_open", "french_open", "wimbledon", "us_open")
CLAY = ("french_open", "monte_carlo", "madrid", "italian", "rome", "barcelona", "hamburg", "rio", "buenos_aires", "munich",
        "estoril", "geneva", "lyon", "bastad", "gstaad", "umag", "kitzbuhel", "charleston", "stuttgart", "rabat", "strasbourg",
        "palermo", "prague", "bogota", "houston", "marrakech", "cordoba", "santiago", "parma", "clay")
GRASS = ("wimbledon", "queens", "halle", "eastbourne", "hertogenbosch", "mallorca", "berlin", "nottingham", "birmingham",
         "newport", "bad_homburg", "stuttgart_grass", "grass")


class OddsApiError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.ODDS_API_KEY)


def _get(path: str, **params):
    r = requests.get(BASE + path, params={"apiKey": config.ODDS_API_KEY, **params}, timeout=30)
    if r.status_code == 401:
        raise OddsApiError("The Odds API odrzuciło klucz (401) - sprawdź ODDS_API_KEY")
    if r.status_code == 429:
        raise OddsApiError("The Odds API: wyczerpany limit kredytów (429)")
    if r.status_code != 200:
        raise OddsApiError(f"The Odds API: HTTP {r.status_code} {r.text[:200]}")
    quota = {"remaining": r.headers.get("x-requests-remaining"), "used": r.headers.get("x-requests-used")}
    return r.json(), quota


def tennis_sports() -> list[dict]:
    data, _ = _get("/sports")
    return [s for s in data if str(s.get("group") or "").lower() == "tennis" and s.get("active")
            and str(s.get("key") or "").startswith(("tennis_atp", "tennis_wta"))]


def guess_surface(key: str, title: str = "", history_lookup=None) -> str:
    k = (key + " " + title).lower().replace(" ", "_").replace("'", "")
    if any(x in k for x in GRASS):
        return "Grass"
    if any(x in k for x in CLAY):
        return "Clay"
    if history_lookup:
        s = history_lookup(title)
        if s:
            return s
    return "Hard"


def _median(xs):
    xs = [float(x) for x in xs if x]
    return round(statistics.median(xs), 3) if xs else None


def parse_events(sport: dict, events: list[dict], resolve=None, history_lookup=None) -> list[dict]:
    key = sport.get("key", "")
    tour = "WTA" if key.startswith("tennis_wta") else "ATP"
    title = sport.get("title") or key
    surface = guess_surface(key, title, history_lookup)
    bo = 5 if tour == "ATP" and any(s in key for s in SLAMS) else 3
    rows = []
    for ev in events:
        h, a = ev.get("home_team") or "", ev.get("away_team") or ""
        if not h or not a:
            continue
        p1 = (resolve(tour, h) if resolve else None) or to_td(h)
        p2 = (resolve(tour, a) if resolve else None) or to_td(a)
        prices = {h: [], a: []}
        totals, spreads = [], []
        for bk in ev.get("bookmakers") or []:
            pin = bk.get("key") == "pinnacle"
            for mk in bk.get("markets") or []:
                oc = mk.get("outcomes") or []
                if mk.get("key") == "h2h":
                    for o in oc:
                        if o.get("name") in prices and o.get("price"):
                            prices[o["name"]].append((pin, o["price"]))
                elif mk.get("key") == "totals":
                    ov = [o for o in oc if o.get("name") == "Over"]
                    un = [o for o in oc if o.get("name") == "Under"]
                    if ov and un and ov[0].get("point") == un[0].get("point"):
                        totals.append((ov[0]["point"], ov[0]["price"], un[0]["price"]))
                elif mk.get("key") == "spreads":
                    x = [o for o in oc if o.get("name") == h]
                    y = [o for o in oc if o.get("name") == a]
                    if x and y and x[0].get("point") is not None:
                        spreads.append((x[0]["point"], x[0]["price"], y[0]["price"]))

        def pick(lst):
            pins = [p for is_pin, p in lst if is_pin]
            return round(float(pins[0]), 3) if pins else _median([p for _, p in lst])
        row = {"source": "oddsapi", "tour": tour, "tournament": title, "surface": surface, "best_of": bo,
               "date": str(ev.get("commence_time") or "")[:16].replace("T", " "), "p1": p1, "p2": p2,
               "o1": pick(prices[h]), "o2": pick(prices[a])}
        if totals:
            line = Counter(t[0] for t in totals).most_common(1)[0][0]
            row.update(total_line=line, o_over=_median([t[1] for t in totals if t[0] == line]),
                       o_under=_median([t[2] for t in totals if t[0] == line]))
        if spreads:
            line = Counter(s[0] for s in spreads).most_common(1)[0][0]
            row.update(hcp_line=line, o_h1=_median([s[1] for s in spreads if s[0] == line]),
                       o_h2=_median([s[2] for s in spreads if s[0] == line]))
        rows.append(row)
    return rows


def fetch_all(resolve=None, history_lookup=None, tours=None) -> tuple[list[dict], dict]:
    tours = tours or config.TOURS
    rows, quota, errors = [], {}, []
    for sp in tennis_sports():
        tour = "WTA" if sp["key"].startswith("tennis_wta") else "ATP"
        if tour not in tours:
            continue
        try:
            evs, quota = _get(f"/sports/{sp['key']}/odds", regions=config.ODDS_REGIONS, markets=config.ODDS_MARKETS,
                              oddsFormat="decimal", dateFormat="iso")
            rows += parse_events(sp, evs, resolve, history_lookup)
        except OddsApiError as e:
            errors.append(f"{sp['key']}: {e}")
            if "429" in str(e):
                break
        try:
            if quota.get("remaining") is not None and float(quota["remaining"]) < 15:
                errors.append("zostało < 15 kredytów - przerywam do następnego miesiąca")
                break
        except ValueError:
            pass
    return rows, {"quota": quota, "errors": errors}
