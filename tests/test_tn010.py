"""Testy tnpred 0.1.0 (tenis). Izolacja: baza, historia i parametry w katalogach tymczasowych, bez internetu."""
import sqlite3
import re
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="tnpred_test_")
os.environ.update({"TN_DB_PATH": os.path.join(_TMP, "t.db"), "TN_HISTORY_DIR": os.path.join(_TMP, "hist"),
                   "TN_PARAMS_DIR": os.path.join(_TMP, "params"), "TN_AUTO_BOOTSTRAP": "0", "TN_DEMO": "0",
                   "GITHUB_TOKEN": "", "GITHUB_REPO": "", "ODDS_API_KEY": ""})

import io  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402

import pandas as pd  # noqa: E402

from tnpred import bets, betmarkets as bm, bootstrap, db, ledger, names, oddsapi, pointmodel as pm, synthetic, tdata  # noqa: E402
from tnpred.elo import Elo, initial_rating  # noqa: E402
from tnpred.model import TennisModel  # noqa: E402

_DF = None


def demo_df():
    global _DF
    if _DF is None:
        _DF = synthetic.generate(n_players=40, years=2, seed=11)
    return _DF


class PointModel(unittest.TestCase):
    def test_hold_known_value(self):
        self.assertAlmostEqual(pm.p_hold(0.6), 0.7357, places=3)
        self.assertAlmostEqual(pm.p_hold(0.5), 0.5, places=6)

    def test_symmetric_match(self):
        d = pm.match_dist(0.64, 0.64, 3)
        self.assertAlmostEqual(d["p_match"], 0.5, places=6)
        self.assertAlmostEqual(sum(d["games"].values()), 1.0, places=9)
        self.assertAlmostEqual(sum(d["sets"].values()), 1.0, places=9)

    def test_bo5_amplifies_favourite(self):
        self.assertGreater(pm.match_dist(0.66, 0.62, 5, 10)["p_match"], pm.match_dist(0.66, 0.62, 3)["p_match"])

    def test_set_dist_sums_and_tb(self):
        d = pm.set_dist(0.7, 0.7, True)
        self.assertAlmostEqual(sum(p for *_, p in d), 1.0, places=9)
        tb = sum(p for a, b, p in d if a + b == 13)
        self.assertGreater(tb, 0.15)

    def test_serve_probs_hits_target(self):
        pa, pb = pm.serve_probs(0.7, 0.64)
        self.assertAlmostEqual(pm.p_match_bo3(pa, pb), 0.7, delta=0.01)
        self.assertGreater(pa, pb)

    def test_summary_markets_consistent(self):
        s = pm.summarize(pm.match_dist(0.66, 0.6, 3), 3)
        self.assertAlmostEqual(s["p1"] + s["p2"], 1.0, places=9)
        self.assertGreaterEqual(s["over"]["20.5"], s["over"]["22.5"])
        self.assertGreater(s["hcp"]["+1.5"], s["hcp"]["-1.5"])
        self.assertAlmostEqual(s["win_a_set"]["1"], 1 - s["sets"]["0-2"], places=9)


class Names(unittest.TestCase):
    def test_resolve_variants(self):
        idx = names.NameIndex(["Sinner J.", "De Minaur A.", "Auger-Aliassime F.", "Kwon S.W.", "Zverev A.", "Zverev M."])
        self.assertEqual(idx.resolve("Jannik Sinner"), "Sinner J.")
        self.assertEqual(idx.resolve("Alex de Minaur"), "De Minaur A.")
        self.assertEqual(idx.resolve("Félix Auger Aliassime"), "Auger-Aliassime F.")
        self.assertEqual(idx.resolve("Soonwoo Kwon"), "Kwon S.W.")
        self.assertEqual(idx.resolve("Alexander Zverev"), "Zverev A.")
        self.assertIsNone(idx.resolve("Nobody Atall"))
        self.assertEqual(names.to_td("Joao Fonseca"), "Fonseca J.")


class TennisData(unittest.TestCase):
    def test_normalize_xlsx_format(self):
        raw = pd.DataFrame([{"ATP": 1, "Location": "Paris", "Tournament": "Paris Masters", "Date": "2025-10-30", "Series": "Masters 1000",
                             "Court": "Indoor", "Surface": "Hard", "Round": "2nd Round", "Best of": 3, "Winner": "Sinner J.",
                             "Loser": "Zverev A.", "WRank": 1, "LRank": 3, "W1": 7, "L1": 6, "W2": 6, "L2": 3, "Wsets": 2, "Lsets": 0,
                             "Comment": "Completed", "PSW": 1.4, "PSL": 3.1, "AvgW": 1.38, "AvgL": 3.0}])
        buf = io.BytesIO()
        raw.to_excel(buf, index=False)
        df = tdata.normalize(pd.read_excel(io.BytesIO(buf.getvalue())), "ATP")
        self.assertEqual(df.loc[0, "winner"], "Sinner J.")
        d = tdata.add_derived(df)
        self.assertEqual(int(d.loc[0, "total_games"]), 22)
        self.assertEqual(int(d.loc[0, "n_tb"]), 1)
        self.assertTrue(bool(d.loc[0, "completed"]))

    def test_history_roundtrip(self):
        df = demo_df()
        p = tdata.save_history(df[df.tour == "ATP"], "ATP", 2025)
        back = tdata.read_csv(p)
        self.assertEqual(len(back), int((df.tour == "ATP").sum()))


class ManualAndFallback(unittest.TestCase):
    def test_xlsx_in_tour_folders(self):
        from pathlib import Path
        d = Path(_TMP) / "manual"
        (d / "WTA").mkdir(parents=True, exist_ok=True)
        raw = pd.DataFrame([{"WTA": 1, "Location": "Riyadh", "Tournament": "WTA Finals", "Date": "2025-11-05", "Tier": "Tour Championships",
                             "Court": "Indoor", "Surface": "Hard", "Round": "Round Robin", "Best of": 3, "Winner": "Sabalenka A.",
                             "Loser": "Gauff C.", "WRank": 1, "LRank": 3, "W1": 6, "L1": 4, "W2": 6, "L2": 2, "Wsets": 2, "Lsets": 0,
                             "Comment": "Completed", "PSW": 1.5, "PSL": 2.6}])
        raw.to_excel(d / "WTA" / "2025.xlsx", index=False)
        rep = []
        df = tdata.load_history_dir(d, report=rep)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.loc[0, "tour"], "WTA")
        self.assertIn("WTA/2025.xlsx: 1", rep[0])

    def test_discover_links_from_page(self):
        from unittest import mock
        html = ('<a href="hrjk-NEW/2025/2025.xlsx">2025</a> <a href="/hrjk-NEW/2025w/2025.xlsx">2025</a> '
                '<a href="hrjk-NEW/2010/2010.xls">2010</a>')
        resp = mock.Mock(status_code=200, text=html)
        tdata._LINKS.clear()
        with mock.patch.object(tdata.requests, "get", return_value=resp):
            links = tdata.discover_links()
        tdata._LINKS.clear()
        self.assertEqual(links[("ATP", 2025)], "https://tennis-data.co.uk/hrjk-NEW/2025/2025.xlsx")
        self.assertEqual(links[("WTA", 2025)], "https://tennis-data.co.uk/hrjk-NEW/2025w/2025.xlsx")
        self.assertIn(("ATP", 2010), links)

    def test_default_url_pattern(self):
        self.assertEqual(tdata.url_for("WTA", 2025), "https://tennis-data.co.uk/hrjk-85HytOjkhth76j_ygh4jf7/2025w/2025.xlsx")


class EloTests(unittest.TestCase):
    def test_update_moves_ratings(self):
        e = Elo()
        p = e.update("ATP|A", "ATP|B", "Clay", pd.Timestamp("2025-01-01"))
        self.assertAlmostEqual(p, 0.5, places=6)
        self.assertGreater(e.r["ATP|A"], e.r["ATP|B"])
        self.assertGreater(e.rs[("ATP|A", "Clay")], e.rs[("ATP|B", "Clay")])

    def test_initial_from_rank(self):
        self.assertGreater(initial_rating(5), initial_rating(150))


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = TennisModel(demo_df(), params={})

    def test_predict_structure(self):
        a, b = self.m.players("ATP")[:2]
        p = self.m.predict("ATP", "Clay", 3, a, b, 1.8, 2.1)
        self.assertAlmostEqual(p["m"]["p1"] + p["m"]["p2"], 1.0, places=6)
        self.assertIsNotNone(p["p_market"])
        self.assertTrue(p["base"])
        cat = bm.catalogue(p)
        self.assertIn("w1", cat)
        self.assertIn("o22.5", cat)
        self.assertIn("s2-0", cat)

    def test_unknown_player_warns(self):
        p = self.m.predict("ATP", "Hard", 3, "Kowalski Z.", self.m.players("ATP")[0])
        self.assertTrue(p["warn"])

    def test_walk_forward_no_lookahead(self):
        df = self.m.df
        first = df.iloc[0]
        self.assertAlmostEqual(first.p_elo_w, 1 / (1 + 10 ** ((initial_rating(first.lrank) - initial_rating(first.wrank)) / 400)), places=6)

    def test_fit_blend_in_range(self):
        w = self.m.fit_blend()
        for v in w.values():
            self.assertTrue(0 <= v <= 1)


class Settlement(unittest.TestCase):
    def res(self, winner="A", sets=((6, 4), (6, 7), (7, 5)), comment="Completed"):
        r = {"winner": winner, "loser": "B" if winner == "A" else "A", "comment": comment}
        for i, (a, b) in enumerate(sets, 1):
            r[f"w{i}"], r[f"l{i}"] = a, b
        return r

    def test_markets(self):
        o = bm.oriented(self.res(), "A")
        self.assertTrue(bm.leg_won("w1", o))
        self.assertTrue(bm.leg_won("o22.5", o))     # 19+16 = 35 gemów
        self.assertTrue(bm.leg_won("tb", o))
        self.assertTrue(bm.leg_won("s2-1", o))
        self.assertTrue(bm.leg_won("ws2", o))
        self.assertTrue(bm.leg_won("h1-2.5", o))    # 19-16 = +3
        self.assertFalse(bm.leg_won("h1-3.5", o))
        self.assertTrue(bm.leg_won("fs1", o))
        self.assertTrue(bm.leg_won("f1o9.5", o))

    def test_perspective_flip(self):
        o = bm.oriented(self.res(), "B")
        self.assertTrue(bm.leg_won("w2", o))
        self.assertTrue(bm.leg_won("s1-2", o))
        self.assertTrue(bm.leg_won("h1+3.5", o))

    def test_retired_is_void(self):
        self.assertEqual(bm.leg_won("w1", bm.oriented(self.res(comment="Retired"), "A")), "void")

    def test_leg_id_roundtrip(self):
        leg = bm.leg_id("ATP", "2026-11-02", "Sinner J.", "De Minaur A.", "Hard", 3, "h1-3.5")
        self.assertEqual(bm.parse_leg(leg)[-1], "h1-3.5")


class OddsApiParse(unittest.TestCase):
    def test_parse_events(self):
        sport = {"key": "tennis_atp_wimbledon", "title": "ATP Wimbledon"}
        ev = [{"home_team": "Jannik Sinner", "away_team": "Alex de Minaur", "commence_time": "2026-07-01T12:00:00Z",
               "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [{"name": "Jannik Sinner", "price": 1.25},
                                                                                         {"name": "Alex de Minaur", "price": 4.2}]},
                                                              {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 33.5},
                                                                                             {"name": "Under", "price": 1.9, "point": 33.5}]}]},
                              {"key": "x", "markets": [{"key": "h2h", "outcomes": [{"name": "Jannik Sinner", "price": 1.22},
                                                                                   {"name": "Alex de Minaur", "price": 4.5}]}]}]}]
        idx = names.NameIndex(["Sinner J.", "De Minaur A."])
        rows = oddsapi.parse_events(sport, ev, resolve=lambda t, n: idx.resolve(n))
        r = rows[0]
        self.assertEqual((r["p1"], r["p2"], r["surface"], r["best_of"]), ("Sinner J.", "De Minaur A.", "Grass", 5))
        self.assertEqual(r["o1"], 1.25)  # Pinnacle ma pierwszeństwo
        self.assertEqual(r["total_line"], 33.5)


class DailyHistorySync(unittest.TestCase):
    def test_sync_history_pulls_changed_files_once(self):
        from unittest import mock
        from tnpred import gh_store
        st = bootstrap.State(os.path.join(_TMP, "sync.db"))
        df = demo_df()
        text = tdata.history_text(df[df.tour == "ATP"].tail(50))
        with mock.patch.object(gh_store, "enabled", return_value=True), \
             mock.patch.object(gh_store, "list_dir", return_value={"ATP_2026.csv": "abc"}), \
             mock.patch.object(gh_store, "pull_raw", return_value=text) as pr:
            n1 = bootstrap.sync_history(st)
            n2 = bootstrap.sync_history(st)
        self.assertEqual(n1, 50)
        self.assertEqual(n2, 0)
        self.assertEqual(pr.call_count, 1)          # drugi raz ten sam sha -> nie pobiera

    def test_push_history_skips_unchanged(self):
        from unittest import mock
        from tnpred import cli, gh_store
        df = demo_df()
        atp = df[df.tour == "ATP"].tail(30)
        same_sha = gh_store.git_sha(tdata.history_text(atp))
        with mock.patch.object(gh_store, "enabled", return_value=True), \
             mock.patch.object(gh_store, "list_dir", return_value={f"ATP_{pd.Timestamp.today().year}.csv": same_sha}), \
             mock.patch.object(cli.tdata, "download_any", side_effect=lambda t, y: (atp if t == "ATP" else df[df.tour == "WTA"].tail(30), "test")), \
             mock.patch.object(gh_store, "push") as push:
            cli.main(["push-history", "--no-tune"])
        names = [c.args[1] for c in push.call_args_list]
        self.assertEqual(len(names), 1)               # ATP bez zmian, wysłane tylko WTA
        self.assertIn("WTA_", names[0])


class GhCheck(unittest.TestCase):
    def test_check_messages(self):
        from unittest import mock
        from tnpred import gh_store
        with mock.patch.object(gh_store, "_call", return_value=mock.Mock(status_code=404)):
            ok, msg = gh_store.check()
        self.assertFalse(ok)
        self.assertIn("GITHUB_REPO", msg)
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"permissions": {"push": False}}
        with mock.patch.object(gh_store, "_call", return_value=resp):
            ok, msg = gh_store.check()
        self.assertFalse(ok)
        self.assertIn("Read and write", msg)

    def test_version_on_page(self):
        from tnpred import __version__
        from tnpred.web import create_app
        st = bootstrap.State(os.path.join(_TMP, "ver.db"))
        c = create_app(st, background=False).test_client()
        self.assertIn(f"tenis v{__version__}".encode(), c.get("/data").data)


class NonBlockingPages(unittest.TestCase):
    def test_loading_page_while_model_builds(self):
        from tnpred.web import create_app
        st = bootstrap.State(os.path.join(_TMP, "load.db"))
        db.upsert_matches(st.conn, demo_df())
        app = create_app(st, background=False)
        st.mark_changed()
        st.model = None
        with st.model_lock:                    # symulacja: model właśnie się liczy
            r = app.test_client().get("/")
            d = app.test_client().get("/data")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Ładuję dane".encode(), r.data)
        self.assertIn(b"historia z repo", d.data)

    def test_stale_model_serves_pages(self):
        from tnpred.web import create_app
        st = bootstrap.State(os.path.join(_TMP, "stale.db"))
        db.upsert_matches(st.conn, demo_df())
        app = create_app(st, background=False)
        st.get_model()
        st.mark_changed()                      # nowe dane -> model nieaktualny
        with st.model_lock:
            r = app.test_client().get("/ranking")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Ładuję dane".encode(), r.data)


class ForkSafety(unittest.TestCase):
    def test_background_restarts_in_new_process(self):
        from unittest import mock
        st = bootstrap.State(os.path.join(_TMP, "fork.db"))
        with mock.patch.object(bootstrap, "start_background") as sb:
            self.assertTrue(bootstrap.ensure_background(st))
            self.assertFalse(bootstrap.ensure_background(st))      # ten sam proces - drugi raz nie
            st.model_lock.acquire()                                  # kopia po fork z „zamkniętą” blokadą
            st.bg_pid = -1
            self.assertTrue(bootstrap.ensure_background(st))
        self.assertEqual(sb.call_count, 2)
        self.assertFalse(st.model_lock.locked())                     # świeża blokada w nowym procesie


class StartTimes(unittest.TestCase):
    def test_when_statuses(self):
        from tnpred import views as V
        now = pd.Timestamp("2026-10-31 12:00", tz="UTC")
        self.assertEqual(V.when("2026-10-31 13:00", now)["status"], "soon")
        self.assertEqual(V.when("2026-10-31 13:00", now)["time"], "14:00")      # czas polski (UTC+1)
        self.assertEqual(V.when("2026-10-31 11:00", now)["status"], "live")
        self.assertEqual(V.when("2026-10-31 06:00", now)["status"], "done")
        self.assertEqual(V.when("2026-11-02", now)["status"], "future")
        self.assertIn("godz. nieznana", V.when("2026-11-02", now)["label"])

    def test_manual_time_to_utc(self):
        from tnpred.web import _manual_date
        self.assertEqual(_manual_date("2026-11-02", "14:30"), "2026-11-02 13:30")
        self.assertEqual(_manual_date("2026-11-02", ""), "2026-11-02")


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tnpred.web import create_app
        cls.st = bootstrap.State(os.path.join(_TMP, "app.db"))
        df = demo_df()
        db.upsert_matches(cls.st.conn, df)
        db.upsert_upcoming(cls.st.conn, synthetic.upcoming(df, n=4))
        cls.app = create_app(cls.st, background=False)
        bootstrap.refresh(cls.st, network=False)
        cls.c = cls.app.test_client()

    def test_pages(self):
        for u in ["/", "/?tour=WTA", "/match", "/suggest?min_p=55", "/coupon", "/ranking", "/recent?days=30", "/backtest",
                  "/track", "/bets", "/data", "/healthz"]:
            r = self.c.get(u)
            self.assertEqual(r.status_code, 200, u)
        self.assertIn(b'class="b ', self.c.get("/").data)        # kafelki
        self.assertIn(b'class="pg ', self.c.get("/").data)       # piktogramy H2H/forma
        self.assertIn(b"mrow", self.c.get("/recent?days=30").data)

    def test_match_page_and_coupon_bet(self):
        up = db.load_upcoming(self.st.conn).iloc[0]
        r = self.c.get("/match", query_string={"tour": up.tour, "p1": up.p1, "p2": up.p2, "surface": "Hard"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"data-id=", r.data)
        leg = bm.leg_id(up.tour, up.date, up.p1, up.p2, "Hard", 3, "w1")
        d = self.c.get("/api/coupon", query_string={"leg": leg, "odds": ""}).get_json()
        self.assertAlmostEqual(d["legs"][0]["kurs_uzyty"], float(up.o1))
        before = len(bets.load(self.st.conn))
        r = self.c.post("/api/bets", json={"legs": [leg], "odds": [""], "stake": "10"})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(len(bets.load(self.st.conn)), before + 1)

    def test_manual_add_and_ledger(self):
        a, b = self.st.get_model().players("WTA")[:2]
        day = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        r = self.c.post("/upcoming/add", data={"date": day, "tour": "WTA", "surface": "Clay", "bo": "3", "p1": a, "p2": b, "o1": "1.9", "o2": "1.9"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(((ledger.load(self.st.conn).p1 == a)).any())
        txt, n = bootstrap.manual_export(self.st)
        self.assertGreaterEqual(n, 1)

    def test_started_match_keeps_prematch_odds(self):
        past = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        a, b = self.st.get_model().players("ATP")[5:7]
        db.upsert_upcoming(self.st.conn, [{"source": "oddsapi", "tour": "ATP", "tournament": "T", "surface": "Hard", "best_of": 3,
                                           "date": past, "p1": a, "p2": b, "o1": 1.8, "o2": 2.0}])
        rows = bootstrap.keep_prematch_odds(self.st, [{"tour": "ATP", "date": past, "p1": a, "p2": b, "o1": 1.1, "o2": 7.0}])
        self.assertEqual(rows, [])
        html = self.c.get("/").data.decode()
        self.assertIn("rozpoczęty", html)

    def test_403_marks_blocked_and_skips(self):
        from unittest import mock
        st = bootstrap.State(os.path.join(_TMP, "blk.db"))
        db.upsert_matches(st.conn, demo_df())
        with mock.patch.object(bootstrap.tdata, "download_any", side_effect=RuntimeError("https://x: HTTP 403")) as m:
            bootstrap.fetch_results(st, years=1)
            self.assertEqual(m.call_count, 1)             # po 403 nie próbuje dalej
            bootstrap.fetch_results(st, years=1)
            self.assertEqual(m.call_count, 1)             # przez 24 h w ogóle nie próbuje
        self.assertTrue(db.meta_get(st.conn, "tdata_blocked_at"))
        self.assertIn("python -m tnpred push-history", " ".join(x["opis"] for x in st.diag["kroki"]))

    def test_fit_s0_in_realistic_range(self):
        s0 = self.st.get_model().fit_s0()
        for v in s0.values():
            self.assertTrue(0.5 <= v < 0.72, s0)

    def test_fetch_odds_with_slim_model_data(self):
        """Regresja: od 0.2.0 dane modelu nie mają kolumny location - pobieranie kursów wywracało się (KeyError)."""
        from unittest import mock
        from tnpred import oddsapi
        seen = {}

        def fake_fetch(resolve=None, history_lookup=None, tours=None):
            seen["surface"] = history_lookup("ATP Doha Open")
            a, b = self.st.get_model().players("ATP")[:2]
            return [{"source": "oddsapi", "tour": "ATP", "tournament": "ATP Doha", "surface": "Hard", "best_of": 3,
                     "date": "2099-01-01 12:00", "p1": a, "p2": b, "o1": 1.9, "o2": 1.9}], {"quota": {"remaining": "400"}, "errors": []}
        db.meta_set(self.st.conn, "odds_at", "2000-01-01T00:00:00+00:00")
        with mock.patch.object(oddsapi, "enabled", return_value=True), mock.patch.object(oddsapi, "fetch_all", side_effect=fake_fetch):
            n = bootstrap.fetch_odds(self.st, force=True)
        self.assertEqual(n, 1)
        self.assertEqual(seen["surface"], "Hard")

    def test_print_view(self):
        r = self.c.get("/print")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Zapisz jako PDF", r.data)
        self.assertIn(b'class="m"', r.data)
        self.assertIn(b"/print?auto=1", self.c.get("/").data)

    def test_mounted_under_prefix(self):
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from flask import Flask
        outer = Flask("outer")
        outer.wsgi_app = DispatcherMiddleware(outer.wsgi_app, {"/tennis": self.app})
        r = outer.test_client().get("/tennis/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'href="/tennis/match"', r.data)
        self.assertIn(b"TN_R='/tennis'", r.data)

    def test_bets_settle_from_results(self):
        conn = self.st.conn
        m = self.st.get_model()
        r = m.df[m.df.completed].iloc[-1]
        leg = bm.leg_id(r.tour, f"{r.date:%Y-%m-%d}", r.winner, r.loser, r.surface, r.best_of, "w1")
        bid = bets.add_bet(conn, [{"id": leg, "mecz": "x", "rynek": "y", "p": 0.5, "kurs": 2.0}], 2.0, 10)
        bets.settle_open(conn, self.st.lookup)
        self.assertEqual(conn.execute("SELECT status FROM bets WHERE id=?", (bid,)).fetchone()[0], "won")


class PlayerStyle(unittest.TestCase):
    def test_adjust(self):
        from tnpred import style
        st = {"b": 3.45, "tours": ["ATP"], "players": {"ATP": {"Big S.": 0.13, "Grinder G.": -0.12}}}
        up, info = style.adjust(st, "ATP", "Big S.", "Other O.", 0.40)
        self.assertGreater(up, 0.48)
        self.assertEqual(info, [("Big S.", 0.13)])
        down, _ = style.adjust(st, "ATP", "Grinder G.", "Other O.", 0.40)
        self.assertLess(down, 0.32)
        self.assertEqual(style.adjust(st, "WTA", "Big S.", "x", 0.40), (0.40, []))      # WTA bez korekty
        self.assertEqual(style.adjust(st, "ATP", "Nobody", "x", 0.40), (0.40, []))      # brak danych = bez zmian

    def test_compute_and_predict(self):
        from tnpred import style
        m = TennisModel(demo_df(), params={})
        st = style.compute(m, tours=["ATP", "WTA"], min_matches=5)
        self.assertTrue(st["players"].get("ATP"))
        name, val = next(iter(st["players"]["ATP"].items()))
        self.assertLess(abs(val), 1.0)
        m.style = {**st, "players": {"ATP": {name: 0.2}}, "tours": ["ATP"]}
        other = [n for n in st["players"]["ATP"] if n != name][0]
        p = m.predict("ATP", "Hard", 3, name, other)
        self.assertGreater(p["m"]["p_tb"], p["p_tb_base"])
        self.assertEqual(p["style"][0][0], name)


def _espn_comp(n1, n2, status="STATUS_FINAL", done=True, rnd="Round 1", date="2026-11-09T12:00Z", sets=((6, 4), (7, 6)), w=0):
    c = []
    for i, n in enumerate((n1, n2)):
        ls = [{"value": s[0] if i == w else s[1]} for s in sets] if done else []
        c.append({"athlete": {"displayName": n}, "winner": done and i == w, "linescores": ls})
    return {"date": date, "timeValid": True, "status": {"type": {"name": status, "completed": done, "detail": "x"}},
            "round": {"displayName": rnd}, "competitors": c}


def _espn_event(name, city, comps, doubles=()):
    return {"name": name, "major": False, "venue": {"displayName": f"{city}, X"},
            "groupings": [{"grouping": {"displayName": "Women's Singles"}, "competitions": comps},
                          {"grouping": {"displayName": "Women's Doubles"}, "competitions": list(doubles)}]}


class EspnPatch(unittest.TestCase):
    """0.3.11: łatka wyników + terminarz z ESPN (bez internetu - feed podstawiony)."""

    def setUp(self):
        from tnpred import espn
        self.espn = espn
        self.st = bootstrap.State(":memory:")
        df = demo_df()
        db.upsert_matches(self.st.conn, df)
        self.st.mark_changed()
        self.m = self.st.get_model()
        w = df[df.tour == "WTA"]
        self.city = str(w.location.iloc[-1])
        pl = sorted(set(w.winner) | set(w.loser))
        self.a, self.b, self.c, self.d = pl[:4]
        full = lambda td: f"{td.split()[-1][0]}xx {' '.join(td.split()[:-1])}"      # „Moro A.” -> „Axx Moro”
        self.fa, self.fb, self.fc, self.fd = (full(x) for x in (self.a, self.b, self.c, self.d))
        today = pd.Timestamp.now(tz="UTC")
        self.day = f"{today:%Y-%m-%d}"
        self.data = {"events": [
            _espn_event("Some Open", self.city, [
                _espn_comp(self.fa, self.fb, date=f"{self.day}T10:00Z"),
                _espn_comp(self.fc, self.fd, status="STATUS_RETIRED", date=f"{self.day}T11:00Z", sets=((6, 3), (2, 1)), w=1),
                _espn_comp(self.fa, self.fc, rnd="Qualifying 1st Round", date=f"{self.day}T09:00Z"),
                _espn_comp(self.fb, self.fd, status="STATUS_WALKOVER", date=f"{self.day}T09:00Z", sets=()),
                _espn_comp(self.fa, self.fd, status="STATUS_SCHEDULED", done=False, rnd="Round 2",
                           date=f"{(today + pd.Timedelta(days=1)):%Y-%m-%d}T15:00Z"),
                _espn_comp("Nowa Zawodniczka", self.fc, status="STATUS_SCHEDULED", done=False, rnd="Round 2",
                           date=f"{(today + pd.Timedelta(days=1)):%Y-%m-%d}T17:00Z")],
                doubles=[_espn_comp(self.fa, self.fb)]),
            _espn_event("Austin 125", self.city, [_espn_comp(self.fb, self.fc)]),
            _espn_event("Unknown City Cup", "Sopo", [_espn_comp(self.fb, self.fc)]),
        ]}

    def getter(self, tour, start, end):
        return self.data if tour == "WTA" else {"events": []}

    def test_parse_filters_and_scores(self):
        known = self.espn.places(db.load_matches(self.st.conn)).get("WTA", {})
        res, sched, skipped = self.espn.parse("WTA", self.data, known, self.m.resolve)
        self.assertEqual(len(res), 2)                         # bez kwalifikacji, walkowera, debla, 125 i obcego miasta
        self.assertEqual({"Austin 125", "Unknown City Cup"}, skipped)
        r1, r2 = res
        self.assertEqual((r1["winner"], r1["loser"], r1["w2"], r1["l2"], r1["wsets"], r1["lsets"]), (self.a, self.b, 7, 6, 2, 0))
        self.assertEqual((r2["winner"], r2["comment"], r2["lsets"], r2["wsets"]), (self.d, "Retired", 0, 1))      # przy kreczu liczą się tylko skończone sety
        self.assertEqual(r1["round"], "1st Round")
        self.assertEqual(r1["location"], "ESPN")
        self.assertEqual(len(sched), 2)
        self.assertEqual(sched[1]["p1"], "Zawodniczka N.")    # nieznana - zapis jak w tennis-data
        self.assertEqual(sched[0]["source"], "espn")

    def test_uncovered_drops_matches_already_in_tennis_data(self):
        row = {"tour": "WTA", "date": self.day, "winner": self.a, "loser": self.b}
        hist = pd.DataFrame([{"tour": "WTA", "date": pd.Timestamp(self.day) - pd.Timedelta(days=2), "winner": self.b,
                              "loser": self.a, "location": "X"}])
        self.assertEqual(self.espn.uncovered([row], hist), [])
        hist.loc[0, "date"] = pd.Timestamp(self.day) - pd.Timedelta(days=9)
        self.assertEqual(len(self.espn.uncovered([row], hist)), 1)

    def test_bootstrap_step_adds_results_schedule_and_is_idempotent(self):
        from unittest import mock
        from tnpred import espn
        odds_row = {"source": "oddsapi", "tour": "WTA", "tournament": "T", "surface": "Hard", "best_of": 3,
                    "date": f"{(pd.Timestamp.now(tz='UTC') + pd.Timedelta(days=1)):%Y-%m-%d} 15:00",
                    "p1": self.d, "p2": self.a, "o1": 1.8, "o2": 2.0}
        db.upsert_upcoming(self.st.conn, [odds_row])
        v0 = self.st.data_version
        with mock.patch.object(espn, "fetch", self.getter):
            n = bootstrap.fetch_espn(self.st)
            self.assertEqual(n, 2)
            self.assertGreater(self.st.data_version, v0)
            m = self.st.get_model()
            self.assertEqual(str(m.df.date.max())[:10], self.day)      # świeże wyniki w modelu
            up = db.load_upcoming(self.st.conn, include_past_days=1)
            self.assertEqual(sorted(up.source), ["espn", "oddsapi"])    # mecz z kursami nie nadpisany
            self.assertEqual(float(up[up.source == "oddsapi"].o1.iloc[0]), 1.8)
            v1 = self.st.data_version
            bootstrap.fetch_espn(self.st)                                # drugi raz: bez zmian, bez przeliczania modelu
            self.assertEqual(self.st.data_version, v1)
            # tennis-data publikuje ten mecz -> łatka znika
            td = pd.DataFrame([{**{c: None for c in tdata.COLS}, "date": self.day, "tour": "WTA", "tournament": "Some Open",
                                "location": self.city, "surface": "Hard", "round": "1st Round", "best_of": 3,
                                "winner": self.a, "loser": self.b, "w1": 6, "l1": 4, "w2": 7, "l2": 6, "wsets": 2, "lsets": 0,
                                "comment": "Completed"}])
            db.upsert_matches(self.st.conn, tdata._from_norm(td))
            self.assertEqual(bootstrap.fetch_espn(self.st), 1)
            self.assertEqual(len(db.espn_signature(self.st.conn)), 1)

    def test_feed_error_is_visible_and_harmless(self):
        from unittest import mock
        from tnpred import espn

        def boom(*a, **k):
            raise espn.EspnError("ESPN WTA: HTTP 403")
        with mock.patch.object(espn, "fetch", boom):
            self.assertEqual(bootstrap.fetch_espn(self.st), 0)
        step = [s for s in self.st.diag["kroki"] if s["krok"].startswith("ESPN")][-1]
        self.assertFalse(step["ok"])
        self.assertIn("403", step["opis"])


class PicksTests(unittest.TestCase):
    """0.3.12: klikalne kafelki -> Moje typy, rozliczenie wszedł/nie wszedł, zestawienie."""

    @classmethod
    def setUpClass(cls):
        from tnpred.web import create_app
        cls.st = bootstrap.State(os.path.join(_TMP, "picks.db"))
        df = demo_df()
        db.upsert_matches(cls.st.conn, df)
        db.upsert_upcoming(cls.st.conn, synthetic.upcoming(df, n=3))
        cls.app = create_app(cls.st, background=False)
        bootstrap.refresh(cls.st, network=False)
        cls.c = cls.app.test_client()

    def test_tiles_clickable_toggle_and_page(self):
        from tnpred import picks
        html = self.c.get("/").data.decode()
        legs_ = re.findall(r'data-pick="([^"]+)"', html)
        self.assertGreaterEqual(len(legs_), 5)
        keys = {l.split("~")[-1] for l in legs_}
        self.assertTrue({"w1", "w2", "tb", "str"} <= keys and any(k.startswith("o") for k in keys))
        leg = next(l for l in legs_ if l.endswith("~tb"))
        import html as _h
        leg = _h.unescape(leg)
        r = self.c.post("/api/picks", json={"leg": leg}).get_json()
        self.assertEqual(r, {"ok": True, "on": True})
        self.assertIn('pk on', self.c.get("/").data.decode())             # zaznaczony po odświeżeniu
        df = picks.load(self.st.conn)
        self.assertEqual(len(df), 1)
        self.assertTrue(0 < df.p.iloc[0] < 1)
        self.assertEqual(df.grp.iloc[0], "Tie-break")
        self.assertEqual(self.c.post("/api/picks", json={"leg": leg}).get_json()["on"], False)   # drugie kliknięcie usuwa
        self.assertEqual(len(picks.load(self.st.conn)), 0)
        self.assertEqual(self.c.post("/api/picks", json={"leg": "zly"}).status_code, 400)
        self.c.post("/api/picks", json={"leg": leg})
        r = self.c.get("/picks")
        self.assertEqual(r.status_code, 200)
        self.assertIn("w grze", r.data.decode())

    def test_settle_and_summary(self):
        from tnpred import picks
        conn = sqlite3.connect(":memory:")
        mk = lambda key: bm.leg_id("ATP", "2026-11-09", "A X.", "B Y.", "Hard", 3, key)  # noqa: E731
        for key, p in (("w1", 0.7), ("w2", 0.3), ("tb", 0.4), ("str", 0.6), ("o22.5", 0.5)):
            picks.add(conn, mk(key), key, p, None, 2.0 if key == "w2" else None)
        res = {"winner": "A X.", "loser": "B Y.", "w1": 7, "l1": 6, "w2": 6, "l2": 3, "comment": "Completed"}
        n = picks.settle_open(conn, lambda t, d, a, b: res)
        self.assertEqual(n, 5)
        st = dict(zip(*[picks.load(conn)[c] for c in ("key", "status")]))
        self.assertEqual(st, {"w1": "hit", "w2": "miss", "tb": "hit", "str": "hit", "o22.5": "miss"})   # 22 gemy < 22.5
        s = picks.summary(picks.load(conn))
        self.assertEqual((s["all"]["hit"], s["all"]["n"]), (3, 5))
        self.assertAlmostEqual(s["all"]["exp"], 0.5)
        self.assertEqual(s["all"]["n_kurs"], 1)
        self.assertAlmostEqual(s["all"]["profit"], -1.0)
        self.assertIn("Zwycięzca – underdog", [k["label"] for k in s["kinds"]])
        text, k = picks.export_text(conn)
        c2 = sqlite3.connect(":memory:")
        self.assertEqual(picks.import_text(c2, text), 5)
        self.assertEqual(picks.import_text(c2, text), 0)
        # krecz = zwrot
        c3 = sqlite3.connect(":memory:")
        picks.add(c3, mk("w1"), "w1", 0.7)
        picks.settle_open(c3, lambda *a: {**res, "comment": "Retired"})
        self.assertEqual(picks.load(c3).status.iloc[0], "void")


class CouponTests(unittest.TestCase):
    """0.3.13: szkic -> zatwierdzony kupon (na stałe), AKO gdy wszystkie kursy, migracja bazy z 0.3.12."""

    def mk(self, key, a="A X.", b="B Y."):
        return bm.leg_id("ATP", "2026-11-09", a, b, "Hard", 3, key)

    def test_confirm_lock_and_status(self):
        from tnpred import picks
        conn = sqlite3.connect(":memory:")
        with self.assertRaises(ValueError):
            picks.confirm(conn)                                    # pusty szkic
        picks.add(conn, self.mk("w1"), "A wygra", 0.7, None, 1.5)
        picks.add(conn, self.mk("tb", "C Z.", "D W."), "TB", 0.4, None, 2.0)
        self.assertEqual(len(picks.draft(conn)), 2)
        c1 = picks.confirm(conn, "pierwszy")
        self.assertEqual(len(picks.draft(conn)), 0)
        pid = int(picks.load(conn).id.iloc[0])
        with self.assertRaises(picks.Locked):
            picks.remove(conn, pick_id=pid)
        with self.assertRaises(picks.Locked):
            picks.set_kurs(conn, pid, 3.0)
        picks.add(conn, self.mk("str", "E V.", "F U."), "bez straty", 0.6)      # nowy szkic, bez kursu
        c2 = picks.confirm(conn)
        cps = {c["id"]: c for c in picks.coupons(conn)}
        self.assertEqual((cps[c1]["kind"], round(cps[c1]["odds"], 2), round(cps[c1]["p"], 2)), ("AKO", 3.0, 0.28))
        self.assertEqual((cps[c2]["kind"], cps[c2]["odds"]), ("bez kursów", None))
        res = {"A X.": {"winner": "A X.", "loser": "B Y.", "w1": 6, "l1": 4, "w2": 6, "l2": 2, "comment": "Completed"},
               "C Z.": {"winner": "C Z.", "loser": "D W.", "w1": 7, "l1": 6, "w2": 6, "l2": 3, "comment": "Completed"}}
        picks.settle_open(conn, lambda t, d, a, b: res.get(a))
        cps = {c["id"]: c for c in picks.coupons(conn)}
        self.assertEqual((cps[c1]["status"], round(cps[c1]["profit"], 2)), ("won", 2.0))
        self.assertEqual(cps[c2]["status"], "open")
        cs = picks.coupon_summary(list(cps.values()))
        self.assertEqual((cs["n"], cs["won"], cs["n_kurs"]), (1, 1, 1))
        # eksport/import z kuponami
        c9 = sqlite3.connect(":memory:")
        picks.import_coupons(c9, picks.export_coupons(conn)[0])
        picks.import_text(c9, picks.export_text(conn)[0])
        self.assertEqual([c["n"] for c in picks.coupons(c9)], [1, 2])

    def test_migration_from_0312(self):
        from tnpred import picks
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE picks (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, leg TEXT UNIQUE, tour TEXT, "
                     "date TEXT, p1 TEXT, p2 TEXT, key TEXT, label TEXT, grp TEXT, p REAL, ref REAL, kurs REAL, status TEXT, settled_at TEXT)")
        conn.execute("INSERT INTO picks (leg, tour, date, p1, p2, key, label, grp, p, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (self.mk("w1"), "ATP", "2026-11-09", "A X.", "B Y.", "w1", "x", "g", 0.6, "open"))
        self.assertEqual(len(picks.draft(conn)), 1)                # stare typy = szkic
        old_csv = "id,created_at,leg,tour,date,p1,p2,key,label,grp,p,ref,kurs,status,settled_at\n5,,%s,ATP,2026-11-09,C,D,tb,tb,g,0.4,,,open,\n" % self.mk("tb", "C", "D")
        self.assertEqual(picks.import_text(conn, old_csv), 1)
        self.assertEqual(picks.confirm(conn), 1)

    def test_web_confirm_flow(self):
        from tnpred.web import create_app
        st = bootstrap.State(os.path.join(_TMP, "coupon.db"))
        df = demo_df()
        db.upsert_matches(st.conn, df)
        db.upsert_upcoming(st.conn, synthetic.upcoming(df, n=2))
        app = create_app(st, background=False)
        bootstrap.refresh(st, network=False)
        c = app.test_client()
        import html as _h
        legs_ = [_h.unescape(x) for x in re.findall(r'data-pick="([^"]+)"', c.get("/").data.decode())]
        for leg in legs_[:2]:
            self.assertTrue(c.post("/api/picks", json={"leg": leg}).get_json()["on"])
        self.assertIn("Zatwierdź kupon", c.get("/picks").data.decode())
        r = c.post("/picks/confirm", data={"note": "test"})
        self.assertEqual(r.status_code, 302)
        page = c.get("/picks").data.decode()
        self.assertIn("Kupon nr 1", page)
        r = c.post("/api/picks", json={"leg": legs_[0]})
        self.assertEqual(r.status_code, 409)                       # zatwierdzony typ nie znika z kafelka
        self.assertIn("pk on", c.get("/").data.decode())


class SyncOrderTests(unittest.TestCase):
    """0.3.14: restart z pustą bazą nie może nadpisać GitHuba (zgubione kupony 11.11)."""

    def test_no_upload_before_download_and_grow_only(self):
        from unittest import mock
        from tnpred import gh_store, picks
        remote = {}
        mk = lambda k: bm.leg_id("ATP", "2026-11-09", "A X.", "B Y.", "Hard", 3, k)  # noqa: E731
        c0 = sqlite3.connect(":memory:")
        picks.add(c0, mk("w1"), "A", 0.7)
        picks.confirm(c0)
        remote["picks"] = picks.export_text(c0)[0]
        remote["coupons"] = picks.export_coupons(c0)[0]
        pushed = []

        def pull(path):
            k = [k for k, v in gh_store.FILES.items() if path.endswith(v)][0]
            return remote.get(k), None

        def push(text, path, message=""):
            pushed.append(path)
            k = [k for k, v in gh_store.FILES.items() if path.endswith(v)][0]
            remote[k] = text
        st = bootstrap.State(":memory:")                         # świeży Render: pusta baza
        with mock.patch.object(gh_store, "enabled", lambda: True), mock.patch.object(gh_store, "pull", pull), \
                mock.patch.object(gh_store, "push", push), mock.patch.object(gh_store, "check", lambda: (True, "ok")):
            bootstrap.sync_up(st)                               # przed odczytem: nic nie wysyła
            self.assertEqual(pushed, [])
            bootstrap.sync_down(st)
            self.assertTrue(st.gh_loaded)
            self.assertEqual(len(picks.coupons(st.conn)), 1)       # kupon wrócił
            bootstrap.sync_up(st, ("picks", "coupons"))
            self.assertEqual(pushed, [])                           # bez zmian
            with self.assertRaises(RuntimeError):                  # kupony tylko przybywają
                gh_store.sync_up("coupons", lambda: ("id,created_at,note\n", 0), "kuponów")
        self.assertIn("1,", remote["coupons"])


if __name__ == "__main__":
    unittest.main()
