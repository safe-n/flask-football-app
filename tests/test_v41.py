import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fbpred import config, db, draws, ledger, params
from fbpred.backtest import DRAW_CALIB, bias_shift, bias_table, summarize, walk_forward
from fbpred.cli import main as cli_main
from fbpred.predictor import MatchPredictor, shift_prob
from fbpred.synthetic import generate
from fbpred.web import create_app

DF = generate(n_seasons=3, seed=17, league="E0", with_upcoming=True)
FIN = DF[DF.hg.notna()].copy()
UP = DF[DF.hg.isna()].copy()


def rows_of(df, recent=False):
    d = df.copy()
    if recent:   # przesuń daty tak, by nierozegrane mecze wypadły jutro (aplikacja ukrywa mecze z wcześniejszych dni)
        d["date"] = d["date"] + (pd.Timestamp.today().normalize() + pd.Timedelta(days=1) - d.loc[d.hg.isna(), "date"].min())
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in d.columns]
    return d[cols].astype(object).where(d[cols].notna(), None).to_dict("records")


class TestDrawMarkets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.P = MatchPredictor(FIN)

    def test_ht_or_ft_respects_probability_bounds(self):
        for h, a in [("Arsenal", "Chelsea"), ("Man City", "Wolves"), ("Everton", "Fulham")]:
            hv = self.P.predict(h, a)["halves"]
            lo, hi = max(hv["draw_ht"], hv["draw_ft"]), min(1.0, hv["draw_ht"] + hv["draw_ft"])
            self.assertGreaterEqual(hv["draw_ht_or_ft"], lo - 1e-3)
            self.assertLessEqual(hv["draw_ht_or_ft"], hi + 1e-3)
            self.assertGreaterEqual(hv["draw_either_half"], max(hv["draw_ht"], hv["draw_2h"]) - 1e-3)
            # inkluzja-wykluczenie: P(HT lub FT) = P(HT) + P(FT) - P(HT i FT)
            self.assertAlmostEqual(hv["draw_ht_or_ft"], hv["draw_ht"] + hv["draw_ft"] - hv["htft"]["X/X"], delta=0.012)

    def test_draw_probability_falls_with_more_goals_expected(self):
        """Reguła z rachunku: im więcej xG w połowie, tym rzadszy remis."""
        from scipy.stats import poisson
        k = np.arange(15)
        d = lambda lh, la: float((poisson.pmf(k, lh) * poisson.pmf(k, la)).sum())  # noqa: E731
        self.assertGreater(d(0.3, 0.3), d(0.6, 0.6))
        self.assertGreater(d(0.6, 0.6), d(1.0, 1.0))
        self.assertGreater(d(0.5, 0.5), d(0.8, 0.2))   # wyrównane mecze częściej remisują niż jednostronne

    def test_calibration_shift_moves_only_draw_markets(self):
        base = self.P.predict("Arsenal", "Chelsea")
        cal = MatchPredictor(FIN, calib={"draw_ht": -0.4, "draw_ht_or_ft": 0.3}).predict("Arsenal", "Chelsea")
        self.assertLess(cal["halves"]["draw_ht"], base["halves"]["draw_ht"])
        self.assertGreater(cal["halves"]["draw_ht_or_ft"], base["halves"]["draw_ht_or_ft"])
        self.assertEqual(cal["halves"]["draw_2h"], base["halves"]["draw_2h"])     # bez zmian
        self.assertEqual(cal["1x2"], base["1x2"])                                 # 1X2 nietknięte
        self.assertEqual(shift_prob(0.4, 0.0), 0.4)
        self.assertAlmostEqual(shift_prob(0.5, 1.0), 1 / (1 + np.exp(-1.0)), places=9)

    def test_draw_table_sorted_with_fair_odds_and_lift(self):
        up = UP.copy()
        t = draws.draw_table(self.P, FIN, up, "ht_or_ft", days=4000)
        self.assertEqual(len(t), len(UP))
        self.assertTrue(t["HT_lub_FT_%"].is_monotonic_decreasing)
        self.assertTrue(np.allclose(t["kurs_fair"], 100 / t["HT_lub_FT_%"], atol=0.02))
        self.assertIn("vs_liga_pp", t.columns)
        with self.assertRaises(ValueError):
            draws.draw_table(self.P, FIN, up, "nieznany")
        base = draws.base_rates(FIN)
        self.assertTrue(all(0 < v < 1 for v in base.values()))
        self.assertGreaterEqual(base["ht_or_ft"], max(base["ht"], base["ft"]))


class TestBacktestDrawMarkets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = walk_forward(FIN, min_train=380, step_days=42, progress=False)

    def test_new_markets_present_and_consistent(self):
        r = self.res
        for c in ("y_draw_either", "p_draw_either", "y_draw_htft", "p_draw_htft"):
            self.assertIn(c, r.columns)
        self.assertTrue((r["y_draw_either"] >= r["y_draw_ht"]).all())      # 'HT lub 2H' >= 'HT'
        self.assertTrue((r["y_draw_htft"] >= r["y_draw_ht"]).all())
        rynki = set(summarize(r)["rynek"])
        self.assertTrue({"Remis HT lub 2H", "Remis HT lub FT"} <= rynki)

    def test_bias_table_and_shift(self):
        bt = bias_table(self.res)
        self.assertIn("wniosek", bt.columns)
        self.assertIn("Remis HT lub FT", set(bt["rynek"]))
        # sztucznie zawyżony model: shift musi sprowadzić średnią do faktycznej częstości
        rng = np.random.default_rng(0)
        y = (rng.random(3000) < 0.40).astype(int)
        biased = pd.DataFrame({"y": y, "p": np.full(3000, 0.50)})
        s = bias_shift(biased, "y", "p")
        self.assertLess(s, -0.2)
        corrected = np.mean(1 / (1 + np.exp(-(np.log(0.5 / 0.5) + s))))
        self.assertAlmostEqual(corrected, y.mean(), places=3)
        fair = pd.DataFrame({"y": y, "p": np.full(3000, y.mean())})
        self.assertEqual(bias_shift(fair, "y", "p"), 0.0)                    # brak istotnego błędu -> brak korekty
        self.assertEqual(bias_shift(biased.head(50), "y", "p"), 0.0)         # mała próba -> brak korekty


class TestLedgerMigration(unittest.TestCase):
    OLD = """CREATE TABLE predictions (fixture_id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT,
        logged_at TEXT, model_version TEXT, p1 REAL, px REAL, p2 REAL, q1 REAL, qx REAL, q2 REAL, p_over25 REAL,
        p_btts REAL, p_draw_ht REAL, p_draw_2h REAL, o_home REAL, o_draw REAL, o_away REAL, o_over25 REAL,
        o_under25 REAL, payload TEXT)"""

    def test_old_database_is_migrated_and_roundtrips(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(self.OLD)
        conn.execute("INSERT INTO predictions (fixture_id, league, date, home, away, p1, px, p2) VALUES (1,'E0','2020-01-01','A','B',.4,.3,.3)")
        ledger.ensure(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
        self.assertTrue({"p_draw_either", "p_draw_htft"} <= cols)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)   # stare dane zostały
        # logowanie zapisuje nowe rynki, eksport/import zachowuje je
        db.connect(":memory:")
        mconn = db.connect(":memory:")
        db.upsert_matches(mconn, rows_of(DF))
        P = MatchPredictor(db.load_matches(mconn, "E0"))
        n = ledger.log_predictions(mconn, P, db.load_upcoming(mconn, "E0"), "E0")
        row = mconn.execute("SELECT p_draw_either, p_draw_htft FROM predictions").fetchone()
        self.assertTrue(all(v and 0 < v < 1 for v in row))
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "p.csv"
            self.assertEqual(ledger.export_csv(mconn, f), n)
            self.assertIn("p_draw_htft", pd.read_csv(f).columns)
            fresh = db.connect(":memory:")
            self.assertEqual(ledger.import_csv(fresh, f), n)
            old_csv = pd.read_csv(f).drop(columns=["p_draw_either", "p_draw_htft"])   # dziennik z wersji sprzed 0.4.1
            old_csv.to_csv(f, index=False)
            self.assertEqual(ledger.import_csv(db.connect(":memory:"), f), n)

    def test_track_summary_has_new_markets(self):
        conn = db.connect(":memory:")
        db.upsert_matches(conn, rows_of(DF))
        P = MatchPredictor(db.load_matches(conn, "E0"))
        up = db.load_upcoming(conn, "E0")
        ledger.log_predictions(conn, P, up, "E0")
        for fid in up["fixture_id"]:
            conn.execute("UPDATE matches SET hg=1, ag=1, hg_ht=1, ag_ht=0, status='FT' WHERE fixture_id=?", (int(fid),))
        conn.commit()
        tab, _ = ledger.track_summary(ledger.settled(conn, "E0"), base=ledger.league_base_rates(db.load_matches(conn, "E0")))
        self.assertTrue({"Remis HT lub 2H", "Remis HT lub FT"} <= set(tab["rynek"]))


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR)
        config.DB_PATH, config.HISTORY_DIR = Path(self.tmp.name) / "x.db", Path(self.tmp.name) / "history"
        config.PARAMS_DIR = Path(self.tmp.name) / "params"
        config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = False, ["E0"]

    def tearDown(self):
        config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR = self.old
        self.tmp.cleanup()


class TestWebAndTune(Env):
    def test_draws_page_and_match_sections(self):
        from fbpred import history
        history.save_matches(rows_of(DF, recent=True), config.HISTORY_DIR)
        db.upsert_matches(db.connect(config.DB_PATH), [r for r in rows_of(DF, recent=True) if r["status"] == "NS"])
        c = create_app().test_client()
        for market in draws.MARKETS:
            self.assertEqual(c.get(f"/draws?league=E0&market={market}&days=30").status_code, 200, market)
        page = c.get("/draws?league=E0&days=30").data.decode()
        self.assertIn("kurs_fair", page)
        self.assertIn("Remisy", page)
        self.assertEqual(c.get("/draws?league=E0&market=xyz").status_code, 400)
        m = c.get("/match?league=E0&home=Arsenal&away=Chelsea").data.decode()
        self.assertIn("Remis do przerwy LUB na koniec", m)
        self.assertIn("HT lub FT", c.get("/?league=E0").data.decode())

    def test_tune_saves_draw_shift_and_predictor_uses_it(self):
        conn = db.connect(config.DB_PATH)
        db.upsert_matches(conn, rows_of(DF))
        cli_main(["tune", "--league", "E0", "--min-train", "380", "--step", "63", "--ridges", "10", "--xis", "0.0019",
                  "--shot-weights", "0.5"])
        saved = json.loads((config.PARAMS_DIR / "params_E0.json").read_text())
        self.assertEqual(set(saved["draw_shift"]), set(DRAW_CALIB))
        self.assertTrue(all(isinstance(v, float) for v in saved["draw_shift"].values()))
        P, p = params.build_predictor(db.load_matches(conn, "E0"), "E0")
        self.assertEqual(P.calib, saved["draw_shift"])
        self.assertEqual(p["shot_weight"], saved["shot_weight"])


if __name__ == "__main__":
    unittest.main()
