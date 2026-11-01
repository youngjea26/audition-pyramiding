"""한국투자증권 종목별 투자자매매동향(일별)에서 외국인·기관 순매수 금액(백만원)을 받는다.

종목마다 기준일부터 30거래일씩 과거로 넘기며 시작일까지 받는다. 이미 받은 종목은 겹치는 날까지만 더 받는다(증분).
종목들을 여러 스레드로 동시에 받되, 전체 호출 간격은 하나의 자물쇠로 묶어 초당 한도(약 20회)를 넘지 않게 한다.
받다가 실패한 종목은 저장하지 않는다(일부만 저장되면 다음 실행이 완료로 착각한다). 다음 실행이 다시 받는다.
사용: python -I collect_kis_flow.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <시총 하한(원)> <시작일 YYYYMMDD>
"""
import datetime as dt
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://openapi.koreainvestment.com:9443"
WORKERS = 8
MIN_GAP = 0.07            # 호출 사이 최소 간격(초) — 초당 약 14회

_gate = threading.Lock()
_last = [0.0]


def throttle():
    with _gate:
        wait = _last[0] + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


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


def token(env, tdir):
    f = Path(tdir) / "kis_token.json"
    if f.exists():
        t = json.loads(f.read_text(encoding="utf-8"))
        if t["expires"] > time.time() + 600:
            return t["token"]
    body = json.dumps({"grant_type": "client_credentials", "appkey": env["KIS_APP_KEY"],
                       "appsecret": env["KIS_APP_SECRET"]}).encode()
    req = urllib.request.Request(BASE + "/oauth2/tokenP", data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))
    f.write_text(json.dumps({"token": res["access_token"], "expires": time.time() + 80000}),
                 encoding="utf-8")
    return res["access_token"]


def page(env, tok, code, day):
    q = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                "FID_INPUT_DATE_1": day, "FID_ORG_ADJ_PRC": "",
                                "FID_ETC_CLS_CODE": "1"})
    req = urllib.request.Request(
        BASE + "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily?" + q,
        headers={"authorization": "Bearer " + tok, "appkey": env["KIS_APP_KEY"],
                 "appsecret": env["KIS_APP_SECRET"], "tr_id": "FHPTJ04160001", "custtype": "P"})
    err = ""
    for attempt in range(6):
        throttle()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8"))
            if j.get("rt_cd") == "0":
                return j.get("output2") or j.get("output") or []
            err = "rt_cd %s %s" % (j.get("rt_cd"), j.get("msg1"))
            time.sleep(1.0 * (attempt + 1))
        except urllib.error.HTTPError as e:
            err = "HTTP %s" % e.code
            if e.code in (500, 429):
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            time.sleep(1.0 * (attempt + 1))
    print("  호출 실패 %s %s — %s" % (code, day, err), flush=True)
    return None


def to_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def fetch_stock(env, tok, out, code, latest, start):
    """한 종목을 끝까지 받아 저장한다. 성공하면 True, 실패하면 False(저장하지 않음)."""
    f = out / (code + ".json")
    have = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    newest = max(have) if have else None
    if newest and newest >= latest:
        return True
    day = latest
    while True:
        got = page(env, tok, code, day)
        if got is None:
            return False
        if not got:
            break
        for r in got:
            have[r["stck_bsop_date"]] = [to_int(r.get("frgn_ntby_tr_pbmn")),
                                         to_int(r.get("orgn_ntby_tr_pbmn"))]
        oldest = min(r["stck_bsop_date"] for r in got)
        if oldest <= start or (newest and oldest <= newest):
            break
        nxt = (dt.datetime.strptime(oldest, "%Y%m%d") - dt.timedelta(days=1)).strftime("%Y%m%d")
        if nxt >= day:
            break
        day = nxt
    f.write_text(json.dumps(have), encoding="utf-8")
    return True


def main():
    env_path, krx_dir, out_dir, floor, start = sys.argv[1:6]
    env = load_env(env_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days = sorted(p for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5)
    latest = days[-1].stem
    rows = json.loads(days[-1].read_text(encoding="utf-8"))
    codes = [r["ISU_CD"] for r in rows if int(r["MKTCAP"] or 0) >= int(floor)]
    tok = token(env, out.parent / "kis")
    ok = bad = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_stock, env, tok, out, c, latest, start) for c in codes]
        for n, fu in enumerate(futs, 1):
            if fu.result():
                ok += 1
            else:
                bad += 1
            if n % 40 == 0:
                print("진행 %d/%d (%.0f초)" % (n, len(codes), time.time() - t0), flush=True)
    print("완료 %d/%d 종목, 실패 %d, 기준 %s (%.0f초)" % (ok, len(codes), bad, latest, time.time() - t0), flush=True)
    if bad:
        # 일부 실패해도 나머지로 페이지를 만든다. 실패한 종목은 저장하지 않았으므로 다음 실행이 다시 받는다.
        print("경고: 수급 %d종목은 이번에 받지 못했다(수급 열 '-')" % bad, flush=True)


main()
