"""KRX Open API 에서 2022-01 ~ 2025-03 일별매매정보를 받아 «현재 유니버스 종목만» 압축해 저장한다.

원본 페이지의 고점대비는 «2022년 이후 고점»이고 후보 폭의 평상 범위도 2022년 이후 기준이다. 이 구간을 맞추기 위해 쓴다.
하루치 전종목(약 0.7MB)을 그대로 두면 800일에 500MB 이상이라, 최신일 시총 2000억 이상 종목만 [종가, 상장주식수, 거래량]으로 남긴다.
이 구간은 바뀌지 않으므로 한 번 받으면 다음 실행은 전부 건너뛴다.

빈 응답은 휴장일 수도, KRX 의 일시적 공백일 수도 있다. 코스피 지수 일별 자료(거래일 달력)에 있는 날이 비었으면
저장하지 않고 다음 실행이 다시 받는다. 달력에 없는 날의 빈 응답은 휴장으로 보고 빈 파일로 저장한다.

사용: python -I collect_krx_history.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <코스피 지수 json> <시작일> <종료일> [시총 하한(원)]
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

ENDPOINTS = (("KOSPI", "stk_bydd_trd"), ("KOSDAQ", "ksq_bydd_trd"))
WORKERS = 4
MIN_GAP = 0.08
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


def fetch(key, endpoint, day):
    url = "https://data-dbg.krx.co.kr/svc/apis/sto/%s?%s" % (
        endpoint, urllib.parse.urlencode({"basDd": day}))
    req = urllib.request.Request(url, headers={"AUTH_KEY": key})
    err = ""
    for attempt in range(4):
        throttle()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8")).get("OutBlock_1", [])
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit("인증 실패 HTTP %s (%s)" % (e.code, endpoint))
            err = "HTTP %s" % e.code
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
        time.sleep(2 * (attempt + 1))
    print("  호출 실패 %s %s — %s" % (endpoint, day, err), flush=True)
    return None


def main():
    env_path, krx_dir, out_dir, index_json, start, end = sys.argv[1:7]
    floor = int(sys.argv[7]) if len(sys.argv) > 7 else 200000000000
    key = load_env(env_path)["KRX_API_KEY"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    days = sorted(p for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5 and p.stem >= "20250401")
    last_rows = json.loads(days[-1].read_text(encoding="utf-8"))
    universe = {r["ISU_CD"] for r in last_rows if int(r["MKTCAP"] or 0) >= floor}
    cal = set()
    ip = Path(index_json)
    if ip.exists():
        cal = set(json.loads(ip.read_text(encoding="utf-8")))

    d0 = dt.datetime.strptime(start, "%Y%m%d").date()
    d1 = dt.datetime.strptime(end, "%Y%m%d").date()
    todo, d = [], d0
    while d <= d1:
        day = d.strftime("%Y%m%d")
        d += dt.timedelta(days=1)
        if dt.datetime.strptime(day, "%Y%m%d").weekday() >= 5 or (out / (day + ".json")).exists():
            continue
        todo.append(day)
    print("유니버스 %d종목, 받을 날 %d일" % (len(universe), len(todo)), flush=True)
    if not todo:
        return

    stats = {"trading": 0, "holiday": 0, "unsure": 0}
    done = [0]
    lock = threading.Lock()

    def one(day):
        rows, bad = [], False
        for _, ep in ENDPOINTS:
            r = fetch(key, ep, day)
            if r is None:
                bad = True
            else:
                rows += r
        with lock:
            done[0] += 1
            if done[0] % 100 == 0:
                print("진행 %d/%d (%s)" % (done[0], len(todo), day), flush=True)
        if bad:
            return
        if not rows:
            if day in cal:                       # 달력에는 거래일인데 KRX 가 비었다 — 저장하지 않는다
                with lock:
                    stats["unsure"] += 1
                print("  경고: %s 는 거래일인데 KRX 가 비어 있다(저장 안 함)" % day, flush=True)
                return
            with lock:
                stats["holiday"] += 1
            (out / (day + ".json")).write_text("{}", encoding="utf-8")
            return
        comp = {}
        for r in rows:
            c = r.get("ISU_CD")
            if c in universe:
                try:
                    comp[c] = [int(r["TDD_CLSPRC"]), int(r["LIST_SHRS"] or 0), int(r["ACC_TRDVOL"] or 0)]
                except (TypeError, ValueError):
                    pass
        with lock:
            stats["trading"] += 1
        (out / (day + ".json")).write_text(json.dumps(comp, separators=(",", ":")), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(one, todo))
    print("완료: 거래일 %d, 휴장 %d, 확인 필요 %d" % (stats["trading"], stats["holiday"], stats["unsure"]), flush=True)


main()
