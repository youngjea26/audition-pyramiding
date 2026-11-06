"""일봉으로 상태를 재현한다. 서버 없이(배치에서) «장 마감 후 상태»를 만들기 위한 것이다.

하루를 시가·저가·고가·종가(상승일) 또는 시가·고가·저가·종가(하락일) 네 점의 가격 경로로 보고, 실시간 엔진과 같은 상태 머신
(states.py)에 날짜 순서로 넣는다. 일봉에는 분 단위 순서가 없어 고가와 저가의 선후는 가정이다 — 장중 돌파가 있었는지(고가가 기준
고가를 넘었나)와 종가로 확정됐는지(종가가 넘었나)는 일봉만으로 정확히 알 수 있고, 가정이 영향을 주는 것은 돌파 전의 접근 단계 이벤트뿐이다.
"""
from datetime import datetime, timedelta

from . import indicators as ix, states as S
from .config import PARAMS as P

SESSIONS = 40            # 최근 몇 거래일을 재현할지(돌파 후 EXTENDED 판정 구간 30 + 여유)


def base_at(s, i):
    """i 번째 거래일이 끝난 시점의 기준 — 다음 거래일의 «전일까지» 기준과 같다."""
    ds, cl, hi, lo, vol = s["ds"], s["close"], s["high"], s["low"], s["vol"]
    cutoff = (datetime.strptime(ds[i], "%Y%m%d") - timedelta(days=P.window_days)).strftime("%Y%m%d")
    h52 = max(h for h, d in zip(hi[: i + 1], ds[: i + 1]) if d >= cutoff)
    a = ix.atr(hi[: i + 1], lo[: i + 1], cl[: i + 1], P.atr_period)
    v20 = sum(vol[i - 19: i + 1]) if i >= 19 else 0
    return {
        "high_52w_prev": h52, "close": cl[i], "high_10d": max(hi[max(0, i - 9): i + 1]),
        "bbw": ix.bbw(cl[: i + 1], P.bbw_window), "atr_pct": (a / cl[i]) if a else None,
        "vol5_ratio": (sum(vol[i - 4: i + 1]) / 5) / (v20 / 20) if v20 else None,
    }


def day_path(o, h, l, c):
    """상승일은 시가→저가→고가→종가, 하락일은 시가→고가→저가→종가로 본다."""
    return [o, l, h, c] if c >= o else [o, h, l, c]


def replay_stock(symbol, s, sessions=SESSIONS):
    """한 종목의 상태와 이벤트. 반환: (StockState, 이벤트 목록). 이벤트는 {day, kind, price}."""
    n = len(s["ds"])
    st = S.StockState(symbol)
    events = []
    for j in range(max(1, n - sessions), n):
        base = base_at(s, j - 1)
        day = s["ds"][j]
        S.start_session(st, base, day)
        run_hi = 0.0
        for price in day_path(s["open"][j], s["high"][j], s["low"][j], s["close"][j]):
            run_hi = max(run_hi, price)
            S.on_tick(st, base, price, run_hi)
        S.on_close(st, base, s["close"][j], s["high"][j])
        events += [{"day": day, "kind": e["kind"], "price": e["price"]} for e in S.drain(st)]
    return st, events


def end_of_day_state(st, gap_pct):
    """장 마감 후 보여 줄 상태. 돌파 계열은 그대로, 접근 구간(NORMAL~READY)은 «내일 장의 기준(오늘 고가 포함)» 대비 이격률로 다시 정한다."""
    return S.zone_for_gap(gap_pct) if st.state in S.ZONES else st.state
