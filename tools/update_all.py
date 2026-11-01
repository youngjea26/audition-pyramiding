"""데이터를 모두 갱신하고 페이지를 다시 만든다. 로컬과 GitHub Actions 에서 같은 방식으로 돈다.

사용: python tools/update_all.py <my-agent 폴더>
키는 <폴더>/.env 또는 환경변수(KRX_API_KEY, DART_API_KEY, KIS_APP_KEY, KIS_APP_SECRET)에서 읽는다.
이미 받은 날짜·종목은 건너뛰므로 두 번째 실행부터는 최근 며칠분만 받는다.
"""
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
TOOLS = ROOT / "tools"
ENV = str(ROOT / ".env")
KRX = str(ROOT / "cache" / "krx")
DART = str(ROOT / "cache" / "dart")
KIS = str(ROOT / "cache" / "kis")
FLOW = str(ROOT / "cache" / "kis_flow")
FLOOR = "500000000000"
START = "20250401"

today = dt.date.today()
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


for sub in ("krx", "dart", "kis", "kis_flow"):
    (ROOT / "cache" / sub).mkdir(parents=True, exist_ok=True)

run("collect_krx.py", ENV, KRX, START, today.strftime("%Y%m%d"))
run("collect_krx.py", ENV, KRX, f"{annual_year - 1}1220", f"{annual_year - 1}1231")   # 재무 크로스용 전전년 연말 시총
run("collect_dart.py", ENV, KRX, DART, FLOOR, report_year)
run("collect_dart_annual.py", ENV, KRX, DART, FLOOR, annual_year)
run("collect_kis.py", ENV, KRX, KIS, FLOOR, "all", "refresh")
run("collect_kis_flow.py", ENV, KRX, FLOW, FLOOR, START)
run("build_audition.py", ROOT, FLOOR)
print("완료", flush=True)

