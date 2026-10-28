import unittest

import pandas as pd

from fbpred import stats
from fbpred.synthetic import generate


class TestHighlights(unittest.TestCase):
    def test_base_rates_and_highlights(self):
        df = generate(n_seasons=3, seed=2, league="E0", start_year=2023, with_upcoming=False)
        base = stats.base_rates(df)
        for k in stats.HL_KEYS:
            self.assertIn(k, base)
            self.assertTrue(0 < base[k] < 1)
        pred = {"goals": {"btts_yes": base["btts"] + 0.09},
                "halves": {"draw_ht": base["draw_ht"] + 0.01, "draw_2h": base["draw_2h"] + 0.09,
                           "draw_either_half": 0.99, "draw_ht_or_ft": base["draw_ht_or_ft"], "draw_ft": base["draw_ft"] + 0.2}}
        hl = stats.highlights(pred, base)
        self.assertTrue(hl["btts"] and hl["draw_2h"] and hl["draw_either_half"] and hl["draw_ft"])
        self.assertFalse(hl["draw_ht"] or hl["draw_ht_or_ft"])
        self.assertFalse(any(stats.highlights(pred, {}).values()))        # brak średnich -> brak wyróżnień


if __name__ == "__main__":
    unittest.main()
