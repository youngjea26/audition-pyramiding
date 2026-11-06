"""장중 가변 항목과 Live Score (docs/w52_spec.md §6). 순수 함수.

정적 점수(최대 84) + 장중 항목(상대 거래량 6, 돌파 캔들 품질 4, 돌파 폭 2, 업종 동반돌파 4 = 최대 16) = Live Score(100).
점수는 후보 검토 우선순위일 뿐 매수 신호가 아니다.
"""

# 시각(09:00 기준 분) → 하루 거래량 대비 누적 비율. 분봉 이력이 쌓이기 전까지 쓰는 일반적인 U자형 곡선(가정).
# 서버가 분 단위 스냅샷을 쌓으면(volume_profile 표) 종목별 실측 곡선으로 대체한다.
DEFAULT_CURVE = [(0, 0.0), (10, 0.08), (30, 0.16), (60, 0.26), (120, 0.40), (180, 0.52), (240, 0.65),
                 (300, 0.78), (345, 0.86), (375, 0.95), (390, 1.0)]


def expected_fraction(minute, curve=DEFAULT_CURVE):
    """minute 분까지 «평소 쌓였을 거래량 비율»(0~1). 곡선 사이는 직선으로 잇는다."""
    if minute <= curve[0][0]:
        return curve[0][1]
    for (m0, f0), (m1, f1) in zip(curve, curve[1:]):
        if minute <= m1:
            return f0 + (f1 - f0) * (minute - m0) / (m1 - m0)
    return 1.0


def rel_volume(cum_vol, avg_vol20, minute, curve=DEFAULT_CURVE):
    """같은 시각 대비 상대 거래량. 기준 거래량이 없거나 장 초반(비율 0)이면 None."""
    f = expected_fraction(minute, curve)
    if not avg_vol20 or f <= 0.02:
        return None
    return cum_vol / (avg_vol20 * f)


def rel_volume_points(rv):
    if rv is None:
        return 0
    return 6 if rv >= 2.0 else 4 if rv >= 1.5 else 2 if rv >= 1.2 else 0


def candle_points(price, open_, high, low):
    """돌파 캔들 품질: 현재가가 당일 고저폭 상단 25% 이내이고 시가 위면 4점, 상단 50% 이내이고 시가 위면 2점."""
    rng = high - low
    if rng <= 0 or price <= open_:
        return 0
    pos = (price - low) / rng
    return 4 if pos >= 0.75 else 2 if pos >= 0.5 else 0


def width_points(price, level):
    """돌파 폭: 기준 고가 대비 0~3% 위면 2점(너무 멀리 간 종목은 가점 없음)."""
    if not level or price <= level:
        return 0
    return 2 if price / level - 1 <= 0.03 else 0


def sector_points(n_other_breaking):
    """같은 업종의 다른 종목이 돌파 중이면: 1종목 2점, 2종목 이상 4점."""
    return 0 if n_other_breaking <= 0 else 2 if n_other_breaking == 1 else 4


def live_components(tick, base, level, n_other_breaking, curve=DEFAULT_CURVE):
    rv = rel_volume(tick.cum_vol, base.get("avg_vol20"), tick.minute_of_day, curve)
    parts = {
        "rel_volume": None if rv is None else round(rv, 2),
        "rel_volume_pts": rel_volume_points(rv),
        "candle_pts": candle_points(tick.price, tick.open, tick.high, tick.low),
        "width_pts": width_points(tick.price, level),
        "sector_pts": sector_points(n_other_breaking),
    }
    parts["live_pts"] = parts["rel_volume_pts"] + parts["candle_pts"] + parts["width_pts"] + parts["sector_pts"]
    return parts
