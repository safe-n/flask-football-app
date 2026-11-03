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


_IDX: dict = {}
_REC_COLS = ("date", "tournament", "surface", "round", "winner", "loser", "comment", "total_games",
             "w1", "l1", "w2", "l2", "w3", "l3", "w4", "l4", "w5", "l5")


def _index(df: pd.DataFrame) -> dict:
    """Indeks zawodnik -> numery wierszy + kolumny jako zwykłe tablice; budowany raz na wersję danych
    (zamiast przeszukiwać i konwertować 25 tys. meczów przy każdej karcie meczu)."""
    key = (id(df), len(df))
    idx = _IDX.get(key)
    if idx is None:
        _IDX.clear()
        rows: dict = {}
        for i, (t, w, l) in enumerate(zip(df.tour.astype(str), df.winner.astype(str), df.loser.astype(str))):
            rows.setdefault((t, w), []).append(i)
            rows.setdefault((t, l), []).append(i)
        cols = {}
        for c in _REC_COLS:
            if c in df.columns:
                v = df[c]
                cols[c] = (v.astype(str) if str(v.dtype) == "category" else v).to_numpy()
        idx = {"rows": rows, "cols": cols}
        _IDX[key] = idx
    return idx


def _rows(df: pd.DataFrame, tour: str, name: str):
    return _index(df)["rows"].get((str(tour), str(name)), [])


def _rec(df: pd.DataFrame, i: int) -> dict:
    cols = _index(df)["cols"]
    r = {c: a[i] for c, a in cols.items()}
    r["date"] = pd.Timestamp(r["date"])
    return r


def player_matches(df: pd.DataFrame, tour: str, name: str, before=None) -> pd.DataFrame:
    d = df.iloc[_rows(df, tour, name)]
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
    both = sorted(set(_rows(df, tour, p1)) & set(_rows(df, tour, p2)), reverse=True)   # wiersze są po dacie
    rows = []
    for r in (_rec(df, i) for i in both):
        won = r["winner"] == p1
        rows.append({"res": "W" if won else "P",
                     "tip": f"{r['date']:%Y-%m-%d} {r['tournament']} ({r['surface']}, {r['round']}): {_score(r, not won)}"})
    w = sum(1 for r in rows if r["res"] == "W")
    return {"n": len(rows), "w1": w, "w2": len(rows) - w, "rows": rows[:n], "html": chips(rows[:n])}


def form(df: pd.DataFrame, tour: str, name: str, n: int = 10, surface: str | None = None) -> dict:
    picked = []
    for i in reversed(_rows(df, tour, name)):        # od najnowszego
        if surface and _index(df)["cols"]["surface"][i] != surface:
            continue
        picked.append(i)
        if len(picked) >= n:
            break
    rows = []
    for r in (_rec(df, i) for i in picked):
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
