import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fbpred import avail, config
from fbpred.fetch import ApiClient

FIX = [{"fixture": {"id": 900, "date": "2026-10-30T19:45:00+00:00"},
        "teams": {"home": {"name": "AC Milan"}, "away": {"name": "Bologna"}}},
       {"fixture": {"id": 901, "date": "2026-10-30T17:00:00+00:00"},
        "teams": {"home": {"name": "Inter"}, "away": {"name": "Torino"}}}]
INJ = [{"fixture": {"id": 900}, "team": {"name": "AC Milan"}, "player": {"name": "R. Leao", "type": "Missing Fixture", "reason": "Knee Injury"}},
       {"fixture": {"id": 900}, "team": {"name": "Bologna"}, "player": {"name": "J. Zirkzee", "type": "Questionable", "reason": "Suspended"}},
       {"fixture": {"id": 901}, "team": {"name": "Inter"}, "player": {"name": "X", "type": "Missing Fixture", "reason": "Illness"}}]
LU = [{"team": {"name": "AC Milan"}, "formation": "4-2-3-1", "coach": {"name": "Allegri"},
       "startXI": [{"player": {"name": "Maignan"}}], "substitutes": [{"player": {"name": "Sportiello"}}]}]


class Fake:
    """Atrapa klienta: liczy zapytania, ma cache jak prawdziwy."""
    def __init__(self, data):
        self.data, self.used, self.remaining, self.seen = data, 0, 99, set()

    def cached(self, path, params, ttl=None):
        return (path, json.dumps(params, sort_keys=True)) in self.seen

    def get(self, path, params, ttl=None):
        k = (path, json.dumps(params, sort_keys=True))
        if k not in self.seen:
            self.used += 1
            self.seen.add(k)
        return self.data[path]


class TestAvail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.budget = avail.Budget(Path(self.tmp.name), cap=10)

    def tearDown(self):
        self.tmp.cleanup()

    def test_injuries_per_team_and_name_matching(self):
        c = Fake({"/fixtures": FIX, "/injuries": INJ})
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=c, budget=self.budget)
        self.assertTrue(r["ok"])
        self.assertEqual(r["fixture_id"], 900)
        self.assertEqual([k["gracz"] for k in r["kontuzje"]["home"]], ["R. Leao"])
        self.assertEqual(r["kontuzje"]["away"][0]["powod"], "Suspended")      # wpis Interu (inny mecz) pominięty

    def test_second_call_uses_cache_and_budget_counts_only_real_requests(self):
        c = Fake({"/fixtures": FIX, "/injuries": INJ})
        avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=c, budget=self.budget)
        self.assertEqual((c.used, self.budget.used()), (2, 2))               # fixtures + injuries
        avail.for_match("I1", "Inter", "Torino", "2026-10-30", client=c, budget=self.budget)
        self.assertEqual(c.used, 2)                                           # inny mecz tego dnia: z cache, 0 zapytań
        self.assertEqual(self.budget.used(), 2)

    def test_lineups_only_on_request(self):
        c = Fake({"/fixtures": FIX, "/injuries": INJ, "/lineups": LU})
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=c, budget=self.budget)
        self.assertIsNone(r["sklady"])
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", with_lineups=True, client=c, budget=self.budget)
        self.assertEqual(r["sklady"]["home"]["formacja"], "4-2-3-1")

    def test_daily_cap_blocks_new_requests_but_not_cached(self):
        c = Fake({"/fixtures": FIX, "/injuries": INJ})
        b = avail.Budget(Path(self.tmp.name), cap=1)
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=c, budget=b)
        self.assertFalse(r["ok"])
        self.assertTrue(any("limit" in u for u in r["uwagi"]))
        self.assertEqual(c.used, 1)                                           # drugi wymagałby przekroczenia limitu

    def test_unknown_match_and_unknown_league_and_api_error(self):
        c = Fake({"/fixtures": [], "/injuries": []})
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=c, budget=self.budget)
        self.assertFalse(r["ok"]); self.assertTrue(r["uwagi"])
        self.assertFalse(avail.for_match("XX", "a", "b", "2026-10-30", client=c, budget=self.budget)["ok"])

        class Boom(Fake):
            def get(self, *a, **k):
                raise RuntimeError("HTTP 403")
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=Boom({}), budget=self.budget)
        self.assertFalse(r["ok"]); self.assertIn("403", r["uwagi"][0])        # błąd nie wywraca strony

    def test_free_plan_error_is_explained(self):
        class Free(Fake):
            def get(self, *a, **k):
                raise RuntimeError("API zwróciło błąd: {'plan': 'Free plans do not have access to this season, try from 2021 to 2023.'}")
        r = avail.for_match("I1", "Milan", "Bologna", "2026-10-30", client=Free({}), budget=self.budget)
        self.assertFalse(r["ok"]); self.assertIn("płatnego planu", r["uwagi"][0])

    def test_season_of(self):
        self.assertEqual((avail.season_of("2026-10-30"), avail.season_of("2027-03-01")), (2026, 2026))

    def test_real_client_cached_flag(self):
        with tempfile.TemporaryDirectory() as d:
            c = ApiClient(key="K", cache_dir=Path(d))
            self.assertFalse(c.cached("/x", {"a": 1}))
            c._file("/x", {"a": 1}).write_text(json.dumps({"response": []}))
            self.assertTrue(c.cached("/x", {"a": 1}))
            self.assertEqual(c.get("/x", {"a": 1}), []); self.assertEqual(c.used, 0)

    def test_probe_prints_report(self):
        data = {"/status": {"subscription": {"plan": "Free"}, "requests": {"current": 3, "limit_day": 100}},
                "/odds/bets": [{"id": 99, "name": None}, {"id": 1, "name": "Match Winner"}, {"id": 13, "name": "First Half Winner"}, {"id": 5, "name": "Goals Over/Under"}],
                "/fixtures": FIX, "/odds": [{"bookmakers": [{"bets": [{"id": 1, "name": "Match Winner"}, {"id": 20, "name": "Double Chance - First Half"}, {"id": 13, "name": "First Half Winner", "values": [{"value": "Home", "odd": "2.5"}, {"value": "Draw", "odd": "2.1"}, {"value": "Away", "odd": "3.4"}]}, {"id": 0, "name": None}]}]}],
                "/injuries": INJ}
        lines = []
        avail.probe("I1", client=Fake(data), out=lines.append)
        text = "\n".join(lines)
        self.assertIn("plan=Free", text); self.assertIn("First Half Winner", text); self.assertIn("Double Chance - First Half", text); self.assertIn("Draw=2.1", text)

    def test_probe_continues_after_api_error(self):
        class Err(Fake):
            def get(self, path, params, ttl=None):
                if path == "/fixtures":
                    raise RuntimeError("API zwróciło błąd: {'plan': 'Free plans do not have access to this season'}")
                return super().get(path, params, ttl)
        lines = []
        avail.probe("I1", client=Err({"/status": {}, "/odds/bets": [{"id": 1, "name": "Match Winner"}]}), out=lines.append)
        text = "\n".join(lines)
        self.assertIn("BŁĄD w kroku 'najbliższe mecze'", text)
        self.assertIn("Free plans do not have access", text)
        self.assertIn("zużyto zapytań", text)                               # raport doszedł do końca

    def test_match_page_shows_block_when_enabled(self):
        from tests.test_v4 import Env
        from fbpred import db, history, csvdata
        from tests.test_bootstrap import fd_csv
        import pandas as pd
        env = Env(); env.setUp()
        try:
            sy = 2025
            history.save_matches(csvdata.parse_csv(fd_csv(sy), "E0", sy), config.HISTORY_DIR)
            from fbpred.web import create_app
            app = create_app()
            conn = db.connect(config.DB_PATH)
            teams = sorted(set(db.load_matches(conn, "E0")["home"]))[:2]
            fake = {"ok": True, "uwagi": [], "kontuzje": {"home": [{"gracz": "Test Player", "status": "Missing Fixture", "powod": "Knee"}], "away": []},
                    "sklady": None, "fixture_id": 1, "limit_dzis": "2/40"}
            c = app.test_client()
            url = f"/match?league=E0&home={teams[0]}&away={teams[1]}&date=2026-10-30"
            for _ in range(60):
                with mock.patch.object(avail, "enabled", return_value=True), mock.patch.object(avail, "for_match", return_value=fake):
                    r = c.get(url)
                if r.status_code == 200:
                    break
                import time; time.sleep(1)
            html = r.get_data(as_text=True)
            self.assertIn("Dostępność zawodników", html)
            self.assertIn("Test Player", html)
            self.assertIn("lineups=1", html)
        finally:
            env.tearDown()


if __name__ == "__main__":
    unittest.main()
