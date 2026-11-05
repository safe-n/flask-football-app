import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd

from fbpred import config, db, extsource, leagues, sportsdb
from fbpred.synthetic import generate


def ev(i, day, home, away, hs=None, as_=None, status="Not Started", ts=None, **kw):
    return {"idEvent": str(i), "dateEvent": day, "strHomeTeam": home, "strAwayTeam": away, "intHomeScore": hs, "intAwayScore": as_,
            "strStatus": status, "strTimestamp": ts, "strTime": "19:45:00", "strPostponed": "no", **kw}


class TestParse(unittest.TestCase):
    def test_finished_upcoming_and_skips(self):
        f = sportsdb.parse_event(ev(1, "2026-09-24", "Roma", "Lille", "2", "1", "Match Finished", "2026-09-24T19:45:00"), "EL", 2026)
        self.assertEqual((f["status"], f["hg"], f["ag"], f["kickoff"], f["season"]), ("FT", 2, 1, "2026-09-24 19:45", 2026))
        n = sportsdb.parse_event(ev(2, "2026-11-27", "Roma", "Porto"), "EL", 2026)
        self.assertEqual((n["status"], n["hg"]), ("NS", None))
        self.assertIsNone(sportsdb.parse_event(ev(3, "2026-08-20", "A", "B", "1", "0", "Match Finished"), "EL", 2026))   # eliminacje
        self.assertIsNone(sportsdb.parse_event(ev(4, "2027-03-12", "A", "B", "1", "1", "AET"), "EL", 2026))              # dogrywka
        self.assertIsNone(sportsdb.parse_event(ev(5, "2026-10-01", "A", "B", "1", "0", "Live"), "EL", 2026))             # w trakcie
        self.assertIsNone(sportsdb.parse_event(ev(6, "2026-10-01", "A", "B", strPostponed="yes"), "EL", 2026))
        self.assertIsNone(sportsdb.parse_event(ev(7, "2026-10-01", "", "B"), "EL", 2026))
        self.assertIsNone(sportsdb.parse_event(ev(8, "2026-10-01", "A", "B", "1", "0", "Not Started"), "EL", 2026))      # niespójne
        self.assertEqual(sportsdb.kickoff_of({"dateEvent": "2026-10-01", "strTime": "21:00:00"}), "2026-10-01 21:00")
        self.assertIsNone(sportsdb.kickoff_of({"dateEvent": "2026-10-01", "strTime": "00:00:00"}))

    def test_fixture_id_stable_and_matches_other_sources(self):
        import zlib
        r = sportsdb.parse_event(ev(1, "2026-09-24", "Roma", "Lille"), "EL", 2026)
        self.assertEqual(r["fixture_id"], zlib.crc32(b"EL|2026-09-24|Roma|Lille") & 0x7FFFFFFF)

    def setUp(self):
        self._pause, sportsdb.ROUND_PAUSE = sportsdb.ROUND_PAUSE, 0

    def tearDown(self):
        sportsdb.ROUND_PAUSE = self._pause

    def test_fetch_merges_and_dedupes_when_truncated(self):
        calls = []
        season_ev = [ev(i, "2026-09-24", f"H{i}", f"A{i}", "1", "0", "Match Finished") for i in range(100)]   # ucięte do 100

        def fake(path, params=None):
            calls.append(path)
            if path == "eventsseason.php":
                return season_ev
            if path == "eventsround.php":
                return [ev(100 + params["r"], "2026-10-01", "X", f"Y{params['r']}")] if params["r"] <= 2 else []
            return [season_ev[0]]                                                    # past/next: duplikat
        old, sportsdb._get = sportsdb._get, fake
        try:
            rows = sportsdb.fetch_season("EL", 2026)
        finally:
            sportsdb._get = old
        self.assertEqual(len(rows), 102)                                              # 100 + 2 z kolejek, bez duplikatów
        self.assertIn("eventsround.php", calls)

    def test_probe_runs_offline(self):
        out = []
        old_p, sportsdb.ROUND_PAUSE = sportsdb.ROUND_PAUSE, 0
        old, sportsdb._get = sportsdb._get, lambda path, params=None: [ev(1, "2026-09-24", "A", "B", "1", "0", "Match Finished", "2026-09-24T19:45:00")]
        try:
            sportsdb.probe("EL", 2026, out=out.append)
        finally:
            sportsdb._get = old
            sportsdb.ROUND_PAUSE = old_p
        self.assertTrue(any("1 z wynikiem" in x for x in out))
        self.assertTrue(any("liga w danych" in x for x in out))


class TestRateLimit(unittest.TestCase):
    def test_partial_result_kept(self):
        old_p, sportsdb.ROUND_PAUSE = sportsdb.ROUND_PAUSE, 0

        def fake(path, params=None):
            if path == "eventsseason.php":
                return [ev(1, "2026-09-24", "A", "B", "1", "0", "Match Finished")]
            if params["r"] == 1:
                return [ev(2, "2026-10-01", "C", "D", "2", "2", "Match Finished")]
            raise sportsdb.RateLimited("limit")
        old, sportsdb._get = sportsdb._get, fake
        try:
            rows = sportsdb.fetch_season("EL", 2026)
            self.assertEqual(len(rows), 2)                                           # nie tracimy tego, co się udało
            self.assertTrue(extsource.partial())
            sportsdb._get = lambda path, params=None: (_ for _ in ()).throw(sportsdb.RateLimited("limit"))
            with self.assertRaises(sportsdb.RateLimited):                            # nic nie pobrano -> błąd
                sportsdb.fetch_season("EL", 2026)
        finally:
            sportsdb._get = old
            sportsdb.ROUND_PAUSE = old_p


class TestLeagueFilter(unittest.TestCase):
    def test_conference_league_rejected(self):
        e = ev(1, "2026-09-24", "A", "B", "1", "0", "Match Finished", strLeague="UEFA Conference League")
        self.assertIsNone(sportsdb.parse_event(e, "EL", 2026))
        e["strLeague"] = "UEFA Europa League"
        self.assertIsNotNone(sportsdb.parse_event(e, "EL", 2026))
        e.pop("strLeague")
        self.assertIsNotNone(sportsdb.parse_event(e, "EL", 2026))                    # brak nazwy: nie odrzucamy


class TestRouting(unittest.TestCase):
    def test_catalog_and_router(self):
        self.assertIn("EL", leagues.NO_CSV)
        self.assertEqual(leagues.name("EL"), "Liga Europy")
        self.assertTrue(extsource.enabled("EL"))                                      # bez tokenu football-data.org
        self.assertEqual(extsource.source_name("EL"), "TheSportsDB")
        self.assertEqual(extsource.source_name("CL"), "football-data.org")


class TestPagesWithoutHalves(unittest.TestCase):
    """EL nie ma połówek, kartek ani rożnych - żadna zakładka nie może się wywrócić."""
    def setUp(self):
        self._old = config.DB_PATH
        config.DB_PATH = Path(tempfile.mkdtemp()) / "el.db"

    def tearDown(self):
        config.DB_PATH = self._old

    def test_pages(self):
        from fbpred.web import create_app
        df = generate(n_seasons=3, seed=11, league="E0", start_year=2023, with_upcoming=True)
        rows = []
        tom = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        for r in df.to_dict("records"):
            r = {k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
            r["date"] = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
            r.update(league="EL", hg_ht=None, ag_ht=None, h_yellow=None, a_yellow=None, h_corners=None, a_corners=None,
                     h_sot=None, a_sot=None, referee=None, stats_done=0)
            if r.get("hg") is None:
                r["date"], r["kickoff"] = tom, f"{tom} 19:45"
            rows.append(r)
        db.upsert_matches(db.connect(config.DB_PATH), rows)
        c = create_app().test_client()
        home, away = next((r["home"], r["away"]) for r in rows if r.get("hg") is None)
        for url in ("/?league=EL", f"/match?league=EL&home={home}&away={away}", "/suggest?league=EL&leagues=EL&days=3",
                    "/recent?league=EL&days=30", "/draws?league=EL", "/export/recent.pdf?days=30"):
            for _ in range(60):
                r = c.get(url)
                if r.status_code != 503:
                    break
                time.sleep(0.5)
            self.assertEqual(r.status_code, 200, url)


if __name__ == "__main__":
    unittest.main()
