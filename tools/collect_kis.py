"""한국투자증권 현재가 시세로 종목별 업종(bstp_kor_isnm)과 PBR·PER 을 받는다.

종목들을 여러 스레드로 동시에 받되, 전체 호출 간격은 하나의 자물쇠로 묶어 초당 한도(약 20회)를 넘지 않게 한다.

사용: python -I collect_kis.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <시총 하한(원)> [종목 수 제한] [refresh]
"""
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


def token(env, out):
    f = out / "kis_token.json"
    if f.exists():
        t = json.loads(f.read_text(encoding="utf-8"))
        if t["expires"] > time.time() + 600:
            return t["token"]
    body = json.dumps({"grant_type": "client_credentials", "appkey": env["KIS_APP_KEY"],
                       "appsecret": env["KIS_APP_SECRET"]}).encode()
    req = urllib.request.Request(BASE + "/oauth2/tokenP", data=body,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit("토큰 발급 실패 HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
    f.write_text(json.dumps({"token": res["access_token"], "expires": time.time() + 70000}),
                 encoding="utf-8")
    return res["access_token"]


def price(env, tok, code):
    q = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    req = urllib.request.Request(
        BASE + "/uapi/domestic-stock/v1/quotations/inquire-price?" + q,
        headers={"authorization": "Bearer " + tok, "appkey": env["KIS_APP_KEY"],
                 "appsecret": env["KIS_APP_SECRET"], "tr_id": "FHKST01010100", "custtype": "P"})
    err = ""
    for attempt in range(5):
        throttle()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:100])
            if e.code in (500, 429):
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            time.sleep(1.5 * (attempt + 1))
    print("  호출 실패 %s — %s" % (code, err), flush=True)
    return None


def main():
    env_path, krx_dir, out_dir, floor = sys.argv[1:5]
    limit = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].isdigit() else None
    refresh = len(sys.argv) > 6 and sys.argv[6] == "refresh"     # PBR 은 매일 바뀌므로 전체를 다시 받는다
    env = load_env(env_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days = sorted(p for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5)
    rows = json.loads(days[-1].read_text(encoding="utf-8"))
    codes = [r["ISU_CD"] for r in rows if int(r["MKTCAP"] or 0) >= int(floor)]
    if limit:
        codes = codes[:limit]
    tok = token(env, out)
    f = out / "kis.json"
    res = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    todo = [c for c in codes if refresh or c not in res or res[c].get("sector") is None]

    def one(code):
        j = price(env, tok, code)
        o = (j or {}).get("output") or {}
        if j and j.get("rt_cd") == "0":
            rec = {"sector": o.get("bstp_kor_isnm", "").strip(),
                   "pbr": o.get("pbr", "").strip(), "per": o.get("per", "").strip()}
            # 52주 신고가 매매용: 종목 상태 플래그(관리·경고·정지·단기과열·정리매매)와 KIS 가 계산한 52주 고가(대조 검증용)
            for k in ("iscd_stat_cls_code", "temp_stop_yn", "mrkt_warn_cls_code", "invt_caful_yn", "short_over_yn",
                      "mang_issu_cls_code", "sltr_yn", "w52_hgpr", "w52_hgpr_date"):
                rec[k] = (o.get(k) or "").strip()
            return code, rec
        if j:
            print("  실패", code, j.get("msg1"), flush=True)
        return code, None

    t0 = time.time()
    bad = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for n, (code, val) in enumerate(ex.map(one, todo), 1):
            if val is None:
                bad += 1
            else:
                res[code] = val          # 결과는 주 스레드에서만 모은다
            if n % 100 == 0:
                print("진행 %d/%d (%.0f초)" % (n, len(todo), time.time() - t0), flush=True)
    f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("저장 %d종목 (이번에 %d종목 받음, 실패 %d, %.0f초)" % (len(res), len(todo) - bad, bad, time.time() - t0), flush=True)


main()
