"""한국투자증권 현재가 시세로 종목별 업종(bstp_kor_isnm)과 PBR·PER 을 받는다.

사용: python -I collect_kis.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <시총 하한(원)> [종목 수 제한]
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://openapi.koreainvestment.com:9443"


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
    f.write_text(json.dumps({"token": res["access_token"], "expires": time.time() + 80000}),
                 encoding="utf-8")
    return res["access_token"]


def price(env, tok, code):
    q = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    req = urllib.request.Request(
        BASE + "/uapi/domestic-stock/v1/quotations/inquire-price?" + q,
        headers={"authorization": "Bearer " + tok, "appkey": env["KIS_APP_KEY"],
                 "appsecret": env["KIS_APP_SECRET"], "tr_id": "FHKST01010100", "custtype": "P"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 500 or e.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            sys.exit("HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
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
    for n, code in enumerate(codes, 1):
        if not refresh and code in res and res[code].get("sector") is not None:
            continue
        j = price(env, tok, code)
        o = (j or {}).get("output") or {}
        if j and j.get("rt_cd") == "0":
            res[code] = {"sector": o.get("bstp_kor_isnm", "").strip(),
                         "pbr": o.get("pbr", "").strip(), "per": o.get("per", "").strip()}
        else:
            print("실패", code, (j or {}).get("msg1"), flush=True)
        time.sleep(0.12)
        if n % 50 == 0:
            f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            print("진행 %d/%d" % (n, len(codes)), flush=True)
    f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("저장 %d종목" % len(res), flush=True)


main()
