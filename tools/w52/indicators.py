"""순수 지표 함수. 외부 의존 없음(표준 라이브러리만). 값은 tests/test_indicators.py 로 검증한다."""
import datetime as dt
import math


def sma(values, n):
    """마지막 n개 평균. 모자라면 None."""
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def weekly_closes(dates, closes):
    """일봉(YYYYMMDD, 종가)을 주봉 종가 목록으로. 각 ISO 주의 마지막 거래일 종가. 마지막 주는 미완성 봉일 수 있다."""
    out, last_key = [], None
    for d, c in zip(dates, closes):
        y, m, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
        iso = dt.date(y, m, dd).isocalendar()
        key = (iso[0], iso[1])
        if key == last_key:
            out[-1] = c
        else:
            out.append(c)
            last_key = key
    return out


def weekly_ma(wcloses, n):
    """주봉 종가의 n주 단순이동평균: (오늘 값, 1주 전 값). 모자라면 (None, None)."""
    if len(wcloses) < n + 1:
        return (sma(wcloses, n), None) if len(wcloses) >= n else (None, None)
    return sma(wcloses, n), sma(wcloses[:-1], n)


def bbw(closes, n=20, k=2.0):
    """볼린저 밴드 폭 = (상단 − 하단) / 중심선, 표준편차는 모집단 기준."""
    if len(closes) < n:
        return None
    w = closes[-n:]
    mid = sum(w) / n
    if mid == 0:
        return None
    sd = math.sqrt(sum((x - mid) ** 2 for x in w) / n)
    return 2 * k * sd / mid


def bbw_series(closes, n=20, k=2.0):
    """각 시점의 BBW (앞쪽 n-1개는 None)."""
    return [bbw(closes[: i + 1], n, k) if i + 1 >= n else None for i in range(len(closes))]


def pctile_in_history(value, history):
    """history 안에서 value 의 백분위(0~100, 동률은 중간 순위). history 가 비면 None."""
    h = [x for x in history if x is not None]
    if value is None or not h:
        return None
    less = sum(1 for x in h if x < value)
    eq = sum(1 for x in h if x == value)
    return (less + 0.5 * eq) / len(h) * 100.0


def true_ranges(highs, lows, closes):
    """TR[i] (i>=1): max(H-L, |H-prevC|, |L-prevC|). TR[0] 은 H-L."""
    tr = []
    for i in range(len(closes)):
        if i == 0:
            tr.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            tr.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return tr


def atr(highs, lows, closes, n=14):
    """Wilder ATR: 처음 n개 TR(1번부터)의 평균, 이후 (이전×(n-1)+TR)/n. 모자라면 None."""
    if len(closes) < n + 1:
        return None
    tr = true_ranges(highs, lows, closes)
    a = sum(tr[1: n + 1]) / n
    for i in range(n + 1, len(tr)):
        a = (a * (n - 1) + tr[i]) / n
    return a


def adx(highs, lows, closes, n=14):
    """Wilder ADX. 2n 개 이상의 봉이 필요하다. 모자라면 None."""
    if len(closes) < 2 * n + 1:
        return None
    tr = true_ranges(highs, lows, closes)
    pdm, mdm = [0.0], [0.0]
    for i in range(1, len(closes)):
        up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
    trs, ps, ms = sum(tr[1: n + 1]), sum(pdm[1: n + 1]), sum(mdm[1: n + 1])
    dx = []

    def _dx(trs, ps, ms):
        if trs == 0:
            return 0.0
        pdi, mdi = 100 * ps / trs, 100 * ms / trs
        s = pdi + mdi
        return 0.0 if s == 0 else 100 * abs(pdi - mdi) / s

    dx.append(_dx(trs, ps, ms))
    for i in range(n + 1, len(closes)):
        trs = trs - trs / n + tr[i]
        ps = ps - ps / n + pdm[i]
        ms = ms - ms / n + mdm[i]
        dx.append(_dx(trs, ps, ms))
    a = sum(dx[:n]) / n
    for v in dx[n:]:
        a = (a * (n - 1) + v) / n
    return a


def percentile_ranks(values):
    """{키: 값} → {키: 백분위 0~100}. 동률은 중간 순위. 값이 None 인 키는 뺀다."""
    items = [(k, v) for k, v in values.items() if v is not None]
    n = len(items)
    if n == 0:
        return {}
    srt = sorted(v for _, v in items)
    import bisect
    out = {}
    for k, v in items:
        lo, hi = bisect.bisect_left(srt, v), bisect.bisect_right(srt, v)
        out[k] = (lo + 0.5 * (hi - lo)) / n * 100.0
    return out


def adjust_splits(closes, shares, *price_arrays):
    """액면분할·병합·무상증자 보정. 상장주식수가 25% 넘게 변하고 시총이 거의 이어지면(±12%) 이전 가격을 1/배율로 나눈다.

    closes·shares 는 날짜 순서이고 결측은 None. 보정한 (closes, *price_arrays) 를 새 리스트로 돌려준다.
    """
    adj = [list(a) for a in (closes,) + price_arrays]
    last = None
    for i in range(len(closes)):
        if closes[i] is None:
            continue
        if last is not None and shares[i] and shares[last]:
            s, p = shares[i] / shares[last], closes[i] / closes[last]
            if abs(s - 1) > 0.25 and abs(p * s - 1) < 0.12:
                for arr in adj:
                    for k in range(i):
                        if arr[k] is not None:
                            arr[k] /= s
        last = i
    return adj
