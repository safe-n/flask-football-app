import sqlite3
import unittest

import numpy as np
import pandas as pd

from fbpred import csvdata, db
from fbpred.fetch import parse_fixture, parse_odds, parse_statistics
from fbpred.models import markets as mk
from fbpred.models.counts import CountModel, to_long
from fbpred.models.goals import DixonColes, score_matrix
from fbpred.odds import edge, implied_probs, kelly
from fbpred.predictor import MatchPredictor
from fbpred.synthetic import generate

DF = generate(n_seasons=3, seed=3, with_upcoming=False)


class TestGoals(unittest.TestCase):
    def test_matrix_sums_to_one(self):
        m = score_matrix(1.6, 1.1, rho=-0.1)
        self.assertAlmostEqual(m.sum(), 1.0, places=9)
        self.assertAlmostEqual(sum(mk.outcome_1x2(m).values()), 1.0, places=9)

    def test_total_pmf_matches_poisson_sum(self):
        m = score_matrix(1.0, 2.0, rho=0.0, max_goals=15)
        tot = mk.total_pmf(m)
        self.assertAlmostEqual(tot.sum(), 1.0, places=9)
        self.assertAlmostEqual(float(np.dot(np.arange(len(tot)), tot)), 3.0, places=2)

    def test_dc_recovers_strength_ordering(self):
        dc = DixonColes().fit(DF)
        self.assertGreater(dc.ha, 0.1)
        s = dc.strengths()
        self.assertEqual(len(s), 20)

    def test_unknown_team_uses_average(self):
        dc = DixonColes().fit(DF)
        lh, la = dc.lambdas("Nieznany FC", "Arsenal")
        self.assertTrue(lh > 0 and la > 0)


class TestCounts(unittest.TestCase):
    def test_yellow_referee_effect_sign(self):
        m = CountModel(use_ref=True, kmax=15).fit(to_long(DF, "h_yellow", "a_yellow"))
        self.assertGreater(m.alpha, 0)  # dane są nadmiernie rozproszone
        self.assertAlmostEqual(m.pmf(2.0).sum(), 1.0, places=9)
        # różne sędziowie dają różne oczekiwania
        vals = {r: m.mean("Arsenal", "Chelsea", 1, r) for r in list(m.r)[:5]}
        self.assertGreater(max(vals.values()) - min(vals.values()), 0.05)


class TestPredictor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.P = MatchPredictor(DF)

    def test_probabilities_consistent(self):
        p = self.P.predict("Man City", "Wolves", "M Oliver")
        self.assertAlmostEqual(sum(p["1x2"].values()), 1.0, places=2)
        self.assertAlmostEqual(sum(p["halves"]["htft"].values()), 1.0, places=2)
        h = p["halves"]
        self.assertGreaterEqual(h["draw_either_half"], max(h["draw_ht"], h["draw_2h"]))
        self.assertLessEqual(h["draw_both_halves"], min(h["draw_ht"], h["draw_2h"]))
        self.assertAlmostEqual(p["goals"]["over_2.5"] + p["goals"]["under_2.5"], 1.0, places=3)
        for key in ("yellow", "corners"):
            o = list(p[key]["over"].values())
            self.assertTrue(all(a >= b for a, b in zip(o, o[1:])))  # P(>linia) maleje

    def test_works_without_optional_columns(self):
        P = MatchPredictor(DF[["date", "home", "away", "hg", "ag", "referee"]])
        p = P.predict("Arsenal", "Chelsea")
        self.assertNotIn("yellow", p)
        self.assertNotIn("halves", p)


class TestOdds(unittest.TestCase):
    def test_margin_removal_and_kelly(self):
        q = implied_probs([2.0, 3.5, 4.0])
        self.assertAlmostEqual(sum(q), 1.0)
        self.assertAlmostEqual(edge(0.5, 2.2), 0.1)
        self.assertEqual(kelly(0.4, 2.0), 0.0)  # brak przewagi
        self.assertLessEqual(kelly(0.9, 3.0), 0.03)  # cap


class TestData(unittest.TestCase):
    def test_db_upsert_does_not_wipe_with_none(self):
        conn = db.connect(":memory:")
        db.upsert_matches(conn, [dict(fixture_id=1, league="X", date="2024-01-01", home="A", away="B",
                                      hg=2, ag=1, o_home=2.0)])
        db.upsert_matches(conn, [dict(fixture_id=1, league="X", date="2024-01-01", home="A", away="B",
                                      h_yellow=3)])
        r = conn.execute("SELECT hg, o_home, h_yellow FROM matches").fetchone()
        self.assertEqual(r, (2, 2.0, 3))

    def test_parse_football_data_csv(self):
        csv = ("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,Referee,HS,AS,HST,AST,HC,AC,HY,AY,HR,AR,"
               "B365H,B365D,B365A,PSCH,PSCD,PSCA,P>2.5,P<2.5\n"
               "E0,16/08/2024,Man United,Fulham,1,0,0,0,R Jones,14,10,5,2,7,8,2,1,0,0,1.6,4.2,5.5,1.62,4.1,5.4,1.7,2.2\n"
               "E0,17/08/2024,Ipswich,Liverpool,,,,,,,,,,,,,,,,3.0,3.5,2.2,,,,,\n")
        rows = csvdata.parse_csv(csv, "E0", 2024)
        self.assertEqual(len(rows), 2)
        r = rows[0]
        self.assertEqual((r["date"], r["hg"], r["hg_ht"], r["h_yellow"], r["h_corners"]), ("2024-08-16", 1, 0, 2, 7))
        self.assertEqual(r["o_home"], 1.62)  # preferuje Pinnacle zamknięcia
        self.assertEqual(rows[1]["status"], "NS")
        self.assertEqual(rows[1]["o_home"], 3.0)  # fallback na Bet365

    def test_parse_api_payloads(self):
        item = {"fixture": {"id": 7, "date": "2024-08-16T19:00:00+00:00", "referee": "Michael Oliver, England",
                            "status": {"short": "FT"}},
                "league": {"season": 2024}, "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
                "goals": {"home": 2, "away": 2}, "score": {"halftime": {"home": 1, "away": 0}}}
        r = parse_fixture(item, "39")
        self.assertEqual((r["referee"], r["hg_ht"], r["hg"]), ("Michael Oliver", 1, 2))
        st = parse_statistics([
            {"team": {"name": "A"}, "statistics": [{"type": "Yellow Cards", "value": None},
                                                  {"type": "Corner Kicks", "value": 6}]},
            {"team": {"name": "B"}, "statistics": [{"type": "Yellow Cards", "value": 3}]}], "A")
        self.assertEqual((st["h_yellow"], st["h_corners"], st["a_yellow"]), (0, 6, 3))
        o = parse_odds([{"bookmakers": [{"id": 8, "bets": [
            {"name": "Match Winner", "values": [{"value": "Home", "odd": "2.1"}, {"value": "Draw", "odd": "3.3"},
                                                {"value": "Away", "odd": "3.6"}]},
            {"name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "1.9"},
                                                    {"value": "Under 2.5", "odd": "1.95"}]}]}]}], 8)
        self.assertEqual((o["o_home"], o["o_over25"]), (2.1, 1.9))


if __name__ == "__main__":
    unittest.main()
