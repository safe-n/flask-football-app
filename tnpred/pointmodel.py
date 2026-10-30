"""Model punkt -> gem -> set -> mecz (łańcuch Markowa, dokładnie, bez symulacji).

pa = szansa, że zawodnik A wygra punkt przy WŁASNYM serwisie, pb = to samo dla B.
Założenie upraszczające: punkty niezależne i jednakowe (brak „momentum”) - standard w modelach tenisowych;
w praktyce daje dobre O/U gemów i tie-breaki, gdy pa/pb są dobrze dobrane.
"""
from __future__ import annotations

from functools import lru_cache

from scipy.optimize import brentq


def p_hold(p: float) -> float:
    """Szansa utrzymania gema serwisowego przy szansie punktu p."""
    q = 1 - p
    deuce = p * p / (1 - 2 * p * q)
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


@lru_cache(maxsize=20_000)
def p_tiebreak(pa: float, pb: float, target: int = 7) -> float:
    """Szansa, że A wygra tie-break, gdy A serwuje pierwszy punkt (potem B, B, A, A, ...)."""
    x = pa * (1 - pb)          # A wygrywa obie piłki w parze (jedna przy serwisie każdego)
    y = (1 - pa) * pb
    deuce_a = x / (x + y) if x + y > 0 else 0.5
    probs = {(0, 0): 1.0}
    win = 0.0
    for n in range(0, 2 * target):          # numer punktu
        nxt: dict[tuple[int, int], float] = {}
        for (a, b), pr in probs.items():
            if a + b != n:
                continue
            if a == b and a >= target - 1:   # remis w końcówce -> wzór zamknięty
                win += pr * deuce_a
                continue
            srv_a = ((n + 1) // 2) % 2 == 0
            pw = pa if srv_a else 1 - pb
            for da, db, pp in ((1, 0, pw), (0, 1, 1 - pw)):
                na, nb = a + da, b + db
                if na >= target and na - nb >= 2:
                    win += pr * pp
                elif nb >= target and nb - na >= 2:
                    pass
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0.0) + pr * pp
        probs = {k: v for k, v in nxt.items()}
        if not probs:
            break
    return win


@lru_cache(maxsize=20_000)
def set_dist(pa: float, pb: float, a_serves_first: bool, tb_target: int = 7) -> tuple:
    """Rozkład wyniku seta: krotka ((gemy_A, gemy_B, prawd.), ...). 7-6 / 6-7 = tie-break."""
    ha, hb = p_hold(pa), p_hold(pb)
    probs = {(0, 0): 1.0}
    out: dict[tuple[int, int], float] = {}
    for _ in range(13):
        nxt: dict[tuple[int, int], float] = {}
        for (a, b), pr in probs.items():
            if a == 6 and b == 6:
                ptb = p_tiebreak(pa, pb, tb_target) if a_serves_first else 1 - p_tiebreak(pb, pa, tb_target)
                out[(7, 6)] = out.get((7, 6), 0.0) + pr * ptb
                out[(6, 7)] = out.get((6, 7), 0.0) + pr * (1 - ptb)
                continue
            srv_a = ((a + b) % 2 == 0) == a_serves_first
            pw = ha if srv_a else 1 - hb
            for na, nb, pp in ((a + 1, b, pw), (a, b + 1, 1 - pw)):
                done = (na >= 6 and na - nb >= 2) or (nb >= 6 and nb - na >= 2) or na == 7 or nb == 7
                if done:
                    out[(na, nb)] = out.get((na, nb), 0.0) + pr * pp
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0.0) + pr * pp
        probs = nxt
        if not probs:
            break
    return tuple((a, b, p) for (a, b), p in sorted(out.items()))


@lru_cache(maxsize=1_500)    # każdy wpis to pełny rozkład gemów - mały cache, bo Render ma 512 MB na piłkę+tenis
def match_dist(pa: float, pb: float, best_of: int = 3, final_tb: int = 7) -> dict:
    """Pełny rozkład meczu (średnia z dwóch możliwości, kto serwuje pierwszy).

    Zwraca: p_match, sety {„2-0”: p,...}, gemy {(gA, gB): p}, p_tb (≥1 tie-break), set1 (rozkład 1. seta).
    """
    need = best_of // 2 + 1
    res_sets: dict[str, float] = {}
    games: dict[tuple[int, int], float] = {}
    p_tb = 0.0
    for first_a in (True, False):
        # stan: (sety A, sety B, A serwuje pierwszy w secie, gemy A, gemy B, był TB) -> prawd.
        states = {(0, 0, first_a, 0, 0, False): 0.5}
        while states:
            nxt: dict = {}
            for (sa, sb, srv, ga, gb, tb), pr in states.items():
                last = sa == need - 1 and sb == need - 1
                for a, b, ps in set_dist(pa, pb, srv, final_tb if last else 7):
                    nsa, nsb = sa + (a > b), sb + (b > a)
                    ntb = tb or (a + b == 13)
                    nsrv = srv if (a + b) % 2 == 0 else not srv
                    key = (nsa, nsb, nsrv, ga + a, gb + b, ntb)
                    p = pr * ps
                    if nsa == need or nsb == need:
                        sc = f"{nsa}-{nsb}"
                        res_sets[sc] = res_sets.get(sc, 0.0) + p
                        g = (ga + a, gb + b)
                        games[g] = games.get(g, 0.0) + p
                        if ntb:
                            p_tb += p
                    else:
                        nxt[key] = nxt.get(key, 0.0) + p
            states = nxt
    s1: dict[tuple[int, int], float] = {}
    for first_a in (True, False):
        for a, b, ps in set_dist(pa, pb, first_a, 7):
            s1[(a, b)] = s1.get((a, b), 0.0) + 0.5 * ps
    p_match = sum(v for k, v in res_sets.items() if int(k.split("-")[0]) == need)
    return {"p_match": p_match, "sets": res_sets, "games": games, "p_tb": p_tb, "set1": s1}


def _r(x: float) -> float:
    return round(min(max(x, 0.30), 0.92), 3)


def p_match_bo3(pa: float, pb: float) -> float:
    return match_dist(_r(pa), _r(pb), 3, 7)["p_match"]


@lru_cache(maxsize=20_000)
def _solve(p_target: float, s0: float) -> float:
    lo, hi = -min(0.25, s0 - 0.31), min(0.25, 0.91 - s0)
    f = lambda d: p_match_bo3(s0 + d, s0 - d) - p_target  # noqa: E731
    if f(lo) > 0:
        return lo
    if f(hi) < 0:
        return hi
    return brentq(f, lo, hi, xtol=1e-4)


def serve_probs(p_match: float, s0: float) -> tuple[float, float]:
    """Dobiera pa = s0 + d, pb = s0 - d tak, by szansa wygrania meczu do 2 setów = p_match.

    s0 = średnia szansa punktu przy serwisie dla touru i nawierzchni (np. ATP trawa ~0,67, WTA mączka ~0,56).
    """
    p = round(min(max(p_match, 0.01), 0.99), 3)
    d = _solve(p, round(s0, 3))
    return _r(s0 + d), _r(s0 - d)


def summarize(dist: dict, best_of: int) -> dict:
    """Rynki z rozkładu: zwycięzca, sety, gemy (O/U, handicap), tie-break, 1. set."""
    g = dist["games"]
    tot: dict[int, float] = {}
    diff: dict[int, float] = {}
    for (a, b), p in g.items():
        tot[a + b] = tot.get(a + b, 0.0) + p
        diff[a - b] = diff.get(a - b, 0.0) + p
    mean = sum(k * v for k, v in tot.items())
    lines = [18.5, 19.5, 20.5, 21.5, 22.5, 23.5, 24.5] if best_of == 3 else [33.5, 35.5, 36.5, 37.5, 38.5, 39.5, 41.5]
    over = {f"{x}": sum(v for k, v in tot.items() if k > x) for x in lines}
    hcp = {}
    for h in (1.5, 2.5, 3.5, 4.5, 5.5):  # handicap gemów zawodnika 1: -h oznacza „wygra o więcej niż h gemów”
        hcp[f"-{h}"] = sum(v for k, v in diff.items() if k > h)
        hcp[f"+{h}"] = sum(v for k, v in diff.items() if k > -h)
    s1 = dist["set1"]
    s1_tot = {}
    for (a, b), p in s1.items():
        s1_tot[a + b] = s1_tot.get(a + b, 0.0) + p
    need = best_of // 2 + 1
    sets = dict(sorted(dist["sets"].items(), key=lambda kv: (-int(kv[0].split("-")[0]), kv[0])))
    win_set1 = 1 - sets.get(f"0-{need}", 0.0)   # zawodnik 1 wygra co najmniej seta
    win_set2 = 1 - sets.get(f"{need}-0", 0.0)
    return {
        "p1": dist["p_match"], "p2": 1 - dist["p_match"], "sets": sets,
        "games_mean": mean, "games_pmf": dict(sorted(tot.items())), "over": over,
        "hcp": hcp, "diff_mean": sum(k * v for k, v in diff.items()), "p_tb": dist["p_tb"],
        "set1_p1": sum(p for (a, b), p in s1.items() if a > b),
        "set1_over9.5": sum(v for k, v in s1_tot.items() if k > 9.5),
        "set1_tb": s1.get((7, 6), 0.0) + s1.get((6, 7), 0.0),
        "win_a_set": {"1": win_set1, "2": win_set2},
        "straight": sets.get(f"{need}-0", 0.0) + sets.get(f"0-{need}", 0.0),
    }
