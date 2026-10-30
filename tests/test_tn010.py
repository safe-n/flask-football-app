"""Testy tnpred 0.1.0 (tenis). Izolacja: baza, historia i parametry w katalogach tymczasowych, bez internetu."""
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

    def test_sackmann_parse(self):
        raw = pd.DataFrame([{"tourney_name": "Wimbledon", "surface": "Grass", "tourney_level": "G", "tourney_date": 20250630,
                             "round": "F", "best_of": 5, "winner_name": "Jannik Sinner", "loser_name": "Carlos Alcaraz",
                             "winner_rank": 1, "loser_rank": 2, "score": "4-6 6-4 6-4 6-4"},
                            {"tourney_name": "Wimbledon", "surface": "Grass", "tourney_level": "G", "tourney_date": 20250630,
                             "round": "R128", "best_of": 5, "winner_name": "Alex de Minaur", "loser_name": "X Y",
                             "winner_rank": 10, "loser_rank": 200, "score": "7-6(5) 2-0 RET"}])
        df = tdata.from_sackmann(raw, "ATP")
        f = df[df["round"] == "The Final"].iloc[0]
        self.assertEqual((f.winner, f.loser, int(f.wsets), int(f.lsets), f.series), ("Sinner J.", "Alcaraz C.", 3, 1, "Grand Slam"))
        r = df[df["round"] == "1st Round"].iloc[0]
        self.assertEqual(r.comment, "Retired")
        self.assertEqual(int(r.w1), 7)


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


if __name__ == "__main__":
    unittest.main()
