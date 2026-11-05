"""Styl zawodnika: skłonność do tie-breaków ponad to, co wynika z siły (Elo/rynek) i nawierzchni.

Model punktowy zna tylko szansę zwycięstwa, więc mecz dwóch „serwujących wież” i dwóch „ścianiarzy” o tej samej różnicy
Elo dostawał ten sam % tie-breaka. Tu liczymy dla każdego zawodnika średnią różnicę „było TB - model przewidywał”
z ostatnich N meczów, mocno ściągniętą do zera przy małej próbie (k meczów „wirtualnych” na poziomie średniej):

    styl = suma(TB - p_tb_modelu z N ostatnich meczów) / (n + k)
    p_tb' = logistic(logit(p_tb) + b * (styl1 + styl2))

Walidacja (uczone 2023-2025, test 2026, 4671 meczów): ATP log-loss TB 0.6702 -> 0.6631, WTA bez zysku (0.5425 -> 0.5433),
dlatego domyślnie tylko ATP. Przykład: Hurkacz 63% TB przy 44% oczekiwanych (233 mecze) -> styl ≈ +0.13.

Liczenie zajmuje kilkadziesiąt sekund, więc robi to Twój komputer (push-history / python -m tnpred style) i wysyła gotową
tabelę do gałęzi z historią; Render tylko ją wczytuje (tennis_params/style.json).
"""
from __future__ import annotations

import json
import math
from collections import defaultdict, deque

import pandas as pd

from . import config

DEFAULTS = {"b": 3.45, "N": 80, "k": 40, "tours": ["ATP"]}


def path():
    return config.PARAMS_DIR / "style.json"


def load() -> dict:
    p = path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return {**DEFAULTS, **d}
        except (ValueError, OSError):
            pass
    return {**DEFAULTS, "players": {}}


def save(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_text(d), encoding="utf-8")


def to_text(d: dict) -> str:
    return json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True)


def compute(m, tours=None, years: float = 3, N: int | None = None, k: float | None = None, b: float | None = None,
            min_matches: int = 10) -> dict:
    """Liczy styl TB z historii modelu `m` (TennisModel). Residua liczone względem modelu BEZ stylu."""
    from . import backtest
    tours = list(tours or DEFAULTS["tours"])
    N = int(N or DEFAULTS["N"])
    k = float(k if k is not None else DEFAULTS["k"])
    b = float(b if b is not None else DEFAULTS["b"])
    since = m.df.date.max() - pd.Timedelta(days=int(365 * years)) if len(m.df) else None
    players: dict = {}
    counts: dict = {}
    for t in tours:
        bt = backtest.rows(m, tour=t, since=since)
        if bt.empty:
            continue
        bt = bt[bt.completed & bt.p_tb.notna()].sort_values("date")
        hist = defaultdict(lambda: deque(maxlen=N))
        for r in bt.itertuples():
            res = float(r.tb) - float(r.p_tb)
            hist[r.p1].append(res)
            hist[r.p2].append(res)
        players[t] = {pl: round(sum(h) / (len(h) + k), 4) for pl, h in hist.items() if len(h) >= min_matches}
        counts[t] = {pl: len(h) for pl, h in hist.items() if len(h) >= min_matches}
    return {"b": b, "N": N, "k": k, "tours": tours, "players": players, "n": counts,
            "fitted_at": pd.Timestamp.utcnow().isoformat(), "last_match": str(m.df.date.max().date()) if len(m.df) else None}


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def adjust(st: dict, tour: str, p1: str, p2: str, p_tb: float) -> tuple[float, list]:
    """Zwraca (p_tb po korekcie, [(zawodnik, styl), ...]). Bez danych - bez zmian."""
    if not st or tour not in st.get("tours", []) or p_tb is None or p_tb != p_tb:
        return p_tb, []
    tab = st.get("players", {}).get(tour, {})
    info = [(n, float(tab[n])) for n in (p1, p2) if n in tab]
    if not info:
        return p_tb, []
    s = sum(v for _, v in info)
    return 1.0 / (1.0 + math.exp(-(_logit(p_tb) + st.get("b", DEFAULTS["b"]) * s))), info


def top(st: dict, tour: str = "ATP", n: int = 10) -> list[tuple[str, float, int]]:
    tab = st.get("players", {}).get(tour, {})
    cnt = st.get("n", {}).get(tour, {})
    srt = sorted(tab.items(), key=lambda kv: kv[1], reverse=True)
    return [(p, v, cnt.get(p, 0)) for p, v in srt[:n]] + [(p, v, cnt.get(p, 0)) for p, v in srt[-n:]]
