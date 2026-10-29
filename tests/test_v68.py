import unittest

import pandas as pd

from fbpred import recent
from fbpred.synthetic import generate


class TestRecentHalves(unittest.TestCase):
    def test_either_half_and_second_half_shown_and_settled(self):
        """Genoa–Juventus 2–0 (do przerwy 2–0, 2. połowa 0–0): remis w 2. połowie = TAK, HT lub 2H = TAK, remis HT i HT lub FT = nie."""
        df = generate(n_seasons=2, seed=4, league="E0", start_year=2024, with_upcoming=False).reset_index(drop=True)
        i = df["date"].idxmax()
        df.loc[i, ["hg", "ag", "hg_ht", "ag_ht"]] = [2, 0, 2, 0]
        res = recent.recent_predictions(df, days=10)
        self.assertFalse(res.empty)
        tab = recent.show_table(res)
        for col in ("remis_2H_%", "był_remis_2H", "HT_lub_2H_%", "był_HT_lub_2H"):
            self.assertIn(col, tab.columns)
        row = tab[(res["home"] == df.loc[i, "home"]).to_numpy() & (res["date"] == df.loc[i, "date"]).to_numpy()].iloc[0]
        self.assertEqual((row["był_remis_HT"], row["był_remis_2H"], row["był_HT_lub_2H"], row["był_HT_lub_FT"]),
                         ("nie", "TAK", "TAK", "nie"))

    def test_summary_mentions_halves_markets(self):
        df = generate(n_seasons=2, seed=4, league="E0", start_year=2024, with_upcoming=False)
        txt = recent.summary(recent.recent_predictions(df, days=10))
        self.assertIn("HT lub 2H: zaszło", txt)


if __name__ == "__main__":
    unittest.main()
