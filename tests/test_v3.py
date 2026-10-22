import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from fbpred import bootstrap, config, csvdata, db, history, notify, report
from fbpred.predictor import MatchPredictor
from fbpred.simulate import simulate_table
from fbpred.synthetic import generate
from tests.test_bootstrap import fd_csv

DF = generate(n_seasons=2, seed=9, with_upcoming=False)


def rows_of(df):
    d = df.copy()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in d.columns]
    return d[cols].astype(object).where(d[cols].notna(), None).to_dict("records")


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name) / "history"

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_creates_file_per_league_season_and_is_idempotent(self):
        r1 = history.save_matches(rows_of(DF), self.h)
        self.assertEqual(sorted(r1["files"]), ["DEMO_2021.csv", "DEMO_2022.csv"])
        self.assertEqual(sum(v["dodane"] for v in r1["files"].values()), len(DF))
        text = (self.h / "DEMO_2021.csv").read_text()
        r2 = history.save_matches(rows_of(DF), self.h)       # to samo drugi raz
        self.assertEqual(sum(v["dodane"] + v["zmienione"] for v in r2["files"].values()), 0)
        self.assertEqual(text, (self.h / "DEMO_2021.csv").read_text())  # plik bez zmian -> brak diffa w gicie

    def test_new_rows_added_and_corrections_applied_without_deleting(self):
        first = rows_of(DF)[:300]
        history.save_matches(first, self.h)
        more = rows_of(DF)[250:400]                           # 50 powtórzonych + 100 nowych
        more[0] = {**more[0], "hg": 7}                        # korekta wyniku
        r = history.save_matches(more, self.h)
        st = r["files"]["DEMO_2021.csv"]                      # sezon 2021 ma 380 meczów; reszta idzie do pliku 2022
        self.assertEqual(st["dodane"], 80)
        self.assertEqual(st["zmienione"], 1)
        self.assertEqual(st["razem"], 380)                    # nic nie zniknęło
        self.assertEqual(r["files"]["DEMO_2022.csv"]["dodane"], 20)
        got = history.read_file(self.h / "DEMO_2021.csv").set_index("fixture_id")
        self.assertEqual(int(got.loc[more[0]["fixture_id"], "hg"]), 7)

    def test_none_does_not_wipe_existing_values(self):
        rs = rows_of(DF)[:5]
        history.save_matches(rs, self.h)
        stripped = [{**r, "h_yellow": None, "o_home": None} for r in rs]
        history.save_matches(stripped, self.h)
        got = history.read_file(self.h / "DEMO_2021.csv")
        self.assertTrue(got["h_yellow"].notna().all())
        self.assertTrue(got["o_home"].notna().all())

    def test_validation_rejects_and_sanitizes(self):
        good = rows_of(DF)[0]
        bad_score = {**rows_of(DF)[1], "hg": 99}
        bad_teams = {**rows_of(DF)[2], "away": rows_of(DF)[2]["home"]}
        ht_gt_ft = {**rows_of(DF)[3], "hg": 1, "hg_ht": 3, "ag_ht": 0}
        weird_odds = {**rows_of(DF)[4], "o_home": 0.5}
        r = history.save_matches([good, bad_score, bad_teams, ht_gt_ft, weird_odds], self.h)
        self.assertEqual(len(r["rejected"]), 2)
        self.assertEqual(r["sanitized"], 2)
        got = history.read_file(self.h / "DEMO_2021.csv")
        self.assertEqual(len(got), 3)
        row = got[got["fixture_id"] == ht_gt_ft["fixture_id"]].iloc[0]
        self.assertTrue(pd.isna(row["hg_ht"]))                # tylko HT usunięty, mecz zostaje

    def test_roundtrip_to_db_and_aliases(self):
        (self.h).mkdir(parents=True)
        (self.h / "aliases.json").write_text(json.dumps({"Man City": "Manchester City"}))
        history.save_matches(rows_of(DF), self.h)
        conn = db.connect(":memory:")
        n = history.load_into_db(conn, self.h)
        self.assertEqual(n, len(DF))
        teams = {r[0] for r in conn.execute("SELECT DISTINCT home FROM matches")}
        self.assertIn("Manchester City", teams)
        self.assertNotIn("Man City", teams)
        self.assertEqual(db.load_matches(conn, "DEMO")["hg"].isna().sum(), 0)

    def test_export_from_db(self):
        conn = db.connect(":memory:")
        db.upsert_matches(conn, rows_of(DF))
        res = history.export_from_db(conn, self.h)
        self.assertEqual(sum(v["dodane"] for v in res["files"].values()), len(DF))
        self.assertFalse(history.status(self.h).empty)

    def test_odds_archive_dedup(self):
        up = [{"fixture_id": 1, "league": "E0", "date": "2026-10-25", "home": "A", "away": "B",
               "o_home": 2.0, "o_draw": 3.3, "o_away": 3.8},
              {"fixture_id": 2, "league": "E0", "date": "2026-10-25", "home": "C", "away": "D"}]  # bez kursów
        self.assertEqual(history.archive_odds(up, self.h, "2026-10-22"), 1)
        self.assertEqual(history.archive_odds(up, self.h, "2026-10-22"), 0)   # ten sam dzień: bez duplikatów
        self.assertEqual(history.archive_odds(up, self.h, "2026-10-23"), 1)   # nowy dzień: nowy snapshot
        self.assertEqual(len(pd.read_csv(self.h / "odds" / "E0.csv")), 2)


class TestOfflineStartAndWeekly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV)
        config.DB_PATH = Path(self.tmp.name) / "x.db"
        config.HISTORY_DIR = Path(self.tmp.name) / "history"
        config.LEDGER_CSV = Path(self.tmp.name) / "ledger" / "p.csv"

    def tearDown(self):
        config.DB_PATH, config.HISTORY_DIR, config.LEDGER_CSV = self.old
        self.tmp.cleanup()

    def test_start_from_history_without_internet(self):
        sy = bootstrap.season_now()
        for y in (sy - 2, sy - 1):                             # historia: 2 sezony zapisane wcześniej
            history.save_matches(csvdata.parse_csv(fd_csv(y), "E0", y), config.HISTORY_DIR)
        with mock.patch.object(csvdata, "download", side_effect=OSError("brak sieci")), \
             mock.patch.object(csvdata, "download_fixtures", side_effect=OSError("brak sieci")):
            bootstrap.run_once(["E0"], log=lambda *_: None)
        self.assertEqual(bootstrap.STATUS["state"], "ready")   # działa mimo braku internetu
        conn = db.connect(config.DB_PATH)
        self.assertEqual(bootstrap.count_finished(conn, "E0"), 760)

    def test_weekly_update_adds_only_new(self):
        y = bootstrap.season_now()
        full = fd_csv(y).split("\n")
        part, whole = "\n".join(full[:201]), "\n".join(full)   # nagłówek + 200 meczów, potem całość
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, yy: part if yy == y else full[0]):
            r1 = history.update_from_source(["E0"], [y], config.HISTORY_DIR, log=lambda *_: None)
        self.assertEqual(r1[0]["dodane"], 200)
        with mock.patch.object(csvdata, "download", side_effect=lambda lg, yy: whole):
            r2 = history.update_from_source(["E0"], [y], config.HISTORY_DIR, log=lambda *_: None)
        self.assertEqual((r2[0]["dodane"], r2[0]["zmienione"], r2[0]["razem"]), (180, 0, 380))
        log = (config.HISTORY_DIR / "UPDATES.log").read_text()
        self.assertEqual(len(log.strip().splitlines()), 2)


class TestShotBlend(unittest.TestCase):
    def test_zero_weight_equals_baseline_and_blend_changes_lambdas(self):
        fin = DF
        base = MatchPredictor(fin)
        same = MatchPredictor(fin, shot_weight=0.0)
        mixed = MatchPredictor(fin, shot_weight=0.6)
        self.assertEqual(base.lambdas("Arsenal", "Chelsea"), same.lambdas("Arsenal", "Chelsea"))
        self.assertIsNotNone(mixed.sot)
        self.assertNotEqual(base.lambdas("Arsenal", "Chelsea"), mixed.lambdas("Arsenal", "Chelsea"))
        p = mixed.predict("Arsenal", "Chelsea")
        self.assertAlmostEqual(sum(p["1x2"].values()), 1.0, places=2)

    def test_without_sot_columns_it_degrades_gracefully(self):
        P = MatchPredictor(DF.drop(columns=["h_sot", "a_sot"]), shot_weight=0.5)
        self.assertIsNone(P.sot)
        self.assertGreater(P.predict("Arsenal", "Chelsea")["xg"]["home"], 0)

    def test_simulation_uses_blended_matrix(self):
        P = MatchPredictor(DF, shot_weight=0.5)
        tab, _ = simulate_table(DF, P, None, n=500)
        self.assertAlmostEqual(tab["mistrz_%"].sum(), 100, delta=1.0)


class TestNotifyAndReport(unittest.TestCase):
    def test_chunking_respects_limit(self):
        text = "\n\n".join(f"mecz {i}\n" + "x" * 300 for i in range(40))
        parts = notify.chunk(text, 3800)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 3800 for p in parts))
        self.assertEqual("\n\n".join(parts), text)

    def test_format_match_flags_suspicious_edge(self):
        pred = {"home": "A", "away": "B", "1x2": {"1": .5, "X": .3, "2": .2},
                "goals": {"over_2.5": .55, "btts_yes": .5}}
        row = {"date": "2026-10-25"}
        txt = notify.format_match(pred, row, [{"rynek": "1", "kurs": 3.0, "edge": 0.5}])
        self.assertIn("A – B (25.10)", txt)
        self.assertIn("podejrzanie", txt)

    def test_send_requires_credentials_and_posts_to_telegram(self):
        with self.assertRaises(RuntimeError):
            notify.send_telegram("hej", token="", chat_id="")
        with mock.patch.object(notify.requests, "post") as post:
            post.return_value.raise_for_status = lambda: None
            self.assertEqual(notify.send_telegram("hej", token="T", chat_id="C"), 1)
            self.assertIn("botT/sendMessage", post.call_args[0][0])

    def test_markdown_table(self):
        md = report.to_markdown(pd.DataFrame({"rynek": ["1X2"], "model": [1.0832], "n": [10]}))
        self.assertTrue(md.startswith("| rynek | model | n |"))
        self.assertIn("1.0832", md)
        self.assertEqual(report.to_markdown(pd.DataFrame()), "_brak danych_")


if __name__ == "__main__":
    unittest.main()
