"""리스크 패널 계산 (docs/w52_spec.md §7). 화면 JS 와 같은 식이다. 가격·수량 수준만 계산하며 주문 기능은 없다.

계좌 2억원 · 거래당 리스크 1%(200만원) · 기본 손절 -8% → 최대 기본 포지션 = 200만원 / 8% = 2,500만원.
1/3 분할 진입 · +1R 도달 시 본절권 관리 · +3R 도달 시 50% 익절 · 잔량은 주봉 종가가 5주선 아래로 이탈하면 정리.
"""
from .config import PARAMS as P


def plan(entry, account=P.account, risk_pct=P.risk_pct, stop_pct=P.stop_pct, tranches=3, ma5w=None):
    risk_amount = account * risk_pct
    stop = entry * (1 - stop_pct)
    r = entry - stop                                   # 1R(주당 손실폭)
    position = risk_amount / stop_pct                  # 최대 기본 포지션(금액)
    shares = int(position // entry)
    per = shares // tranches
    return {
        "risk_amount": risk_amount, "position": position, "stop": stop, "r_per_share": r, "shares": shares,
        "tranche_shares": [per] * (tranches - 1) + [shares - per * (tranches - 1)],
        "tranche_amount": position / tranches,
        "breakeven_trigger": entry + r,                # +1R: 도달하면 손절을 본절권(진입가)으로 옮겨 관리
        "take_profit_3r": entry + 3 * r,               # +3R: 50% 익절
        "take_profit_shares": shares // 2,
        "trail_rule": "잔량은 주봉 종가가 5주선(%s) 아래로 이탈하면 정리" % ("%.0f" % ma5w if ma5w else "-"),
    }
