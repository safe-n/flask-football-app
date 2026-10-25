import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import pandas as pd

from fbpred import bootstrap, config, csvdata, db, fdorg, history, recent
from tests.test_bootstrap import fd_csv
from tests.test_v4 import fake_resp, match

config.FDORG_PAUSE = 0.0
TODAY = pd.Timestamp.today().normalize()
d = lambda n: (TODAY + pd.Timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.FDORG_TOKEN, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES)
        config.DB_PATH, config.HISTORY_DIR = Path(self.tmp.name) / "x.db", Path(self.tmp.name) / "history"
        config.FDORG_TOKEN, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = "", False, ["E0"]
        bootstrap.DIAG.clear()
        sy = bootstrap.season_now()
        for y in (sy - 2, sy - 1):
            history.save_matches(csvdata.parse_csv(fd_csv(y), "E0", y), config.HISTORY_DIR)
        self.conn = db.connect(config.DB_PATH)
        history.load_into_db(self.conn, config.HISTORY_DIR, ["E0"])
        self.a, self.b = sorted(set(db.load_matches(self.conn, "E0")["home"]))[:2]
        self.fid = zlib.crc32(f"E0|{d(-1)}|{self.a}|{self.b}".encode()) & 0x7FFFFFFF   # jak w csvdata.parse_csv
        db.upsert_matches(self.conn, [dict(fixture_id=self.fid, league="E0", season=sy, date=d(-1), home=self.a,
                                           away=self.b, status="NS")])

    def tearDown(self):
        config.DB_PATH, config.HISTORY_DIR, config.FDORG_TOKEN, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = self.old
        self.tmp.cleanup()

    def payload(self):
        sy = bootstrap.season_now()
        m = match(5, "FINISHED", (self.a + " FC", self.a, "AAA"), (self.b + " FC", self.b, "BBB"),
                  {"home": 3, "away": 1}, {"home": 1, "away": 1}, date=d(-1))
        m["season"] = {"startDate": f"{sy}-08-01"}
        return {"matches": [m]}

    def refresh(self):
        with mock.patch.object(csvdata, "download", side_effect=OSError("x")), \
             mock.patch.object(csvdata, "download_fixtures", side_effect=OSError("x")):
            bootstrap.refresh(["E0"], log_predictions=False, log=lambda *_: None)


class TestFastResults(Env):
    def test_without_token_match_stays_pending_and_diag_explains(self):
        with mock.patch.object(fdorg.requests, "get") as get:
            self.refresh()
        get.assert_not_called()                                          # bez tokenu żadnych zapytań
        self.assertIn("wymagają tokenu", bootstrap.DIAG["E0"]["wyniki_szybkie"])
        self.assertTrue(db.load_matches(self.conn, "E0", finished_only=False).query("fixture_id == @self.fid")["hg"].isna().all())

    def test_with_token_result_is_filled_and_shows_in_recent(self):
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(fdorg.requests, "get", return_value=fake_resp(self.payload())) as get:
            self.refresh()
        self.assertEqual(get.call_count, 1)                              # jedno zapytanie na ligę
        row = self.conn.execute("SELECT hg, ag, hg_ht, ag_ht, status FROM matches WHERE fixture_id=?", (self.fid,)).fetchone()
        self.assertEqual(row, (3, 1, 1, 1, "FT"))
        self.assertIn("dopisano 1 z 1", bootstrap.DIAG["E0"]["wyniki_szybkie"])
        res = recent.recent_predictions(db.load_matches(self.conn, "E0"), days=3)
        self.assertIn(f"{self.a}|{self.b}", set(res["home"] + "|" + res["away"]))   # mecz wchodzi do 'Ostatnich'

    def test_later_csv_row_fills_same_record_without_duplicate(self):
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(fdorg.requests, "get", return_value=fake_resp(self.payload())):
            self.refresh()
        csv = ("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,HY,AY,HC,AC\n"
               f"E0,{pd.Timestamp(d(-1)):%d/%m/%Y},{self.a},{self.b},3,1,1,1,2,3,6,4\n")
        db.upsert_matches(self.conn, csvdata.parse_csv(csv, "E0", bootstrap.season_now()))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM matches WHERE home=? AND away=? AND date=?",
                                           (self.a, self.b, d(-1))).fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT h_yellow, h_corners FROM matches WHERE fixture_id=?", (self.fid,)).fetchone(), (2, 6))

    def test_api_error_does_not_break_refresh(self):
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(fdorg.requests, "get", return_value=fake_resp({}, 403)):
            self.refresh()
        self.assertIn("błąd", bootstrap.DIAG["E0"]["wyniki_szybkie"])

    def test_describe_exposes_pid(self):
        import os
        self.assertEqual(bootstrap.describe()["pid"], os.getpid())


if __name__ == "__main__":
    unittest.main()


class TestParamsLocation(unittest.TestCase):
    """Regresja: parametry z `tune` leżały w ignorowanym przez git data/, więc Render ich nie widział."""

    def test_saved_to_tracked_params_dir_and_read_back_with_legacy_fallback(self):
        from fbpred import params
        with tempfile.TemporaryDirectory() as tmp:
            old = (config.DB_PATH, config.PARAMS_DIR)
            config.DB_PATH, config.PARAMS_DIR = Path(tmp) / "data" / "x.db", Path(tmp) / "params"
            try:
                (Path(tmp) / "data").mkdir()
                (Path(tmp) / "data" / "params_E0.json").write_text('{"ridge": 7.0, "xi": 0.003}')   # stara lokalizacja
                self.assertEqual(params.load("E0")["ridge"], 7.0)                                  # nadal czytana lokalnie
                self.assertIn("dostrojone", params.describe("E0")["zrodlo"])
                f = params.save("E0", {"ridge": 15.0, "xi": 0.001, "blend_w": 0.3})
                self.assertEqual(f.parent, Path(tmp) / "params")                                   # zapis do params/
                self.assertEqual(params.load("E0")["ridge"], 15.0)                                 # params/ ma pierwszeństwo
                self.assertIn("DOMYŚLNE", params.describe("D1")["zrodlo"])                         # brak pliku -> jasny komunikat
            finally:
                config.DB_PATH, config.PARAMS_DIR = old

    def test_data_page_shows_parameter_source(self):
        from fbpred.web import create_app
        with tempfile.TemporaryDirectory() as tmp:
            old = (config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR)
            config.DB_PATH, config.HISTORY_DIR = Path(tmp) / "x.db", Path(tmp) / "history"
            config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR = False, ["E0"], Path(tmp) / "params"
            try:
                sy = bootstrap.season_now()
                history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
                page = create_app().test_client().get("/data?league=E0").data.decode()
                self.assertIn("Parametry modelu używane przez ten serwis", page)
                self.assertIn("DOMYŚLNE", page)
                self.assertIn("0.0019", page)                                   # xi nie może być zaokrąglone do 0
            finally:
                config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR = old
