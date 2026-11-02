"""한국투자증권 국내업종 일자별 지수로 코스피 지수 이력을 받는다(후보 폭 차트의 기준).

한 번에 100거래일씩 과거로 넘긴다. 이미 받은 구간과 겹치는 페이지까지만 받는다(증분). 첫 페이지는 항상 다시 받아
오늘 값을 덮어쓴다. 장 마감(15:40) 전이면 오늘 행은 장중 값이라 버린다.

사용: python -I collect_kis_index.py <env 경로> <출력 폴더> <시작일 YYYYMMDD>
출력: <출력 폴더>/kospi.json = {날짜: 종가지수}
"""
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://openapi.koreainvestment.com:9443"
KST = dt.timezone(dt.timedelta(hours=9))
CLOSE_HHMM = (15, 40)


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
    f.write_text(json.dumps({"token": res["access_token"], "expires": time.time() + 70000}),
                 encoding="utf-8")
    return res["access_token"]


def page(env, tok, day):
    q = urllib.parse.urlencode({"FID_PERIOD_DIV_CODE": "D", "FID_COND_MRKT_DIV_CODE": "U",
                                "FID_INPUT_ISCD": "0001", "FID_INPUT_DATE_1": day})
    req = urllib.request.Request(
        BASE + "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price?" + q,
        headers={"authorization": "Bearer " + tok, "appkey": env["KIS_APP_KEY"],
                 "appsecret": env["KIS_APP_SECRET"], "tr_id": "FHPUP02120000", "custtype": "P"})
    err = ""
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8"))
            if j.get("rt_cd") == "0":
                return j.get("output2") or j.get("output") or []
            err = "rt_cd %s %s" % (j.get("rt_cd"), j.get("msg1"))
        except urllib.error.HTTPError as e:
            err = "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:120])
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
        time.sleep(1.0 * (attempt + 1))
    sys.exit("코스피 지수 호출 실패 %s — %s" % (day, err))


def main():
    env_path, out_dir, start = sys.argv[1:4]
    env = load_env(env_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tok = token(env, out.parent / "kis")
    f = out / "kospi.json"
    have = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    newest = max(have) if have else None
    now = dt.datetime.now(KST)
    today = now.strftime("%Y%m%d")
    closed = (now.hour, now.minute) >= CLOSE_HHMM
    day = today
    while True:
        rows = page(env, tok, day)
        if not rows:
            break
        for r in rows:
            d = r.get("stck_bsop_date", "")
            try:
                v = float(r.get("bstp_nmix_prpr"))
            except (TypeError, ValueError):
                continue
            if d and (d != today or closed):
                have[d] = v
        oldest = min(r["stck_bsop_date"] for r in rows if r.get("stck_bsop_date"))
        if oldest <= start or (newest and oldest <= newest):
            break
        nxt = (dt.datetime.strptime(oldest, "%Y%m%d") - dt.timedelta(days=1)).strftime("%Y%m%d")
        if nxt >= day:
            break
        day = nxt
        time.sleep(0.2)
    f.write_text(json.dumps(dict(sorted(have.items()))), encoding="utf-8")
    ks = sorted(have)
    print("코스피 지수 %d일 (%s ~ %s)" % (len(ks), ks[0], ks[-1]), flush=True)


main()
