"""H2H, forma, bilans na nawierzchni, zmęczenie - piktogramy jak w fbpred (W = wygrana, P = porażka, z perspektywy zawodnika 1)."""
from __future__ import annotations

import html

import pandas as pd


def _score(r, flip: bool) -> str:
    sets = []
    for i in range(1, 6):
        a, b = r.get(f"w{i}"), r.get(f"l{i}")
        if a is None or b is None or a != a or b != b:
            break
        sets.append(f"{int(b)}-{int(a)}" if flip else f"{int(a)}-{int(b)}")
    s = " ".join(sets)
    c = str(r.get("comment") or "")
    return s + ("" if c.lower().startswith("compl") else f" ({c})")


def player_matches(df: pd.DataFrame, tour: str, name: str, before=None) -> pd.DataFrame:
    d = df[(df.tour == tour) & ((df.winner == name) | (df.loser == name))]
    if before is not None:
        d = d[d.date < pd.Timestamp(before)]
    return d


def chips(rows: list[dict]) -> str:
    out = []
    for r in rows:
        tip = html.escape(r["tip"])
        out.append(f'<span class="pg {r["res"]}" title="{tip}">{r["res"]}</span>')
    return "".join(out)


def h2h(df: pd.DataFrame, tour: str, p1: str, p2: str, n: int = 6) -> dict:
    d = df[(df.tour == tour) & (((df.winner == p1) & (df.loser == p2)) | ((df.winner == p2) & (df.loser == p1)))]
    d = d.sort_values("date", ascending=False)
    rows = []
    for r in d.to_dict("records"):
        won = r["winner"] == p1
        rows.append({"res": "W" if won else "P",
                     "tip": f"{r['date']:%Y-%m-%d} {r['tournament']} ({r['surface']}, {r['round']}): {_score(r, not won)}"})
    w = sum(1 for r in rows if r["res"] == "W")
    return {"n": len(rows), "w1": w, "w2": len(rows) - w, "rows": rows[:n], "html": chips(rows[:n])}


def form(df: pd.DataFrame, tour: str, name: str, n: int = 10, surface: str | None = None) -> dict:
    d = player_matches(df, tour, name)
    if surface:
        d = d[d.surface == surface]
    d = d.sort_values("date", ascending=False).head(n)
    rows = []
    for r in d.to_dict("records"):
        won = r["winner"] == name
        opp = r["loser"] if won else r["winner"]
        rows.append({"res": "W" if won else "P",
                     "tip": f"{r['date']:%Y-%m-%d} {r['tournament']} ({r['surface']}): {'wygrana z' if won else 'porażka z'} {opp} {_score(r, not won)}"})
    w = sum(1 for r in rows if r["res"] == "W")
    return {"n": len(rows), "w": w, "rows": rows, "html": chips(rows)}


def surface_record(df: pd.DataFrame, tour: str, name: str, surface: str, days: int = 365) -> tuple[int, int]:
    d = player_matches(df, tour, name)
    if len(d):
        d = d[(d.surface == surface) & (d.date >= d.date.max() - pd.Timedelta(days=days))]
    w = int((d.winner == name).sum())
    return w, int(len(d) - w)


def fatigue(df: pd.DataFrame, tour: str, name: str, ref_date=None) -> dict:
    """Ile meczów / gemów w ostatnich 7 i 14 dniach (gemy ≈ czas na korcie). Tylko informacyjnie."""
    ref = pd.Timestamp(ref_date) if ref_date is not None else (df.date.max() + pd.Timedelta(days=1) if len(df) else pd.Timestamp.today())
    d = player_matches(df, tour, name, before=ref)
    out = {}
    for k in (7, 14):
        x = d[d.date >= ref - pd.Timedelta(days=k)]
        g = x.get("total_games")
        out[f"m{k}"] = int(len(x))
        out[f"g{k}"] = int(g.sum()) if g is not None and len(x) else 0
    last = d.date.max() if len(d) else None
    out["days_since"] = int((ref - last).days) if last is not None and last == last else None
    return out


def underdog_flag(h: dict, p_fav: float, fav_is_p1: bool) -> bool:
    """⚑: faworyt (≥ 60%) wygrał ≤ 20% z co najmniej 3 spotkań z tym rywalem."""
    if h["n"] < 3 or p_fav < 0.6:
        return False
    wins = h["w1"] if fav_is_p1 else h["w2"]
    return wins / h["n"] <= 0.2
