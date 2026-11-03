"""데이터를 모두 갱신하고 페이지를 다시 만든다. 로컬과 GitHub Actions 에서 같은 방식으로 돈다.

사용: python tools/update_all.py <my-agent 폴더>
키는 <폴더>/.env 또는 환경변수(KRX_API_KEY, DART_API_KEY, KIS_APP_KEY, KIS_APP_SECRET)에서 읽는다.
이미 받은 날짜·종목은 건너뛰므로 두 번째 실행부터는 최근 며칠분만 받는다.

당일 저녁 갱신: KRX Open API 는 전 거래일 자료를 다음 영업일에야 올린다. 그래서 KRX 에 아직 없는 날(보통 오늘)은
한국투자증권 일자별 시세·투자자 매매동향·코스피 지수로 채우고, 다음 영업일에 KRX 확정 자료로 바꾼다.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
TOOLS = ROOT / "tools"
ENV = str(ROOT / ".env")
KRX = ROOT / "cache" / "krx"
DART = str(ROOT / "cache" / "dart")
KIS = str(ROOT / "cache" / "kis")
KIS_DAILY = str(ROOT / "cache" / "kis_daily")
KIS_INDEX = ROOT / "cache" / "kis_index"
FLOW = str(ROOT / "cache" / "kis_flow")
FLOOR = "500000000000"         # 화면에 올리는 기준: 시총 5000억
BUFFER = "400000000000"        # 수집은 4000억부터 — 당일 5000억을 넘어 새로 들어오는 종목을 놓치지 않는다
START = "20250401"
HIST_START = "20220103"       # 원본이 쓰는 «2022년 이후» 구간 — 고점대비·후보 폭 평상 범위
HIST_END = "20250331"
HIST = ROOT / "cache" / "hist"

KST = dt.timezone(dt.timedelta(hours=9))
today = dt.datetime.now(KST).date()
# 확정 사업보고서 연도: 3월 말에 나오므로 4월부터 전년도, 그 전엔 전전년도
annual_year = today.year - 1 if today.month >= 4 else today.year - 2
# 최신 분기 보고서 연도: 1Q 가 5월 중순에 나오므로 5월부터 올해, 그 전엔 전년도 3분기
report_year = today.year if today.month >= 5 else today.year - 1


def run(script, *args):
    cmd = [sys.executable, str(TOOLS / script), *map(str, args)]
    print("▶", script, flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"{script} 실패 (종료 코드 {r.returncode})")


def nonempty(day):
    p = KRX / (day + ".json")
    return p.exists() and p.stat().st_size > 5


def reconcile_krx():
    """KRX 가 빈 응답을 줬던 날을 코스피 지수 일별 자료(거래일 달력)와 맞춰 본다.

    지수에는 있는데 KRX 캐시가 비어 있으면 누락이다. 지워서 다시 받는다.
    가장 최근 거래일 3개는 KRX 미게시가 정상이라 검사에서 뺀다.
    """
    f = KIS_INDEX / "kospi.json"
    if not f.exists():
        return
    dates = sorted(d for d in json.loads(f.read_text(encoding="utf-8")) if d >= START)
    if len(dates) < 4:
        return
    missing = [d for d in dates[:-3] if not nonempty(d)]
    if not missing:
        print("KRX 교차 검증: 누락된 거래일 없음", flush=True)
        return
    print("KRX 교차 검증: 지수에는 있는데 KRX 가 비어 있는 날", missing, flush=True)
    for d in missing:
        (KRX / (d + ".json")).unlink(missing_ok=True)
    run("collect_krx.py", ENV, KRX, missing[0], missing[-1])
    still = [d for d in missing if not nonempty(d)]
    if still:
        print("경고: 다시 받아도 KRX 가 비어 있는 거래일", still, flush=True)


def universe_codes(floor):
    days = sorted(p for p in KRX.glob("*.json") if p.stat().st_size > 5)
    rows = json.loads(days[-1].read_text(encoding="utf-8"))
    return {r["ISU_CD"] for r in rows if int(r["MKTCAP"] or 0) >= int(floor)}


def dart_due():
    """재무(반기·분기·사업보고서)는 분기·연 단위로만 바뀌므로 매일 받지 않는다(DART 는 밤에 느려 수십 배 걸리기도 한다).

    처음이거나, 유니버스에 재무가 없는 새 종목이 들어왔거나, 마지막으로 받은 지 7일이 지났을 때만 다시 받는다.
    이유를 돌려주고, 받을 필요가 없으면 None 을 돌려준다.
    """
    fin, ann = Path(DART) / "fin.json", Path(DART) / "annual.json"
    if not fin.exists() or not ann.exists():
        return "처음 받는다"
    if os.environ.get("DART_MODE", "auto") == "skip":      # 저녁 실행: 재무는 아침 실행이 갱신한다
        return None
    age = (time.time() - min(fin.stat().st_mtime, ann.stat().st_mtime)) / 86400
    if age >= 7:
        return "마지막으로 받은 지 %.0f일" % age
    j = json.loads(fin.read_text(encoding="utf-8"))
    no_fin = set(j.get("no_fin", []))
    uni = universe_codes(BUFFER)
    have = set(j.get("fin", {})) | no_fin | {c for c in uni if (c[:-1] + "0") in no_fin}
    missing = uni - have
    if missing:
        return "재무가 없는 새 종목 %d개" % len(missing)
    return None


for sub in ("krx", "hist", "dart", "kis", "kis_daily", "kis_index", "kis_flow"):
    (ROOT / "cache" / sub).mkdir(parents=True, exist_ok=True)

run("collect_kis_index.py", ENV, KIS_INDEX, HIST_START)
run("collect_krx.py", ENV, KRX, START, today.strftime("%Y%m%d"))
run("collect_krx.py", ENV, KRX, f"{annual_year - 1}1220", f"{annual_year - 1}1231")   # 재무 크로스용 전전년 연말 시총
reconcile_krx()
run("collect_krx_history.py", ENV, KRX, HIST, KIS_INDEX / "kospi.json", HIST_START, HIST_END, "200000000000")
why = dart_due()
if why:
    print("재무 갱신:", why, flush=True)
    run("collect_dart.py", ENV, KRX, DART, BUFFER, report_year)
    run("collect_dart_annual.py", ENV, KRX, DART, BUFFER, annual_year)
else:
    print("재무 갱신 건너뜀 (7일 이내에 받았고 새 종목도 없다)", flush=True)
run("collect_kis.py", ENV, KRX, KIS, BUFFER, "all", "refresh")
run("collect_kis_daily.py", ENV, KRX, KIS_DAILY, BUFFER)
run("collect_kis_flow.py", ENV, KRX, FLOW, BUFFER, START)
run("build_audition.py", ROOT, FLOOR)
print("완료", flush=True)
