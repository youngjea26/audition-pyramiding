import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import risk  # noqa: E402


class Plan(unittest.TestCase):
    def test_default_numbers_match_spec(self):
        p = risk.plan(50_000, ma5w=48_000)
        self.assertEqual(p["risk_amount"], 2_000_000)            # 계좌 2억 x 1%
        self.assertEqual(p["position"], 25_000_000)              # 200만원 / 8% = 최대 기본 포지션 2,500만원
        self.assertAlmostEqual(p["stop"], 46_000)                # -8%
        self.assertAlmostEqual(p["r_per_share"], 4_000)
        self.assertEqual(p["shares"], 500)
        self.assertEqual(p["tranche_shares"], [166, 166, 168])   # 1/3 분할, 나머지는 마지막에
        self.assertEqual(sum(p["tranche_shares"]), p["shares"])
        self.assertAlmostEqual(p["breakeven_trigger"], 54_000)   # +1R
        self.assertAlmostEqual(p["take_profit_3r"], 62_000)      # +3R
        self.assertEqual(p["take_profit_shares"], 250)           # 50% 익절
        self.assertIn("5주선(48000)", p["trail_rule"])

    def test_loss_at_stop_equals_risk_amount(self):
        p = risk.plan(123_456, account=300_000_000, risk_pct=0.005, stop_pct=0.05)
        loss = p["position"] * 0.05
        self.assertAlmostEqual(loss, 300_000_000 * 0.005)


if __name__ == "__main__":
    unittest.main()
