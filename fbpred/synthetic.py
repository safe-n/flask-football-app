"""Generator syntetycznej ligi - do testów i demo bez dostępu do API.

Dane są SZTUCZNE (znane prawdziwe parametry), więc pozwalają sprawdzić, czy modele
potrafią je odzyskać i czy backtest działa. Nie wnioskuj z nich nic o prawdziwym futbolu.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models.goals import score_matrix
from .models import markets as mk

TEAMS = ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea",
         "Crystal Palace", "Everton", "Fulham", "Ipswich", "Leicester", "Liverpool",
         "Man City", "Man United", "Newcastle", "Nottm Forest", "Southampton", "Tottenham",
         "West Ham", "Wolves"]
REFEREES = ["M Oliver", "A Taylor", "P Tierney", "S Attwell", "A Madley", "C Pawson",
            "S Hooper", "R Jones", "D Coote", "T Robinson"]


def generate(n_seasons: int = 3, seed: int = 7, league: str = "DEMO", start_year: int = 2021,
             margin: float = 0.05, with_upcoming: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    T = len(TEAMS)
    att = rng.normal(0, 0.28, T)
    de = rng.normal(0, 0.22, T)
    cards = rng.normal(0, 0.12, T)
    corner_t = rng.normal(0, 0.10, T)
    ref_eff = dict(zip(REFEREES, rng.normal(0, 0.15, len(REFEREES))))
    mu, ha = 0.12, 0.25
    rows = []
    fid = 1
    for s in range(n_seasons):
        year = start_year + s
        pairs = [(i, j) for i in range(T) for j in range(T) if i != j]
        rng.shuffle(pairs)
        n_days = len(pairs) // 10
        last = s == n_seasons - 1
        for k, (i, j) in enumerate(pairs):
            day = k // 10
            date = pd.Timestamp(f"{year}-08-10") + pd.Timedelta(days=7 * day + int(rng.integers(0, 2)))
            upcoming = with_upcoming and last and day >= n_days - 1
            lh = np.exp(mu + ha + att[i] + de[j])
            la = np.exp(mu + att[j] + de[i])
            ref = REFEREES[int(rng.integers(0, len(REFEREES)))]
            row = dict(fixture_id=fid, league=league, season=year, date=date.strftime("%Y-%m-%d"),
                       home=TEAMS[i], away=TEAMS[j], referee=ref, status="NS" if upcoming else "FT")
            fid += 1
            # kursy z "prawdziwych" prawdopodobieństw + marża + szum
            m = score_matrix(lh, la)
            p = np.array(list(mk.outcome_1x2(m).values()))
            p = p * np.exp(rng.normal(0, 0.04, 3))
            p /= p.sum()
            odds = 1 / (p * (1 + margin))
            tot = mk.total_pmf(m)
            po = float(np.clip(mk.over(tot, 2.5) * np.exp(rng.normal(0, 0.04)), 0.05, 0.95))
            row.update(o_home=round(odds[0], 2), o_draw=round(odds[1], 2), o_away=round(odds[2], 2),
                       o_over25=round(1 / (po * (1 + margin / 2)), 2),
                       o_under25=round(1 / ((1 - po) * (1 + margin / 2)), 2))
            if not upcoming:
                hg, ag = int(rng.poisson(lh)), int(rng.poisson(la))
                hg_ht = int(rng.binomial(hg, 0.44))
                ag_ht = int(rng.binomial(ag, 0.44))
                rf = np.exp(ref_eff[ref])
                mh_y = 1.75 * np.exp(cards[i] - 0.5 * cards[j]) * rf * 0.97
                ma_y = 1.95 * np.exp(cards[j] - 0.5 * cards[i]) * rf * 1.03
                mh_c = 5.4 * np.exp(att[i] * 0.8 + corner_t[i] - 0.4 * de[j])
                ma_c = 4.5 * np.exp(att[j] * 0.8 + corner_t[j] - 0.4 * de[i])
                row.update(
                    hg=hg, ag=ag, hg_ht=hg_ht, ag_ht=ag_ht,
                    h_sot=int(rng.negative_binomial(25, 25 / (25 + lh / 0.30))),
                    a_sot=int(rng.negative_binomial(25, 25 / (25 + la / 0.30))),
                    h_yellow=int(rng.negative_binomial(8, 8 / (8 + mh_y))),
                    a_yellow=int(rng.negative_binomial(8, 8 / (8 + ma_y))),
                    h_corners=int(rng.negative_binomial(12, 12 / (12 + mh_c))),
                    a_corners=int(rng.negative_binomial(12, 12 / (12 + ma_c))),
                    stats_done=1,
                )
            rows.append(row)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["date", "fixture_id"]).reset_index(drop=True)
