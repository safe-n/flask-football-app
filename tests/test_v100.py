"""0.10.0 - Moje typy: klikalne kafelki -> szkic kuponu -> kupon na stałe, rozliczanie i zestawienie skuteczności."""
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd

from fbpred import betmarkets as bm, bets, config, db, gh_store, picks
from fbpred.synthetic import generate

RES = dict(hg=2, ag=1, hg_ht=1, ag_ht=1, h_yellow=2, a_yellow=3, h_corners=6, a_corners=5)   # 2:1, do przerwy 1:1


def _leg(key, home="A", away="B", date="2026-11-20", lg="E0"):
    return bm.leg_id(lg, date, home, away, key)


def _mem():
    conn = sqlite3.connect(":memory:")
    picks.ensure(conn)
    return conn


class TestPicksModule(unittest.TestCase):
    def test_kind(self):
        self.assertEqual(picks.kind("1", True), "Zwycięzca – faworyt")
        self.assertEqual(picks.kind("2", False), "Zwycięzca – underdog")
        for key, k in (("X", "Remis (koniec meczu)"), ("d_ft", "Remis (koniec meczu)"), ("o2.5", "Over goli"), ("u2.5", "Under goli"),
                       ("btts", "BTTS"), ("d_ht", "Remisy w połowach"), ("d_htft", "Remisy w połowach"), ("y3.5", "Kartki"),
                       ("c9.5", "Rożne"), ("1X", "Podwójna szansa"), ("cos", "Inne")):
            self.assertEqual(picks.kind(key), k)
            self.assertIn(k, picks.KINDS)

    def test_every_tile_key_settles(self):
        """Każdy klucz klikalnego kafelka musi być znany rozliczaniu (bets.leg_won) i katalogowi rynków."""
        want = {"1": True, "X": False, "2": False, "o2.5": True, "btts": True, "d_ht": True, "d_2h": False, "d_either": True,
                "d_htft": True, "d_ft": False, "y3.5": True, "c9.5": True}
        self.assertEqual(set(want), set(picks.X12) | set(picks.TILE_OF))
        conn = _mem()
        for k in want:
            picks.add(conn, _leg(k), k, 0.5)
        self.assertEqual(picks.settle_open(conn, lambda *a: None), 0)                      # brak wyniku = czekamy
        self.assertEqual(picks.settle_open(conn, lambda *a: {"hg": None, "ag": None}), 0)
        self.assertEqual(picks.settle_open(conn, lambda lg, d, h, a: RES if (lg, d, h, a) == ("E0", "2026-11-20", "A", "B") else None), len(want))
        got = {r[0]: r[1] for r in conn.execute("SELECT key, status FROM picks")}
        self.assertEqual(got, {k: "hit" if v else "miss" for k, v in want.items()})

    def test_halves_wait_for_halftime_score(self):
        conn = _mem()
        picks.add(conn, _leg("d_ht"), "Remis HT", 0.4)
        picks.add(conn, _leg("1"), "1", 0.5)
        self.assertEqual(picks.settle_open(conn, lambda *a: {"hg": 2, "ag": 1}), 1)        # EL: brak wyniku do przerwy
        self.assertEqual(dict(conn.execute("SELECT key, status FROM picks")), {"d_ht": "open", "1": "hit"})

    def test_toggle_lock_and_coupon(self):
        conn = _mem()
        picks.add(conn, _leg("1"), "1", 0.6, 0.55, 1.8, True)
        picks.add(conn, _leg("1"), "1", 0.6)                                               # duplikat ignorowany
        picks.add(conn, _leg("o2.5", "C", "D"), "Over", 0.5, 0.5, 2.0)
        self.assertEqual(len(picks.legs(conn)), 2)
        picks.remove(conn, leg=_leg("o2.5", "C", "D"))
        picks.add(conn, _leg("o2.5", "C", "D"), "Over", 0.5, 0.5, 2.0)
        p, odds = picks.joint(picks.draft(conn))
        self.assertAlmostEqual(p, 0.3)
        self.assertAlmostEqual(odds, 3.6)
        cid = picks.confirm(conn, "notka")
        self.assertTrue(picks.draft(conn).empty)
        with self.assertRaises(ValueError):
            picks.confirm(conn)                                                            # pusty szkic
        with self.assertRaises(picks.Locked):
            picks.remove(conn, leg=_leg("1"))
        with self.assertRaises(picks.Locked):
            picks.set_kurs(conn, 1, 3.0)
        c = picks.coupons(conn)[0]
        self.assertEqual((c["id"], c["kind"], c["status"], c["n"], c["note"]), (cid, "AKO", "open", 2, "notka"))
        picks.settle_open(conn, lambda *a: RES)
        c = picks.coupons(conn)[0]
        self.assertEqual(c["status"], "won")
        self.assertAlmostEqual(c["profit"], 2.6)
        s = picks.coupon_summary(picks.coupons(conn))
        self.assertEqual((s["n"], s["won"], s["n_kurs"]), (1, 1, 1))

    def test_coupon_without_odds_void_and_same_match(self):
        conn = _mem()
        picks.add(conn, _leg("X"), "X", 0.3)
        picks.add(conn, _leg("d_ft"), "Remis FT", 0.3)                                     # to samo zdarzenie, ten sam mecz
        dr = picks.draft(conn)
        self.assertFalse(picks.independent(dr))
        self.assertEqual(picks.joint(dr), (None, None))
        picks.confirm(conn)
        c = picks.coupons(conn)[0]
        self.assertEqual((c["kind"], c["p"], c["odds"], c["profit"]), ("bez kursów", None, None, None))
        picks.set_status(conn, 1, "miss")
        self.assertEqual(picks.coupons(conn)[0]["status"], "lost")
        picks.set_status(conn, 1, "void")
        picks.set_status(conn, 2, "void")
        self.assertEqual(picks.coupons(conn)[0]["status"], "void")
        self.assertEqual(picks.coupon_summary(picks.coupons(conn)), {})

    def test_summary(self):
        conn = _mem()
        for i, (k, p, fav, kurs, st) in enumerate([("1", 0.7, True, 1.5, "hit"), ("1", 0.7, True, None, "miss"), ("2", 0.25, False, 4.0, "hit"),
                                                   ("o2.5", 0.55, None, None, "hit"), ("btts", 0.5, None, None, "open")]):
            picks.add(conn, _leg(k, f"H{i}", f"A{i}"), k, p, None, kurs, fav)
            picks.set_status(conn, i + 1, st)
        s = picks.summary(picks.load(conn))
        self.assertEqual((s["total"], s["open"], s["all"]["n"], s["all"]["hit"]), (5, 1, 4, 3))
        self.assertAlmostEqual(s["all"]["exp"], (0.7 + 0.7 + 0.25 + 0.55) / 4)
        self.assertAlmostEqual(s["all"]["diff"], 0.75 - 0.55)
        self.assertEqual([k["label"] for k in s["kinds"]], ["Zwycięzca – faworyt", "Zwycięzca – underdog", "Over goli"])
        self.assertAlmostEqual(s["all"]["profit"], 0.5 + 3.0)                              # tylko typy z kursem
        self.assertEqual(len(s["strip"]), 4)
        self.assertEqual(picks.summary(pd.DataFrame()), {})

    def test_export_import_roundtrip(self):
        conn = _mem()
        picks.add(conn, _leg("1"), "1 – gospodarz wygra", 0.6, 0.55, 1.8, True)
        picks.add(conn, _leg("btts", "C", "D"), "BTTS", 0.5)
        picks.confirm(conn, "ąę")
        picks.add(conn, _leg("X", "E", "F"), "X", 0.3)                                     # zostaje w szkicu
        ptxt, ctxt = picks.export_text(conn)[0], picks.export_coupons(conn)[0]
        new = _mem()
        self.assertEqual(picks.import_coupons(new, ctxt), 1)
        self.assertEqual(picks.import_text(new, ptxt), 3)
        self.assertEqual(picks.import_text(new, ptxt), 0)                                  # drugi raz nic nie dubluje
        self.assertEqual(picks.export_text(new)[0], ptxt)
        self.assertEqual(len(picks.draft(new)), 1)
        self.assertEqual(picks.coupons(new)[0]["note"], "ąę")
        self.assertEqual(picks.import_text(new, ""), 0)

    def test_gh_sync(self):
        store: dict[str, str] = {}
        old = gh_store.pull, gh_store.push
        gh_store.pull = lambda path=None, branch=None: (store.get(path), "sha" if path in store else None)
        gh_store.push = lambda text, path=None, branch=None, message="": store.__setitem__(path, text)
        try:
            conn = _mem()
            self.assertEqual(gh_store.picks_sync_up(conn), "nic do zapisania")             # pusto - bez pustych plików
            self.assertEqual(store, {})
            picks.add(conn, _leg("1"), "1", 0.6)
            picks.confirm(conn)
            self.assertIn("zapisano 1 typów", gh_store.picks_sync_up(conn))
            self.assertEqual(set(store), {"ledger/picks.csv", "ledger/pick_coupons.csv"})   # osobno od tennis/picks.csv
            self.assertIn("bez zmian", gh_store.picks_sync_up(conn))
            new = _mem()
            self.assertEqual(gh_store.picks_sync_down(new), 1)
            self.assertEqual(picks.coupons(new)[0]["n"], 1)
        finally:
            gh_store.pull, gh_store.push = old


class TestPicksWeb(unittest.TestCase):
    def setUp(self):
        self._old = config.DB_PATH, config.GITHUB_TOKEN
        config.DB_PATH = Path(tempfile.mkdtemp()) / "p.db"
        config.GITHUB_TOKEN = ""                                                           # testy nie piszą do GitHuba
        df = generate(n_seasons=3, seed=11, league="E0", start_year=2023, with_upcoming=True)
        self.rows = []
        for r in df.to_dict("records"):
            r = {k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
            r["date"] = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
            self.rows.append(r)
        self.tom = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        self.up = [r for r in self.rows if r.get("hg") is None][:3]
        for r in self.up:
            r["date"] = self.tom
        self.conn = db.connect(config.DB_PATH)
        db.upsert_matches(self.conn, self.rows)
        from fbpred.web import create_app
        self.c = create_app().test_client()
        for _ in range(60):
            self.html = self.c.get("/?league=E0").get_data(as_text=True)
            if 'class="card"' in self.html:
                break
            time.sleep(0.5)

    def tearDown(self):
        config.DB_PATH, config.GITHUB_TOKEN = self._old

    def _post(self, leg):
        for _ in range(60):
            r = self.c.post("/api/picks", json={"leg": leg})
            if r.status_code != 202:                                                       # 202 = model się jeszcze liczy
                return r
            time.sleep(0.5)
        return r

    def test_tiles_clickable_and_flow(self):
        m = self.up[0]
        legs = re.findall(r'data-pick="([^"]+)"', self.html)
        mine = [l for l in legs if l.startswith(f"E0~{self.tom}~{m['home']}~{m['away']}~")]
        keys = {l.rsplit("~", 1)[1] for l in mine}
        self.assertTrue({"1", "X", "2", "o2.5", "btts", "d_ht", "d_ft"} <= keys, keys)
        self.assertNotIn("yellow_mean", self.html)
        self.assertIn('href="/picks?league=E0"', self.html)                                # pozycja w menu
        leg = next(l for l in mine if l.endswith("~o2.5"))
        shown = int(re.search(re.escape(f'data-pick="{leg}"') + r'[^>]*>O2\.5<b>(\d+)%', self.html).group(1))

        r = self._post(leg)
        self.assertEqual((r.status_code, r.get_json()), (200, {"ok": True, "on": True}))
        row = self.conn.execute("SELECT p, ref, status, grp, coupon, label FROM picks WHERE leg=?", (leg,)).fetchone()
        self.assertEqual(round(100 * row[0]), shown)                                       # procent zapisany = procent widziany
        self.assertIsNotNone(row[1])                                                       # odniesienie: średnia ligi
        self.assertEqual(row[2:5], ("open", "Over goli", None))
        html = self.c.get("/?league=E0").get_data(as_text=True)                            # zaznaczenie przetrwa odświeżenie
        self.assertRegex(html, r'class="b [^"]*pk on"[^>]*' + re.escape(f'data-pick="{leg}"'))
        self.assertEqual(self._post(leg).get_json(), {"ok": True, "on": False})            # drugie kliknięcie usuwa
        self.assertEqual(len(picks.legs(self.conn)), 0)

        leg1 = next(l for l in mine if l.endswith("~1"))
        self._post(leg)
        self._post(leg1)
        page = self.c.get("/picks?league=E0").get_data(as_text=True)
        self.assertIn("Szkic kuponu", page)
        self.assertIn("dwa typy z tego samego meczu", page)
        pid = self.conn.execute("SELECT id FROM picks WHERE leg=?", (leg,)).fetchone()[0]
        self.assertEqual(self.c.post(f"/picks/{pid}/kurs?league=E0", data={"kurs": "1,95"}).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT kurs FROM picks WHERE id=?", (pid,)).fetchone()[0], 1.95)
        self.assertEqual(self.c.post("/picks/confirm?league=E0", data={"note": "test"}).status_code, 302)
        r = self._post(leg)                                                                # zatwierdzony = na stałe
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.get_json()["on"])
        self.c.post(f"/picks/{pid}/delete?league=E0")
        self.c.post(f"/picks/{pid}/kurs?league=E0", data={"kurs": "9"})
        self.assertEqual(self.conn.execute("SELECT kurs, coupon FROM picks WHERE id=?", (pid,)).fetchone(), (1.95, 1))
        self.assertEqual(self.c.post(f"/picks/{pid}/bzdura").status_code, 404)

        db.upsert_matches(self.conn, [{**m, "status": "FT", **RES}])                        # wynik 2:1 -> O2.5 i „1” wchodzą
        page = self.c.get("/picks?league=E0&days=30").get_data(as_text=True)
        self.assertEqual({r[0] for r in self.conn.execute("SELECT status FROM picks")}, {"hit"})
        self.assertIn("Kupon nr 1", page)
        self.assertIn("wszedł", page)
        self.assertIn("Typy wg rodzaju", page)
        self.assertIn("Drukuj / PDF", page)
        self.assertEqual(self._post(leg1.replace("~1", "~X")).status_code, 400)             # po meczu nie da się dodać typu

    def test_api_errors(self):
        self.assertEqual(self.c.post("/api/picks", json={"leg": "zly"}).status_code, 400)
        self.assertEqual(self._post(f"E0~{self.tom}~Nie~Ma~1").status_code, 400)
        m = self.up[1]
        self.assertEqual(self._post(bm.leg_id("E0", self.tom, m["home"], m["away"], "o7.5")).status_code, 400)   # nie ma takiego kafelka
        self.assertEqual(self.c.get("/picks").status_code, 200)                            # pusta strona też działa

    def test_bets_settle_on_page(self):
        """Regresja: /bets podawało wyszukiwarce meczu argumenty w złej kolejności i zakłady nie rozliczały się same."""
        m = self.up[2]
        bets.add_bet(self.conn, [{"id": bm.leg_id("E0", self.tom, m["home"], m["away"], "1"), "mecz": "x", "rynek": "1", "p": 0.5}], 2.0, 10)
        db.upsert_matches(self.conn, [{**m, "status": "FT", **RES}])
        self.assertEqual(self.c.get("/bets?league=E0").status_code, 200)
        self.assertEqual(self.conn.execute("SELECT status FROM bets").fetchone()[0], "won")


if __name__ == "__main__":
    unittest.main()
