import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52.providers import kis  # noqa: E402


def frame(symbol="005930", hhmmss="093015", price=71500, op=70000, hi=72000, lo=69800, vol=1234567, val=88000000000, n=1):
    one = ["0"] * 46
    one[0], one[1], one[2], one[7], one[8], one[9], one[13], one[14] = symbol, hhmmss, str(price), str(op), str(hi), str(lo), str(vol), str(val)
    return "0|H0STCNT0|%03d|%s" % (n, "^".join(one * n))


class Parse(unittest.TestCase):
    def test_parse_single_tick(self):
        t = kis.parse_ws_frame(frame(), day="20261109")[0]
        self.assertEqual((t.symbol, t.ts, t.price, t.open, t.high, t.low), ("005930", "20261109 09:30:15", 71500.0, 70000.0, 72000.0, 69800.0))
        self.assertEqual((t.cum_vol, t.cum_val), (1234567.0, 88000000000.0))
        self.assertEqual(t.minute_of_day, 30)

    def test_parse_multiple_records_in_one_frame(self):
        self.assertEqual(len(kis.parse_ws_frame(frame(n=3), day="20261109")), 3)

    def test_control_and_other_frames_are_ignored(self):
        self.assertEqual(kis.parse_ws_frame('{"header":{"tr_id":"PINGPONG"}}'), [])
        self.assertEqual(kis.parse_ws_frame("0|H0STASP0|001|a^b"), [])
        self.assertEqual(kis.parse_ws_frame(""), [])

    def test_broken_frame_is_skipped_not_raised(self):
        self.assertEqual(kis.parse_ws_frame("0|H0STCNT0|001|005930^093015^abc", day="20261109"), [])

    def test_tick_from_rest_output(self):
        o = {"stck_prpr": "71500", "stck_hgpr": "72000", "stck_lwpr": "69800", "stck_oprc": "70000",
             "acml_vol": "1234567", "acml_tr_pbmn": "88000000000"}
        t = kis.tick_from_price_output("005930", o)
        self.assertEqual((t.price, t.high, t.low, t.open, t.cum_vol), (71500.0, 72000.0, 69800.0, 70000.0, 1234567.0))
        self.assertIsNone(kis.tick_from_price_output("005930", {"stck_prpr": "0"}))
        self.assertIsNone(kis.tick_from_price_output("005930", {}))


class Limits(unittest.TestCase):
    def test_subscription_limit_comes_from_environment(self):
        import os
        os.environ.update({"KIS_APP_KEY": "x", "KIS_APP_SECRET": "y", "KIS_WS_MAX_SUBS": "3"})
        p = kis.KisProvider()
        self.assertEqual(p.subscribe(["a", "b", "c", "d", "e"]), ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
