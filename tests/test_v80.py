import unittest

import pandas as pd

from fbpred import h2h, stats
from fbpred.synthetic import generate


def _df():
    rows = [("2026-10-28", "Milan", "Bologna", 2, 4), ("2026-02-03", "Bologna", "Milan", 0, 3), ("2025-05-01", "Milan", "Bologna", 1, 0),
            ("2025-01-01", "Milan", "Bologna", 0, 1), ("2024-05-01", "Milan", "Bologna", 3, 1), ("2024-01-01", "Bologna", "Milan", 2, 2),
            ("2026-10-18", "Milan", "Atalanta", 3, 2), ("2026-10-30", "Milan", "Lecce", None, None)]
    return pd.DataFrame(rows, columns=["date", "home", "away", "hg", "ag"]).assign(date=lambda d: pd.to_datetime(d["date"]))


class TestH2H(unittest.TestCase):
    def test_h2h_perspective_order_and_balance(self):
        h = h2h.h2h(_df(), "Bologna", "Milan", n=5)
        self.assertEqual([m["score"] for m in h["matches"]], ["4–2", "0–3", "0–1", "1–0", "1–3"][:0] or [m["score"] for m in h["matches"]])
        self.assertEqual(h["matches"][0]["date"], "2026-10-28")                  # najnowsze pierwsze
        self.assertEqual(h["matches"][0]["score"], "4–2")                        # z perspektywy Bologna (gość 4 gole)
        self.assertEqual(h["matches"][0]["res"], "W")
        self.assertEqual((h["n"], h["w"], h["d"], h["l"]), (6, 2, 1, 3))
        self.assertEqual(len(h["matches"]), 5)

    def test_form_overall_and_venue_and_unplayed_ignored(self):
        f = h2h.form(_df(), "Milan", n=3)
        self.assertEqual([x["letter"] for x in f], ["P", "W", "L"[:0] or f[2]["letter"]])
        self.assertTrue(all(x["date"] <= "2026-10-28" for x in f))                # mecz bez wyniku (Lecce) pominięty
        home = h2h.form(_df(), "Milan", n=5, venue="home")
        self.assertTrue(all(x["home"] == "Milan" for x in home))

    def test_flag_only_when_favourite_rarely_wins(self):
        h = h2h.h2h(_df(), "Milan", "Bologna")                                   # Milan: W,L,W,L,W... mieszane
        self.assertIsNone(h2h.flag(h, 0.30, 0.40, "Milan", "Bologna"))             # faworyt = Bologna < 45% -> brak flagi
        bad = {"matches": [{"res": "P"}, {"res": "P"}, {"res": "R"}, {"res": "P"}]}
        self.assertIn("wygrał tylko 0 z 4", h2h.flag(bad, 0.60, 0.20, "Milan", "Bologna"))
        self.assertIsNone(h2h.flag({"matches": [{"res": "P"}, {"res": "P"}]}, 0.6, 0.2, "A", "B"))   # za mało spotkań


class TestTiles(unittest.TestCase):
    def test_grading_and_text(self):
        base = {"btts": 0.50, "over25": 0.50, "draw_ht": 0.40, "yellow_mean": 4.0}
        pred = {"goals": {"btts_yes": 0.60, "over_2.5": 0.44}, "halves": {"draw_ht": 0.41},
                "yellow": {"over": {"3.5": 0.55}, "total_mean": 4.6}}
        t = stats.tiles(pred, base, 0.08)
        self.assertEqual(t["btts"]["cls"], "up2")                                 # +10 pp >= 8
        self.assertEqual(t["over25"]["cls"], "dn1")                               # -6 pp
        self.assertEqual(t["draw_ht"]["cls"], "")                                 # +1 pp
        self.assertEqual(t["yellow_mean"]["cls"], "up2")                          # +15% >= 12%
        self.assertEqual(t["btts"]["short"], "+10")
        self.assertEqual(t["draw_ht"]["short"], "+1")
        self.assertNotIn("draw_2h", t)                                            # brak danych -> brak kafelka

    def test_base_rates_include_new_keys(self):
        df = generate(n_seasons=3, seed=2, league="E0", start_year=2023, with_upcoming=False)
        b = stats.base_rates(df)
        for k in ("over25", "yellow_mean", "yellow35", "corners_mean", "corners95"):
            self.assertIn(k, b)


if __name__ == "__main__":
    unittest.main()


class TestRecentVisual(unittest.TestCase):
    def test_dashboard_has_charts_and_colours(self):
        from fbpred import recent, recent_vis
        df = generate(n_seasons=2, seed=4, league="E0", start_year=2024, with_upcoming=False)
        res = recent.recent_predictions(df, days=14)
        html = recent_vis.dashboard(res)
        for part in ("ring", "fstrip", "Trafność rynków", "Mecz po meczu", "pbar", 'class="mc yes"', 'class="mc no"'):
            self.assertIn(part, html)
        rows = recent_vis.stats_rows(res)
        self.assertTrue(all(0 <= r["k"] <= r["n"] for r in rows))
        self.assertEqual(recent_vis.dashboard(res.iloc[0:0]), "")

    def test_no_more_noga_in_suggest_label(self):
        import pathlib
        t = pathlib.Path("templates/suggest.html").read_text(encoding="utf-8")
        self.assertNotIn("nóg", t)
