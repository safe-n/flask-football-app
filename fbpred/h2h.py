"""H2H (bezpośrednie spotkania) i forma drużyn - szybka ocena wzrokowa na liście meczów.

Dane: wyłącznie to, co jest w bazie (historia od kilku sezonów), więc to NIE jest pełne H2H „od 1996”, tylko ostatnie lata.
Wyniki zawsze z perspektywy wskazanej drużyny: W = wygrana, R = remis, P = porażka. Najnowsze są po LEWEJ.
"""
from __future__ import annotations

import pandas as pd


def _res(gf: int, ga: int) -> str:
    return "W" if gf > ga else "R" if gf == ga else "P"


def _finished(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["hg"].notna() & df["ag"].notna()]


def _row(r, team: str) -> dict:
    gf, ga = (r.hg, r.ag) if r.home == team else (r.ag, r.hg)
    d = pd.Timestamp(r.date).strftime("%Y-%m-%d")
    return {"date": d, "home": r.home, "away": r.away, "hg": int(r.hg), "ag": int(r.ag), "gf": int(gf), "ga": int(ga),
            "res": _res(gf, ga), "score": f"{int(gf)}–{int(ga)}", "tip": f"{d} {r.home} {int(r.hg)}–{int(r.ag)} {r.away}"}


def h2h(df: pd.DataFrame, home: str, away: str, n: int = 5) -> dict:
    """Ostatnie `n` spotkań obu drużyn (dowolne boisko), z perspektywy `home`; bilans z całej dostępnej historii."""
    d = _finished(df)
    d = d[((d["home"] == home) & (d["away"] == away)) | ((d["home"] == away) & (d["away"] == home))]
    d = d.sort_values("date", ascending=False)
    rows = [_row(r, home) for r in d.itertuples(index=False)]
    return {"matches": rows[:n], "n": len(rows), "w": sum(r["res"] == "W" for r in rows),
            "d": sum(r["res"] == "R" for r in rows), "l": sum(r["res"] == "P" for r in rows)}


def form(df: pd.DataFrame, team: str, n: int = 5, venue: str | None = None) -> list[dict]:
    """Ostatnie `n` meczów drużyny (venue: None = wszystkie, 'home' = tylko u siebie, 'away' = tylko na wyjeździe)."""
    d = _finished(df)
    mask = {"home": d["home"] == team, "away": d["away"] == team}.get(venue, (d["home"] == team) | (d["away"] == team))
    d = d[mask].sort_values("date", ascending=False).head(n)
    out = []
    for r in d.itertuples(index=False):
        x = _row(r, team)
        x["letter"] = x["res"]
        out.append(x)
    return out


def flag(h: dict, p_home: float, p_away: float, home: str, away: str, min_n: int = 3, edge: float = 0.45) -> str | None:
    """Ostrzeżenie, gdy faworyt wg modelu rzadko wygrywa z tym rywalem (podpowiedź do własnej analizy, nie sygnał do zakładu)."""
    ms = h["matches"]
    if len(ms) < min_n:
        return None
    fav_home = p_home >= p_away
    fav, pf = (home, p_home) if fav_home else (away, p_away)
    if pf < edge:
        return None
    if fav_home:                                  # wygrane faworyta (wyniki są z perspektywy gospodarza)
        wins = sum(1 for m in ms if m["res"] == "W")
    else:
        wins = sum(1 for m in ms if m["res"] == "P")
    if wins / len(ms) <= 0.2:
        return f"H2H: faworyt ({fav}) wygrał tylko {wins} z {len(ms)} ostatnich spotkań z tym rywalem"
    return None
