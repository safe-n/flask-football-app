import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fbpred import bootstrap, config, csvdata, db
from fbpred.web import create_app  # import PRZED włączeniem AUTO_BOOTSTRAP (moduł tworzy app przy imporcie)
from fbpred.synthetic import generate


def fd_csv(year: int, league: str = "E0") -> str:
    """Sztuczny plik w formacie football-data.co.uk dla jednego sezonu."""
    df = generate(n_seasons=1, seed=year, league=league, start_year=year, with_upcoming=False)
    lines = ["Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,Referee,HC,AC,HY,AY,B365H,B365D,B365A"]
    for r in df.itertuples(index=False):
        lines.append(f"{league},{r.date:%d/%m/%Y},{r.home},{r.away},{int(r.hg)},{int(r.ag)},{int(r.hg_ht)},{int(r.ag_ht)},"
                     f"{r.referee},{int(r.h_corners)},{int(r.a_corners)},{int(r.h_yellow)},{int(r.a_yellow)},"
                     f"{r.o_home},{r.o_draw},{r.o_away}")
    return "\n".join(lines)


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.AUTO_BOOTSTRAP, config.HISTORY_DIR)
        config.DB_PATH = Path(self.tmp.name) / "football.db"
        config.HISTORY_DIR = Path(self.tmp.name) / "history"      # pusta historia: test nie zależy od plików w repo
        config.AUTO_BOOTSTRAP = True
        bootstrap.STATUS.update(state="idle", message="Dane nie zostały jeszcze załadowane.")

    def tearDown(self):
        config.DB_PATH, config.AUTO_BOOTSTRAP, config.HISTORY_DIR = self.old
        self.tmp.cleanup()

    def _patches(self):
        return (mock.patch.object(csvdata, "download", side_effect=lambda lg, y: fd_csv(y, lg)),
                mock.patch.object(csvdata, "download_fixtures", return_value="Div,Date,HomeTeam,AwayTeam\n"))

    def test_empty_db_then_loaded(self):
        with mock.patch.object(bootstrap, "start_background"):  # nie startuj wątku w teście
            client = create_app().test_client()
        bootstrap.STATUS.update(state="loading", message="Pobieram dane...")
        r = client.get("/?league=E0")  # pusta baza -> 503 z ekranem ładowania (a nie pusta strona)
        self.assertEqual(r.status_code, 503)
        self.assertIn("Pobieram dane".encode(), r.data)
        self.assertIn(b'http-equiv="refresh"', r.data)

        p1, p2 = self._patches()
        with p1, p2:
            bootstrap.run_once(["E0"], years=3, log=lambda *_: None)
        self.assertEqual(bootstrap.STATUS["state"], "ready")
        conn = db.connect(config.DB_PATH)
        self.assertGreater(bootstrap.count_finished(conn, "E0"), 1000)
        r = client.get("/strengths?league=E0")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/healthz").json["dane"]["state"], "ready")

    def test_idempotent_no_redownload(self):
        p1, p2 = self._patches()
        with p1 as dl, p2:
            bootstrap.ensure_data(["E0"], years=3, log=lambda *_: None)
            first = dl.call_count
            bootstrap.ensure_data(["E0"], years=3, log=lambda *_: None)  # baza pełna -> brak pobierania
            self.assertEqual(dl.call_count, first)

    def test_one_failing_season_does_not_break_rest(self):
        def flaky(lg, y):
            if y == bootstrap.season_now() - 1:
                raise RuntimeError("404")
            return fd_csv(y, lg)
        with mock.patch.object(csvdata, "download", side_effect=flaky):
            out = bootstrap.ensure_data(["E0"], years=3, log=lambda *_: None)
        self.assertGreater(out["E0"], 600)  # 2 z 3 sezonów


if __name__ == "__main__":
    unittest.main()


class TestStartupRobustness(unittest.TestCase):
    """Regresja: 'idle' na Renderze mimo wdrożonej historii (zmienna nieustawiona / zapisana jako 'true')."""

    def test_auto_bootstrap_parsing(self):
        f = config.auto_bootstrap_default
        self.assertTrue(f({"AUTO_BOOTSTRAP": "1"}))
        self.assertTrue(f({"AUTO_BOOTSTRAP": "true"}))      # wcześniej tylko "1" działało
        self.assertTrue(f({"AUTO_BOOTSTRAP": " Yes "}))
        self.assertFalse(f({"AUTO_BOOTSTRAP": "0", "RENDER": "true"}))  # jawne wyłączenie wygrywa
        self.assertFalse(f({"AUTO_BOOTSTRAP": "off"}))
        self.assertTrue(f({"RENDER": "true"}))              # na Renderze domyślnie włączone
        self.assertTrue(f({"AUTO_BOOTSTRAP": "", "RENDER": "true"}))
        self.assertFalse(f({}))

    def test_history_loads_at_startup_even_when_bootstrap_disabled(self):
        from fbpred import history
        with tempfile.TemporaryDirectory() as tmp:
            old = (config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES)
            config.DB_PATH, config.HISTORY_DIR = Path(tmp) / "x.db", Path(tmp) / "history"
            config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = False, ["E0"]
            bootstrap.STATUS.update(state="idle", message="Dane nie zostały jeszcze załadowane.")
            try:
                sy = bootstrap.season_now()
                history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
                with mock.patch.object(csvdata, "download", side_effect=OSError("brak sieci")):
                    client = create_app().test_client()   # bez wątku, bez sieci
                self.assertEqual(bootstrap.STATUS["state"], "ready")
                self.assertEqual(client.get("/strengths?league=E0").status_code, 200)
                page = client.get("/data?league=E0").data.decode()
                self.assertIn("WYŁĄCZONE", page)            # czytelna podpowiedź zamiast cichego 'idle'
                self.assertIn("AUTO_BOOTSTRAP=False", page)
            finally:
                config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = old

    def test_export_skips_demo_league(self):
        from fbpred import history
        from fbpred.synthetic import generate
        d = generate(n_seasons=1, seed=2, with_upcoming=False)
        d["date"] = d["date"].dt.strftime("%Y-%m-%d")
        cols = [c for c in db.COLUMNS if c in d.columns]
        conn = db.connect(":memory:")
        db.upsert_matches(conn, d[cols].astype(object).where(d[cols].notna(), None).to_dict("records"))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(history.export_from_db(conn, tmp)["files"], {})              # DEMO pominięte
            self.assertEqual(len(history.export_from_db(conn, tmp, include_demo=True)["files"]), 1)
