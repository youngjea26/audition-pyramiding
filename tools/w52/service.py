"""장중 서비스: 거래시간(평일 09:00~15:30 KST)에 전 종목을 폴링하고, 후보만 WebSocket 으로 지켜본다.

- 폴링 한 바퀴(step): 추적 종목 전체의 현재 시세를 가져와 엔진에 넣는다. 상태 머신은 모든 종목, 정밀분석은 -5% 이내만.
- 실시간: 신고가에 가까운 순서로 provider.max_subscriptions 개를 구독하고, 틱이 오면 바로 엔진에 넣는다.
- 15:30 이후 한 번만 종가 확정(end_session)을 한다.
엔진은 여러 스레드(폴링·WebSocket·HTTP)가 함께 쓰므로 하나의 잠금으로 보호한다. 주문 기능은 없다.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
OPEN, CLOSE = (9, 0), (15, 30)


def is_market_open(t):
    return t.weekday() < 5 and OPEN <= (t.hour, t.minute) < CLOSE


def is_after_close(t):
    return t.weekday() < 5 and (t.hour, t.minute) >= CLOSE


class LiveService:
    def __init__(self, engine, provider, poll_interval=40, now=None, log=print):
        self.engine, self.provider, self.poll = engine, provider, poll_interval
        self.now = now or (lambda: datetime.now(KST))
        self.lock = threading.RLock()
        self.version = 0                     # 시세가 갱신될 때마다 올라간다(SSE 가 변화를 알아챈다)
        self.mode = "idle"                   # idle(장 밖) / live(장중) / closed(종가 확정 끝)
        self.session_day = None
        self.closed_day = None
        self.stop = threading.Event()
        self.ws_thread = None
        self.log = log

    # ───────── 한 바퀴
    def step(self):
        t = self.now()
        day = t.strftime("%Y%m%d")
        with self.lock:
            if is_market_open(t):
                if self.session_day != day:
                    self.engine.begin_session(day)
                    self.session_day, self.closed_day, self.mode = day, None, "live"
                for tick in self.provider.snapshot(list(self.engine.states)).values():
                    self.engine.on_tick(tick)
                self._sync_subscriptions()
                self.version += 1
            elif self.session_day == day and self.closed_day != day and is_after_close(t):
                self.engine.end_session()
                self.closed_day, self.mode = day, "closed"
                self.version += 1

    def _sync_subscriptions(self):
        """신고가에 가까운 종목만 실시간으로. WebSocket 스레드는 처음 한 번만 띄운다."""
        if self.provider.max_subscriptions <= 0:
            return
        self.provider.subscribe(self.engine.watch_symbols(self.provider.max_subscriptions))
        if self.ws_thread is None:
            self.ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
            self.ws_thread.start()

    def _ws_loop(self):
        try:
            for tick in self.provider.stream():
                with self.lock:
                    self.engine.on_tick(tick)
                    self.version += 1
        except Exception as e:                 # 실시간이 끊겨도 폴링은 계속된다
            self.log("WebSocket 중단: %s" % e)

    # ───────── 상시 실행·조회
    def run_forever(self):
        while not self.stop.is_set():
            try:
                self.step()
            except Exception as e:
                self.log("폴링 오류: %s" % e)
            self.stop.wait(self.poll)

    def rows(self):
        with self.lock:
            return self.engine.rows()

    def recent_events(self, conn, limit=200):
        with self.lock:
            return [dict(r) for r in conn.execute(
                "SELECT symbol, ts, kind, price, volume, live_score FROM state_events ORDER BY id DESC LIMIT ?", (limit,))]

    def shutdown(self):
        self.stop.set()
        self.provider.close()
