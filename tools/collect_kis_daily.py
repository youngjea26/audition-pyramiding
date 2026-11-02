"""KRX 확정 자료가 아직 없는 최근 거래일(보통 오늘)을 한국투자증권 일자별 시세로 채운다.

KRX Open API 는 전 거래일 자료를 다음 영업일에야 올린다. 장 마감 직후(저녁)에 갱신하려면 당일치는 한국투자증권에서
받아야 한다. 종목마다 최근 30거래일 일자별 시세(종가·거래량·등락률, 수정주가 미반영)에서 «KRX 마지막 날 이후» 날짜만 남긴다.
다음 영업일에 KRX 확정 자료가 올라오면 build_audition.py 는 KRX 쪽을 쓰고 이 파일은 무시한다.
장 마감(15:40) 전이면 오늘 행은 장중 값이라 버린다.

사용: python -I collect_kis_daily.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <시총 하한(원)>
출력: <출력 폴더>/<종목코드>.json = {날짜: [종가, 거래량, 등락률]} 와 _meta.json
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
MIN_GAP = 0.07
KST = dt.timezone(dt.timedelta(hours=9))
CLOSE_HHMM = (15, 40)

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
    f.write_text(json.dumps({"token": res["access_token"], "expires": time.time() + 70000}),
                 encoding="utf-8")
    return res["access_token"]


def daily(env, tok, code):
    q = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "1"})
    req = urllib.request.Request(
        BASE + "/uapi/domestic-stock/v1/quotations/inquire-daily-price?" + q,
        headers={"authorization": "Bearer " + tok, "appkey": env["KIS_APP_KEY"],
                 "appsecret": env["KIS_APP_SECRET"], "tr_id": "FHKST01010400", "custtype": "P"})
    err = ""
    for attempt in range(6):
        throttle()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8"))
            if j.get("rt_cd") == "0":
                return j.get("output") or j.get("output2") or []
            err = "rt_cd %s %s" % (j.get("rt_cd"), j.get("msg1"))
            time.sleep(1.0 * (attempt + 1))
        except urllib.error.HTTPError as e:
            err = "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:120])
            if e.code in (500, 429):
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            time.sleep(1.0 * (attempt + 1))
    print("  호출 실패 %s — %s" % (code, err), flush=True)
    return None


def num(s, cast):
    try:
        return cast(s)
    except (TypeError, ValueError):
        return None


def main():
    env_path, krx_dir, out_dir, floor = sys.argv[1:5]
    env = load_env(env_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days = sorted(p for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5 and p.stem >= "20250401")
    base = days[-1].stem
    rows = json.loads(days[-1].read_text(encoding="utf-8"))
    codes = [r["ISU_CD"] for r in rows if int(r["MKTCAP"] or 0) >= int(floor)]
    tok = token(env, out.parent / "kis")
    for p in out.glob("*.json"):
        p.unlink()

    now = dt.datetime.now(KST)
    today = now.strftime("%Y%m%d")
    closed = (now.hour, now.minute) >= CLOSE_HHMM

    def keep(rs):
        d = {}
        for r in rs:
            day = r.get("stck_bsop_date", "")
            c, v, f = num(r.get("stck_clpr"), int), num(r.get("acml_vol"), int), num(r.get("prdy_ctrt"), float)
            if day > base and c and (day != today or closed):
                d[day] = [c, v or 0, f if f is not None else 0.0]
        return d

    ref = daily(env, tok, "005930")
    gap = sorted(keep(ref or []).keys())
    meta = {"base": base, "gap": gap, "universe": len(codes), "stocks": 0, "built_at": now.isoformat()}
    if not gap:
        (out / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        print("KRX 마지막 날(%s) 이후 채울 거래일 없음" % base, flush=True)
        return

    ok = 0

    def one(code):
        rs = daily(env, tok, code)
        if rs is None:
            return False
        d = {k: v for k, v in keep(rs).items() if k in gap}
        if d:
            (out / (code + ".json")).write_text(json.dumps(d), encoding="utf-8")
        return True

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(one, codes))
    ok = sum(1 for x in res if x)
    meta["stocks"] = ok
    (out / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print("채운 날 %s (KRX 마지막 날 %s), 종목 %d/%d" % (gap, base, ok, len(codes)), flush=True)
    if ok < len(codes):
        print("경고: %d종목은 받지 못했다(그날 표에서 빠진다)" % (len(codes) - ok), flush=True)


main()
