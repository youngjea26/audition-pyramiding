import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import service as svc, store  # noqa: E402
from w52.engine import Engine  # noqa: E402
from w52.providers.mock import MockMarketDataProvider, build_day  # noqa: E402
from test_engine import baseline  # noqa: E402

KST = timezone(timedelta(hours=9))


def at(day, hh, mm):
    return datetime(2026, 11, day, hh, mm, tzinfo=KST)        # 2026-11-09 = 월요일, 14 = 토요일


class Hours(unittest.TestCase):
    def test_market_hours(self):
        self.assertTrue(svc.is_market_open(at(9, 9, 0)))
        self.assertTrue(svc.is_market_open(at(9, 15, 29)))
        self.assertFalse(svc.is_market_open(at(9, 15, 30)))
        self.assertFalse(svc.is_market_open(at(9, 8, 59)))
        self.assertFalse(svc.is_market_open(at(14, 10, 0)))        # 토요일
        self.assertTrue(svc.is_after_close(at(9, 15, 30)))
        self.assertFalse(svc.is_after_close(at(14, 16, 0)))


class Flow(unittest.TestCase):
    def make(self, prices, times):
        conn = store.connect(":memory:")
        eng = Engine({"AAA": baseline("AAA", "S1")}, conn)
        prov = MockMarketDataProvider({"AAA": build_day("AAA", "20261109", prices, vol_per_tick=14000, minute0=60)})
        prov.max_subscriptions = 0                               # 폴링만(결정적으로)
        it = iter(times)
        s = svc.LiveService(eng, prov, now=lambda: next(it))
        return s, conn

    def test_polling_session_then_close_confirmation(self):
        s, conn = self.make([99, 101, 102.5, 103], [at(9, 8, 30), at(9, 9, 5), at(9, 10, 0), at(9, 11, 0), at(9, 12, 0), at(9, 15, 31), at(9, 15, 40)])
        s.step()
        self.assertEqual((s.mode, s.session_day), ("idle", None))      # 장 시작 전
        for _ in range(4):
            s.step()
        self.assertEqual(s.mode, "live")
        self.assertEqual(s.engine.states["AAA"].state, "INTRADAY_BREAKOUT")
        s.step()                                                        # 15:31 → 종가 확정
        self.assertEqual(s.mode, "closed")
        self.assertEqual(s.engine.states["AAA"].state, "CONFIRMED_BREAKOUT")
        v = s.version
        s.step()                                                        # 15:40 — 두 번째 종가 확정은 없다
        self.assertEqual(s.version, v)
        kinds = [r[0] for r in conn.execute("SELECT kind FROM state_events WHERE kind LIKE '%BREAKOUT'")]
        self.assertEqual(kinds, ["INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT"])

    def test_weekend_does_nothing(self):
        s, _ = self.make([99, 101], [at(14, 10, 0), at(14, 16, 0)])
        s.step(); s.step()
        self.assertEqual((s.mode, s.version), ("idle", 0))

    def test_websocket_ticks_reach_the_engine(self):
        conn = store.connect(":memory:")
        eng = Engine({"AAA": baseline("AAA", "S1")}, conn)
        prov = MockMarketDataProvider({"AAA": build_day("AAA", "20261109", [99, 101, 102.5], vol_per_tick=14000, minute0=60)})
        it = iter([at(9, 9, 5)] * 5)
        s = svc.LiveService(eng, prov, now=lambda: next(it))
        eng.begin_session("20261109")
        s.session_day = "20261109"
        prov.subscribe(["AAA"])
        t = threading.Thread(target=s._ws_loop); t.start(); t.join(3)
        self.assertEqual(eng.states["AAA"].state, "INTRADAY_BREAKOUT")
        self.assertGreater(s.version, 0)


if __name__ == "__main__":
    unittest.main()
