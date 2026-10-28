import unittest

from tests.test_v4 import Env


class TestCouponScriptOrder(Env):
    def test_helpers_defined_before_page_script(self):
        """Zestawienie wisiało na 'Ładowanie…': fbLoad było definiowane PO skrypcie strony (ReferenceError)."""
        from fbpred.web import create_app
        html = create_app().test_client().get("/coupon?league=E0").get_data(as_text=True)
        self.assertIn("function fbLoad", html)
        self.assertLess(html.index("function fbLoad"), html.index("getElementById('coupon')"))

    def test_toggle_helpers_present(self):
        from fbpred.web import create_app
        html = create_app().test_client().get("/coupon?league=E0").get_data(as_text=True)
        for name in ("function fbRemove", "function fbHas", "function fbSync"):
            self.assertIn(name, html)


if __name__ == "__main__":
    unittest.main()
