import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_52w as B  # noqa: E402


def stock(sym, gate=1, gap=-0.02, name=None):
    return {"symbol": sym, "name": name or sym, "sector": "S", "gate_pass": gate, "close": 100.0, "high_52w_prev": 102.0,
            "gap_to_high": gap, "rs1m": 80, "rs3m": 85, "fund_status": "PASS", "ma5w": 99.0, "avg_val20": 1e10,
            "caution": 0, "score": {"total": 61.5}}


BASE = {"asof": "20261106", "provisional": True, "stocks": [stock("AAA"), stock("BBB", gate=0), stock("CCC", name="</script>x")]}
STATES = {"asof": "20261106", "events": [{"day": "20261106", "kind": "CONFIRMED_BREAKOUT", "symbol": "AAA", "price": 101}],
          "states": {"AAA": {"state": "CONFIRMED_BREAKOUT", "since": "20261106", "broke_today": True, "breakout_level": 100.5}}}


class Static(unittest.TestCase):
    def test_only_gate_passing_stocks_become_rows(self):
        rows = B.build_rows(BASE, STATES)
        self.assertEqual([r["symbol"] for r in rows], ["AAA", "CCC"])
        a = rows[0]
        self.assertEqual((a["state"], a["broke_today"], a["gap_pct"], a["static_score"], a["live"]),
                         ("CONFIRMED_BREAKOUT", True, -2.0, 61.5, None))
        self.assertEqual(rows[1]["state"], "NORMAL")                   # 재현 결과가 없으면 NORMAL

    def test_render_injects_data_once_and_round_trips(self):
        html, payload = B.render(BASE, STATES, generated_at="2026-11-06 21:00")
        self.assertNotIn(B.PLACEHOLDER, html)
        m = re.search(r"var STATIC=(\{.*?\});\nvar DATA=", html, re.S)
        data = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(data["mode"], "static")
        self.assertEqual(data["generated_at"], "2026-11-06 21:00")
        self.assertEqual(len(data["rows"]), 2)

    def test_html_in_data_cannot_close_the_script_tag(self):
        html, _ = B.render(BASE, STATES)
        start = html.index("var STATIC=")
        end = html.index(";\nvar DATA=")
        self.assertNotIn("</script>", html[start:end])                 # 종목명에 </script> 가 있어도 스크립트가 끊기지 않는다

    def test_page_has_no_order_controls(self):
        html, _ = B.render(BASE, STATES)
        self.assertIn("주문 기능은 없습니다", html)
        for word in ("order-cash", "매수 주문", "submit"):
            self.assertNotIn(word, html)

    def test_missing_placeholder_is_an_error(self):
        orig = B.PLACEHOLDER
        B.PLACEHOLDER = "var NOPE=null;"
        try:
            with self.assertRaises(RuntimeError):
                B.render(BASE, STATES)
        finally:
            B.PLACEHOLDER = orig


if __name__ == "__main__":
    unittest.main()
