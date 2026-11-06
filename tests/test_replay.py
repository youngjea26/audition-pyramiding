import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import replay as R  # noqa: E402


def make_series(tail, n_flat=300):
    """n_flat 거래일 동안 시가 100·고가 101·저가 99·종가 100 으로 횡보한 뒤, tail 의 (시가, 고가, 저가, 종가, 거래량) 이어 붙인다."""
    d, ds = date(2025, 11, 3), []
    while len(ds) < n_flat + len(tail):
        if d.weekday() < 5:
            ds.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    rows = [(100, 101, 99, 100, 1000)] * n_flat + list(tail)
    return {"ds": ds, "open": [r[0] for r in rows], "high": [r[1] for r in rows], "low": [r[2] for r in rows],
            "close": [r[3] for r in rows], "vol": [r[4] for r in rows]}


class Replay(unittest.TestCase):
    def kinds(self, ev):
        return [e["kind"] for e in ev]

    def test_breakout_confirmed_by_close(self):
        # 기준 고가 101. 돌파일: 고가 103, 종가 102.5(>101) → 장중 돌파 + 종가 확정. 다음 날은 확정 유지.
        s = make_series([(100.5, 103, 100, 102.5, 3000), (102.4, 103, 102, 102.8, 2000)])
        st, ev = R.replay_stock("AAA", s)
        self.assertEqual(st.state, "CONFIRMED_BREAKOUT")
        self.assertEqual(st.breakout_level, 101.0)
        k = self.kinds(ev)
        self.assertIn("INTRADAY_BREAKOUT", k)
        self.assertEqual(k.count("CONFIRMED_BREAKOUT"), 1)
        self.assertEqual(ev[-1]["day"], s["ds"][-2])                     # 마지막 이벤트는 돌파일(마지막 날은 이벤트 없음)

    def test_intraday_breakout_failed_at_close(self):
        # 마지막 날: 고가 102(>101) 였지만 종가 100.5(≤101) → FAILED_BREAKOUT, 오늘 돌파였다
        s = make_series([(100, 102, 100, 100.5, 3000)])
        st, ev = R.replay_stock("AAA", s)
        self.assertEqual(st.state, "FAILED_BREAKOUT")
        self.assertTrue(st.broke_today)
        self.assertEqual(self.kinds(ev)[-2:], ["INTRADAY_BREAKOUT", "FAILED_BREAKOUT"])

    def test_no_breakout_when_high_stays_below_reference(self):
        s = make_series([(100, 100.9, 99, 100.5, 1000)])
        st, ev = R.replay_stock("AAA", s)
        self.assertNotIn("INTRADAY_BREAKOUT", self.kinds(ev))
        self.assertFalse(st.broke_today)

    def test_extended_after_ten_percent_run(self):
        # 돌파(종가 확정) 다음 날 종가 112 → 돌파 기준가 101 의 +10% 이상(111.1) → EXTENDED
        s = make_series([(100.5, 103, 100, 102.5, 3000), (103, 112.5, 103, 112, 4000)])
        st, ev = R.replay_stock("AAA", s)
        self.assertEqual(st.state, "EXTENDED")
        self.assertIn("EXTENDED", self.kinds(ev))

    def test_day_path_order_depends_on_candle_color(self):
        self.assertEqual(R.day_path(100, 105, 98, 104), [100, 98, 105, 104])     # 상승일: 저가 먼저
        self.assertEqual(R.day_path(100, 105, 98, 99), [100, 105, 98, 99])       # 하락일: 고가 먼저

    def test_base_at_uses_only_data_up_to_that_day(self):
        s = make_series([(100.5, 103, 100, 102.5, 3000)])
        i = len(s["ds"]) - 2                                                      # 돌파 전날
        self.assertEqual(R.base_at(s, i)["high_52w_prev"], 101)
        self.assertEqual(R.base_at(s, i + 1)["high_52w_prev"], 103)               # 돌파일이 끝나면 기준 고가가 올라간다

    def test_end_of_day_state_recomputes_zone_but_keeps_breakout_states(self):
        import w52.states as S
        near = S.StockState("A", state="NEAR")
        self.assertEqual(R.end_of_day_state(near, -0.5), "READY")                 # 내일 기준 대비 이격률로 다시 정한다
        conf = S.StockState("B", state="CONFIRMED_BREAKOUT")
        self.assertEqual(R.end_of_day_state(conf, -3.0), "CONFIRMED_BREAKOUT")


if __name__ == "__main__":
    unittest.main()
