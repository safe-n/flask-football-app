import tempfile
import unittest
from pathlib import Path

from fbpred import config, db, ledger, pdfexport, recent
from fbpred.synthetic import generate


def _rows(df):
    import pandas as pd
    out = []
    for r in df.to_dict("records"):
        r = {k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
        r["date"] = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
        out.append(r)
    return out


class TestPdf(unittest.TestCase):
    def test_recent_pdf_bytes_and_empty(self):
        df = generate(n_seasons=2, seed=4, league="E0", start_year=2024, with_upcoming=False)
        res = recent.recent_predictions(df, days=14)
        pdf = pdfexport.recent_pdf([("Premier League", recent.summary(res), res)], 14, ["Liga X"])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 3000)
        self.assertTrue(pdfexport.recent_pdf([], 14).startswith(b"%PDF"))

    def test_coupon_pdf(self):
        legs = [{"data": "2026-11-01", "mecz": "Łódź – Gdańsk", "rynek": "Over 2.5", "p": 0.6, "kurs_fair": 1.67, "kurs_uzyty": 1.9, "ostrzezenia": ["test"]},
                {"data": "2026-11-01", "mecz": "A – B", "rynek": "BTTS", "p": 0.55, "kurs_fair": 1.8, "kurs_uzyty": 1.95},
                {"id": "x", "blad": "mecz już rozegrany"}]
        pdf = pdfexport.coupon_pdf({"legs": legs, "ostrzezenia": ["uwaga"]}, stake=10)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertTrue(pdfexport.coupon_pdf({"legs": []}).startswith(b"%PDF"))


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self._old = config.DB_PATH
        config.DB_PATH = Path(tempfile.mkdtemp()) / "x.db"

    def tearDown(self):
        config.DB_PATH = self._old

    def test_journal_and_recent_routes(self):
        from fbpred.web import create_app
        df = generate(n_seasons=3, seed=11, league="E0", start_year=2023, with_upcoming=False)
        conn = db.connect(config.DB_PATH)
        db.upsert_matches(conn, _rows(df))
        c = create_app().test_client()
        r = c.get("/export/journal.pdf")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        self.assertTrue(r.data.startswith(b"%PDF"))
        r = c.get("/export/recent.pdf?days=14")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        self.assertGreater(len(r.data), 3000)
        self.assertEqual(c.get("/export/coupon.pdf").mimetype, "application/pdf")   # puste zestawienie też daje PDF

    def test_buttons_present(self):
        from fbpred.web import create_app
        html = create_app().test_client().get("/coupon?league=E0").get_data(as_text=True)
        self.assertIn("/export/coupon.pdf", html)
        self.assertIn('href="/tennis/"', html)


if __name__ == "__main__":
    unittest.main()
