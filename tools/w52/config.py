"""임계값과 환경변수. 정의는 docs/w52_spec.md 와 같아야 한다. API 키는 서버 환경변수에서만 읽는다."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    # 기준 지표
    window_days: int = 365           # 52주 = 달력 기준 1년(기준일 포함). KIS 의 52주 최고가와 같은 정의
    rs1m_days: int = 21
    rs3m_days: int = 63
    rs_universe_mcap: int = 100_000_000_000      # RS 백분위를 매기는 모집단: 시총 1000억 이상
    sector_min_members: int = 4
    bbw_window: int = 20
    bbw_hist: int = 120
    atr_period: int = 14
    adx_period: int = 14
    # 게이트
    mcap_min: int = 500_000_000_000              # 5,000억
    val_min: int = 5_000_000_000                 # 평균 거래대금 50억
    rs_min: float = 70.0
    # 상태(이격률, %)
    watch_pct: float = -10.0
    near_pct: float = -5.0
    ready_pct: float = -1.0
    extended_pct: float = 10.0
    # 재돌파 대기: 수렴 판정
    rebreak_bbw_ratio: float = 0.7
    rebreak_atr_ratio: float = 0.8
    rebreak_vol_ratio: float = 0.7
    # 리스크 패널(계산기)
    account: int = 200_000_000
    risk_pct: float = 0.01
    stop_pct: float = 0.08


PARAMS = Params()

# 관리·위험 종목 제외에 쓰는 종목 상태 코드(한국투자증권 iscd_stat_cls_code): 관리 51, 거래정지 58, 단기과열 59
RISK_STAT_CODES = {"51", "58", "59"}


def env(name, default=None):
    """서버 환경변수. 코드·페이지·저장소에는 키를 넣지 않는다."""
    return os.environ.get(name, default)


def provider_name():
    return env("PROVIDER", "mock")
