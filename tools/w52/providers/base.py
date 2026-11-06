"""시세 공급자 인터페이스(Provider Adapter). KIS 와 키움을 같은 모양으로 바꿔 끼울 수 있게 한다.

읽기 전용이다. 주문·잔고 조회 메서드는 두지 않는다(tests/test_no_orders.py 가 코드에서 주문 TR 을 막는다).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List


@dataclass(frozen=True)
class Tick:
    symbol: str
    ts: str            # 'YYYYMMDD HH:MM:SS' (KST)
    price: float       # 현재가
    high: float        # 당일 고가(누적)
    low: float         # 당일 저가(누적)
    open: float        # 당일 시가
    cum_vol: float     # 누적 거래량
    cum_val: float     # 누적 거래대금(원)

    @property
    def day(self) -> str:
        return self.ts[:8]

    @property
    def minute_of_day(self) -> int:
        """09:00 = 0."""
        h, m = int(self.ts[9:11]), int(self.ts[12:14])
        return (h - 9) * 60 + m


class MarketDataProvider(ABC):
    name = "base"
    max_subscriptions = 0          # 실시간(WebSocket) 동시 구독 상한. 0 이면 실시간 없음(폴링만)

    @abstractmethod
    def snapshot(self, symbols: Iterable[str]) -> Dict[str, Tick]:
        """REST 처럼 종목들의 현재 시세를 한 번에 가져온다(전 종목 폴링용)."""

    def subscribe(self, symbols: Iterable[str]) -> List[str]:
        """실시간 구독 대상을 정한다. 상한을 넘는 종목은 구독하지 않고, 실제로 구독한 종목을 돌려준다."""
        return []

    def stream(self) -> Iterator[Tick]:
        """구독한 종목의 실시간 시세. 없으면 빈 이터레이터."""
        return iter(())

    def close(self) -> None:
        pass
