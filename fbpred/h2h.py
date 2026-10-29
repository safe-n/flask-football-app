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


# ---------------------------------------------------------------------------------------------------------------------
# Test: czy H2H wnosi informację ponad kursy bukmachera?  (komenda `h2h-test`)
# ---------------------------------------------------------------------------------------------------------------------
def study(df: pd.DataFrame, n_last: int = 5, min_n: int = 3, fav_min: float = 0.45) -> pd.DataFrame:
    """Dla meczów z kursami, w których jest faworyt (p >= fav_min wg kursów bez marży) i były >= min_n wcześniejszych spotkań:
    jaki odsetek ostatnich n_last spotkań wygrał faworyt (`share`) i co stało się w meczu. Tylko dane sprzed meczu."""
    from .odds import implied_probs
    d = _finished(df).sort_values("date")
    need = ("o_home", "o_draw", "o_away")
    if any(c not in d.columns for c in need):
        return pd.DataFrame()
    past: dict[frozenset, list] = {}
    out = []
    for r in d.itertuples(index=False):
        key = frozenset((r.home, r.away))
        prior = past.setdefault(key, [])
        oh, od, oa = r.o_home, r.o_draw, r.o_away
        if len(prior) >= min_n and all(pd.notna(x) and x > 1 for x in (oh, od, oa)):
            p1, _, p2 = implied_probs([float(oh), float(od), float(oa)])
            fav = r.home if p1 >= fav_min and p1 > p2 else r.away if p2 >= fav_min else None
            if fav:
                last = prior[-n_last:]
                wins = sum(1 for h, a, hg, ag in last if (h == fav and hg > ag) or (a == fav and ag > hg))
                fav_home = fav == r.home
                won = (r.hg > r.ag) if fav_home else (r.ag > r.hg)
                lost = (r.hg < r.ag) if fav_home else (r.ag < r.hg)
                out.append({"share": wins / len(last), "n_prior": len(last), "p_fav": p1 if fav_home else p2, "won": int(won),
                            "lost": int(lost), "o_fav": float(oh if fav_home else oa), "o_dog": float(oa if fav_home else oh),
                            "o_draw": float(od), "draw": int(r.hg == r.ag)})
        prior.append((r.home, r.away, int(r.hg), int(r.ag)))
    return pd.DataFrame(out)


BUCKETS = (("faworyt rzadko wygrywał (≤20%)", lambda s: s <= 0.2), ("pośrednio (25–55%)", lambda s: (s > 0.2) & (s < 0.6)),
           ("faworyt zwykle wygrywał (≥60%)", lambda s: s >= 0.6))


def summarize(obs: pd.DataFrame) -> dict:
    """Tabela kubełków + test nachylenia (czy odsetek wygranych faworyta w H2H tłumaczy wynik ponad kursy)."""
    import numpy as np
    rows = []
    for name, f in BUCKETS:
        o = obs[f(obs["share"])]
        if len(o) == 0:
            continue
        var = float((o["p_fav"] * (1 - o["p_fav"])).sum())
        z = float((o["won"].sum() - o["p_fav"].sum()) / np.sqrt(var)) if var > 0 else 0.0
        rows.append({"kubełek": name, "meczów": len(o), "szansa wg kursów": f"{100 * o['p_fav'].mean():.1f}%",
                     "faworyt wygrał": f"{100 * o['won'].mean():.1f}%", "różnica": f"{100 * (o['won'].mean() - o['p_fav'].mean()):+.1f} pp",
                     "z": round(z, 2), "ROI faworyt": f"{100 * float((o['won'] * o['o_fav'] - 1).mean()):+.1f}%",
                     "ROI underdog (wygrana)": f"{100 * float((o['lost'] * o['o_dog'] - 1).mean()):+.1f}%"})
    res = {"tabela": pd.DataFrame(rows), "n": len(obs)}
    if len(obs) >= 30 and obs["share"].std() > 0:
        x = obs["share"].to_numpy(float)
        y = (obs["won"] - obs["p_fav"]).to_numpy(float)
        xc = x - x.mean()
        slope = float((xc * y).sum() / (xc ** 2).sum())
        resid = y - y.mean() - slope * xc
        se = float(np.sqrt((resid ** 2).sum() / (len(x) - 2) / (xc ** 2).sum()))
        res.update(slope=slope, t=slope / se if se > 0 else 0.0)
    return res


def verdict(s: dict) -> str:
    if s["n"] < 200:
        return f"Za mało obserwacji ({s['n']}), by cokolwiek wnioskować - zaimportuj więcej sezonów (fetch-csv)."
    t = s.get("t", 0.0)
    if abs(t) < 2:
        return ("Brak dowodu, że H2H wnosi coś ponad kursy bukmachera (|t| < 2). Traktuj flagę ⚑ jako ciekawostkę do oceny "
                "wzrokowej, nie jako przewagę.")
    if t > 0:
        return "H2H faworyta koreluje z jego wynikiem ponad kursy (t ≥ 2) - efekt wygląda na realny, ale sprawdź na kolejnych sezonach."
    return ("Ujemne nachylenie (t ≤ -2): dobra seria H2H faworyta wiąże się z GORSZYM wynikiem względem kursów - to raczej "
            "przypadek lub artefakt; nie obstawiaj tego.")
