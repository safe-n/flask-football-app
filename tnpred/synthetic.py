"""Dane syntetyczne w formacie tennis-data (tylko testy i podgląd TN_DEMO=1 - NIGDY do prawdziwych decyzji).

Zawodnicy mają ukrytą siłę serwisu/returnu (osobno na nawierzchniach); mecze symulujemy punkt po punkcie,
kursy = prawdziwa szansa + szum + marża. Dzięki temu backtest ma sens: model powinien zbliżać się do „prawdy”.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pointmodel import p_hold, p_tiebreak

FIRST = ["Adam", "Bruno", "Carlos", "Dan", "Emil", "Felix", "Gael", "Hugo", "Ivan", "Jan", "Karol", "Leo", "Marco",
         "Nico", "Oscar", "Pablo", "Rafa", "Stefan", "Tomas", "Uros", "Victor", "Will", "Yann", "Zane"]
LAST = ["Nowak", "Kowal", "Berg", "Costa", "Duval", "Elias", "Ferro", "Garin", "Holm", "Ivanov", "Jorge", "Kral",
        "Lind", "Moro", "Novak", "Ortiz", "Pavel", "Quinn", "Rossi", "Silva", "Tomic", "Ueda", "Vidal", "Weiss",
        "Xu", "Young", "Zeman", "Auger", "Bauer", "Cruz", "De Vries", "El Amin", "Fokin", "Gray", "Hart", "Ito"]
TOURN = [("Melbourne", "Hard", "Grand Slam"), ("Doha", "Hard", "ATP250"), ("Madrid", "Clay", "Masters 1000"),
         ("Rome", "Clay", "Masters 1000"), ("Paris", "Clay", "Grand Slam"), ("London", "Grass", "Grand Slam"),
         ("Halle", "Grass", "ATP500"), ("Montreal", "Hard", "Masters 1000"), ("New York", "Hard", "Grand Slam"),
         ("Vienna", "Hard", "ATP500"), ("Basel", "Hard", "ATP500"), ("Paris Indoor", "Hard", "Masters 1000")]
S0 = {"ATP": {"Hard": 0.645, "Clay": 0.625, "Grass": 0.67}, "WTA": {"Hard": 0.565, "Clay": 0.555, "Grass": 0.575}}


def _play_set(rng, ha, hb, pa, pb, a_first):
    a = b = 0
    srv_a = a_first
    while True:
        if a == 6 and b == 6:
            ptb = p_tiebreak(round(pa, 3), round(pb, 3)) if srv_a else 1 - p_tiebreak(round(pb, 3), round(pa, 3))
            return (7, 6) if rng.random() < ptb else (6, 7)
        if rng.random() < (ha if srv_a else 1 - hb):
            a += 1
        else:
            b += 1
        srv_a = not srv_a
        if (a >= 6 and a - b >= 2) or (b >= 6 and b - a >= 2) or a == 7 or b == 7:
            return a, b


def generate(n_players: int = 64, years: int = 3, tours=("ATP", "WTA"), seed: int = 7,
             end: pd.Timestamp | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = end or pd.Timestamp.today().normalize()
    rows = []
    for tour in tours:
        names = []
        while len(names) < n_players:
            n = f"{rng.choice(LAST)} {rng.choice(FIRST)[0]}."
            if n not in names:
                names.append(n)
        skill = rng.normal(0, 0.035, n_players)
        surf_adj = {s: rng.normal(0, 0.015, n_players) for s in ("Hard", "Clay", "Grass")}
        rank = np.argsort(np.argsort(-skill)) + 1
        start = end - pd.Timedelta(days=365 * years)
        day = start
        k = 0
        while day < end - pd.Timedelta(days=3):
            loc, surf, series = TOURN[k % len(TOURN)]
            k += 1
            bo = 5 if (series == "Grand Slam" and tour == "ATP") else 3
            draw = rng.choice(n_players, 32, replace=False)
            rnd_names = ["1st Round", "2nd Round", "Quarterfinals", "Semifinals", "The Final"]
            alive = list(draw)
            d = day
            for rn in rnd_names:
                nxt = []
                for i in range(0, len(alive) - 1, 2):
                    a, b = alive[i], alive[i + 1]
                    base = S0[tour][surf]
                    pa = base + skill[a] - skill[b] + surf_adj[surf][a] - surf_adj[surf][b]
                    pb = base + skill[b] - skill[a] + surf_adj[surf][b] - surf_adj[surf][a]
                    pa, pb = float(np.clip(pa, 0.4, 0.85)), float(np.clip(pb, 0.4, 0.85))
                    ha, hb = p_hold(pa), p_hold(pb)
                    need = bo // 2 + 1
                    sa = sb = 0
                    sets = []
                    a_first = rng.random() < 0.5
                    while sa < need and sb < need:
                        x, y = _play_set(rng, ha, hb, pa, pb, a_first)
                        sets.append((x, y))
                        if (x + y) % 2 == 1:
                            a_first = not a_first
                        sa, sb = sa + (x > y), sb + (y > x)
                    win, los = (a, b) if sa > sb else (b, a)
                    if sa < sb:
                        sets = [(y, x) for x, y in sets]
                    from .pointmodel import match_dist
                    pt = match_dist(round(pa, 3), round(pb, 3), bo, 10 if bo == 5 else 7)["p_match"]
                    pw = pt if win == a else 1 - pt
                    noisy = float(np.clip(pw + rng.normal(0, 0.04), 0.03, 0.97))
                    marg = 1.04
                    comment = "Completed"
                    if rng.random() < 0.012:
                        comment = "Retired"
                    row = {"date": d, "tour": tour, "tournament": f"{loc} Open", "location": loc, "series": series,
                           "court": "Outdoor", "surface": surf, "round": rn, "best_of": bo,
                           "winner": names[win], "loser": names[los], "wrank": float(rank[win]), "lrank": float(rank[los]),
                           "wsets": float(max(sa, sb)), "lsets": float(min(sa, sb)), "comment": comment,
                           "psw": round(1 / (noisy * marg), 2), "psl": round(1 / ((1 - noisy) * marg), 2),
                           "avgw": round(1 / (noisy * 1.06), 2), "avgl": round(1 / ((1 - noisy) * 1.06), 2)}
                    row["b365w"], row["b365l"], row["maxw"], row["maxl"] = row["avgw"], row["avgl"], row["psw"], row["psl"]
                    for i_s in range(5):
                        row[f"w{i_s + 1}"] = float(sets[i_s][0]) if i_s < len(sets) else np.nan
                        row[f"l{i_s + 1}"] = float(sets[i_s][1]) if i_s < len(sets) else np.nan
                    rows.append(row)
                    nxt.append(win)
                alive = nxt
                d = d + pd.Timedelta(days=1)
            day = day + pd.Timedelta(days=7)
    from .tdata import COLS, _from_norm
    df = pd.DataFrame(rows)
    return _from_norm(df[[c for c in COLS if c in df.columns]])


def upcoming(df: pd.DataFrame, n: int = 8, seed: int = 3) -> list[dict]:
    """Kilka „nadchodzących” meczów zawodników z bazy (do podglądu)."""
    rng = np.random.default_rng(seed)
    out = []
    today = pd.Timestamp.today().normalize()
    for tour in df.tour.unique():
        names = pd.concat([df[df.tour == tour].winner, df[df.tour == tour].loser]).value_counts().index[:24].tolist()
        rng.shuffle(names)
        for i in range(0, min(n, len(names) - 1), 2):
            o1 = round(float(rng.uniform(1.3, 3.2)), 2)
            o2 = round(1 / max(1.05 - 1 / o1, 0.08), 2)
            out.append({"source": "demo", "tour": tour, "tournament": "Demo Indoor", "surface": "Hard",
                        "best_of": 3, "date": (today + pd.Timedelta(days=1 + i // 4)).strftime("%Y-%m-%d"),
                        "p1": names[i], "p2": names[i + 1], "o1": o1, "o2": o2,
                        "total_line": 22.5, "o_over": 1.87, "o_under": 1.93})
    return out
