import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from fbpred import bootstrap, config, csvdata, db, history, ledger
from fbpred.cli import main as cli_main
from fbpred.synthetic import generate
from fbpred.web import create_app
from tests.test_bootstrap import fd_csv

TODAY = pd.Timestamp.today().normalize()
d = lambda n: (TODAY + pd.Timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES,
                    config.GITHUB_TOKEN, config.FDORG_TOKEN)
        config.DB_PATH, config.HISTORY_DIR = Path(self.tmp.name) / "x.db", Path(self.tmp.name) / "history"
        config.LEDGER_CSV = Path(self.tmp.name) / "l.csv"
        config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.GITHUB_TOKEN, config.FDORG_TOKEN = False, ["E0"], "", ""
        bootstrap.DIAG.clear()
        # historia: 2 sezony; z nich bierzemy prawdziwe nazwy drużyn
        sy = bootstrap.season_now()
        for y in (sy - 2, sy - 1):
            history.save_matches(csvdata.parse_csv(fd_csv(y), "E0", y), config.HISTORY_DIR)
        self.conn = db.connect(config.DB_PATH)
        history.load_into_db(self.conn, config.HISTORY_DIR, ["E0"])
        self.a, self.b, self.c, self.e = sorted(set(db.load_matches(self.conn, "E0")["home"]))[:4]

    def tearDown(self):
        (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES,
         config.GITHUB_TOKEN, config.FDORG_TOKEN) = self.old
        self.tmp.cleanup()

    def add_ns(self):
        """wczoraj (wynik jeszcze nie dotarł), dziś i jutro"""
        sy = bootstrap.season_now()
        db.upsert_matches(self.conn, [
            dict(fixture_id=11, league="E0", season=sy, date=d(-1), home=self.a, away=self.b, status="NS"),
            dict(fixture_id=12, league="E0", season=sy, date=d(0), home=self.c, away=self.e, status="NS"),
            dict(fixture_id=13, league="E0", season=sy, date=d(1), home=self.b, away=self.c, status="NS")])


class TestPastUnplayedMatches(Env):
    def test_load_upcoming_since_filters_yesterday(self):
        self.add_ns()
        self.assertEqual(len(db.load_upcoming(self.conn, "E0")), 3)
        up = db.load_upcoming(self.conn, "E0", since=db.today())
        self.assertEqual(sorted(up["fixture_id"]), [12, 13])

    def test_index_hides_yesterday_and_explains(self):
        self.add_ns()
        page = create_app().test_client().get("/?league=E0").data.decode()
        self.assertIn(f"{self.c} – {self.e}", page)                       # dziś
        self.assertIn(f"{self.b} – {self.c}", page)                       # jutro
        self.assertNotIn(f"{self.a} – {self.b}", page)                    # wczoraj: ukryty
        self.assertIn("Pominięto 1 mecz", page)

    def test_draws_page_excludes_yesterday(self):
        self.add_ns()
        page = create_app().test_client().get("/draws?league=E0&days=30").data.decode()
        self.assertNotIn(f"{self.a} – {self.b}", page)
        self.assertIn(f"{self.b} – {self.c}", page)

    def test_table_simulation_still_counts_unplayed_yesterday(self):
        """Dla symulacji sezonu mecz bez wyniku nadal jest do rozegrania - nie wolno go gubić."""
        from fbpred.predictor import MatchPredictor
        from fbpred.simulate import simulate_table
        self.add_ns()
        df = db.load_matches(self.conn, "E0")
        self.conn.execute("UPDATE matches SET season=? WHERE hg IS NULL", (int(df["season"].max()),))  # ten sam sezon co rozegrane
        self.conn.commit()
        _, info = simulate_table(df, MatchPredictor(df), db.load_upcoming(self.conn, "E0"), n=200)
        self.assertEqual(info["pozostalo_meczow"], 3)

    def test_refresh_logs_no_predictions_for_matches_already_played(self):
        self.add_ns()
        with mock.patch.object(csvdata, "download", side_effect=OSError("x")), \
             mock.patch.object(csvdata, "download_fixtures", side_effect=OSError("x")):
            bootstrap.refresh(["E0"], log_predictions=True, log=lambda *_: None)
        got = {r[0] for r in self.conn.execute("SELECT fixture_id FROM predictions")}
        self.assertEqual(got, {12, 13})                                   # nie 11 (wczorajszy)

    def test_cli_log_skips_past_unless_forced(self):
        self.add_ns()
        cli_main(["log", "--league", "E0"])
        self.assertEqual({r[0] for r in self.conn.execute("SELECT fixture_id FROM predictions")}, {12, 13})
        cli_main(["log", "--league", "E0", "--include-past"])
        self.assertEqual(ledger.stats(self.conn, "E0")["w_bazie"], 3)


if __name__ == "__main__":
    unittest.main()
