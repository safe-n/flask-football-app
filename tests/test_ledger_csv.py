import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fbpred import db, ledger
from fbpred.predictor import MatchPredictor
from fbpred.synthetic import generate

DF = generate(n_seasons=3, seed=5, with_upcoming=True)


def make_conn():
    conn = db.connect(":memory:")
    d = DF.copy()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in d.columns]
    db.upsert_matches(conn, d[cols].astype(object).where(d[cols].notna(), None).to_dict("records"))
    return conn


class TestLedgerCsv(unittest.TestCase):
    def test_roundtrip_survives_fresh_db(self):
        conn = make_conn()
        P = MatchPredictor(db.load_matches(conn, "DEMO"))
        up = db.load_upcoming(conn, "DEMO")
        ledger.log_predictions(conn, P, up, "DEMO", blend_w=0.3)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "ledger" / "predictions.csv"
            self.assertEqual(ledger.export_csv(conn, f), len(up))
            fresh = make_conn()                      # symuluje nowy runner / restart Rendera
            self.assertEqual(ledger.import_csv(fresh, f), len(up))
            self.assertEqual(ledger.import_csv(fresh, f), 0)  # idempotentne
            self.assertEqual(ledger.pending(fresh, "DEMO"), len(up))
            for fid in up["fixture_id"]:
                fresh.execute("UPDATE matches SET hg=1, ag=1, hg_ht=0, ag_ht=0, status='FT' WHERE fixture_id=?", (int(fid),))
            fresh.commit()
            s = ledger.settled(fresh, "DEMO")
            self.assertEqual(len(s), len(up))
            tab, _ = ledger.track_summary(s)         # raport działa bez payloadu
            self.assertFalse(tab.empty)

    def test_missing_file_is_ok(self):
        self.assertEqual(ledger.import_csv(make_conn(), "/nie/ma/takiego.csv"), 0)

    def test_prediction_frozen_on_match_day(self):
        conn = make_conn()
        P = MatchPredictor(db.load_matches(conn, "DEMO"))
        up = db.load_upcoming(conn, "DEMO")          # daty w przeszłości -> "dzień meczu minął" -> zamrożone
        self.assertEqual(ledger.log_predictions(conn, P, up, "DEMO"), len(up))
        before = conn.execute("SELECT logged_at, p1 FROM predictions ORDER BY fixture_id").fetchall()
        self.assertEqual(ledger.log_predictions(conn, P, up, "DEMO"), 0)  # drugi raz: nic nie nadpisuje
        self.assertEqual(before, conn.execute("SELECT logged_at, p1 FROM predictions ORDER BY fixture_id").fetchall())

    def test_future_match_is_updated(self):
        conn = make_conn()
        P = MatchPredictor(db.load_matches(conn, "DEMO"))
        up = db.load_upcoming(conn, "DEMO").copy()
        up["date"] = pd.Timestamp.today().normalize() + pd.Timedelta(days=5)  # przyszłość -> można odświeżać
        self.assertEqual(ledger.log_predictions(conn, P, up, "DEMO"), len(up))
        self.assertEqual(ledger.log_predictions(conn, P, up, "DEMO"), len(up))


if __name__ == "__main__":
    unittest.main()
