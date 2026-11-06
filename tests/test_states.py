import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import states as S  # noqa: E402
from w52.providers.mock import MockMarketDataProvider, build_day  # noqa: E402


def base(high=100.0, bbw=0.10, atr=0.04, vol5=1.5, close=99.0, h10=99.0):
    return {"high_52w_prev": high, "bbw": bbw, "atr_pct": atr, "vol5_ratio": vol5, "close": close, "high_10d": h10}


def run_day(st, b, ticks, close=True):
    """하루를 돌린다: start_session → on_tick × N → on_close. 이벤트 종류 목록을 돌려준다."""
    S.start_session(st, b, ticks[0].day)
    for t in ticks:
        S.on_tick(st, b, t.price, t.high)
    if close:
        S.on_close(st, b, ticks[-1].price, ticks[-1].high)
    return [e["kind"] for e in S.drain(st)]


class Zones(unittest.TestCase):
    def test_boundaries(self):
        z = S.zone_for_gap
        self.assertEqual(z(-10.0001), "NORMAL")
        self.assertEqual(z(-10.0), "WATCH")
        self.assertEqual(z(-5.0001), "WATCH")
        self.assertEqual(z(-5.0), "NEAR")
        self.assertEqual(z(-1.0001), "NEAR")
        self.assertEqual(z(-1.0), "READY")
        self.assertEqual(z(0.0), "READY")


class Transitions(unittest.TestCase):
    def test_normal_to_confirmed_via_mock_stream(self):
        """NORMAL → WATCH → NEAR → READY → INTRADAY_BREAKOUT → (종가) CONFIRMED_BREAKOUT"""
        day = "20261109"
        prov = MockMarketDataProvider({"AAA": build_day("AAA", day, [85, 92, 96, 99.5, 101, 102])})
        prov.subscribe(["AAA"])
        st = S.StockState("AAA")
        ticks = list(prov.stream())
        kinds = run_day(st, base(), ticks)
        self.assertEqual(kinds, ["WATCH", "NEAR", "READY", "INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT"])
        self.assertEqual(st.state, "CONFIRMED_BREAKOUT")
        self.assertEqual(st.breakout_level, 100.0)

    def test_intraday_breakout_then_failed_at_close(self):
        day = "20261109"
        st = S.StockState("AAA")
        kinds = run_day(st, base(), build_day("AAA", day, [98, 99.5, 101, 100.5, 99.8]))
        self.assertEqual(kinds, ["NEAR", "READY", "INTRADAY_BREAKOUT", "FAILED_BREAKOUT"])
        self.assertEqual(st.state, "FAILED_BREAKOUT")
        S.start_session(st, base(), "20261110")          # 다음 거래일에 초기화된다
        self.assertEqual(st.state, "NORMAL")
        self.assertEqual(st.breakout_level, 0.0)

    def test_breakout_is_separate_from_close_confirmation(self):
        """장중 돌파 이벤트는 종가 확정 전에 이미 나와 있고, 종가 이벤트는 on_close 에서만 나온다."""
        st = S.StockState("AAA")
        ticks = build_day("AAA", "20261109", [99, 101])
        S.start_session(st, base(), "20261109")
        for t in ticks:
            S.on_tick(st, base(), t.price, t.high)
        self.assertEqual([e["kind"] for e in S.drain(st)], ["READY", "INTRADAY_BREAKOUT"])
        self.assertEqual(st.state, "INTRADAY_BREAKOUT")      # 아직 확정 아님
        S.on_close(st, base(), 101, 101)
        self.assertEqual([e["kind"] for e in S.drain(st)], ["CONFIRMED_BREAKOUT"])

    def test_no_event_without_state_change(self):
        st = S.StockState("AAA")
        kinds = run_day(st, base(), build_day("AAA", "20261109", [80, 81, 82, 83]))
        self.assertEqual(kinds, [])                          # 계속 NORMAL


class ExtendedAndRebreakout(unittest.TestCase):
    def test_full_cycle(self):
        """돌파 확정 → EXTENDED(+10%) → 수렴(REBREAKOUT_WAIT) → 수렴 구간 고점 재돌파(REBREAKOUT)"""
        st = S.StockState("AAA")
        k1 = run_day(st, base(high=100), build_day("AAA", "20261109", [99, 101, 103]))
        self.assertEqual(k1, ["READY", "INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT"])
        # 2일차: 돌파 기준가(100)의 +10% = 110 이상 → EXTENDED. 이날 BBW·ATR 을 «고점 시점 값»으로 기억한다.
        k2 = run_day(st, base(high=103, bbw=0.10, atr=0.04, close=103), build_day("AAA", "20261110", [106, 111, 113]))
        self.assertEqual(k2, ["EXTENDED"])
        self.assertEqual(st.state, "EXTENDED")
        self.assertEqual(st.ext_peak, 113.0)
        self.assertEqual((st.bbw_at_ext, st.atr_pct_at_ext), (0.10, 0.04))
        # 3일차: 수렴 지표가 모두 줄었다(0.06≤0.07, 0.03≤0.032, 0.6≤0.7) 그리고 고점 아래 → REBREAKOUT_WAIT
        b3 = base(high=113, bbw=0.06, atr=0.03, vol5=0.6, close=108, h10=112)
        k3 = run_day(st, b3, build_day("AAA", "20261111", [108, 109, 110]))
        self.assertEqual(k3, ["REBREAKOUT_WAIT"])
        self.assertEqual(st.consol_high, 112)
        # 4일차: 수렴 구간 고점(112) 위로 올라서면 REBREAKOUT, 종가도 위면 유지
        k4 = run_day(st, b3, build_day("AAA", "20261112", [111, 113]))
        self.assertEqual(k4, ["REBREAKOUT"])
        self.assertEqual(st.state, "REBREAKOUT")

    def test_stays_extended_when_not_contracted(self):
        st = S.StockState("AAA", state="EXTENDED", ext_peak=113, bbw_at_ext=0.10, atr_pct_at_ext=0.04,
                          breakout_level=100, breakout_date="20261109", day="20261110")
        S.start_session(st, base(high=113, bbw=0.09, atr=0.03, vol5=0.6, close=108), "20261111")
        self.assertEqual(st.state, "EXTENDED")                # BBW 가 아직 0.7배 이하가 아니다

    def test_rebreakout_that_fails_at_close_returns_to_wait(self):
        st = S.StockState("AAA", state="REBREAKOUT_WAIT", consol_high=112, ext_peak=113, breakout_level=100, day="")
        kinds = run_day(st, base(high=113, close=108), build_day("AAA", "20261112", [111, 113, 111]))
        self.assertEqual(kinds, ["REBREAKOUT", "REBREAKOUT_WAIT"])


class Expiry(unittest.TestCase):
    def test_confirmed_shows_for_five_sessions_then_returns_to_zone(self):
        st = S.StockState("AAA")
        run_day(st, base(), build_day("AAA", "20261109", [99, 101, 103]))
        self.assertEqual(st.state, "CONFIRMED_BREAKOUT")
        days = ["20261110", "20261111", "20261112", "20261113", "20261116"]       # 5거래일
        for d in days:
            S.start_session(st, base(high=103), d)
            self.assertEqual(st.state, "CONFIRMED_BREAKOUT", d)
        S.start_session(st, base(high=103), "20261117")                           # 6번째 → 만료
        self.assertEqual(st.state, "NORMAL")


class MockProvider(unittest.TestCase):
    def test_build_day_accumulates_high_low_and_volume(self):
        t = build_day("AAA", "20261109", [10, 12, 11, 9], vol_per_tick=100)
        self.assertEqual([x.high for x in t], [10, 12, 12, 12])
        self.assertEqual([x.low for x in t], [10, 10, 10, 9])
        self.assertEqual([x.cum_vol for x in t], [100, 200, 300, 400])
        self.assertEqual(t[0].minute_of_day, 0)
        self.assertEqual(t[3].minute_of_day, 3)

    def test_subscription_limit_and_snapshot_cycle(self):
        script = {"S%03d" % i: build_day("S%03d" % i, "20261109", [10, 11]) for i in range(50)}
        p = MockMarketDataProvider(script)
        self.assertEqual(len(p.subscribe(list(script))), 40)         # 상한 초과분은 구독하지 않는다
        s1 = p.snapshot(["S000"])["S000"]
        s2 = p.snapshot(["S000"])["S000"]
        s3 = p.snapshot(["S000"])["S000"]
        self.assertEqual((s1.price, s2.price, s3.price), (10.0, 11.0, 11.0))   # 끝나면 마지막 값을 되풀이한다


if __name__ == "__main__":
    unittest.main()
