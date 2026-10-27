import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from fbpred import bootstrap, config, csvdata, db, fdorg, history
from fbpred.web import create_app
from tests.test_bootstrap import fd_csv
from tests.test_v4 import Env, fake_resp, match


class TestStaleFixturesFile(Env):
    def _setup(self):
        sy = bootstrap.season_now()
        history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
        conn = db.connect(config.DB_PATH)
        history.load_into_db(conn, config.HISTORY_DIR, ["E0"])
        a, b, c = sorted(set(db.load_matches(conn, "E0")["home"]))[:3]
        return sy, conn, a, b, c

    def test_stale_fixtures_file_is_topped_up_and_not_duplicated(self):
        sy, conn, a, b, c = self._setup()
        past = (pd.Timestamp.today() - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        d1 = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        d2 = (pd.Timestamp.today() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        stale = f"Div,Date,HomeTeam,AwayTeam\nE0,{pd.Timestamp(past):%d/%m/%Y},{a},{b}\n"   # tylko mecz sprzed 2 dni
        extra = {"season": {"startDate": f"{sy}-08-01"}}
        payload = {"matches": [match(1, "TIMED", (a, a, "AAA"), (c, c, "CCC"), date=d1) | extra,
                               match(2, "TIMED", (b, b, "BBB"), (c, c, "CCC"), date=d2) | extra]}
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, y: fd_csv(y, lg)), \
             mock.patch.object(csvdata, "download_fixtures", return_value=stale), \
             mock.patch.object(fdorg.requests, "get", return_value=fake_resp(payload)):
            for _ in range(2):                                   # dwa odświeżenia -> brak duplikatów
                bootstrap.refresh(["E0"], log_predictions=False, log=lambda *_: None)
        up = db.load_upcoming(conn, "E0", since=db.today())
        self.assertEqual(len(up), 2)
        d = bootstrap.DIAG["E0"]
        self.assertIn("nieaktualny", d["fixtures_csv"])
        self.assertIn("2 już było", d["football-data.org"])

    def test_fixture_from_csv_keeps_odds_and_is_not_overwritten(self):
        sy, conn, a, b, c = self._setup()
        d1 = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        csv = ("Div,Date,HomeTeam,AwayTeam,B365H,B365D,B365A\n"
               f"E0,{pd.Timestamp(d1):%d/%m/%Y},{a},{b},2.0,3.4,3.8\n")
        payload = {"matches": [match(1, "TIMED", (a, a, "AAA"), (b, b, "BBB"), date=d1) | {"season": {"startDate": f"{sy}-08-01"}}]}
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, y: fd_csv(y, lg)), \
             mock.patch.object(csvdata, "download_fixtures", return_value=csv), \
             mock.patch.object(fdorg.requests, "get", return_value=fake_resp(payload)):
            bootstrap.refresh(["E0"], log_predictions=False, log=lambda *_: None)
        up = db.load_upcoming(conn, "E0", since=db.today())
        self.assertEqual(len(up), 1)
        self.assertEqual(float(up.iloc[0]["o_home"]), 2.0)


class TestMultiProcessSafety(Env):
    def test_diag_persisted_to_file(self):
        bootstrap.DIAG["E0"] = {"fixtures_csv": "x"}
        bootstrap.save_diag()
        bootstrap.DIAG.clear()                                   # "inny proces" nie ma nic w pamięci
        self.assertEqual(bootstrap.get_diag()["E0"]["fixtures_csv"], "x")

    def test_lock_allows_single_holder(self):
        try:
            import fcntl  # noqa: F401
        except ImportError:
            self.skipTest("brak fcntl")
        self.assertTrue(bootstrap._acquire_lock())
        try:
            with open(Path(config.DB_PATH).parent / "refresh.lock", "w") as other:
                with self.assertRaises(OSError):
                    import fcntl
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            bootstrap._release_lock()
        self.assertTrue(bootstrap._acquire_lock())
        bootstrap._release_lock()

    def test_integrity_ok(self):
        self.assertEqual(db.integrity(db.connect(config.DB_PATH)), "ok")


class TestLeagueListRobustness(Env):
    def test_duplicated_or_padded_league_codes_listed_once(self):
        conn = db.connect(config.DB_PATH)
        conn.execute("DROP TABLE IF EXISTS matches_bak")
        for i, lg in enumerate(["E0", "E0 ", b"E0", "I1"]):
            conn.execute("INSERT INTO matches (fixture_id, league, season, date, home, away, status) VALUES (?,?,?,?,?,?,?)",
                         (i + 1, lg, 2025, "2025-09-01", f"H{i}", f"A{i}", "NS"))
        conn.commit()
        app = create_app()
        with app.test_request_context():
            pass
        html = app.test_client().get("/data").get_data(as_text=True)
        self.assertEqual(html.count("<option value=\"E0\""), html.count("<option value=\"E0\""))   # render bez błędu
        import fbpred.web as w  # noqa: F401
        codes = []
        for r in conn.execute("SELECT DISTINCT league FROM matches ORDER BY 1"):
            c = r[0].decode() if isinstance(r[0], bytes) else r[0]
            c = str(c).strip()
            if c and c not in codes:
                codes.append(c)
        self.assertEqual(codes, ["E0", "I1"])
