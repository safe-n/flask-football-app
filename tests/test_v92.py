import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fbpred import config, csvdata, db, fdorg, kickoff


class TestKickoff(unittest.TestCase):
    def test_csv_time_uk_to_utc(self):
        # zima: UK = UTC; lato: UK = UTC+1
        self.assertEqual(csvdata._kickoff_utc("15:00", pd.Timestamp("2026-12-05")), "2026-12-05 15:00")
        self.assertEqual(csvdata._kickoff_utc("15:00", pd.Timestamp("2026-07-05")), "2026-07-05 14:00")
        self.assertIsNone(csvdata._kickoff_utc(None, pd.Timestamp("2026-07-05")))
        self.assertIsNone(csvdata._kickoff_utc("brak", pd.Timestamp("2026-07-05")))
        self.assertIsNone(csvdata._kickoff_utc(float("nan"), pd.Timestamp("2026-07-05")))

    def test_parse_csv_has_kickoff(self):
        txt = "Div,Date,Time,HomeTeam,AwayTeam\nE0,05/12/2026,15:00,Arsenal,Chelsea\nE0,06/12/2026,,Fulham,Everton\n"
        rows = csvdata.parse_csv(txt, "E0", only_div=True)
        self.assertEqual(rows[0]["kickoff"], "2026-12-05 15:00")
        self.assertIsNone(rows[1]["kickoff"])

    def test_fdorg_kickoff(self):
        self.assertEqual(fdorg._kickoff("2026-11-05T20:00:00Z"), "2026-11-05 20:00")
        self.assertIsNone(fdorg._kickoff(None))

    def test_when_statuses(self):
        now = pd.Timestamp("2026-11-05 18:00", tz="UTC")
        w = kickoff.when("2026-11-05 20:00", "2026-11-05", now)
        self.assertEqual((w["status"], w["time"], w["badge"]), ("future", "21:00", "za 2 h 0 min"))   # Warszawa = UTC+1
        self.assertEqual(kickoff.when("2026-11-05 18:30", "2026-11-05", now)["status"], "soon")
        self.assertEqual(kickoff.when("2026-11-05 17:00", "2026-11-05", now)["status"], "live")
        self.assertEqual(kickoff.when("2026-11-05 12:00", "2026-11-05", now)["badge"], "zakończony?")
        n = kickoff.when(None, "2026-11-05", now)                                   # bez godziny: tylko dzień
        self.assertEqual((n["time"], n["status"]), ("", "today"))
        self.assertIn("godz. nieznana", n["label"])
        self.assertEqual(kickoff.when(float("nan"), "2026-11-04", now)["status"], "past")


class TestDb(unittest.TestCase):
    def test_migration_and_coalesce(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        import sqlite3
        c = sqlite3.connect(path)
        c.executescript(db.SCHEMA.replace(",\n    kickoff TEXT", ""))                       # baza sprzed 0.9.2
        c.close()
        conn = db.connect(path)                                                     # stara baza dostaje kolumnę kickoff
        self.assertIn("kickoff", {r[1] for r in conn.execute("PRAGMA table_info(matches)")})
        self.assertNotIn("kickoff", db.COLUMNS)                                     # pliki history/*.csv bez zmian
        row = dict(fixture_id=1, league="E0", season=2026, date="2026-11-05", home="A", away="B", kickoff="2026-11-05 20:00")
        db.upsert_matches(conn, [row])
        db.upsert_matches(conn, [{**row, "kickoff": None}])                         # None nie kasuje godziny
        self.assertEqual(conn.execute("SELECT kickoff FROM matches").fetchone()[0], "2026-11-05 20:00")


class TestPages(unittest.TestCase):
    def setUp(self):
        self._old = config.DB_PATH
        config.DB_PATH = Path(tempfile.mkdtemp()) / "k.db"

    def tearDown(self):
        config.DB_PATH = self._old

    def test_coupon_top_pdf_link(self):
        from fbpred.web import create_app
        html = create_app().test_client().get("/coupon?league=E0").get_data(as_text=True)
        self.assertIn('id="pdftop"', html)
        self.assertIn("Eksport PDF", html)

    def test_index_shows_time_and_status(self):
        from fbpred.synthetic import generate
        from fbpred.web import create_app
        df = generate(n_seasons=3, seed=11, league="E0", start_year=2023, with_upcoming=True)
        rows = []
        for r in df.to_dict("records"):
            r = {k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
            r["date"] = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
            rows.append(r)
        tom = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        for i, r in enumerate([r for r in rows if r.get("hg") is None][:3]):
            r["date"] = tom
            r["kickoff"] = f"{tom} 1{i}:30"
        db.upsert_matches(db.connect(config.DB_PATH), rows)
        c = create_app().test_client()
        for _ in range(40):
            html = c.get("/?league=E0").get_data(as_text=True)
            if "class=\"card\"" in html:
                break
            import time
            time.sleep(0.5)
        self.assertRegex(html, r"\d\d\.\d\d 1[0-9]:30")                  # godzina lokalna w nagłówku meczu
        self.assertIn("<h2>" + tom + "</h2>", html)


if __name__ == "__main__":
    unittest.main()
