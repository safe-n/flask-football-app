import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from fbpred import bootstrap, config, csvdata, db, fdorg, history, names, quality, stats
from fbpred.predictor import MatchPredictor
from fbpred.synthetic import generate
from fbpred.web import create_app, match_sections
from tests.test_bootstrap import fd_csv

config.FDORG_PAUSE = 0.0


def fake_resp(payload, status=200):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = lambda: None if status < 400 else (_ for _ in ()).throw(RuntimeError(f"HTTP {status}"))
    return r


def match(i, status, home, away, ft=None, ht=None, duration="REGULAR", regular=None, date="2025-09-17", refs=None):
    score = {"duration": duration, "fullTime": ft or {"home": None, "away": None}, "halfTime": ht or {"home": None, "away": None}}
    if regular:
        score["regularTime"] = regular
    return {"id": i, "utcDate": f"{date}T19:00:00Z", "status": status, "homeTeam": {"name": home[0], "shortName": home[1], "tla": home[2]},
            "awayTeam": {"name": away[0], "shortName": away[1], "tla": away[2]}, "score": score, "referees": refs or []}


MC = ("Manchester City FC", "Man City", "MCI")
AR = ("Arsenal FC", "Arsenal", "ARS")


class TestFdOrg(unittest.TestCase):
    def test_parse_variants(self):
        ok = fdorg.parse_match(match(1, "FINISHED", MC, AR, {"home": 2, "away": 1}, {"home": 1, "away": 0},
                                     refs=[{"name": "Szymon Marciniak", "type": "REFEREE"}]), "CL", 2025)
        self.assertEqual((ok["hg"], ok["ag"], ok["hg_ht"], ok["status"], ok["referee"]), (2, 1, 1, "FT", "Szymon Marciniak"))
        self.assertEqual(ok["fixture_id"], fdorg.ID_OFFSET + 1)
        self.assertEqual(ok["home"], "Man City")                       # shortName
        ns = fdorg.parse_match(match(2, "TIMED", MC, AR), "CL", 2025)
        self.assertEqual((ns["status"], ns["hg"]), ("NS", None))
        aet = fdorg.parse_match(match(3, "FINISHED", MC, AR, {"home": 3, "away": 2}, duration="EXTRA_TIME",
                                      regular={"home": 1, "away": 1}), "CL", 2025)
        self.assertEqual((aet["hg"], aet["ag"]), (1, 1))               # wynik z 90 minut, nie z dogrywki
        self.assertIsNone(fdorg.parse_match(match(4, "FINISHED", MC, AR, {"home": 3, "away": 2}, duration="PENALTY_SHOOTOUT"), "CL", 2025))
        self.assertIsNone(fdorg.parse_match(match(5, "POSTPONED", MC, AR), "CL", 2025))
        self.assertIsNone(fdorg.parse_match(match(6, "IN_PLAY", MC, AR), "CL", 2025))

    def test_resolver_maps_to_known_names(self):
        known = ["Man City", "Arsenal"]
        row = fdorg.parse_match(match(1, "TIMED", ("Manchester City FC", "Man City FC?", "MCI"), AR), "E0", 2026,
                                resolver=lambda c: names.resolve(c, known))
        self.assertEqual((row["home"], row["away"]), ("Man City", "Arsenal"))

    def test_fetch_season_uses_token_header_and_filters(self):
        payload = {"matches": [match(1, "FINISHED", MC, AR, {"home": 1, "away": 0}, {"home": 0, "away": 0}),
                               match(2, "CANCELLED", MC, AR), match(3, "SCHEDULED", AR, MC)]}
        with mock.patch.object(fdorg.requests, "get", return_value=fake_resp(payload)) as get:
            rows = fdorg.fetch_season("CL", 2025, token="TKN")
        self.assertEqual(len(rows), 2)
        self.assertEqual(get.call_args.kwargs["headers"]["X-Auth-Token"], "TKN")
        self.assertIn("/competitions/CL/matches", get.call_args.args[0])

    def test_errors_are_explicit(self):
        with self.assertRaises(fdorg.FdOrgError):
            fdorg.fetch_season("CL", 2025, token="")  # config.FDORG_TOKEN puste w testach
        with mock.patch.object(fdorg.requests, "get", return_value=fake_resp({}, 403)):
            with self.assertRaises(fdorg.FdOrgError) as cm:
                fdorg.fetch_season("CL", 2020, token="T")
            self.assertIn("plan", str(cm.exception))
        with self.assertRaises(fdorg.FdOrgError):
            fdorg.fetch_season("T1", 2025, token="T")  # liga bez kodu w football-data.org


class TestNamesAndLeagues(unittest.TestCase):
    def test_resolve_real_world_names(self):
        known = ["Man City", "Man United", "Nott'm Forest", "Brighton", "Tottenham", "Wolves", "Newcastle", "Leeds", "Coventry"]
        cases = {"Manchester United FC": "Man United", "Nottingham Forest FC": "Nott'm Forest",
                 "Brighton & Hove Albion FC": "Brighton", "Tottenham Hotspur FC": "Tottenham",
                 "Wolverhampton Wanderers FC": "Wolves", "Newcastle United FC": "Newcastle", "Leeds United FC": "Leeds",
                 "Coventry City FC": "Coventry"}
        for src, want in cases.items():
            self.assertEqual(names.resolve(src, known), want, src)
        self.assertIsNone(names.resolve("Real Betis Balompié", known))      # brak w znanych -> None, nie pomyłka

    def test_discovery_excludes_demo_and_auto_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in ("E0_2025.csv", "D1_2024.csv", "CL_2025.csv", "DEMO_2021.csv", "README.md"):
                (Path(tmp) / f).write_text("x")
            self.assertEqual(history.discover_leagues(tmp), ["CL", "D1", "E0"])
            self.assertEqual(history.resolve_leagues("auto", tmp), ["CL", "D1", "E0"])
            self.assertEqual(history.resolve_leagues("E0, SP1", tmp), ["E0", "SP1"])
        self.assertEqual(history.resolve_leagues("auto", "/nie/ma"), [config.DEFAULT_LEAGUE])


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV, config.FDORG_TOKEN, config.BOOTSTRAP_LEAGUES,
                    config.AUTO_BOOTSTRAP)
        config.DB_PATH = Path(self.tmp.name) / "x.db"
        config.HISTORY_DIR = Path(self.tmp.name) / "history"
        config.LEDGER_CSV = Path(self.tmp.name) / "ledger" / "p.csv"
        config.FDORG_TOKEN, config.BOOTSTRAP_LEAGUES, config.AUTO_BOOTSTRAP = "", [], False
        bootstrap.DIAG.clear()

    def tearDown(self):
        (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV, config.FDORG_TOKEN, config.BOOTSTRAP_LEAGUES,
         config.AUTO_BOOTSTRAP) = self.old
        self.tmp.cleanup()


class TestBootstrapScenarios(Env):
    def test_missing_season_in_history_is_filled(self):
        """Dokładnie luka ze zrzutu: w historii brak jednego sezonu w środku."""
        sy = bootstrap.season_now()
        for y in (sy - 3, sy - 2):                                   # brakuje sy-1 (jak sezonu 2025 u użytkownika)
            history.save_matches(csvdata.parse_csv(fd_csv(y), "E0", y), config.HISTORY_DIR)
        asked = []
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, y: asked.append(y) or fd_csv(y, lg)):
            bootstrap.ensure_data(["E0"], years=4, log=lambda *_: None)
        self.assertEqual(sorted(asked), [sy - 1, sy])                # tylko brakujące, bez ponownego pobierania reszty
        conn = db.connect(config.DB_PATH)
        self.assertEqual(sorted(bootstrap.seasons_in_db(conn, "E0")), [sy - 3, sy - 2, sy - 1, sy])

    def test_upcoming_falls_back_to_football_data_org_with_resolved_names(self):
        """Scenariusz ze zrzutu: fixtures.csv bez meczów ligi -> terminarz z football-data.org z nazwami jak w bazie."""
        sy = bootstrap.season_now()
        history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
        conn = db.connect(config.DB_PATH)
        history.load_into_db(conn, config.HISTORY_DIR, ["E0"])
        team_a, team_b = sorted(set(db.load_matches(conn, "E0")["home"]))[:2]     # prawdziwe nazwy z bazy
        future = (pd.Timestamp.today() + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
        payload = {"matches": [match(77, "TIMED", (team_a + " FC", team_a, "AAA"), (team_b + " FC", team_b, "BBB"),
                                     date=future) | {"season": {"startDate": f"{sy}-08-01"}}]}
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, y: fd_csv(y, lg)), \
             mock.patch.object(csvdata, "download_fixtures", return_value="Div,Date,HomeTeam,AwayTeam\n"), \
             mock.patch.object(fdorg.requests, "get", return_value=fake_resp(payload)):
            bootstrap.refresh(["E0"], log_predictions=False, log=lambda *_: None)
        up = db.load_upcoming(conn, "E0")
        self.assertEqual(len(up), 1)
        self.assertEqual((up.iloc[0]["home"], up.iloc[0]["away"]), (team_a, team_b))   # nazwy zgodne z bazą
        d = bootstrap.DIAG["E0"]
        self.assertIn("bez nadchodzących", d["fixtures_csv"])
        self.assertIn("ok: 1", d["football-data.org"])

    def test_diag_explains_missing_token(self):
        sy = bootstrap.season_now()
        history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, y: fd_csv(y, lg)), \
             mock.patch.object(csvdata, "download_fixtures", side_effect=OSError("timeout")):
            bootstrap.refresh(["E0"], log_predictions=False, log=lambda *_: None)
        d = bootstrap.DIAG["E0"]
        self.assertIn("błąd: timeout", d["fixtures_csv"])
        self.assertIn("brak tokenu", d["football-data.org"])

    def test_champions_league_pipeline(self):
        sy = bootstrap.season_now()
        fin = [match(i, "FINISHED", MC, AR, {"home": i % 3, "away": 1}, {"home": 0, "away": 1}, date=f"{sy}-{9 + i % 2:02d}-{10 + i % 9:02d}")
               for i in range(1, 25)]
        config.FDORG_TOKEN = "TKN"
        with mock.patch.object(fdorg.requests, "get", return_value=fake_resp({"matches": fin})):
            res = history.update_from_source(["CL"], [sy], config.HISTORY_DIR, log=lambda *_: None)
            self.assertEqual(res[0]["dodane"], 24)
            self.assertTrue((config.HISTORY_DIR / f"CL_{sy}.csv").exists())
            bootstrap.refresh(["CL"], log_predictions=False, log=lambda *_: None)
        self.assertIn("ok: 24", bootstrap.DIAG["CL"]["football-data.org"])
        config.FDORG_TOKEN = ""
        bootstrap.refresh(["CL"], log_predictions=False, log=lambda *_: None)
        self.assertIn("brak tokenu", bootstrap.DIAG["CL"]["football-data.org"])

    def test_leagues_auto_from_history(self):
        sy = bootstrap.season_now()
        for lg in ("E0", "D1"):
            history.save_matches(csvdata.parse_csv(fd_csv(sy - 1, lg), lg, sy - 1), config.HISTORY_DIR)
        self.assertEqual(bootstrap.leagues(), ["D1", "E0"])
        config.BOOTSTRAP_LEAGUES = ["E0"]                          # jawna lista wygrywa z auto
        self.assertEqual(bootstrap.leagues(), ["E0"])

    def test_predictions_logged_only_within_horizon(self):
        from fbpred import ledger
        sy = bootstrap.season_now()
        history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
        conn = db.connect(config.DB_PATH)
        history.load_into_db(conn, config.HISTORY_DIR, ["E0"])
        a, b = sorted(set(db.load_matches(conn, "E0")["home"]))[:2]
        soon, far = ((pd.Timestamp.today() + pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in (2, 60))
        db.upsert_matches(conn, [dict(fixture_id=1, league="E0", season=sy, date=soon, home=a, away=b, status="NS"),
                                 dict(fixture_id=2, league="E0", season=sy, date=far, home=b, away=a, status="NS")])
        with mock.patch.object(csvdata, "download", side_effect=OSError("x")), \
             mock.patch.object(csvdata, "download_fixtures", side_effect=OSError("x")):
            bootstrap.refresh(["E0"], log_predictions=True, log=lambda *_: None)
        self.assertEqual(ledger.pending(conn, "E0"), 1)             # tylko mecz za 2 dni, nie za 60


class TestStatsAndWeb(Env):
    def setUp(self):
        super().setUp()
        self.df = generate(n_seasons=3, seed=13, league="E0", with_upcoming=True)
        d = self.df.copy()
        d["date"] = d["date"].dt.strftime("%Y-%m-%d")
        cols = [c for c in db.COLUMNS if c in d.columns]
        self.rows = d[cols].astype(object).where(d[cols].notna(), None).to_dict("records")
        history.save_matches(self.rows, config.HISTORY_DIR)
        db.upsert_matches(db.connect(config.DB_PATH), [r for r in self.rows if r["status"] == "NS"])

    def test_referee_and_team_tables(self):
        fin = self.df[self.df.hg.notna()]
        P = MatchPredictor(fin)
        r = stats.referee_table(fin, P, seasons=2, min_matches=8)
        self.assertTrue((r["mecze"] >= 8).all())
        self.assertIn("mnoznik_model", r.columns)
        self.assertTrue(r["zolte_sr"].is_monotonic_decreasing)
        t = stats.team_table(fin, P, seasons=1)
        self.assertEqual(len(t), 20)
        self.assertTrue({"zolte_za", "rozne_za", "kartki_x", "rozne_x"} <= set(t.columns))
        old = fin.copy()                                           # drużyna spoza ostatniego sezonu znika z tabeli
        old.loc[old["season"] < old["season"].max(), "home"] = old["home"].replace("Arsenal", "Zombie FC")
        self.assertNotIn("Zombie FC", set(stats.team_table(old, MatchPredictor(old), 1)["druzyna"]))

    def test_web_pages(self):
        c = create_app().test_client()
        for url in ("/?league=E0", "/match?league=E0", "/stats?league=E0", "/stats?league=E0&view=teams&seasons=1",
                    "/strengths?league=E0", "/table?league=E0", "/data?league=E0", "/track?league=E0"):
            self.assertEqual(c.get(url).status_code, 200, url)
        page = c.get("/match?league=E0&home=Arsenal&away=Chelsea&referee=M+Oliver").data.decode()
        for needle in ("Żółte kartki", "Rzuty rożne", "Połowy", "Handicap gospodarzy", "Arsenal – Chelsea"):
            self.assertIn(needle, page)
        self.assertEqual(c.get("/match?league=E0&home=Nikt&away=Chelsea").status_code, 404)
        self.assertIn("E0 · Premier League", c.get("/stats?league=E0").data.decode())

    def test_strengths_page_lists_only_active_teams(self):
        old = [dict(r, fixture_id=900000 + i, season=2019, date="2019-09-01", home="Norwich", away="Watford", hg=1, ag=0)
               for i, r in enumerate(self.rows[:40])]
        db.upsert_matches(db.connect(config.DB_PATH), old)
        page = create_app().test_client().get("/strengths?league=E0").data.decode()
        self.assertIn("Arsenal", page)
        self.assertNotIn("Norwich", page)

    def test_data_page_shows_diagnostics_and_upcoming_counts(self):
        bootstrap.DIAG["E0"] = {"fixtures_csv": "błąd: timeout", "football-data.org": "brak tokenu"}
        page = create_app().test_client().get("/data?league=E0").data.decode()
        self.assertIn("Diagnostyka", page)
        self.assertIn("błąd: timeout", page)
        self.assertIn("nadchodzace", page)

    def test_match_sections_without_cards_data(self):
        fin = self.df[self.df.hg.notna()][["date", "home", "away", "hg", "ag", "hg_ht", "ag_ht", "referee"]]
        head, sections, notes = match_sections(MatchPredictor(fin).predict("Arsenal", "Chelsea"))
        self.assertTrue(notes)                                      # Liga Mistrzów z darmowego źródła: bez kartek/rożnych
        self.assertNotIn("Żółte", " ".join(t for t, _ in sections))


class TestQualityGap(unittest.TestCase):
    def test_gap_detected(self):
        df = generate(n_seasons=3, seed=2, with_upcoming=False)
        msgs = [m for _, m in quality.check(df[df.season != 2022])]
        self.assertTrue(any("brakujące sezony" in m and "2022" in m for m in msgs))
        self.assertTrue(any("sezony ciągłe" in m for _, m in quality.check(df)))


if __name__ == "__main__":
    unittest.main()
