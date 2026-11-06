import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import indicators as ix  # noqa: E402


class SmaWeekly(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ix.sma([1, 2, 3, 4, 5], 3), 4.0)
        self.assertIsNone(ix.sma([1, 2], 3))

    def test_weekly_closes_takes_last_day_of_each_week(self):
        dates = ["20261102", "20261103", "20261104", "20261105", "20261106", "20261109"]   # 월~금, 다음 주 월
        self.assertEqual(ix.weekly_closes(dates, [1, 2, 3, 4, 5, 6]), [5, 6])

    def test_weekly_closes_across_year_boundary_is_one_iso_week(self):
        dates = ["20251229", "20251230", "20251231", "20260102"]       # 2026-W01
        self.assertEqual(ix.weekly_closes(dates, [1, 2, 3, 4]), [4])

    def test_weekly_ma_now_and_one_week_ago(self):
        now, prev = ix.weekly_ma([1, 2, 3, 4, 5, 6], 5)
        self.assertEqual(now, 4.0)        # (2+3+4+5+6)/5
        self.assertEqual(prev, 3.0)       # (1+2+3+4+5)/5
        self.assertEqual(ix.weekly_ma([1, 2, 3], 5), (None, None))


class Bollinger(unittest.TestCase):
    def test_constant_series_has_zero_width(self):
        self.assertEqual(ix.bbw([10.0] * 20), 0.0)

    def test_known_width_for_1_to_20(self):
        # 1..N 의 모분산 = (N²−1)/12, 평균 10.5 → BBW = 4σ / 평균
        expected = 4 * math.sqrt((20 ** 2 - 1) / 12) / 10.5
        self.assertAlmostEqual(ix.bbw(list(range(1, 21))), expected, places=9)

    def test_percentile_in_history(self):
        self.assertAlmostEqual(ix.pctile_in_history(5, list(range(1, 10))), 50.0)
        self.assertIsNone(ix.pctile_in_history(5, []))


class AtrAdx(unittest.TestCase):
    def test_atr_hand_computed_with_period_2(self):
        highs, lows, closes = [10, 12, 11], [8, 9, 9], [9, 11, 10]
        # TR1 = max(3, |12-9|, |9-9|) = 3, TR2 = max(2, |11-11|, |9-11|) = 2 → 처음 평균 2.5
        self.assertAlmostEqual(ix.atr(highs, lows, closes, 2), 2.5)
        highs, lows, closes = highs + [13], lows + [10], closes + [12]
        # TR3 = max(3, |13-10|, |10-10|) = 3 → (2.5×1 + 3)/2
        self.assertAlmostEqual(ix.atr(highs, lows, closes, 2), 2.75)

    def test_atr_constant_range(self):
        c = [10.0] * 40
        self.assertAlmostEqual(ix.atr([x + 1 for x in c], [x - 1 for x in c], c, 14), 2.0)

    def test_adx_pure_uptrend_is_100(self):
        n = 60
        lows = [float(i) for i in range(n)]
        highs = [x + 2 for x in lows]
        closes = [x + 1 for x in lows]
        self.assertAlmostEqual(ix.adx(highs, lows, closes, 14), 100.0, places=6)

    def test_adx_flat_is_zero_and_choppy_is_low(self):
        flat = [10.0] * 60
        self.assertEqual(ix.adx([x + 1 for x in flat], [x - 1 for x in flat], flat, 14), 0.0)
        c = [10.0 if i % 2 == 0 else 11.0 for i in range(80)]
        self.assertLess(ix.adx([x + 1 for x in c], [x - 1 for x in c], c, 14), 20.0)

    def test_not_enough_bars(self):
        self.assertIsNone(ix.atr([1, 2], [1, 2], [1, 2], 14))
        self.assertIsNone(ix.adx([1] * 20, [1] * 20, [1] * 20, 14))


class RankAndSplit(unittest.TestCase):
    def test_percentile_ranks_and_ties(self):
        r = ix.percentile_ranks({"a": 1, "b": 2, "c": 3, "d": 4})
        self.assertAlmostEqual(r["a"], 12.5)
        self.assertAlmostEqual(r["d"], 87.5)
        t = ix.percentile_ranks({"a": 1, "b": 1, "x": None})
        self.assertEqual(t, {"a": 50.0, "b": 50.0})

    def test_split_adjustment_scales_earlier_prices(self):
        closes = [100, 100, 20, 20]
        shares = [1, 1, 5, 5]
        highs = [110, 110, 22, 22]
        c, h = ix.adjust_splits(closes, shares, highs)
        self.assertEqual([round(x) for x in c], [20, 20, 20, 20])
        self.assertEqual([round(x) for x in h], [22, 22, 22, 22])

    def test_rights_issue_is_not_treated_as_split(self):
        closes, shares = [100, 95], [1.0, 1.5]       # 시총이 이어지지 않는다(±12% 밖)
        self.assertEqual(ix.adjust_splits(closes, shares)[0], [100.0, 95.0])


if __name__ == "__main__":
    unittest.main()
