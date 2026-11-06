"""52주 신고가 정적 페이지(장 마감 후 스냅샷) 생성 — 서버 없이 GitHub Pages 에서 볼 수 있다.

실시간 화면(w52/ui/w52.html)을 그대로 쓰고, 배치 결과를 페이지 안에 심어 API 호출 없이 그린다.
입력: cache/w52/baseline.json (지표·게이트·점수), cache/w52/static_states.json (일봉으로 재현한 상태)
출력: audition-copy/w52.html
사용: python -I tools/build_52w.py <my-agent 폴더>
주문 기능은 없다.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

UI = Path(__file__).resolve().parent / "w52" / "ui" / "w52.html"
KST = timezone(timedelta(hours=9))
PLACEHOLDER = "var STATIC=null;"


def build_rows(baseline, states):
    """게이트를 통과한 종목의 화면용 행. 실시간 엔진의 rows() 와 같은 모양(live 는 없음)."""
    rows = []
    for m in baseline["stocks"]:
        if not m.get("gate_pass"):
            continue
        st = states.get("states", {}).get(m["symbol"], {})
        rows.append({
            "symbol": m["symbol"], "name": m["name"], "sector": m.get("sector"), "state": st.get("state", "NORMAL"),
            "price": m["close"], "high_52w_prev": m["high_52w_prev"], "gap_pct": round(m["gap_to_high"] * 100, 2),
            "static_score": (m.get("score") or {}).get("total"), "live": None,
            "rs1m": m.get("rs1m"), "rs3m": m.get("rs3m"), "fund_status": m.get("fund_status"), "ma5w": m.get("ma5w"),
            "avg_val20": m.get("avg_val20"), "caution": m.get("caution"), "since": st.get("since", ""),
            "breakout_level": st.get("breakout_level"), "broke_today": bool(st.get("broke_today")),
        })
    return rows


def render(baseline, states, generated_at=None):
    rows = build_rows(baseline, states)
    payload = {"mode": "static", "day": baseline["asof"], "provisional": bool(baseline.get("provisional")),
               "generated_at": generated_at or datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "rows": rows,
               "events": states.get("events", [])[-60:]}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = UI.read_text(encoding="utf-8")
    if html.count(PLACEHOLDER) != 1:
        raise RuntimeError("w52.html 에서 데이터 자리(%s)를 찾지 못했다" % PLACEHOLDER)
    return html.replace(PLACEHOLDER, "var STATIC=%s;" % data), payload


def main(root):
    root = Path(root)
    w = root / "cache" / "w52"
    baseline = json.loads((w / "baseline.json").read_text(encoding="utf-8"))
    states = json.loads((w / "static_states.json").read_text(encoding="utf-8"))
    html, payload = render(baseline, states)
    out = root / "audition-copy"
    out.mkdir(parents=True, exist_ok=True)
    (out / "w52.html").write_text(html, encoding="utf-8")
    counts = {}
    for r in payload["rows"]:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print("w52.html 생성: 기준일 %s, 게이트 통과 %d종목, 상태 %s" % (payload["day"], len(payload["rows"]), counts))


if __name__ == "__main__":
    main(sys.argv[1])
