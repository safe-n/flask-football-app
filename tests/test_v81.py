import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fbpred import bets, config, db, h2h


class TestLegWon(unittest.TestCase):
    R = {"hg": 2, "ag": 1, "hg_ht": 0, "ag_ht": 0, "h_yellow": 2, "a_yellow": 3, "h_corners": 6, "a_corners": 5}

    def test_markets(self):
        t = lambda k: bets.leg_won(k, self.R)  # noqa: E731
        self.assertTrue(t("1")); self.assertFalse(t("X")); self.assertTrue(t("1X")); self.assertTrue(t("12"))
        self.assertTrue(t("o2.5")); self.assertFalse(t("o3.5")); self.assertTrue(t("u3.5")); self.assertTrue(t("btts"))
        self.assertTrue(t("d_ht")); self.assertFalse(t("d_2h")); self.assertTrue(t("d_either")); self.assertTrue(t("d_htft"))
        self.assertTrue(t("y4.5")); self.assertFalse(t("y5.5")); self.assertTrue(t("c10.5")); self.assertFalse(t("c11.5"))
        self.assertIsNone(bets.leg_won("d_ht", {"hg": 1, "ag": 1}))               # brak wyniku do przerwy
        self.assertIsNone(bets.leg_won("1", {"hg": None, "ag": None}))


class TestBetsJournal(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(Path(tempfile.mkdtemp()) / "b.db")

    LEGS = [{"id": "E0~2026-10-30~A~B~1", "mecz": "A – B", "rynek": "1", "p": 0.6},
            {"id": "E0~2026-10-30~C~D~btts", "mecz": "C – D", "rynek": "BTTS", "p": 0.5}]

    def test_add_settle_and_summary(self):
        bid = bets.add_bet(self.conn, self.LEGS, 3.0, 10)
        res = {("A", "B"): {"hg": 1, "ag": 0}, ("C", "D"): None}
        look = lambda lg, d, h, a: res.get((h, a))  # noqa: E731
        self.assertEqual(bets.settle_open(self.conn, look), 0)                    # drugi mecz bez wyniku: zakład czeka
        res[("C", "D")] = {"hg": 2, "ag": 2}
        self.assertEqual(bets.settle_open(self.conn, look), 1)
        df = bets.load(self.conn)
        self.assertEqual(df.iloc[0]["status"], "won")
        self.assertAlmostEqual(df.iloc[0]["profit"], 20.0)
        s = bets.summary(df)
        self.assertAlmostEqual(s["roi"], 2.0); self.assertAlmostEqual(s["trafnosc_wg_modelu"], 0.3)
        self.assertAlmostEqual(s["zysk_wg_modelu"], 10 * (0.3 * 3 - 1))
        self.assertTrue(bid)

    def test_one_lost_leg_settles_ako_early(self):
        bets.add_bet(self.conn, self.LEGS, 3.0, 10)
        look = lambda lg, d, h, a: {"hg": 0, "ag": 1} if h == "A" else None  # noqa: E731
        bets.settle_open(self.conn, look)
        self.assertEqual(bets.load(self.conn).iloc[0]["status"], "lost")

    def test_validation_and_csv_roundtrip(self):
        with self.assertRaises(ValueError):
            bets.add_bet(self.conn, self.LEGS, 1.0, 10)
        bets.add_bet(self.conn, self.LEGS, 3.0, 10, note="test")
        f = Path(tempfile.mkdtemp()) / "x.csv"
        self.assertEqual(bets.export_csv(self.conn, f), 1)
        other = db.connect(Path(tempfile.mkdtemp()) / "o.db")
        self.assertEqual(bets.import_csv(other, f), 1)
        self.assertEqual(bets.import_csv(other, f), 0)                            # idempotentnie
        self.assertEqual(len(bets.load(other)), 1)

    def test_sparkline(self):
        self.assertEqual(bets.sparkline([1.0]), "")
        self.assertIn("polyline", bets.sparkline([5.0, -3.0, 8.0]))


class TestWeb(unittest.TestCase):
    def setUp(self):
        self._old = config.DB_PATH
        config.DB_PATH = Path(tempfile.mkdtemp()) / "w.db"

    def tearDown(self):
        config.DB_PATH = self._old

    def test_bets_page_and_manual_status(self):
        from fbpred.web import create_app
        c = create_app().test_client()
        r = c.get("/bets?league=E0")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Brak zakładów", r.get_data(as_text=True))
        conn = db.connect(config.DB_PATH)
        bid = bets.add_bet(conn, TestBetsJournal.LEGS, 2.5, 20)
        self.assertEqual(c.post(f"/bets/{bid}/won?league=E0").status_code, 302)
        html = c.get("/bets?league=E0").get_data(as_text=True)
        self.assertIn("wygrany", html); self.assertIn("+30.00", html)
        self.assertEqual(c.post(f"/bets/{bid}/delete?league=E0").status_code, 302)
        self.assertEqual(c.post("/api/bets", json={"legs": []}).status_code, 400)
        self.assertEqual(c.post(f"/bets/{bid}/hack").status_code, 404)

    def test_coupon_has_save_button(self):
        from fbpred.web import create_app
        html = create_app().test_client().get("/coupon?league=E0").get_data(as_text=True)
        self.assertIn("Zapisz w dzienniku zakładów", html)


class TestH2HStudy(unittest.TestCase):
    def _df(self):
        rows, d = [], pd.Timestamp("2020-01-01")
        for i in range(8):        # A (faworyt wg kursów) regularnie przegrywa z B
            rows.append(("A", "B", 0, 1, 1.8, 3.6, 4.5)); rows.append(("B", "A", 1, 0, 4.5, 3.6, 1.8))
        df = pd.DataFrame(rows, columns=["home", "away", "hg", "ag", "o_home", "o_draw", "o_away"])
        df["date"] = [d + pd.Timedelta(days=7 * i) for i in range(len(df))]
        return df

    def test_study_uses_only_prior_meetings(self):
        o = h2h.study(self._df())
        self.assertGreater(len(o), 5)
        self.assertTrue((o["share"] == 0).all())                                  # faworyt A nigdy nie wygrał
        self.assertTrue((o["won"] == 0).all())
        self.assertGreaterEqual(o["n_prior"].min(), 3)
        s = h2h.summarize(o)
        self.assertEqual(s["tabela"].iloc[0]["meczów"], len(o))
        self.assertIn("Za mało", h2h.verdict(s))                                  # < 200 obserwacji

    def test_cli_registered(self):
        from fbpred import cli
        self.assertTrue(hasattr(cli, "cmd_h2h"))


if __name__ == "__main__":
    unittest.main()
