"""MockMarketDataProvider — 실제 API 없이 상태 전이를 시험하기 위한 가짜 시세 공급자.

종목마다 가격 경로를 주면 1분 간격 틱(09:00부터)을 만들고, 당일 고가·저가·누적 거래량을 이어 붙인다.
"""
from typing import Dict, Iterable, Iterator, List

from .base import MarketDataProvider, Tick


def build_day(symbol, day, prices, start_cum_vol=0, vol_per_tick=1000, minute0=0):
    """prices: 1분 간격 가격 목록 → Tick 목록. high·low·cum_vol 은 누적으로 계산한다."""
    ticks, hi, lo, cv = [], None, None, start_cum_vol
    for i, p in enumerate(prices):
        hi = p if hi is None else max(hi, p)
        lo = p if lo is None else min(lo, p)
        cv += vol_per_tick
        mm = minute0 + i
        ts = "%s %02d:%02d:00" % (day, 9 + mm // 60, mm % 60)
        ticks.append(Tick(symbol, ts, float(p), float(hi), float(lo), float(prices[0]), float(cv), float(cv * p)))
    return ticks


class MockMarketDataProvider(MarketDataProvider):
    name = "mock"
    max_subscriptions = 40

    def __init__(self, script: Dict[str, List[Tick]]):
        self.script = {s: list(t) for s, t in script.items()}
        self._subs: List[str] = []
        self._pos = {s: 0 for s in script}

    def snapshot(self, symbols: Iterable[str]) -> Dict[str, Tick]:
        """종목마다 다음 틱 하나를 꺼내 준다(폴링 한 바퀴). 끝난 종목은 마지막 틱을 되풀이한다."""
        out = {}
        for s in symbols:
            t = self.script.get(s)
            if not t:
                continue
            i = min(self._pos[s], len(t) - 1)
            out[s] = t[i]
            self._pos[s] = i + 1
        return out

    def subscribe(self, symbols: Iterable[str]) -> List[str]:
        self._subs = [s for s in symbols if s in self.script][: self.max_subscriptions]
        return list(self._subs)

    def stream(self) -> Iterator[Tick]:
        """구독 종목의 모든 틱을 시각 순서로."""
        ticks = [t for s in self._subs for t in self.script[s]]
        return iter(sorted(ticks, key=lambda t: (t.ts, t.symbol)))


class DemoProvider(MockMarketDataProvider):
    """화면 시연용: 배치 기준(baselines)의 종목마다 정해진 시나리오(확정·실패·횡보 등)로 가격을 움직인다. 폴링할 때마다 한 걸음."""
    name = "demo"
    SCENARIOS = [
        [-0.12, -0.08, -0.04, -0.005, 0.012, 0.02, 0.025, 0.03],        # 접근 → 돌파 → 종가 확정
        [-0.07, -0.03, -0.004, 0.012, 0.004, -0.002, -0.004, -0.003],   # 돌파 후 밀려 종가 실패
        [-0.30, -0.28, -0.27, -0.27, -0.26, -0.26, -0.25, -0.25],       # 멀리 있는 종목
        [-0.06, -0.045, -0.02, -0.008, -0.007, -0.006, -0.005, -0.004], # 접근만 하고 돌파는 못 함
        [-0.03, -0.01, 0.01, 0.06, 0.10, 0.12, 0.13, 0.13],             # 돌파 후 +10% 이상 → EXTENDED
    ]

    def __init__(self, baselines):
        super().__init__({})
        self.base = {s: b for s, b in baselines.items() if b.get("gate_pass")}
        self.step_no = 0
        self.hi, self.lo, self.open = {}, {}, {}

    def snapshot(self, symbols):
        self.step_no += 1
        out = {}
        for i, s in enumerate(symbols):
            b = self.base.get(s)
            if not b:
                continue
            sc = self.SCENARIOS[sum(map(ord, s)) % len(self.SCENARIOS)]
            gap = sc[min(self.step_no - 1, len(sc) - 1)]
            price = round(b["high_52w_prev"] * (1 + gap), 2)
            self.open.setdefault(s, price)
            self.hi[s] = max(self.hi.get(s, price), price)
            self.lo[s] = min(self.lo.get(s, price), price)
            minute = min(self.step_no * 25, 389)
            from ..live import expected_fraction
            mult = 2.3 if sum(map(ord, s)) % 2 == 0 else 1.0
            vol = (b.get("avg_vol20") or 100000) * expected_fraction(minute) * mult
            ts = "20261109 %02d:%02d:00" % (9 + minute // 60, minute % 60)
            out[s] = Tick(s, ts, price, self.hi[s], self.lo[s], self.open[s], vol, vol * price)
        return out
