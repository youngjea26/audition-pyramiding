"""52주 신고가 상태 머신 (docs/w52_spec.md §5). 입출력이 순수해서 Mock 시세로 전이를 검증할 수 있다.

흐름: start_session(날짜가 바뀔 때) → on_tick(장중 매 시세) → on_close(종가 확정).
돌파 이벤트(INTRADAY_BREAKOUT, 장중)와 종가 확정 이벤트(CONFIRMED_BREAKOUT / FAILED_BREAKOUT)는 분리되어 있다.
주문 기능은 없다.
"""
from dataclasses import dataclass, field

from .config import PARAMS as P

ZONES = ("NORMAL", "WATCH", "NEAR", "READY")
CONFIRM_SESSIONS = 5           # 종가 확정 후 CONFIRMED_BREAKOUT 로 보여 주는 거래일 수
EXTEND_WINDOW = 30             # 돌파 후 이 거래일 안에서만 EXTENDED 를 판정한다


@dataclass
class StockState:
    symbol: str
    state: str = "NORMAL"
    since: str = ""
    day: str = ""
    breakout_level: float = 0.0       # 돌파 당시의 기준 고가(52주 최고가 또는 수렴 구간 고점)
    breakout_date: str = ""
    broke_today: bool = False
    sessions_since_breakout: int = 0
    ext_peak: float = 0.0
    bbw_at_ext: float = 0.0
    atr_pct_at_ext: float = 0.0
    consol_high: float = 0.0
    events: list = field(default_factory=list)    # 이번 호출에서 생긴 이벤트(호출자가 비운다)


def zone_for_gap(gap_pct):
    """이격률(%) → NORMAL / WATCH / NEAR / READY. 0 이하는 READY, 돌파(0 초과)는 호출자가 따로 본다."""
    gap_pct = round(gap_pct, 6)          # 99/100-1 = -1.0000000000000009 처럼 경계값이 부동소수점 오차로 넘어가지 않게
    if gap_pct < P.watch_pct:
        return "NORMAL"
    if gap_pct < P.near_pct:
        return "WATCH"
    if gap_pct < P.ready_pct:
        return "NEAR"
    return "READY"


def _emit(st, kind, price, day):
    st.events.append({"symbol": st.symbol, "kind": kind, "price": price, "day": day})


def _set(st, state, day):
    st.state, st.since = state, day


def contraction(base, st):
    """EXTENDED 이후 BBW·ATR·거래량이 모두 줄었나(수렴)."""
    if not st.ext_peak or base.get("bbw") is None or base.get("atr_pct") is None or base.get("vol5_ratio") is None:
        return False
    return (base["bbw"] <= st.bbw_at_ext * P.rebreak_bbw_ratio
            and base["atr_pct"] <= st.atr_pct_at_ext * P.rebreak_atr_ratio
            and base["vol5_ratio"] <= P.rebreak_vol_ratio
            and base["close"] < st.ext_peak)


def start_session(st, base, day):
    """새 거래일 시작. 어제의 상태를 오늘 기준으로 정리하고, 새 기준 지표(base)로 일 단위 전이를 판정한다."""
    if st.day == day:
        return
    st.day, st.broke_today = day, False
    if st.breakout_level:
        st.sessions_since_breakout += 1
        if st.sessions_since_breakout > EXTEND_WINDOW and st.state in ZONES:
            st.breakout_level, st.sessions_since_breakout = 0.0, 0
    if st.state in ("CONFIRMED_BREAKOUT", "REBREAKOUT") and st.sessions_since_breakout > CONFIRM_SESSIONS:
        _set(st, "NORMAL", day)                       # 확정 표시 기간이 끝났다 — 첫 시세에서 이격률로 다시 정한다
    elif st.state in ("FAILED_BREAKOUT", "INTRADAY_BREAKOUT"):
        st.breakout_level, st.sessions_since_breakout = 0.0, 0
        _set(st, "NORMAL", day)
    elif st.state == "EXTENDED" and contraction(base, st):
        _set(st, "REBREAKOUT_WAIT", day)
        st.consol_high = base.get("high_10d") or base["close"]
        _emit(st, "REBREAKOUT_WAIT", base["close"], day)


def on_tick(st, base, price, day_high):
    """장중 시세 한 건. base 는 전일까지의 기준(high_52w_prev, bbw, atr_pct ...). 이벤트는 st.events 에 쌓인다."""
    day = st.day
    top = max(price, day_high or price)
    ref = base["high_52w_prev"]
    if st.state in ZONES:
        if top > ref:                                  # 장중 신고가 돌파
            st.breakout_level, st.breakout_date, st.broke_today = ref, day, True
            st.sessions_since_breakout = 0
            _set(st, "INTRADAY_BREAKOUT", day)
            _emit(st, "INTRADAY_BREAKOUT", price, day)
        elif st.breakout_level and price >= st.breakout_level * (1 + P.extended_pct / 100):
            _enter_extended(st, base, price, day)
        else:
            z = zone_for_gap((price / ref - 1) * 100)
            if z != st.state:
                _set(st, z, day)
                _emit(st, z, price, day)
        return
    if st.state in ("INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT", "REBREAKOUT"):
        if st.breakout_level and price >= st.breakout_level * (1 + P.extended_pct / 100):
            _enter_extended(st, base, price, day)
        return
    if st.state == "EXTENDED":
        st.ext_peak = max(st.ext_peak, top)
        return
    if st.state == "REBREAKOUT_WAIT" and st.consol_high and top > st.consol_high:
        st.breakout_level, st.broke_today = st.consol_high, True
        st.sessions_since_breakout = 0
        _set(st, "REBREAKOUT", day)
        _emit(st, "REBREAKOUT", price, day)


def _enter_extended(st, base, price, day):
    st.ext_peak = price
    st.bbw_at_ext = base.get("bbw") or 0.0
    st.atr_pct_at_ext = base.get("atr_pct") or 0.0
    _set(st, "EXTENDED", day)
    _emit(st, "EXTENDED", price, day)


def on_close(st, base, close, day_high):
    """종가 확정. 장중 돌파가 종가로 확정됐는지, 실패했는지 가른다."""
    day = st.day
    if st.state == "INTRADAY_BREAKOUT":
        if close > st.breakout_level:
            st.sessions_since_breakout = 0
            _set(st, "CONFIRMED_BREAKOUT", day)
            _emit(st, "CONFIRMED_BREAKOUT", close, day)
        else:
            _set(st, "FAILED_BREAKOUT", day)
            _emit(st, "FAILED_BREAKOUT", close, day)
    elif st.state == "REBREAKOUT":
        if close <= st.breakout_level:
            _set(st, "REBREAKOUT_WAIT", day)           # 재돌파가 종가로 이어지지 못했다 — 다시 대기
            _emit(st, "REBREAKOUT_WAIT", close, day)
    elif st.state == "REBREAKOUT_WAIT":
        st.consol_high = max(st.consol_high, day_high or close)
    elif st.state == "EXTENDED":
        st.ext_peak = max(st.ext_peak, day_high or close)


def drain(st):
    ev, st.events = st.events, []
    return ev
