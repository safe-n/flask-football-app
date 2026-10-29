import unittest

from tests.test_v4 import Env


class TestAkoPanel(Env):
    def test_coupon_page_has_live_ako_and_odds_multiplication(self):
        from fbpred.web import create_app
        html = create_app().test_client().get("/coupon?league=E0").get_data(as_text=True)
        self.assertIn("function ako(", html)
        self.assertIn("oAll*=v", html)                                      # mnożenie wpisanych kursów
        self.assertIn("1/pAll", html)                                       # uczciwy kurs AKO z prognoz
        self.assertLess(html.index("function fbLoad"), html.index("function ako("))

    def test_legs_label_explained(self):
        from fbpred.web import create_app
        html = create_app().test_client().get("/suggest?league=E0").get_data(as_text=True)
        self.assertIn("Typów w auto-kuponie", html)
        self.assertNotIn("nóg", html)


if __name__ == "__main__":
    unittest.main()
