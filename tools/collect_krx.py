"""KRX Open API 일별매매정보를 날짜별 JSON 캐시로 받는다. 이미 받은 날짜는 건너뛴다.

사용: python -I collect_krx.py <env 경로> <캐시 폴더> <시작일 YYYYMMDD> <종료일 YYYYMMDD>
"""
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
ENDPOINTS = (("KOSPI", "stk_bydd_trd"), ("KOSDAQ", "ksq_bydd_trd"))
KEEP = ("ISU_CD", "ISU_NM", "MKT_NM", "SECT_TP_NM", "TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "FLUC_RT",
        "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS")


def load_env(path):
    """.env 파일(로컬)과 환경변수(GitHub Actions 의 Secrets)를 모두 읽는다. 환경변수가 우선."""
    import os
    env = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("KRX_API_KEY", "DART_API_KEY", "KIS_APP_KEY", "KIS_APP_SECRET"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def fetch(key, endpoint, day):
    url = "https://data-dbg.krx.co.kr/svc/apis/sto/%s?%s" % (
        endpoint, urllib.parse.urlencode({"basDd": day}))
    req = urllib.request.Request(url, headers={"AUTH_KEY": key})
    err = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8")).get("OutBlock_1", [])
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit("인증 실패 HTTP %s (%s) — 키 또는 이용 신청을 확인하세요" % (e.code, endpoint))
            err = "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:200])
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            time.sleep(2 * (attempt + 1))
    sys.exit("재시도 초과: %s %s — 마지막 오류: %s" % (endpoint, day, err))


def needs_ohlc(f, day):
    """예전에 받은 캐시는 시가·고가·저가를 버렸다. 52주 신고가용으로 최근 약 320거래일은 다시 받는다.

    받은 내용이 있는 파일(빈 휴장 파일은 제외)의 앞부분에 고가 필드가 없으면 다시 받아야 하는 파일이다.
    """
    cutoff = (dt.datetime.now(KST).date() - dt.timedelta(days=470)).strftime("%Y%m%d")
    if day < cutoff or f.stat().st_size <= 5:
        return False
    with open(f, encoding="utf-8") as fh:
        return "TDD_HGPRC" not in fh.read(900)


def main():
    env_path, cache_dir, start, end = sys.argv[1:5]
    key = load_env(env_path)["KRX_API_KEY"]
    out = Path(cache_dir)
    out.mkdir(parents=True, exist_ok=True)
    d = dt.datetime.strptime(start, "%Y%m%d").date()
    last = dt.datetime.strptime(end, "%Y%m%d").date()
    got = skipped = holiday = 0
    while d <= last:
        day = d.strftime("%Y%m%d")
        d += dt.timedelta(days=1)
        if dt.datetime.strptime(day, "%Y%m%d").weekday() >= 5:
            continue
        f = out / (day + ".json")
        if f.exists() and not needs_ohlc(f, day):
            skipped += 1
            continue
        rows = []
        for name, ep in ENDPOINTS:
            for r in fetch(key, ep, day):
                rec = {k: r.get(k, "") for k in KEEP}
                rec["MKT"] = name
                rows.append(rec)
            time.sleep(0.15)
        if not rows and (dt.datetime.now(KST).date() - dt.datetime.strptime(day, "%Y%m%d").date()).days <= 14:
            # 빈 응답은 휴장일 수도, 아직 미게시이거나 KRX 가 일시적으로 비워 준 것일 수도 있다.
            # 최근 2주는 캐시하지 않아 다음 실행이 다시 조회한다. 더 오래된 날의 교차 검증은 update_all.py 가 한다.
            continue
        f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        if rows:
            got += 1
        else:
            holiday += 1
        if (got + holiday) % 20 == 0:
            print("진행 %s 거래일 %d 휴장 %d 건너뜀 %d" % (day, got, holiday, skipped), flush=True)
    print("완료 거래일 %d 휴장 %d 건너뜀 %d" % (got, holiday, skipped), flush=True)


main()

