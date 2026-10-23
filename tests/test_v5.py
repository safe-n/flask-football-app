import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fbpred import config, db, fatigue as fat, history, notify, params, rest
from fbpred.backtest import walk_forward
from fbpred.cli import main as cli_main
from fbpred.predictor import MatchPredictor, format_prediction
from fbpred.synthetic import generate
from fbpred.web import create_app


def rows_of(df):
    d = df.copy()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in d.columns]
    return d[cols].astype(object).where(d[cols].notna(), None).to_dict("records")


def mini(rows):
    """rows: (date, home, away) -> ramka meczów do kalendarza."""
    return pd.DataFrame({"date": pd.to_datetime([r[0] for r in rows]), "home": [r[1] for r in rows], "away": [r[2] for r in rows]})


class TestCalendar(unittest.TestCase):
    def test_days_since_and_flags(self):
        cal = rest.Calendar.from_matches(mini([("2026-10-17", "A", "B"), ("2026-10-24", "A", "C")]))
        self.assertEqual(cal.days_since("A", "2026-10-24"), (7, "L"))
        self.assertEqual(cal.days_since("B", "2026-10-21"), (4, "L"))
        self.assertEqual(cal.days_since("A", "2026-10-10"), (None, None))       # brak wcześniejszego meczu
        self.assertEqual(cal.days_since("Nikt", "2026-10-24"), (None, None))
        i = cal.info("A", "B", "2026-10-20")
        self.assertTrue(i["home_short"] and i["away_short"])                      # 3 dni
        self.assertFalse(cal.info("A", "B", "2026-10-23")["home_short"])          # 6 dni od 17.10 = normalny tydzień
        self.assertTrue(cal.info("A", "B", "2026-10-25")["home_short"])           # 1 dzień po meczu z 24.10
        self.assertFalse(cal.info("A", "Nikt", "2026-10-20")["away_short"])       # brak danych = neutralnie

    def test_champions_league_resolved_by_name(self):
        conn = db.connect(":memory:")
        db.upsert_matches(conn, [
            dict(fixture_id=1, league="CL", season=2026, date="2026-10-21", home="Manchester City FC", away="Real Madrid", status="FT", hg=2, ag=1),
            dict(fixture_id=2, league="CL", season=2026, date="2026-10-22", home="Napoli", away="Arsenal FC", status="FT", hg=0, ag=0)])
        league = mini([("2026-10-17", "Man City", "Arsenal"), ("2026-10-17", "Chelsea", "Liverpool")])
        cal = rest.build_calendar(league, conn)
        self.assertTrue(cal.has_cl)
        i = cal.info("Man City", "Chelsea", "2026-10-24")                         # LM 3 dni wcześniej vs tylko liga 7 dni
        self.assertEqual((i["home_days"], i["home_tag"], i["home_cl"], i["home_short"]), (3, "CL", True, True))
        self.assertEqual((i["away_days"], i["away_cl"], i["away_short"]), (7, False, False))


class TestStats(unittest.TestCase):
    def test_poisson_offset_recovers_coefficients(self):
        rng = np.random.default_rng(1)
        n = 40000
        x = (rng.random(n) < 0.3).astype(float)
        off = np.log(rng.uniform(0.8, 2.0, n))
        y = rng.poisson(np.exp(off + 0.1 - 0.2 * x))
        beta, se = fat.poisson_offset(y.astype(float), off, np.column_stack([x, np.ones(n)]))
        self.assertAlmostEqual(beta[0], -0.2, delta=3 * se[0])
        self.assertAlmostEqual(beta[1], 0.1, delta=3 * se[1])
        self.assertLess(se[0], 0.03)


class TestFatigueDetection(unittest.TestCase):
    """Test z zasadą: wykryj prawdziwy efekt, nie zgłaszaj nieistniejącego."""

    def _run(self, effect):
        df = generate(n_seasons=5, seed=31, with_upcoming=False, midweek_every=3, rest_effect=effect)
        res = walk_forward(df, 380, 56, progress=False)
        feats = rest.Calendar.from_matches(df).features(res)
        sides = fat.side_frame(res, feats, "E0")
        t = fat.mean_shift_test(sides)
        return t, fat.holdout_gain(sides), fat.uncertainty_test(res, feats)

    def test_real_effect_is_found_and_adopted(self):
        t, ho, _ = self._run(-0.25)
        row = t[t["klucz"] == "own_short"].iloc[0]
        self.assertLess(row["z"], -fat.Z_MIN)
        self.assertEqual(row["wniosek"], "ISTOTNE")
        self.assertGreater(ho["gain_per_100"], 0)
        coefs = fat.significant_coefs(t, ho)
        self.assertIn("own_short", coefs)
        self.assertLess(coefs["own_short"], 0)

    def test_no_effect_adopts_nothing(self):
        t, ho, u = self._run(0.0)
        self.assertTrue((t["z"].abs() < fat.Z_MIN).all())
        self.assertEqual(fat.significant_coefs(t, ho), {})
        self.assertIn("nieistotna", u["wniosek"])

    def test_holdout_blocks_significant_but_useless_coefficients(self):
        t = pd.DataFrame([{"klucz": "own_short", "z": -4.0, "wspolczynnik": -0.1}])
        self.assertEqual(fat.significant_coefs(t, {"gain_per_100": -0.01}), {})
        self.assertEqual(fat.significant_coefs(t, {"gain_per_100": 0.2}), {"own_short": -0.1})


class TestPredictorRestAndAdjust(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = generate(n_seasons=3, seed=4, with_upcoming=False)
        cls.cal = rest.Calendar.from_matches(cls.df)
        cls.date = (cls.df["date"].max() + pd.Timedelta(days=2))        # 2 dni po ostatniej kolejce = krótka przerwa dla grających wtedy
        last = cls.df[cls.df["date"] == cls.df["date"].max()].iloc[0]
        cls.h, cls.a = last["home"], last["away"]

    def test_rest_info_always_visible_but_xg_unchanged_without_coefficients(self):
        base = MatchPredictor(self.df).predict(self.h, self.a)
        P = MatchPredictor(self.df, calendar=self.cal)
        p = P.predict(self.h, self.a, date=self.date)
        self.assertTrue(p["rest"]["home_short"] and p["rest"]["away_short"])
        self.assertEqual(p["xg"], base["xg"])                              # bez współczynników: tylko informacja
        self.assertEqual(p["rest"]["factors"], (1.0, 1.0))
        self.assertIn("krótka przerwa", format_prediction(p))

    def test_significant_coefficients_scale_expected_goals(self):
        base = MatchPredictor(self.df).predict(self.h, self.a)
        P = MatchPredictor(self.df, calendar=self.cal, fatigue={"own_short": -0.2, "opp_short": 0.1})
        p = P.predict(self.h, self.a, date=self.date)
        f = np.exp(-0.2 + 0.1)                                              # obie drużyny zmęczone
        self.assertAlmostEqual(p["rest"]["factors"][0], f, places=3)
        self.assertAlmostEqual(p["xg"]["home"], base["xg"]["home"] * f, delta=0.02)
        self.assertLess(p["xg"]["home"], base["xg"]["home"])
        self.assertLess(p["goals"]["over_2.5"], base["goals"]["over_2.5"])  # mniej goli -> mniejsze szanse na over
        self.assertGreater(p["halves"]["draw_ht"], base["halves"]["draw_ht"])  # i częstsze remisy do przerwy
        no_date = P.predict(self.h, self.a)                                # bez daty nie ma korekty
        self.assertNotIn("rest", no_date)
        self.assertEqual(no_date["xg"], base["xg"])

    def test_manual_adjustment(self):
        P = MatchPredictor(self.df)
        base = P.predict(self.h, self.a)
        p = P.predict(self.h, self.a, adj=(0.8, 1.1))
        self.assertAlmostEqual(p["xg"]["home"], base["xg"]["home"] * 0.8, delta=0.02)
        self.assertAlmostEqual(p["xg"]["away"], base["xg"]["away"] * 1.1, delta=0.02)
        self.assertLess(p["1x2"]["1"], base["1x2"]["1"])
        self.assertEqual(p["manual_adj"], (0.8, 1.1))
        self.assertIn("ręczna korekta", format_prediction(p))


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES)
        config.DB_PATH, config.HISTORY_DIR = Path(self.tmp.name) / "x.db", Path(self.tmp.name) / "history"
        config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = False, ["E0"]

    def tearDown(self):
        config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = self.old
        self.tmp.cleanup()


class TestWebCliNotify(Env):
    def _seed(self):
        df = generate(n_seasons=3, seed=8, league="E0", with_upcoming=False)
        conn = db.connect(config.DB_PATH)
        db.upsert_matches(conn, rows_of(df))
        history.save_matches(rows_of(df), config.HISTORY_DIR)
        last = df[df["date"] == df["date"].max()].iloc[0]
        nxt = (df["date"].max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        db.upsert_matches(conn, [dict(fixture_id=9999999, league="E0", season=int(last["season"]), date=nxt,
                                      home=last["home"], away=last["away"], status="NS")])
        return last, nxt

    def test_pages_show_rest_warning_and_accept_adjustments(self):
        last, nxt = self._seed()
        c = create_app().test_client()
        page = c.get("/?league=E0").data.decode()
        self.assertIn("krótka przerwa", page)
        self.assertIn(f"date={nxt}", page)                                  # karta linkuje do podglądu z datą
        m = c.get(f"/match?league=E0&home={last['home']}&away={last['away']}&date={nxt}&adj_h=0.8&adj_a=1.1").data.decode()
        self.assertIn("Odpoczynek i korekty", m)
        self.assertIn("Ręczna korekta xG", m)
        self.assertEqual(c.get(f"/match?league=E0&home={last['home']}&away={last['away']}&adj_h=abc").status_code, 200)

    def test_notify_mentions_short_rest(self):
        last, nxt = self._seed()
        conn = db.connect(config.DB_PATH)
        P, p = params.build_predictor(db.load_matches(conn, "E0"), "E0")
        pred = P.predict(last["home"], last["away"], date=nxt)
        self.assertIn("krótka przerwa", notify.format_match(pred, {"date": nxt}, []))

    def test_cli_fatigue_test_runs_and_saves_parameters(self):
        df = generate(n_seasons=4, seed=31, league="E0", with_upcoming=False, midweek_every=3, rest_effect=-0.25)
        db.upsert_matches(db.connect(config.DB_PATH), rows_of(df))
        cli_main(["fatigue-test", "--leagues", "E0", "--min-train", "380", "--step", "84", "--apply"])
        saved = json.loads((config.DB_PATH.parent / "params_E0.json").read_text())
        self.assertIn("fatigue", saved)
        self.assertTrue(set(saved["fatigue"]) <= set(fat.TERMS))
        P, _ = params.build_predictor(db.load_matches(db.connect(config.DB_PATH), "E0"), "E0")
        self.assertEqual(P.fatigue, saved["fatigue"] or {})
        self.assertIsNotNone(P.calendar)


if __name__ == "__main__":
    unittest.main()
