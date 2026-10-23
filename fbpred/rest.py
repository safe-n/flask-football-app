"""Kalendarz meczów drużyn i dni odpoczynku (liga + opcjonalnie Liga Mistrzów dopasowana po nazwach)."""
from __future__ import annotations

import numpy as np
import pandas as pd

SHORT_DAYS = 4     # "krótka przerwa": poprzedni mecz najwyżej 4 dni wcześniej (np. środa -> niedziela, wtorek -> sobota)
CL_DAYS = 5        # mecz Ligi Mistrzów w ciągu ostatnich 5 dni
NEUTRAL_DAYS = 7   # brak poprzedniego meczu (początek danych/sezonu) traktujemy jak normalny tydzień


class Calendar:
    def __init__(self, by_team: dict[str, tuple[np.ndarray, list[str]]]):
        self.by_team = by_team
        self.has_cl = any("CL" in tags for _, tags in by_team.values())

    @classmethod
    def from_matches(cls, df: pd.DataFrame, extra: pd.DataFrame | None = None) -> "Calendar":
        parts = [pd.DataFrame({"team": df[c], "date": pd.to_datetime(df["date"]), "tag": "L"}) for c in ("home", "away")]
        if extra is not None and len(extra):
            parts.append(extra[["team", "date", "tag"]].assign(date=lambda x: pd.to_datetime(x["date"])))
        long = pd.concat(parts, ignore_index=True).sort_values("date")
        by = {t: (g["date"].to_numpy("datetime64[D]"), g["tag"].tolist()) for t, g in long.groupby("team")}
        return cls(by)

    def days_since(self, team: str, date) -> tuple[int | None, str | None]:
        """(dni od poprzedniego meczu, jego typ 'L'=liga / 'CL'), albo (None, None) gdy brak wcześniejszego meczu."""
        e = self.by_team.get(team)
        if e is None:
            return None, None
        dates, tags = e
        d = np.datetime64(pd.Timestamp(date).date())
        i = int(np.searchsorted(dates, d, side="left")) - 1
        if i < 0:
            return None, None
        return int((d - dates[i]).astype(int)), tags[i]

    def info(self, home: str, away: str, date) -> dict:
        out = {}
        for side, team in (("home", home), ("away", away)):
            days, tag = self.days_since(team, date)
            eff = NEUTRAL_DAYS if days is None else days
            out[f"{side}_days"] = days
            out[f"{side}_tag"] = tag
            out[f"{side}_short"] = eff <= SHORT_DAYS
            out[f"{side}_cl"] = tag == "CL" and eff <= CL_DAYS
        return out

    def features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cechy odpoczynku dla każdego meczu z df (kolumny: short_h, short_a, cl_h, cl_a, rest_h, rest_a)."""
        rows = []
        for r in df[["home", "away", "date"]].itertuples(index=False):
            i = self.info(r.home, r.away, r.date)
            rows.append({"rest_h": i["home_days"], "rest_a": i["away_days"], "short_h": i["home_short"],
                         "short_a": i["away_short"], "cl_h": i["home_cl"], "cl_a": i["away_cl"]})
        return pd.DataFrame(rows, index=df.index)


def cl_extra(conn, known_teams: list[str]) -> pd.DataFrame:
    """Mecze Ligi Mistrzów (rozegrane) przypisane do drużyn ligi krajowej po dopasowaniu nazw."""
    from . import names
    rows = conn.execute("SELECT date, home, away FROM matches WHERE league='CL' AND hg IS NOT NULL").fetchall()
    if not rows:
        return pd.DataFrame(columns=["team", "date", "tag"])
    cache: dict[str, str | None] = {}
    out = []
    for date, h, a in rows:
        for nm in (h, a):
            if nm not in cache:
                cache[nm] = names.resolve(nm, known_teams)
            if cache[nm]:
                out.append({"team": cache[nm], "date": date, "tag": "CL"})
    return pd.DataFrame(out, columns=["team", "date", "tag"])


def build_calendar(df: pd.DataFrame, conn=None) -> Calendar:
    """Kalendarz z meczów ligi + (jeśli w bazie są) meczów Ligi Mistrzów."""
    extra = None
    if conn is not None:
        try:
            extra = cl_extra(conn, sorted(set(df["home"]) | set(df["away"])))
        except Exception:  # noqa: BLE001 - brak LM nie może psuć prognoz
            extra = None
    return Calendar.from_matches(df, extra)
