import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import live, store  # noqa: E402
from w52.engine import Engine  # noqa: E402
from w52.providers.base import Tick  # noqa: E402
from w52.providers.mock import MockMarketDataProvider, build_day  # noqa: E402

DAY = "20261109"


def baseline(sym, sector, gate=1, high=100.0):
    return {"symbol": sym, "name": sym, "sector": sector, "gate_pass": gate, "high_52w_prev": high, "close": 95.0,
            "avg_vol20": 100_000.0, "score_total": 60.0, "bbw": 0.10, "atr_pct": 0.04, "vol5_ratio": 1.5, "high_10d": 99.0}


def day_ticks(sym, prices, minute0=60, vol=14_000, day=DAY):
    return build_day(sym, day, prices, vol_per_tick=vol, minute0=minute0)


def run_engine(eng, script, day=DAY):
    prov = MockMarketDataProvider(script)
    prov.subscribe(list(script))
    eng.begin_session(day)
    events = []
    for t in prov.stream():
        events += eng.on_tick(t)
    events += eng.end_session()
    return events


class LiveParts(unittest.TestCase):
    def test_expected_fraction_interpolates(self):
        self.assertEqual(live.expected_fraction(0), 0.0)
        self.assertAlmostEqual(live.expected_fraction(20), 0.12)       # 10분 0.08 ~ 30분 0.16 의 중간
        self.assertEqual(live.expected_fraction(390), 1.0)
        self.assertEqual(live.expected_fraction(500), 1.0)

    def test_points_thresholds(self):
        self.assertEqual([live.rel_volume_points(x) for x in (None, 1.19, 1.2, 1.5, 2.0)], [0, 0, 2, 4, 6])
        self.assertEqual(live.candle_points(price=108, open_=100, high=110, low=100), 4)     # 상단 80%
        self.assertEqual(live.candle_points(price=106, open_=100, high=110, low=100), 2)     # 상단 60%
        self.assertEqual(live.candle_points(price=102, open_=100, high=110, low=100), 0)
        self.assertEqual(live.candle_points(price=99, open_=100, high=110, low=95), 0)       # 시가 아래
        self.assertEqual(live.width_points(102, 100), 2)
        self.assertEqual(live.width_points(105, 100), 0)
        self.assertEqual(live.width_points(99, 100), 0)
        self.assertEqual([live.sector_points(n) for n in (0, 1, 2, 5)], [0, 2, 4, 4])

    def test_rel_volume_is_none_early_in_the_session(self):
        self.assertIsNone(live.rel_volume(1000, 100_000, 0))
        self.assertAlmostEqual(live.rel_volume(26_000, 100_000, 60), 1.0)


class EngineFlow(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.base = {"AAA": baseline("AAA", "S1"), "BBB": baseline("BBB", "S1"), "CCC": baseline("CCC", "S2"),
                     "EEE": baseline("EEE", "S3"), "DDD": baseline("DDD", "S4", gate=0)}
        self.script = {
            "AAA": day_ticks("AAA", [96, 99.5, 101, 102.5]),
            "BBB": day_ticks("BBB", [96, 99.5, 100.5, 101.5]),
            "CCC": day_ticks("CCC", [96, 98, 98.5, 98.9]),       # 마지막 -1.1% — 경계(-1%) 아래라 NEAR 유지
            "EEE": day_ticks("EEE", [80, 82, 83, 84]),
            "DDD": day_ticks("DDD", [96, 99.5, 101, 102]),
        }

    def kinds(self, sym):
        return [r[0] for r in self.conn.execute("SELECT kind FROM state_events WHERE symbol=? ORDER BY id", (sym,))]

    def test_states_events_and_close_confirmation(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        self.assertEqual(self.kinds("AAA"), ["NEAR", "READY", "INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT"])
        self.assertEqual(self.kinds("CCC"), ["NEAR"])                  # 98~99 는 NEAR, 돌파 없음
        self.assertEqual(self.kinds("EEE"), [])                        # 계속 NORMAL — 이벤트 없음
        self.assertEqual(self.kinds("DDD"), [])                        # 게이트 탈락 종목은 추적하지 않는다
        self.assertNotIn("DDD", eng.states)
        row = self.conn.execute("SELECT state FROM state_current WHERE symbol='AAA'").fetchone()
        self.assertEqual(row["state"], "CONFIRMED_BREAKOUT")

    def test_breakout_and_confirmation_events_are_separate_records(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        rows = self.conn.execute("SELECT kind, ts FROM state_events WHERE symbol='AAA' AND kind IN "
                                 "('INTRADAY_BREAKOUT','CONFIRMED_BREAKOUT') ORDER BY id").fetchall()
        self.assertEqual([r["kind"] for r in rows], ["INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT"])
        self.assertLess(rows[0]["ts"], rows[1]["ts"])                  # 장중 돌파가 종가 확정보다 먼저
        self.assertTrue(rows[1]["ts"].endswith("15:30:00"))

    def test_precision_analysis_only_within_5pct(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        self.assertIsNone(eng.live["EEE"])                             # -16% 부근 — 정밀분석 안 함
        self.assertIsNotNone(eng.live["AAA"])
        self.assertIsNotNone(eng.live["CCC"])                          # -1% 부근 — 정밀분석 함

    def test_sector_co_breakout_points(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        pts = {}
        for r in self.conn.execute("SELECT symbol, payload FROM state_events WHERE kind='INTRADAY_BREAKOUT'"):
            pts[r["symbol"]] = json.loads(r["payload"])["sector_pts"]
        self.assertEqual(pts["AAA"], 0)      # 같은 분에 AAA 가 먼저 돌파 — 그 시점엔 업종 동료가 없다
        self.assertEqual(pts["BBB"], 2)      # BBB 가 돌파할 때는 AAA 가 이미 돌파 중

    def test_live_score_is_static_plus_live_parts(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        a = eng.live["AAA"]
        self.assertEqual(a["live_score"], round(60.0 + a["live_pts"], 2))
        self.assertLessEqual(a["live_pts"], 16)
        self.assertEqual(a["candle_pts"], 4)                           # 시가 96 → 고가 102.5 에서 마감
        self.assertGreaterEqual(a["rel_volume"], 2.0)                  # 거래량을 크게 줬다
        self.assertEqual(a["rel_volume_pts"], 6)

    def test_state_survives_restart(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        eng2 = Engine(self.base, self.conn)                            # 같은 DB 로 다시 시작
        self.assertEqual(eng2.states["AAA"].state, "CONFIRMED_BREAKOUT")
        self.assertEqual(eng2.states["AAA"].breakout_level, 100.0)

    def test_failed_breakout_recorded_at_close(self):
        eng = Engine({"AAA": baseline("AAA", "S1")}, self.conn)
        run_engine(eng, {"AAA": day_ticks("AAA", [98, 99.5, 101, 100.5, 99.8])})
        self.assertEqual(self.kinds("AAA"), ["NEAR", "READY", "INTRADAY_BREAKOUT", "FAILED_BREAKOUT"])

    def test_watch_symbols_puts_breakouts_first_and_respects_limit(self):
        eng = Engine(self.base, self.conn)
        run_engine(eng, self.script)
        w = eng.watch_symbols(2)
        self.assertEqual(len(w), 2)
        self.assertEqual(set(w), {"AAA", "BBB"})                       # 돌파 상태 두 종목이 먼저
        self.assertNotIn("EEE", eng.watch_symbols(10))

    def test_multi_day_cycle_through_engine(self):
        """엔진을 3거래일 이어서 돌려 확정 → 이튿날 신고가 갱신 상태가 DB 에 남는지."""
        eng = Engine({"AAA": baseline("AAA", "S1")}, self.conn)
        run_engine(eng, {"AAA": day_ticks("AAA", [99, 101, 102.5])}, day="20261109")
        eng.base["AAA"]["high_52w_prev"] = 102.5                       # 이튿날 기준(전일 고가)
        run_engine(eng, {"AAA": day_ticks("AAA", [102, 103, 104], day="20261110")}, day="20261110")
        self.assertEqual(eng.states["AAA"].state, "CONFIRMED_BREAKOUT")
        n = self.conn.execute("SELECT COUNT(*) FROM state_events WHERE kind='CONFIRMED_BREAKOUT'").fetchone()[0]
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
