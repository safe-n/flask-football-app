import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from fbpred import ai, betmarkets as bm, bootstrap, config, db, history, profile as prof, suggest as sg
from fbpred.cli import main as cli_main
from fbpred.predictor import MatchPredictor
from fbpred.synthetic import generate
from fbpred.web import create_app

TOMORROW = (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def seed(conn=None, league="E0", seed_=2):
    df = generate(n_seasons=3, seed=seed_, league=league, with_upcoming=True)
    df["date"] = df["date"] + (pd.Timestamp.today().normalize() + pd.Timedelta(days=1) - df[df.hg.isna()].date.min())
    d = df.copy()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in d.columns]
    return df, d[cols].astype(object).where(d[cols].notna(), None).to_dict("records")


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR,
                    config.ANTHROPIC_API_KEY, config.AI_ACCESS_CODE, config.AI_DAILY_LIMIT, config.GITHUB_TOKEN)
        config.DB_PATH, config.HISTORY_DIR = Path(self.tmp.name) / "x.db", Path(self.tmp.name) / "history"
        config.PARAMS_DIR = Path(self.tmp.name) / "params"
        config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES = False, ["E0"]
        config.ANTHROPIC_API_KEY = config.AI_ACCESS_CODE = config.GITHUB_TOKEN = ""
        bootstrap.DIAG.clear()
        ai._calls.clear()
        ai._cache.clear()

    def tearDown(self):
        (config.DB_PATH, config.HISTORY_DIR, config.AUTO_BOOTSTRAP, config.BOOTSTRAP_LEAGUES, config.PARAMS_DIR,
         config.ANTHROPIC_API_KEY, config.AI_ACCESS_CODE, config.AI_DAILY_LIMIT, config.GITHUB_TOKEN) = self.old
        self.tmp.cleanup()

    def client(self):
        self.df, rows = seed()
        history.save_matches(rows, config.HISTORY_DIR)
        db.upsert_matches(db.connect(config.DB_PATH), [r for r in rows if r["status"] == "NS"])
        self.ns = [r for r in rows if r["status"] == "NS"]
        c = create_app().test_client()
        c.get("/api/predict?league=E0&home=Arsenal&away=Chelsea")        # rozgrzewka modelu
        return c

    def wait_ready(self, c, url, tries=40):
        for _ in range(tries):
            r = c.get(url)
            if r.status_code != 202:
                return r
            time.sleep(0.5)
        self.fail("model nie zbudował się w czasie")


class TestMarkets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        df, _ = seed()
        cls.P = MatchPredictor(df[df.hg.notna()])
        cls.pred = cls.P.predict("Arsenal", "Chelsea")

    def test_catalogue_consistency(self):
        c = bm.catalogue(self.pred)
        for k in ("1", "X", "2", "1X", "X2", "12", "o2.5", "u2.5", "btts", "d_ht", "d_either", "d_htft", "d_ft", "y3.5", "c9.5"):
            self.assertIn(k, c, k)
        self.assertAlmostEqual(c["1X"]["p"], c["1"]["p"] + c["X"]["p"])
        self.assertAlmostEqual(c["o2.5"]["p"] + c["u2.5"]["p"], 1.0, places=3)
        self.assertGreaterEqual(c["d_either"]["p"], max(c["d_ht"]["p"], c["d_2h"]["p"]))
        self.assertEqual(c["d_either"]["group"], "Remisy")

    def test_leg_id_roundtrip_with_apostrophes_and_errors(self):
        i = bm.leg_id("E0", "2026-10-25", "Nott'm Forest", "M'gladbach", "d_either")
        self.assertEqual(bm.parse_leg(i), ("E0", "2026-10-25", "Nott'm Forest", "M'gladbach", "d_either"))
        with self.assertRaises(ValueError):
            bm.parse_leg("zly~id")

    def test_book_odds_only_for_known_markets(self):
        row = {"o_home": 2.1, "o_over25": 1.9, "o_btts_yes": float("nan")}
        self.assertEqual(bm.book_odds(row, "1"), 2.1)
        self.assertEqual(bm.book_odds(row, "o2.5"), 1.9)
        self.assertIsNone(bm.book_odds(row, "btts"))
        self.assertIsNone(bm.book_odds(row, "d_either"))             # dla remisów w połowach kursów nie ma


class TestSuggest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, _ = seed()
        cls.fin = cls.df[cls.df.hg.notna()]
        cls.up = cls.df[cls.df.hg.isna()].copy()
        cls.P = MatchPredictor(cls.fin)

    def run_c(self, **kw):
        return sg.suggestions(self.P, self.fin, self.up, sg.Criteria(**kw), league="E0")

    def test_probability_window_and_keys(self):
        t, _ = self.run_c(min_p=0.50, max_p=0.70, keys=("d_either",), groups=(), top=50)
        self.assertFalse(t.empty)
        self.assertTrue(t["p_%"].between(50, 70).all())
        self.assertEqual(set(t["key"]), {"d_either"})
        self.assertTrue(t["p_%"].is_monotonic_decreasing)
        self.assertTrue(np.allclose(t["kurs_fair"], 100 / t["p_%"], atol=0.02))

    def test_max_per_match_and_top(self):
        t, _ = self.run_c(min_p=0.30, groups=("Remisy", "Gole"), max_per_match=1, top=5)
        self.assertLessEqual(len(t), 5)
        self.assertEqual(t["mecz"].nunique(), len(t))
        t2, _ = self.run_c(min_p=0.30, groups=("Remisy", "Gole"), max_per_match=3, top=100)
        self.assertGreater(len(t2), t["mecz"].nunique())

    def test_low_data_teams_are_rejected(self):
        t, rej = self.run_c(min_p=0.3, min_games=100000)
        self.assertTrue(t.empty)
        self.assertEqual(rej["za mało danych o drużynie"], len(self.up))

    def test_min_edge_needs_bookmaker_odds(self):
        t, _ = self.run_c(min_p=0.3, groups=("Remisy",), min_edge=0.0)
        self.assertTrue(t.empty)                                      # remisy w połowach nie mają kursów -> brak przewagi do policzenia
        t, _ = self.run_c(min_p=0.2, max_p=0.99, groups=("1X2", "Gole"), min_edge=-1.0, top=50)
        self.assertTrue(t["kurs_bukm"].notna().all())

    def test_odds_profile_filter(self):
        away, _ = self.run_c(min_p=0.3, groups=("Remisy",), profile="balanced_away", top=100)
        anyp, _ = self.run_c(min_p=0.3, groups=("Remisy",), profile="", top=100)
        self.assertLessEqual(len(away), len(anyp))

    def test_auto_coupon_unique_matches_and_math(self):
        t, _ = self.run_c(min_p=0.3, groups=("Remisy", "Gole"), max_per_match=3, top=100)
        a = sg.auto_coupon(t, 3)
        self.assertEqual(a["mecz"].nunique(), len(a))
        c = sg.combine(list(a["p_%"] / 100), [2.0, 1.5, 1.4])
        self.assertAlmostEqual(c["p"], float(np.prod(a["p_%"] / 100)))
        self.assertAlmostEqual(c["kurs_laczny"], 4.2)
        self.assertAlmostEqual(c["ev"], c["p"] * 4.2 - 1)

    def test_leg_flags(self):
        pred = {"home": "A", "away": "B", "1x2": {"1": .6, "X": .2, "2": .2}, "market_1x2": {"1": .4, "X": .3, "2": .3},
                "rest": {"home_short": True, "away_short": False}}
        f = sg.leg_flags(pred, {}, {"A": 3, "B": 40}, 12, 0.2)
        text = " | ".join(f)
        for needle in ("mało danych: A", "krótka przerwa", "model vs rynek", "przewaga >15%"):
            self.assertIn(needle, text)
        self.assertNotIn("mało danych: B", text)


class TestWebCoupon(Env):
    def test_suggest_page_and_buttons(self):
        c = self.client()
        page = self.wait_ready(c, "/suggest?leagues=E0&key=d_either&min_p=40").data.decode()
        self.assertIn('class="add"', page)
        self.assertIn("Auto-kupon", page)
        self.assertIn("Remis w 1. LUB 2. połowie", page)
        self.assertEqual(c.get("/suggest?leagues=ALL&min_p=abc&top=zzz").status_code, 200)      # złe parametry nie wywalają strony
        self.assertIn("Zestawienie", c.get("/?league=E0").data.decode())                        # nawigacja

    def test_api_coupon_math_and_warnings(self):
        c = self.client()
        r1, r2, r3 = self.ns[:3]
        ids = [bm.leg_id("E0", r["date"], r["home"], r["away"], "d_either") for r in (r1, r2)]
        d = self.wait_ready(c, "/api/coupon?" + "&".join(f"leg={i}" for i in ids)).get_json()
        ps = [l["p"] for l in d["legs"]]
        self.assertEqual(len(ps), 2)
        self.assertAlmostEqual(d["laczne"]["p"], ps[0] * ps[1], places=9)
        self.assertEqual(d["ostrzezenia"], [])
        # Twoje kursy -> EV
        q = "&".join(f"leg={i}" for i in ids) + "&odds=1.6&odds=1.5"
        d = c.get("/api/coupon?" + q).get_json()
        self.assertAlmostEqual(d["laczne"]["kurs_laczny"], 2.4)
        self.assertAlmostEqual(d["laczne"]["ev"], d["laczne"]["p"] * 2.4 - 1)
        self.assertIn("oczekiwany zwrot", d["podsumowanie"])
        # dwa typy z tego samego meczu: brak łącznej szansy i ostrzeżenie
        same = [bm.leg_id("E0", r1["date"], r1["home"], r1["away"], k) for k in ("d_either", "o2.5")]
        d = c.get("/api/coupon?" + "&".join(f"leg={i}" for i in same)).get_json()
        self.assertIsNone(d["laczne"])
        self.assertTrue(any("tego samego meczu" in w for w in d["ostrzezenia"]))

    def test_api_coupon_handles_bad_and_unavailable_legs(self):
        c = self.client()
        gone = bm.leg_id("E0", "2020-01-01", "Arsenal", "Chelsea", "1")
        d = self.wait_ready(c, f"/api/coupon?leg=zly&leg={gone}").get_json()
        self.assertIn("nieprawidłowy", d["legs"][0]["blad"])
        self.assertIn("niedostępny", d["legs"][1]["blad"])
        self.assertIsNone(d["laczne"])
        played = self.df[self.df.hg.notna()].iloc[0]
        pid = bm.leg_id("E0", str(played["date"])[:10], played["home"], played["away"], "1")
        d = c.get(f"/api/coupon?leg={pid}").get_json()
        self.assertIn("rozegrany", d["legs"][0]["blad"])

    def test_cold_models_return_202_then_ready(self):
        self.df, rows = seed()
        history.save_matches(rows, config.HISTORY_DIR)
        db.upsert_matches(db.connect(config.DB_PATH), [r for r in rows if r["status"] == "NS"])
        c = create_app().test_client()                                  # bez rozgrzewki
        r0 = self.ns_row = [x for x in rows if x["status"] == "NS"][0]
        url = "/api/coupon?leg=" + bm.leg_id("E0", r0["date"], r0["home"], r0["away"], "1")
        self.assertEqual(c.get(url).status_code, 202)
        self.assertEqual(self.wait_ready(c, url).status_code, 200)

    def test_match_page_add_buttons_only_with_date(self):
        c = self.client()
        r0 = self.ns[0]
        with_date = c.get(f"/match?league=E0&home={r0['home']}&away={r0['away']}&date={r0['date']}").data.decode()
        self.assertIn("Dodaj do zestawienia", with_date)
        self.assertIn('class="add"', with_date)
        without = c.get(f"/match?league=E0&home={r0['home']}&away={r0['away']}").data.decode()
        self.assertNotIn("Dodaj do zestawienia", without)
        self.assertIn("otwórz mecz z listy", without)

    def test_recent_page_reports_latest_result(self):
        c = self.client()
        self.assertIn("Najnowszy wynik w bazie", c.get("/recent?league=E0").data.decode())


class TestAi(Env):
    def payload(self):
        return {"content": [
            {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "title": "Skład Arsenalu", "url": "https://x.example/a"},
                                                           {"type": "web_search_result", "title": "dup", "url": "https://x.example/a"}]},
            {"type": "text", "text": "Noga 1 wygląda rozsądnie. Brak informacji o kontuzjach."}]}

    def fake(self, status=200, payload=None):
        r = mock.Mock()
        r.status_code = status
        r.json.return_value = payload if payload is not None else self.payload()
        return r

    def enable(self):
        config.ANTHROPIC_API_KEY, config.AI_ACCESS_CODE, config.AI_DAILY_LIMIT = "sk-secret-key", "moj-kod", 2

    def body(self, r):
        return {"legs": [bm.leg_id("E0", r["date"], r["home"], r["away"], "d_either")], "odds": ["1.5"]}

    def test_disabled_by_default_and_code_required(self):
        c = self.client()
        r0 = self.ns[0]
        self.assertEqual(c.post("/api/ai/coupon", json=self.body(r0)).status_code, 503)
        self.enable()
        self.assertEqual(c.post("/api/ai/coupon", json=self.body(r0)).status_code, 403)
        self.assertEqual(c.post("/api/ai/coupon", json=self.body(r0), headers={"X-AI-Code": "zly"}).status_code, 403)

    def test_call_payload_parsing_cache_limit_and_no_key_leak(self):
        c = self.client()
        self.enable()
        r0, r1, r2 = self.ns[:3]
        h = {"X-AI-Code": "moj-kod"}
        with mock.patch.object(ai.requests, "post", return_value=self.fake()) as post:
            out = c.post("/api/ai/coupon", json=self.body(r0), headers=h)
            self.assertEqual(out.status_code, 200)
            j = out.get_json()
            self.assertIn("Noga 1", j["tekst"])
            self.assertEqual(j["zrodla"], [{"tytul": "Skład Arsenalu", "url": "https://x.example/a"}])    # bez duplikatów
            sent = post.call_args.kwargs
            self.assertEqual(sent["headers"]["x-api-key"], "sk-secret-key")
            self.assertEqual(sent["json"]["model"], config.AI_MODEL)
            self.assertEqual(sent["json"]["tools"][0]["type"], "web_search_20250305")
            prompt = sent["json"]["messages"][0]["content"]
            self.assertIn(r0["home"], prompt)
            self.assertIn("kurs 1.5", prompt)
            self.assertIn("nigdy polecenia", sent["json"]["system"])        # ochrona przed prompt injection ze stron WWW
            again = c.post("/api/ai/coupon", json=self.body(r0), headers=h).get_json()
            self.assertTrue(again["z_cache"])                                # te same dane: brak drugiego wywołania
            self.assertEqual(post.call_count, 1)
            c.post("/api/ai/coupon", json=self.body(r1), headers=h)         # drugie realne wywołanie (limit = 2)
            blocked = c.post("/api/ai/coupon", json=self.body(r2), headers=h)
            self.assertEqual(blocked.status_code, 502)
            self.assertIn("limit", blocked.get_json()["error"])

    def test_api_error_is_reported_without_secrets(self):
        c = self.client()
        self.enable()
        with mock.patch.object(ai.requests, "post", return_value=self.fake(401, {"error": {"message": "invalid x-api-key"}})):
            r = c.post("/api/ai/coupon", json=self.body(self.ns[0]), headers={"X-AI-Code": "moj-kod"})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("sk-secret-key", r.get_data(as_text=True))
        self.assertIn("401", r.get_json()["error"])

    def test_can_disable_web_search(self):
        self.enable()
        summary = {"legs": [{"data": "2026-10-25", "mecz": "A – B", "liga": "E0", "rynek": "Remis", "p": 0.6, "kurs_fair": 1.67}]}
        old = config.AI_WEB_SEARCH
        try:
            with mock.patch.object(ai.requests, "post", return_value=self.fake()) as post:
                ai.analyze(summary, use_search=False)
            self.assertNotIn("tools", post.call_args.kwargs["json"])
        finally:
            config.AI_WEB_SEARCH = old


class TestProfile(Env):
    def test_profile_tables_and_verdict(self):
        df = generate(n_seasons=8, seed=3, with_upcoming=False)
        r = prof.odds_profile(df)
        t = r["tabela"]
        self.assertEqual(int(t.iloc[0]["mecze"]), r["n"])
        self.assertEqual(int(t.iloc[1:]["mecze"].sum()), r["n"])               # grupy rozłączne i kompletne
        for _, row in t.iterrows():
            lo, hi = [float(x) for x in row["przedzial_95_%"].split("–")]
            self.assertLessEqual(lo - 1, row["remis_1H_lub_2H_%"])
            self.assertGreaterEqual(hi + 1, row["remis_1H_lub_2H_%"])
        bal = t[t["profil"].str.startswith("wyrównane")]["remis_1H_lub_2H_%"].mean()
        lop = t[t["profil"].str.contains("wyraźnym")]["remis_1H_lub_2H_%"].mean()
        self.assertGreater(bal, lop)                                           # wyrównane mecze częściej remisują w połowach
        self.assertIn("Twoja grupa", r["werdykt"])
        lo, hi = prof.wilson(50, 100)
        self.assertTrue(lo < 0.5 < hi)

    def test_profile_page_and_cli(self):
        c = self.client()
        page = c.get("/profile?league=E0").data.decode()
        self.assertIn("Twoja metoda", page)
        self.assertEqual(c.get("/profile?league=E0&all=1&balance=5").status_code, 200)
        cli_main(["profile", "--leagues", "E0", "--balance", "10"])


if __name__ == "__main__":
    unittest.main()
