import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from fbpred import bootstrap, config, csvdata, db, gh_store, history, ledger, recent
from fbpred.predictor import MatchPredictor
from fbpred.synthetic import generate
from fbpred.web import create_app
from tests.test_bootstrap import fd_csv


class FakeGitHub:
    """Minimalny symulator GitHub REST API: repo z gałęzią main i plikami; sprawdza token, sha i istnienie gałęzi."""

    def __init__(self, token="TKN", repo="u/r"):
        self.token, self.repo = token, repo
        self.branches = {"main": {}}
        self.puts = 0
        self.log = []

    def __call__(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.log.append((method, url))
        r = mock.Mock()
        r.status_code = 200
        if (headers or {}).get("Authorization") != f"Bearer {self.token}":
            r.status_code = 401
            return r
        path = url.replace("https://api.github.com", "")
        base = f"/repos/{self.repo}"
        if method == "GET" and path == base:
            r.json.return_value = {"default_branch": "main"}
        elif method == "GET" and path.startswith(f"{base}/git/ref/heads/"):
            b = path.rsplit("/", 1)[1]
            if b not in self.branches:
                r.status_code = 404
            else:
                r.json.return_value = {"object": {"sha": f"commit-{b}"}}
        elif method == "POST" and path == f"{base}/git/refs":
            self.branches[json["ref"].split("/")[-1]] = dict(self.branches["main"])
            r.status_code = 201
        elif method == "GET" and path.startswith(f"{base}/contents/"):
            f, b = path.split("/contents/")[1], (params or {}).get("ref", "main")
            data = self.branches.get(b, {}).get(f)
            if data is None:
                r.status_code = 404
            else:
                r.json.return_value = {"encoding": "base64", "content": base64.b64encode(data[0].encode()).decode(), "sha": data[1]}
        elif method == "PUT" and path.startswith(f"{base}/contents/"):
            f, b = path.split("/contents/")[1], json["branch"]
            cur = self.branches[b].get(f)
            if cur and json.get("sha") != cur[1]:
                r.status_code = 409                      # jak prawdziwy GitHub: aktualizacja wymaga aktualnego sha
            else:
                self.puts += 1
                self.branches[b][f] = (base64.b64decode(json["content"]).decode(), f"sha{self.puts}")
                r.status_code = 201 if cur is None else 200
        else:
            r.status_code = 404
        return r


def rows_of(df):
    d = df.copy()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in d.columns]
    return d[cols].astype(object).where(d[cols].notna(), None).to_dict("records")


DF = generate(n_seasons=3, seed=12, league="E0", with_upcoming=True)


def seeded_conn():
    conn = db.connect(":memory:")
    db.upsert_matches(conn, rows_of(DF))
    return conn


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES,
                    config.GITHUB_TOKEN, config.GITHUB_REPO, config.FDORG_TOKEN)
        config.DB_PATH, config.HISTORY_DIR = Path(self.tmp.name) / "x.db", Path(self.tmp.name) / "history"
        config.LEDGER_CSV = Path(self.tmp.name) / "ledger" / "p.csv"
        config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = False, ["E0"]
        config.GITHUB_TOKEN, config.GITHUB_REPO, config.FDORG_TOKEN = "", "", ""
        bootstrap.DIAG.clear()

    def tearDown(self):
        (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES,
         config.GITHUB_TOKEN, config.GITHUB_REPO, config.FDORG_TOKEN) = self.old
        self.tmp.cleanup()


class TestGhStore(Env):
    def setUp(self):
        super().setUp()
        config.GITHUB_TOKEN, config.GITHUB_REPO = "TKN", "u/r"
        self.gh = FakeGitHub()

    def test_disabled_without_credentials(self):
        config.GITHUB_TOKEN = ""
        self.assertFalse(gh_store.enabled())

    def test_ledger_survives_service_restart(self):
        """Sedno problemu użytkownika: restart Rendera kasuje SQLite - dziennik ma wrócić z GitHuba."""
        with mock.patch.object(gh_store.requests, "request", self.gh):
            conn1 = seeded_conn()
            P = MatchPredictor(db.load_matches(conn1, "E0"))
            up = db.load_upcoming(conn1, "E0")
            n = ledger.log_predictions(conn1, P, up, "E0")
            self.assertGreater(n, 0)
            self.assertIn("zapisano", gh_store.sync_up(conn1))
            self.assertIn("ledger-data", self.gh.branches)               # gałąź utworzona automatycznie
            self.assertIn("ledger/predictions.csv", self.gh.branches["ledger-data"])
            # --- restart: zupełnie nowa, pusta baza (jak na Renderze po uśpieniu)
            conn2 = seeded_conn()
            self.assertEqual(ledger.stats(conn2, "E0")["w_bazie"], 0)
            self.assertEqual(gh_store.sync_down(conn2), n)
            st = ledger.stats(conn2, "E0")
            self.assertEqual((st["w_bazie"], st["oczekujace"]), (n, n))
            for fid in up["fixture_id"]:                                  # mecze się odbyły -> rozliczenie
                conn2.execute("UPDATE matches SET hg=2, ag=1, hg_ht=1, ag_ht=0, status='FT' WHERE fixture_id=?", (int(fid),))
            conn2.commit()
            self.assertEqual(ledger.stats(conn2, "E0")["rozliczone"], n)

    def test_commits_only_when_content_changes(self):
        with mock.patch.object(gh_store.requests, "request", self.gh):
            conn = seeded_conn()
            P = MatchPredictor(db.load_matches(conn, "E0"))
            up = db.load_upcoming(conn, "E0")
            ledger.log_predictions(conn, P, up, "E0")
            gh_store.sync_up(conn)
            self.assertEqual(self.gh.puts, 1)
            ledger.log_predictions(conn, P, up, "E0")                    # te same prognozy, inny logged_at
            self.assertIn("bez zmian", gh_store.sync_up(conn))
            self.assertEqual(self.gh.puts, 1)                             # brak zbędnego commita
            conn.execute("UPDATE predictions SET p1 = p1 * 0.9")          # realna zmiana treści
            conn.commit()
            gh_store.sync_up(conn)
            self.assertEqual(self.gh.puts, 2)                             # aktualizacja z poprawnym sha

    def test_empty_ledger_is_not_pushed(self):
        with mock.patch.object(gh_store.requests, "request", self.gh):
            self.assertIn("pusty", gh_store.sync_up(seeded_conn()))
            self.assertEqual(self.gh.puts, 0)

    def test_bad_token_gives_clear_error_without_leaking_it(self):
        config.GITHUB_TOKEN = "SEKRET123"
        with mock.patch.object(gh_store.requests, "request", self.gh):
            with self.assertRaises(gh_store.GhStoreError) as cm:
                gh_store.pull()
        self.assertIn("Contents", str(cm.exception))
        self.assertNotIn("SEKRET123", str(cm.exception))

    def test_bootstrap_uses_store_and_reports_in_diag(self):
        sy = bootstrap.season_now()
        history.save_matches(csvdata.parse_csv(fd_csv(sy - 1), "E0", sy - 1), config.HISTORY_DIR)
        with mock.patch.object(gh_store.requests, "request", self.gh), \
             mock.patch.object(csvdata, "download", side_effect=lambda lg, y: fd_csv(y, lg)), \
             mock.patch.object(csvdata, "download_fixtures", return_value="Div,Date,HomeTeam,AwayTeam\n"):
            bootstrap.run_once(["E0"], years=2, log=lambda *_: None)
        d = bootstrap.DIAG["dziennik"]
        self.assertIn("GitHub", d["trwalosc"])
        self.assertIn("zapis", d)

    def test_bootstrap_without_token_explains_why_ledger_is_volatile(self):
        config.GITHUB_TOKEN = ""
        bootstrap._ledger_pull(db.connect(":memory:"), lambda *_: None)
        self.assertIn("WYŁĄCZONA", bootstrap.DIAG["dziennik"]["trwalosc"])


class TestRecent(Env):
    def test_no_lookahead_and_window(self):
        fin = DF[DF.hg.notna()]
        res = recent.recent_predictions(fin, days=10)
        self.assertGreater(len(res), 5)
        self.assertTrue((pd.to_datetime(res["date"]) > fin["date"].max() - pd.Timedelta(days=10)).all())
        # pierwsza kolejka okna: prognoza identyczna z modelem uczonym tylko na meczach sprzed niej
        first = res.iloc[0]
        start = pd.to_datetime(res["date"]).min()
        train = fin[fin["date"] < start]
        direct = MatchPredictor(train, as_of=start).predict(first["home"], first["away"])
        self.assertAlmostEqual(first["p1"], direct["1x2"]["1"], places=4)
        # wynik rzeczywiście z danych, nie z prognozy
        row = fin[(fin.home == first["home"]) & (fin.away == first["away"]) & (fin.date == first["date"])].iloc[0]
        self.assertEqual((first["hg"], first["ag"]), (row["hg"], row["ag"]))

    def test_table_and_summary(self):
        res = recent.recent_predictions(DF[DF.hg.notna()], days=10)
        t = recent.show_table(res)
        self.assertTrue({"mecz", "wynik", "model_1/X/2_%", "trafiony", "był_remis_HT", "był_HT_lub_FT"} <= set(t.columns))
        self.assertIn("mała próba", recent.summary(res))
        self.assertEqual(recent.show_table(pd.DataFrame()).shape, (0, 0))


class TestWebTrack(Env):
    def _client(self):
        history.save_matches(rows_of(DF), config.HISTORY_DIR)
        db.upsert_matches(db.connect(config.DB_PATH), [r for r in rows_of(DF) if r["status"] == "NS"])
        return create_app().test_client()

    def test_empty_ledger_explains_itself(self):
        c = self._client()
        page = c.get("/track?league=E0").data.decode()
        self.assertIn("W bazie: 0 prognoz", page)
        self.assertIn("nie trafią tu wstecznie", page)
        self.assertIn("trwałość dziennika jest wyłączona", page)          # brak tokenu -> jasna przyczyna
        self.assertIn("/recent?league=E0", page)

    def test_recent_page(self):
        c = self._client()
        page = c.get("/recent?league=E0&days=14").data.decode()
        self.assertEqual(c.get("/recent?league=E0").status_code, 200)
        self.assertIn("Retrospektywa", page)
        self.assertIn("trafiony", page)


if __name__ == "__main__":
    unittest.main()
