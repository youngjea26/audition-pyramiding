"""한국투자증권(KIS) 시세 공급자 — 읽기 전용(시세 조회만).

- snapshot(): REST 현재가(inquire-price)를 여러 스레드로 폴링한다. 전 종목(약 530개)을 약 40초에 한 바퀴 돈다.
- subscribe()/stream(): WebSocket 체결가(H0STCNT0). 동시 구독 상한은 KIS_WS_MAX_SUBS(기본 40)이고, 실제 한도는 장중에 확인한다.
키는 서버 환경변수(KIS_APP_KEY, KIS_APP_SECRET)에서만 읽는다. 주문·잔고 관련 호출은 없다.

⚠ WebSocket 프레임의 필드 순서(WS_FIELDS)는 KIS 문서 기준이며 장중 실제 프레임으로 검증이 필요하다.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Iterator, List

from ..config import env
from .base import MarketDataProvider, Tick

KST = timezone(timedelta(hours=9))
REST = "https://openapi.koreainvestment.com:9443"
WS_URL = "ws://ops.koreainvestment.com:21000"
WS_TR = "H0STCNT0"          # 국내주식 실시간 체결가(시세 조회)
# H0STCNT0 데이터 필드 순서(^ 구분): 종목코드, 체결시각, 현재가, ..., 시가, 고가, 저가, ..., 체결량, 누적거래량, 누적거래대금
WS_FIELDS = {"symbol": 0, "time": 1, "price": 2, "open": 7, "high": 8, "low": 9, "cum_vol": 13, "cum_val": 14}
MIN_GAP = 0.07                # REST 호출 간격(초) — 초당 약 14회, KIS 한도(초당 20회) 안


def now_ts():
    return datetime.now(KST).strftime("%Y%m%d %H:%M:%S")


def parse_ws_frame(text, day=None):
    """WebSocket 텍스트 프레임 → Tick 목록. 제어 메시지(JSON)나 다른 TR 이면 빈 목록.

    형식: '0|H0STCNT0|건수|값^값^...' (건수가 2 이상이면 레코드가 이어 붙는다).
    """
    if not text or text[0] not in "01":
        return []
    parts = text.split("|", 3)
    if len(parts) < 4 or parts[1] != WS_TR:
        return []
    day = day or datetime.now(KST).strftime("%Y%m%d")
    n = max(1, int(parts[2] or 1))
    vals = parts[3].split("^")
    width = len(vals) // n
    ticks = []
    for i in range(n):
        f = vals[i * width:(i + 1) * width]
        try:
            hhmmss = f[WS_FIELDS["time"]]
            ticks.append(Tick(
                symbol=f[WS_FIELDS["symbol"]], ts="%s %s:%s:%s" % (day, hhmmss[:2], hhmmss[2:4], hhmmss[4:6]),
                price=float(f[WS_FIELDS["price"]]), high=float(f[WS_FIELDS["high"]]), low=float(f[WS_FIELDS["low"]]),
                open=float(f[WS_FIELDS["open"]]), cum_vol=float(f[WS_FIELDS["cum_vol"]]),
                cum_val=float(f[WS_FIELDS["cum_val"]])))
        except (IndexError, ValueError):
            continue
    return ticks


def tick_from_price_output(symbol, o):
    """inquire-price 응답(output) → Tick. 값이 비어 있으면 None."""
    try:
        price = float(o["stck_prpr"])
        if price <= 0:
            return None
        return Tick(symbol, now_ts(), price, float(o.get("stck_hgpr") or price), float(o.get("stck_lwpr") or price),
                    float(o.get("stck_oprc") or price), float(o.get("acml_vol") or 0), float(o.get("acml_tr_pbmn") or 0))
    except (KeyError, ValueError, TypeError):
        return None


class KisProvider(MarketDataProvider):
    name = "kis"

    def __init__(self, workers=8):
        self.key, self.secret = env("KIS_APP_KEY"), env("KIS_APP_SECRET")
        if not self.key or not self.secret:
            raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 환경변수가 없다")
        self.max_subscriptions = int(env("KIS_WS_MAX_SUBS", "40"))
        self.workers = workers
        self._tok, self._tok_exp = None, 0.0
        self._subs: List[str] = []
        self._gate, self._last = threading.Lock(), [0.0]
        self._stop = False

    # ───────── REST
    def _token(self):
        if self._tok and self._tok_exp > time.time() + 600:
            return self._tok
        body = json.dumps({"grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret}).encode()
        req = urllib.request.Request(REST + "/oauth2/tokenP", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8"))
        self._tok, self._tok_exp = res["access_token"], time.time() + 70000
        return self._tok

    def _throttle(self):
        with self._gate:
            wait = self._last[0] + MIN_GAP - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last[0] = time.time()

    def _price(self, symbol):
        q = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
        req = urllib.request.Request(
            REST + "/uapi/domestic-stock/v1/quotations/inquire-price?" + q,
            headers={"authorization": "Bearer " + self._token(), "appkey": self.key, "appsecret": self.secret,
                     "tr_id": "FHKST01010100", "custtype": "P"})
        for attempt in range(4):
            self._throttle()
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    j = json.loads(r.read().decode("utf-8"))
                return tick_from_price_output(symbol, j.get("output") or {}) if j.get("rt_cd") == "0" else None
            except urllib.error.HTTPError as e:
                if e.code in (500, 429):
                    time.sleep(1.0 * (attempt + 1))
                    continue
                return None
            except Exception:
                time.sleep(1.0 * (attempt + 1))
        return None

    def snapshot(self, symbols: Iterable[str]) -> Dict[str, Tick]:
        syms = list(symbols)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            ticks = list(ex.map(self._price, syms))
        return {s: t for s, t in zip(syms, ticks) if t is not None}

    # ───────── WebSocket
    def subscribe(self, symbols: Iterable[str]) -> List[str]:
        self._subs = list(symbols)[: self.max_subscriptions]
        return list(self._subs)

    def _approval_key(self):
        body = json.dumps({"grant_type": "client_credentials", "appkey": self.key, "secretkey": self.secret}).encode()
        req = urllib.request.Request(REST + "/oauth2/Approval", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))["approval_key"]

    def stream(self) -> Iterator[Tick]:
        try:
            import websocket          # websocket-client
        except ImportError as e:
            raise RuntimeError("WebSocket 은 `pip install websocket-client` 가 필요하다") from e
        approval = self._approval_key()
        ws = websocket.create_connection(WS_URL, timeout=30)
        sent = set()

        def sync_subscriptions():
            """_subs 와 실제 구독을 맞춘다: 새로 들어온 종목은 구독(tr_type 1), 빠진 종목은 해지(tr_type 2)해 한도를 비운다."""
            want = set(self._subs)
            for s in want - sent:
                ws.send(json.dumps({"header": {"approval_key": approval, "custtype": "P", "tr_type": "1",
                                               "content-type": "utf-8"},
                                    "body": {"input": {"tr_id": WS_TR, "tr_key": s}}}))
                sent.add(s)
            for s in sent - want:
                ws.send(json.dumps({"header": {"approval_key": approval, "custtype": "P", "tr_type": "2",
                                               "content-type": "utf-8"},
                                    "body": {"input": {"tr_id": WS_TR, "tr_key": s}}}))
                sent.discard(s)

        try:
            ws.settimeout(1.0)
            while not self._stop:
                sync_subscriptions()
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if isinstance(msg, str) and msg.startswith("{") and '"PINGPONG"' in msg:
                    ws.pong(msg)                  # 연결 유지
                    continue
                for t in parse_ws_frame(msg):
                    yield t
        finally:
            ws.close()

    def close(self):
        self._stop = True
