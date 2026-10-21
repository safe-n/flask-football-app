import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fbpred import csvdata, db, ledger, params, quality
from fbpred.backtest import best_blend, paired_ci, walk_forward
from fbpred.models import markets as mk
from fbpred.models.goals import score_matrix
from fbpred.odds import apply_blend, blend_probs, implied_probs, value_picks
from fbpred.predictor import MatchPredictor
from fbpred.simulate import simulate_table
from fbpred.synthetic import generate

DF = generate(n_seasons=3, seed=11, with_upcoming=True)
FIN = DF[DF.hg.notna()].copy()


class TestExtraMarkets(unittest.TestCase):
    def setUp(self):
        self.m = score_matrix(1.7, 1.0, rho=-0.05)

    def test_double_chance_and_dnb(self):
        p = mk.outcome_1x2(self.m)
        dc = mk.double_chance(self.m)
        self.assertAlmostEqual(dc["1X"], p["1"] + p["X"])
        dnb = mk.draw_no_bet(self.m)
        self.assertAlmostEqual(dnb["home"] + dnb["away"], 1.0)

    def test_asian_handicap(self):
        for line in (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0):
            a = mk.asian(self.m, line)
            self.assertAlmostEqual(sum(a.values()), 1.0, places=9)
        self.assertAlmostEqual(mk.asian(self.m, -0.5)["win"], mk.outcome_1x2(self.m)["1"], places=9)
        self.assertAlmostEqual(mk.asian(self.m, 0.0)["push"], mk.outcome_1x2(self.m)["X"], places=9)
        self.assertEqual(mk.asian(self.m, -0.5)["push"], 0.0)

    def test_clean_sheets_and_exact_total(self):
        cs = mk.clean_sheets(self.m)
        self.assertLessEqual(cs["home_win_to_nil"], cs["home_cs"] + 1e-12)  # wygrana do zera => czyste konto gospodarzy
        self.assertLessEqual(cs["away_win_to_nil"], cs["away_cs"] + 1e-12)
        self.assertAlmostEqual(cs["home_cs"], self.m[:, 0].sum())
        tot = mk.total_pmf(self.m)
        self.assertAlmostEqual(sum(mk.exact_total(tot).values()), 1.0, places=6)

    def test_predict_contains_extra(self):
        p = MatchPredictor(FIN).predict("Arsenal", "Chelsea", "M Oliver")
        self.assertIn("extra", p)
        self.assertAlmostEqual(p["extra"]["asian"]["-0.5"]["win"], p["1x2"]["1"], places=3)


class TestOdds(unittest.TestCase):
    def test_power_devig_sums_to_one_and_shrinks_longshot(self):
        odds = [1.5, 4.2, 7.5]
        pw, pr = implied_probs(odds, "power"), implied_probs(odds, "proportional")
        self.assertAlmostEqual(sum(pw), 1.0, places=9)
        self.assertLess(pw[2], pr[2])  # power obniża prawdopodobieństwo outsidera

    def test_blend_and_apply(self):
        self.assertAlmostEqual(sum(blend_probs([.5, .3, .2], [.4, .3, .3], 0.3)), 1.0)
        pred = {"1x2": {"1": .5, "X": .3, "2": .2}, "goals": {"over_2.5": .5, "under_2.5": .5, "btts_yes": .5, "btts_no": .5}}
        row = {"o_home": 2.0, "o_draw": 3.4, "o_away": 4.0}
        out = apply_blend(pred, row, 0.5)
        self.assertIn("1x2_blend", out)
        self.assertEqual(apply_blend({"1x2": pred["1x2"]}, {}, 0.5).get("1x2_blend"), None)
        self.assertIsInstance(value_picks(out, row), list)


class TestBacktestStats(unittest.TestCase):
    def test_paired_ci_sign(self):
        a = np.full(200, 0.9) + np.random.default_rng(0).normal(0, 0.05, 200)
        b = np.full(200, 1.0) + np.random.default_rng(1).normal(0, 0.05, 200)
        d, lo, hi = paired_ci(a, b)
        self.assertLess(d, 0)
        self.assertLess(hi, 0)

    def test_walk_forward_has_no_lookahead_and_blend(self):
        res = walk_forward(FIN, min_train=380, step_days=28, progress=False)
        self.assertTrue(res["date"].is_monotonic_increasing)
        self.assertGreater(len(res), 300)
        bl = best_blend(res)
        self.assertIsNotNone(bl)
        self.assertLessEqual(bl["logloss"], min(bl["model"], bl["rynek"]) + 1e-9)


class TestSimulate(unittest.TestCase):
    def test_probabilities_consistent(self):
        P = MatchPredictor(FIN)
        up = DF[DF.hg.isna()]
        tab, info = simulate_table(FIN, P, up, n=2000, n_european=4, n_relegated=3)
        self.assertEqual(len(tab), 20)
        self.assertAlmostEqual(tab["mistrz_%"].sum(), 100, delta=0.6)
        self.assertAlmostEqual(tab["top4_%"].sum(), 400, delta=1.5)
        self.assertAlmostEqual(tab["spadek_%"].sum(), 300, delta=1.5)
        self.assertEqual(info["pozostalo_meczow"], len(up))
        self.assertTrue((tab["pkt_oczek"] >= tab["pkt_teraz"]).all())

    def test_fallback_completes_round_robin(self):
        P = MatchPredictor(FIN)
        _, info = simulate_table(FIN, P, None, n=500)
        self.assertIn("dogrywka", info["metoda"])
        self.assertEqual(info["pozostalo_meczow"], 10)  # brakujące 10 meczów ostatniej kolejki


class TestLedger(unittest.TestCase):
    def test_log_then_settle(self):
        conn = db.connect(":memory:")
        d = DF.copy()
        d["date"] = d["date"].dt.strftime("%Y-%m-%d")
        cols = [c for c in db.COLUMNS if c in d.columns]
        db.upsert_matches(conn, d[cols].astype(object).where(d[cols].notna(), None).to_dict("records"))
        P = MatchPredictor(db.load_matches(conn, "DEMO"))
        up = db.load_upcoming(conn, "DEMO")
        self.assertEqual(ledger.log_predictions(conn, P, up, "DEMO", blend_w=0.3), len(up))
        self.assertEqual(ledger.pending(conn, "DEMO"), len(up))
        self.assertTrue(ledger.settled(conn, "DEMO").empty)
        for fid in up["fixture_id"]:
            conn.execute("UPDATE matches SET hg=2, ag=1, hg_ht=1, ag_ht=0, status='FT' WHERE fixture_id=?", (int(fid),))
        conn.commit()
        s = ledger.settled(conn, "DEMO")
        self.assertEqual(len(s), len(up))
        self.assertTrue((s["y"] == 0).all())
        tab, sim = ledger.track_summary(s)
        self.assertIn("1X2", set(tab["rynek"]))
        self.assertIn("ROI_%", sim)

    def test_purge_stale(self):
        conn = db.connect(":memory:")
        db.upsert_matches(conn, [dict(fixture_id=1, league="X", date="2000-01-01", home="A", away="B")])
        self.assertEqual(db.purge_stale_upcoming(conn), 1)


class TestQualityAndParams(unittest.TestCase):
    def test_quality_detects_problems(self):
        bad = FIN.copy()
        bad = pd.concat([bad, bad.iloc[[0]]])  # duplikat
        bad.loc[bad.index[5], "hg_ht"] = 9  # HT > FT
        bad.loc[bad.index[7], "away"] = "Man Utd"  # podobna nazwa do "Man United"
        issues = quality.check(bad)
        levels = [lvl for lvl, _ in issues]
        self.assertIn("BŁĄD", levels)
        msgs = " ".join(m for _, m in issues)
        self.assertIn("duplikaty (data+para): 1", msgs)

    def test_params_roundtrip(self):
        from fbpred import config
        with tempfile.TemporaryDirectory() as tmp:
            old = config.DB_PATH
            config.DB_PATH = Path(tmp) / "x.db"
            try:
                self.assertEqual(params.load("ZZ")["ridge"], 10.0)
                params.save("ZZ", {"ridge": 15.0, "xi": 0.001, "blend_w": 0.3})
                p = params.load("ZZ")
                self.assertEqual((p["ridge"], p["blend_w"]), (15.0, 0.3))
            finally:
                config.DB_PATH = old


class TestFixturesCsv(unittest.TestCase):
    def test_parse_fixtures_filters_div_and_derives_season(self):
        csv = ("Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,B365>2.5,B365<2.5\n"
               "E0,25/10/2026,15:00,Arsenal,Chelsea,1.9,3.6,4.2,1.8,2.0\n"
               "D1,25/10/2026,15:30,Bayern,Dortmund,1.5,4.5,6.0,1.4,2.9\n"
               "E0,02/03/2027,15:00,Spurs,Fulham,2.1,3.4,3.5,1.7,2.1\n")
        rows = csvdata.parse_csv(csv, "E0", None, only_div=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["season"] for r in rows], [2026, 2026])  # marzec 2027 -> sezon 2026
        self.assertTrue(all(r["status"] == "NS" and r["hg"] is None for r in rows))
        self.assertEqual(rows[0]["o_over25"], 1.8)


if __name__ == "__main__":
    unittest.main()
