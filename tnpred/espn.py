"""ESPN (site.api.espn.com) - darmowy, nieoficjalny feed bez klucza: wyniki z tego samego dnia i terminarz.

Po co: tennis-data.co.uk publikuje wyniki raz w tygodniu (4-8 dni zwłoki), a The Odds API zna tylko duże turnieje
(brak m.in. ATP 250 typu Stockholm, ATP/WTA Finals). ESPN daje:
  * „szybką łatkę” wyników - mecze z ostatnich dni, których jeszcze nie ma w tennis-data (zastępowane pełnymi danymi
    tennis-data po tygodniowej publikacji; w bazie oznaczone location = "ESPN"),
  * terminarz na dziś/jutro - mecze bez kursów, gdy The Odds API ich nie ma (kursy można dopisać na stronie meczu).

Filtr poziomu: tylko single, bez kwalifikacji, tylko turnieje z miast znanych z historii tennis-data danego touru
(odpada ITF/125/Challenger) albo Finals. Jedno zapytanie na tour (zakres dat).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from .names import norm, to_td

URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
MARK = "ESPN"                      # wartość kolumny location dla meczów z ESPN
ROUNDS = {"round 1": "1st Round", "round 2": "2nd Round", "round 3": "3rd Round", "round 4": "4th Round",
          "round of 128": "1st Round", "round of 64": "2nd Round", "round of 32": "3rd Round", "round of 16": "4th Round",
          "quarterfinal": "Quarterfinals", "quarterfinals": "Quarterfinals", "semifinal": "Semifinals",
          "semifinals": "Semifinals", "final": "The Final", "group stage": "Round Robin", "round robin": "Round Robin"}
SKIP_EVENT = re.compile(r"\b125\b|\bitf\b|challenger|\bw\d{2,3}\b|\bm\d{2}\b|united cup|davis cup|billie jean|laver cup",
                        re.I)
FINALS = {"ATP": {"tournament": "Masters Cup", "series": "Masters Cup", "surface": "Hard", "court": "Indoor"},
          "WTA": {"tournament": "WTA Finals", "series": "Tour Championships", "surface": "Hard", "court": "Indoor"}}


class EspnError(RuntimeError):
    pass


def fetch(tour: str, start: datetime, end: datetime, timeout=(10, 30)) -> dict:
    url = URL.format(tour=tour.lower())
    r = requests.get(url, params={"dates": f"{start:%Y%m%d}-{end:%Y%m%d}"}, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 tnpred"})
    if r.status_code != 200:
        raise EspnError(f"ESPN {tour}: HTTP {r.status_code}")
    return r.json()


def places(hist: pd.DataFrame) -> dict:
    """{tour: {miasto (norm): {tournament, series, surface, court}}} - najnowszy turniej tennis-data w danym mieście."""
    out: dict = {}
    if hist is None or hist.empty or "location" not in hist.columns:
        return out
    h = hist[hist["location"].astype(str) != MARK].dropna(subset=["location"]).sort_values("date")
    for r in h.drop_duplicates(["tour", "location"], keep="last").to_dict("records"):
        out.setdefault(str(r["tour"]), {})[norm(r["location"])] = {
            k: (None if pd.isna(r.get(k)) else str(r.get(k))) for k in ("tournament", "series", "surface", "court")}
    return out


def _city(ev: dict, comp: dict) -> str:
    v = (comp.get("venue") or {}).get("fullName") or (ev.get("venue") or {}).get("displayName") or ""
    return norm(v.split(",")[0])


def event_info(tour: str, ev: dict, known: dict) -> dict | None:
    """Dane turnieju w zapisie tennis-data albo None (turniej spoza zakresu tennis-data)."""
    name = str(ev.get("name") or "")
    if SKIP_EVENT.search(name):
        return None
    if re.search(r"finals", name, re.I) and not re.search(r"next ?gen", name, re.I):
        info = dict(FINALS[tour])
        city = _city(ev, {})
        if city in known and known[city].get("surface"):
            info["surface"] = known[city]["surface"]
        return info
    city = _city(ev, {})
    if city in known:
        return dict(known[city])
    return None


def _sets(c1: dict, c2: dict) -> list[tuple[int, int]]:
    a = [int(x.get("value") or 0) for x in c1.get("linescores") or []]
    b = [int(x.get("value") or 0) for x in c2.get("linescores") or []]
    return list(zip(a, b))


def _done(x: int, y: int) -> bool:
    hi, lo = max(x, y), min(x, y)
    return (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo in (5, 6))


def _round(comp: dict) -> str | None:
    r = norm((comp.get("round") or {}).get("displayName"))
    if not r or "qualif" in r:
        return None
    return ROUNDS.get(r, r.title())


def _name(c: dict) -> str:
    return str((c.get("athlete") or {}).get("displayName") or (c.get("roster") or {}).get("displayName") or "").strip()


def parse(tour: str, data: dict, known: dict, resolve=None, slam_bo5: bool = True):
    """-> (wyniki w kolumnach tennis-data, terminarz w kolumnach tabeli upcoming, pominięte turnieje)."""
    results, schedule, skipped = [], [], set()
    for ev in data.get("events") or []:
        info = event_info(tour, ev, known)
        if info is None:
            skipped.add(str(ev.get("name")))
            continue
        major = bool(ev.get("major"))
        bo = 5 if (tour == "ATP" and major and slam_bo5) else 3
        for g in ev.get("groupings") or []:
            gname = str((g.get("grouping") or {}).get("displayName") or "")
            if "singles" not in gname.lower():
                continue
            for comp in g.get("competitions") or []:
                rnd = _round(comp)
                cs = comp.get("competitors") or []
                if rnd is None or len(cs) != 2:
                    continue
                n1, n2 = _name(cs[0]), _name(cs[1])
                if not n1 or not n2 or "tbd" in (n1 + n2).lower():
                    continue
                st = (comp.get("status") or {}).get("type") or {}
                sname = str(st.get("name") or "")
                when = str(comp.get("date") or comp.get("startDate") or "")
                r1 = resolve(tour, n1) if resolve else None
                r2 = resolve(tour, n2) if resolve else None
                if st.get("completed"):
                    if "WALKOVER" in sname or "CANCEL" in sname or "POSTPONED" in sname:
                        continue
                    if not (r1 and r2):          # łatka tylko dla znanych zawodników (bez dubli nazw; resztę uzupełni tennis-data)
                        continue
                    w = 0 if cs[0].get("winner") else (1 if cs[1].get("winner") else None)
                    if w is None:
                        continue
                    cw, cl = cs[w], cs[1 - w]
                    sets = _sets(cw, cl)
                    if not sets:
                        continue
                    row = {"date": when[:10], "tour": tour, "tournament": info.get("tournament"), "location": MARK,
                           "series": info.get("series"), "court": info.get("court"), "surface": info.get("surface") or "Hard",
                           "round": rnd, "best_of": bo, "winner": r1 if w == 0 else r2, "loser": r2 if w == 0 else r1,
                           "comment": "Retired" if "RETIRED" in sname else "Completed"}
                    for i in range(5):
                        x, y = sets[i] if i < len(sets) else (None, None)
                        row[f"w{i + 1}"], row[f"l{i + 1}"] = x, y
                    row["wsets"] = sum(1 for x, y in sets if x > y and _done(x, y))
                    row["lsets"] = sum(1 for x, y in sets if y > x and _done(x, y))
                    results.append(row)
                else:
                    if not when:
                        continue
                    valid = comp.get("timeValid", True) and "TBD" not in str(st.get("detail") or "")
                    date = when[:16].replace("T", " ") if valid else when[:10]
                    schedule.append({"source": "espn", "tour": tour, "tournament": info.get("tournament"),
                                     "surface": info.get("surface") or "Hard", "best_of": bo, "date": date,
                                     "p1": r1 or to_td(n1), "p2": r2 or to_td(n2), "o1": None, "o2": None,
                                     "live": "IN_PROGRESS" in sname})
    return results, schedule, skipped


def fetch_all(hist: pd.DataFrame, resolve=None, tours=("ATP", "WTA"), days_back: int = 14, days_ahead: int = 2,
              now: datetime | None = None, getter=None):
    now = now or datetime.now(timezone.utc)
    getter = getter or fetch
    known_all = places(hist)
    results, schedule, skipped, errors = [], [], set(), []
    for tour in tours:
        try:
            data = getter(tour, now - timedelta(days=days_back), now + timedelta(days=days_ahead))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{tour}: {e}")
            continue
        r, s, k = parse(tour, data, known_all.get(tour, {}), resolve)
        results += r
        schedule += s
        skipped |= k
    return results, schedule, {"errors": errors, "skipped": sorted(skipped)}


def results_frame(rows: list[dict]) -> pd.DataFrame:
    from .tdata import _from_norm
    if not rows:
        return pd.DataFrame()
    return _from_norm(pd.DataFrame(rows))


def uncovered(rows: list[dict], hist: pd.DataFrame, days: int = 3) -> list[dict]:
    """Mecze z ESPN, których jeszcze nie ma w danych tennis-data (ta sama para w tym samym tourze, ±days dni)."""
    if hist is None or hist.empty or not rows:
        return list(rows)
    h = hist[hist["location"].astype(str) != MARK]
    idx: dict = {}
    for t, d, w, l in zip(h.tour.astype(str), pd.to_datetime(h.date), h.winner.astype(str), h.loser.astype(str)):
        idx.setdefault((t, frozenset((w, l))), []).append(d)
    out = []
    for r in rows:
        d = pd.Timestamp(r["date"])
        ds = idx.get((r["tour"], frozenset((r["winner"], r["loser"]))), [])
        if not any(abs((d - x).days) <= days for x in ds):
            out.append(r)
    return out
