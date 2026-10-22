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
        self.old = (config.DB_PATH, config.AUTO_BOOTSTRAP)
        config.DB_PATH = Path(self.tmp.name) / "football.db"
        config.AUTO_BOOTSTRAP = True
        bootstrap.STATUS.update(state="idle", message="Dane nie zostały jeszcze załadowane.")

    def tearDown(self):
        config.DB_PATH, config.AUTO_BOOTSTRAP = self.old
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
