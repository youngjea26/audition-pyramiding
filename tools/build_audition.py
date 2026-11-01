"""오디션 피라미딩 페이지 복제본 생성기.

원본 HTML(저장본)을 템플릿으로 쓰고, KRX·DART·KIS 캐시로 종목 행·종가 이력·차트·요약 문구를 다시 채운다.
사용: python -I build_audition.py <my-agent 폴더> <시총 하한(원)>
출력: <my-agent>/audition-copy/index.html + assets/
"""
import html
import json
import shutil
import statistics
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
FLOOR = int(sys.argv[2])
FLOOR_TXT = "5000억"
GZ = "20260729"
SRC = ROOT / "오디션 피라미딩.html"
OUT = ROOT / "audition-copy"
B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


# ───────────────────────── 데이터 적재
def load_krx():
    data = {}
    for p in sorted((ROOT / "cache" / "krx").glob("*.json")):
        rows = json.loads(p.read_text(encoding="utf-8"))
        if rows and p.stem >= "20250401":
            data[p.stem] = {r["ISU_CD"]: r for r in rows}
    return data


krx = load_krx()
RD = sorted(krx)
N = len(RD)
LI = N - 1
GI = RD.index(GZ)
ASOF = RD[-1]
fin_all = json.loads((ROOT / "cache" / "dart" / "fin.json").read_text(encoding="utf-8"))["fin"]
kis = json.loads((ROOT / "cache" / "kis" / "kis.json").read_text(encoding="utf-8"))
codes = [c for c, r in krx[ASOF].items() if int(r["MKTCAP"] or 0) >= FLOOR]


def b36(v):
    if v == 0:
        return "0"
    neg, v, s = v < 0, abs(v), ""
    while v:
        v, r = divmod(v, 36)
        s = B36[r] + s
    return "-" + s if neg else s


def encode(arr):
    out, prev = [], 0
    for x in arr:
        if x is None:
            out.append("")
        else:
            out.append(b36(x - prev))
            prev = x
    return ",".join(out)


def build_series(code):
    cl, sh, vo = [None] * N, [None] * N, [0] * N
    for i, d in enumerate(RD):
        r = krx[d].get(code)
        if r:
            c = int(r["TDD_CLSPRC"] or 0)
            if c > 0:
                cl[i], sh[i], vo[i] = c, int(r["LIST_SHRS"] or 0), int(r["ACC_TRDVOL"] or 0)
    adj = [float(x) if x else None for x in cl]
    last = None
    for i in range(N):
        if cl[i] is None:
            continue
        if last is not None and sh[i] and sh[last]:
            s, p = sh[i] / sh[last], cl[i] / cl[last]
            if abs(s - 1) > 0.25 and abs(p * s - 1) < 0.12:   # 액면분할·병합·무상증자 보정
                for k in range(i):
                    if adj[k] is not None:
                        adj[k] /= s
        last = i
    return [round(x) if x else None for x in adj], cl, vo


S = {}
for c in codes:
    adj, raw, vol = build_series(c)
    S[c] = {"adj": adj, "raw": raw, "vol": vol}


def fmt_cap(v):
    return f"{round(v / 1e8):,}억" if v < 1e12 else f"{v / 1e12:.1f}조"


def pct(v):
    return ("+" if v > 0 else "") + f"{v:.1f}%"


def esc(s):
    return html.escape(s, quote=True)


# ───────────────────────── 종목별 지표
FIN_WORDS = ("금융", "증권", "보험", "은행")
annual = json.loads((ROOT / "cache" / "dart" / "annual.json").read_text(encoding="utf-8"))
ye_cap = {y: v["cap"] for y, v in annual.pop("_cap").items()}
flows = {}
if (ROOT / "cache" / "kis_flow").exists():
    for p in (ROOT / "cache" / "kis_flow").glob("*.json"):
        flows[p.stem] = json.loads(p.read_text(encoding="utf-8"))


def grade_of(opm, roe, ni, op):
    if (ni is not None and ni < 0) or (op is not None and op < 0):
        return None
    if opm is None and roe is None:
        return None
    if opm is not None and roe is not None and opm >= 40 and roe >= 20:
        return 3
    if roe is not None and roe >= 10 and (opm is None or opm >= 20):
        return 2
    return 1


def annual_info(code):
    """사업보고서 3년치(당기·전기·전전기)에서 연도별 OPM·ROE·등급을 만든다. 우선주는 보통주 재무를 쓴다."""
    base_code = code[:-1] + "0"
    key = base_code if base_code in annual else (code if code in annual else None)
    if not key:
        return None
    a = annual[key]
    rows = []
    for k in range(3):
        rev, op, ni, eq = (a[x][k] for x in ("rev", "op", "ni", "eq"))
        opm = op / rev * 100 if rev and op is not None else None
        roe = ni / eq * 100 if eq and eq > 0 and ni is not None else None
        rows.append(dict(rev=rev, op=op, ni=ni, eq=eq, opm=opm, roe=roe, g=grade_of(opm, roe, ni, op)))
    return {"pref": key != code, "years": a["y"], "rows": rows}


stocks = []
for c in codes:
    r = krx[ASOF][c]
    a, vol = S[c]["adj"], S[c]["vol"]
    valid = [x for x in a if x]
    last = a[LI]
    ma = sum(valid[-240:]) / 240 if len(valid) >= 240 else None
    above = "" if ma is None else ("1" if last > ma else "0")
    hi = (last / max(valid) - 1) * 100
    vv = [v for v, x in zip(vol, a) if x]
    vr = ""
    if len(vv) >= 50 and sum(vv[-50:]):
        vr = (sum(vv[-5:]) / 5) / (sum(vv[-50:]) / 50)
    w1 = (last / a[LI - 5] - 1) * 100 if a[LI - 5] else None
    g0, g1 = a[GI], last
    ret = (g1 / g0 - 1) * 100 if g0 and g1 else None
    sector = (kis.get(c, {}).get("sector") or "").strip()
    is_fin = any(w in sector for w in FIN_WORDS)
    f = fin_all.get(c)
    pbr = None
    try:
        pbr = float(kis.get(c, {}).get("pbr") or 0) or None
    except ValueError:
        pass
    opm = roe = debt = None
    if f:
        opm, roe, debt = f["opm"], f["roe"], f["debt"]
    reasons, grade, persist, gnote = [], None, False, ""
    ai = annual_info(c)
    if f:
        loss = (opm is not None and opm < 0) or (roe is not None and roe < 0)
        if loss:
            reasons.append("적자")
        if roe is None and f.get("equity") is not None and f["equity"] <= 0:
            reasons.append("자본잠식")
        if not is_fin and debt is not None and debt >= 200:
            reasons.append(f"부채비율 {debt}%")
    if ai and not is_fin:
        rv = [x["rev"] for x in ai["rows"]]
        if None not in rv and rv[0] > rv[1] > rv[2]:
            reasons.append("매출 2년 연속 감소")
    if not reasons:
        r0, r1, r2 = ai["rows"] if ai else (None, None, None)
        if ai and r2["g"]:
            grade = r2["g"]
            persist = bool(r0["g"] and r0["g"] == r1["g"] == r2["g"])
            parts = ["연간 기준"] + (["3년 지속"] if persist else [])
            if r1["roe"] is not None and r2["roe"] is not None:
                parts.append("ROE " + ("↑" if r2["roe"] > r1["roe"] else "↓"))
            if r1["rev"] and r2["rev"]:
                parts.append("매출 " + ("↑" if r2["rev"] > r1["rev"] else "↓"))
            gnote = " · ".join(parts)
        elif f and (roe is not None or opm is not None):
            grade = grade_of(opm, roe, None, None)
            gnote = f'{f.get("보고서", "")} 기준 (사업보고서 없음)'
        if grade and not is_fin and debt is not None and debt >= 100 and grade > 1:
            grade = 1
            gnote += f" · 부채비율 {debt}% (100% 이상이라 2등급으로 내림)"
    # 재무 크로스: ROE 가 늘고 PER 이 줄었나 (최근 두 해, 사업보고서 기준)
    vc, vct, vcw = "-", "", ""
    if ai and not ai["pref"]:
        y1, y2 = ai["years"][1], ai["years"][2]
        r1, r2 = ai["rows"][1], ai["rows"][2]
        cap1, cap2 = ye_cap.get(str(y1), {}).get(c), ye_cap.get(str(y2), {}).get(c)
        if cap1 and cap2 and r1["ni"] and r2["ni"] and r1["ni"] > 0 and r2["ni"] > 0 \
                and r1["roe"] is not None and r2["roe"] is not None:
            up, down = r2["roe"] > r1["roe"], (cap2 / r2["ni"]) < (cap1 / r1["ni"])
            vc = "1" if up and down else "0"
            vct = f"ROE {'증가' if up else '감소'} · PER {'감소' if down else '증가'} ({y1}→{y2})"
            vcw = "" if vc == "1" else "ROE 와 PER 이 함께 좋아지지 않았다"
    stocks.append(dict(
        code=c, name=r["ISU_NM"].strip(), mkt="코스피" if r["MKT"] == "KOSPI" else "코스닥",
        sector=sector, px=int(r["TDD_CLSPRC"]), cap=int(r["MKTCAP"]), fluc=float(r["FLUC_RT"] or 0),
        ret=ret, w1=w1, above=above, hi=hi, vr=vr, opm=opm, roe=roe, debt=debt, pbr=pbr,
        fin=f, is_fin=is_fin, reasons=reasons, grade=grade, persist=persist, gnote=gnote,
        vc=vc, vct=vct, vcw=vcw, adj=a))

by_ret = sorted([s for s in stocks if s["ret"] is not None], key=lambda s: -s["ret"])
base = [s for s in stocks if s["ret"] is not None]
survivors = [s for s in base if s["ret"] > 0]
cut = [s for s in stocks if s["reasons"]]
cut_codes = {s["code"] for s in cut}
cut_pos = sorted([s for s in cut if s["ret"] is not None and s["ret"] > 0], key=lambda s: -s["ret"])
passed = [s for s in stocks if s["code"] not in cut_codes]
passed_sorted = sorted(passed, key=lambda s: (s["ret"] is None, -(s["ret"] or 0)))


# ───────────────────────── HTML 조각
GRADE = {3: ("gS", "특등급"), 2: ("g1", "1등급"), 1: ("g2", "2등급")}


def num_td(v, text, cls=""):
    return f'<td class="n{(" " + cls) if cls else ""}" data-v="{v}">{text}</td>'


def row(s, rank, why=None):
    pos = lambda v: "pos" if v > 0 else ("neg" if v < 0 else "")
    ret, w1 = s["ret"], s["w1"]
    r_cell = ('<td class="n r-cell" data-v="-9999">-</td>' if ret is None else
              f'<td class="n r-cell {pos(ret)}" data-v="{ret}"><b>{pct(ret)}</b></td>')
    w_cell = ('<td class="n w1-cell" data-v="-9999">-</td>' if w1 is None else
              f'<td class="n w1-cell {pos(w1)}" data-v="{w1}">{pct(w1)}</td>')
    ma = ('<td class="c" data-v="-1">-</td>' if s["above"] == "" else
          ('<td class="c" data-v="1"><span class="ok">●</span></td>' if s["above"] == "1"
           else '<td class="c" data-v="0"><span class="no">○</span></td>'))
    p = "-" if s["above"] == "" else ("1" if s["above"] == "1" and s["hi"] > -10 else "0")
    na = '<td class="n" data-v="-9999">-</td>'
    opm = na if s["opm"] is None else num_td(s["opm"], pct(s["opm"]))
    roe = na if s["roe"] is None else num_td(s["roe"], pct(s["roe"]))
    pbr = na if s["pbr"] is None else num_td(s["pbr"], f'{s["pbr"]:.2f}')
    vr = na if s["vr"] == "" else num_td(round(s["vr"], 2), f'{s["vr"]:.2f}')
    if s["grade"]:
        gc, gt = GRADE[s["grade"]]
        grade = (f'<td class="c" data-v="{s["grade"]}"><span class="grd {gc}" title="{esc(s["gnote"])}">'
                 f'{gt}{"★" if s["persist"] else ""}</span></td>')
    else:
        grade = '<td class="c" data-v="0">-</td>'
    debt = ('<td class="n" data-v="-9999">-</td>' if s["debt"] is None or s["is_fin"]
            else num_td(s["debt"], f'{s["debt"]}%'))
    gname = GRADE[s["grade"]][1] if s["grade"] else ""
    attrs = (f'data-mkt="{s["mkt"]}" data-c="{s["code"]}" data-nm="{esc(s["name"])}" '
             f'data-capt="{fmt_cap(s["cap"])}" data-cap="{s["cap"]}" '
             f'data-w1="{"" if w1 is None else round(w1, 4)}" data-above="{s["above"]}" '
             f'data-hi="{round(s["hi"], 4)}" data-vr="{"" if s["vr"] == "" else round(s["vr"], 4)}" '
             f'data-grade="{gname}" data-persist="{"1" if s["persist"] else ""}" '
             f'data-opm="{"" if s["opm"] is None else s["opm"]}" '
             f'data-debt="{"" if s["debt"] is None or s["is_fin"] else s["debt"]}" data-p="{p}" data-vc="{s["vc"]}"'
             + (f' data-vct="{esc(s["vct"])}" data-vcw="{esc(s["vcw"])}"' if s["vct"] else ""))
    mk = "mk1" if s["mkt"] == "코스피" else "mk2"
    fl = s["fluc"]
    tds = (f'<td class="c rk" data-v="{rank}">{rank or ""}</td>'
           f'<td class="c" data-v="{s["code"]}">{s["code"]}</td>'
           f'<td class="nm" data-v="{esc(s["name"])}">{esc(s["name"])}</td>'
           f'<td class="c" data-v="{s["mkt"]}"><span class="mktb {mk}">{s["mkt"]}</span></td>'
           f'<td class="sec" data-v="{esc(s["sector"] or "-")}">{esc(s["sector"] or "-")}</td>'
           f'<td class="n px-cell" data-v="{s["px"]}">{s["px"]:,}</td>'
           f'<td class="n cap-cell" data-v="{s["cap"]}">{fmt_cap(s["cap"])}</td>'
           f'<td class="n {"pos" if fl > 0 else ("neg" if fl < 0 else "")}" data-v="{fl}">{pct(fl)}</td>'
           + r_cell + w_cell
           + '<td class="c d-cell" data-v="-1">-</td><td class="c mc" data-v="-1">-</td>'
           + ma
           + num_td(round(s["hi"], 2), pct(s["hi"])) + vr + opm + roe + pbr + grade + debt)
    if why is not None:
        tds += f'<td class="why">{esc(why)}</td>'
    return f"<tr {attrs}>{tds}</tr>"


# ───────────────────────── 차트 계열
univ0 = [s for s in stocks if s["adj"][GI]]
surv_cnt, surv_rate = [], []
for t in range(GI, N):
    k = sum(1 for s in univ0 if s["adj"][t] and s["adj"][t] > s["adj"][GI])
    surv_cnt.append(k)
    surv_rate.append(round(k / len(univ0) * 100, 1))
labels_s = [f"{int(RD[t][4:6])}/{int(RD[t][6:8])}" for t in range(GI, N)]

# 코스피 시총가중 지수(직접 계산) — 코스피 지수 API 권한이 없어 대신 쓴다
kidx = [1.0] * N
for t in range(1, N):
    a, b = krx[RD[t - 1]], krx[RD[t]]
    num = den = 0
    for c, r in b.items():
        if r["MKT"] != "KOSPI" or c not in a:
            continue
        c1, c0 = int(r["MKTCAP"] or 0), int(a[c]["MKTCAP"] or 0)
        if c0 > 0 and c1 > 0 and abs(c1 / c0 - 1) <= 0.31:
            num += c1
            den += c0
    kidx[t] = kidx[t - 1] * (num / den if den else 1)
W = 60
breadth, blabels = [], []
for t in range(W, N):
    kr = kidx[t] / kidx[t - W] - 1
    tot = win = 0
    for s in stocks:
        a = s["adj"]
        if a[t] and a[t - W]:
            tot += 1
            win += (a[t] / a[t - W] - 1) > kr
    breadth.append(round(win / tot * 100, 1))
    blabels.append(f"{RD[t][4:6]}-{RD[t][6:8]}")
b_now = breadth[-1]
b_med = statistics.median(breadth)
qs = statistics.quantiles(breadth, n=20)
b_narrow, b_ext = statistics.quantiles(breadth, n=4)[0], statistics.quantiles(breadth, n=10)[0]
b_wide = statistics.quantiles(breadth, n=4)[2]
b_word = ("극단적으로 좁은" if b_now <= b_ext else "좁은" if b_now <= b_narrow
          else "넓은" if b_now >= b_wide else "보통")

# 그라운드 제로 거래량
tv = []
for d in RD:
    tv.append(sum(int(r["ACC_TRDVOL"] or 0) for r in krx[d].values()))
prev20 = tv[GI - 20:GI]
vol_ratio = tv[GI] / (sum(prev20) / 20)
vol_rank = 1 + sum(1 for x in prev20 if x > tv[GI])


def ret_between(code, d0, d1):
    a = S[code]["adj"]
    i0 = max(i for i, d in enumerate(RD) if d <= d0)
    i1 = max(i for i, d in enumerate(RD) if d <= d1)
    return (a[i1] / a[i0] - 1) * 100


se41, se49 = ret_between("009150", "20250401", "20260630"), ret_between("009150", "20250409", "20260630")

# ───────────────────────── 템플릿 편집
text = SRC.read_text(encoding="utf-8").replace("\r\n", "\n")
L = text.split("\n")


def line(n):
    return L[n - 1]


def must(n, sub):
    if sub not in line(n):
        sys.exit(f"템플릿 불일치: {n}행에 {sub[:30]!r} 없음")


def rep(n, old, new):
    must(n, old)
    L[n - 1] = L[n - 1].replace(old, new)


def setl(n, old_head, new):
    must(n, old_head)
    L[n - 1] = new


M = f"시총 {FLOOR_TXT} 이상"
M_DYN = f'시총 <span class="capt">{FLOOR_TXT}</span> 이상'      # 시총 선택 버튼이 바꾸는 자리
kp = sum(1 for s in univ0 if s["mkt"] == "코스피")
kq = len(univ0) - kp
live_all = [s for s in passed if s["ret"] is not None and s["ret"] > 0]
n_kp = sum(1 for s in live_all if s["mkt"] == "코스피")
n_kq = len(live_all) - n_kp
rate = len(survivors) / len(univ0) * 100
sv_kq = sum(1 for s in survivors if s["mkt"] == "코스닥")
sv_above = sum(1 for s in survivors if s["above"] == "1")
top30_kq = sum(1 for s in sorted(live_all, key=lambda s: -s["ret"])[:30] if s["mkt"] == "코스닥")
d_iso = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"
sectors = {}
for s in univ0:
    if s["sector"]:
        sectors.setdefault(s["sector"], []).append(s)
sec_n = sum(1 for v in sectors.values() if len(v) >= 4)
with_sec = sum(1 for s in stocks if s["sector"])

# 상단 · 제목
setl(2, "saved from url", "<!-- 오디션 피라미딩 페이지 복제본 · tools/build_audition.py 로 생성 -->")
rep(5, "찰리 기술적 분석 · 오디션 피라미딩", f"오디션 피라미딩 ({M})")
rep(783, "./오디션 피라미딩_files/fonts.css", "./assets/fonts.css")
for n in (784, 785, 786, 787):
    must(n, "") if n == 784 else None
assert "site-bar" in line(784) and line(787).startswith("</div></div>")
for n in (784, 785, 786, 787):
    L[n - 1] = None
rep(789, "오늘의 시장 · 오디션 피라미딩", f"오디션 피라미딩 · {M} 복제본")
rep(791, "시총 1조 이상", M_DYN)
must(793, '<div class="stats">')
L[792] = (
    '<div class="wins" id="capbar" style="margin:6px 0 14px"><span class="wins-l">시총 기준</span>'
    '<button data-cap="5000">5000억</button><button data-cap="7000">7000억</button>'
    '<button data-cap="10000">1조</button><button data-cap="15000">1.5조</button><button data-cap="20000">2조</button>'
    '<span class="filt-note">이상 · 최신 시가총액 기준 · 표·업종·3MC·요약 숫자·차트가 모두 따라 바뀝니다</span></div>\n'
    '<div class="stats">')
setl(792, "기준일 2026-10-28",
     f'<p class="pauth">기준일 {d_iso(ASOF)} · KRX Open API · DART · 한국투자증권 · 직접 수집</p></header>')
setl(794, "오디션 대상",
     f'  <div class="stat" id="st-univ"><div class="l">오디션 대상</div><div class="v">{len(univ0)}</div>'
     f'<div class="s">{M_DYN} · 코스피 {kp} · 코스닥 {kq}</div></div>')
setl(795, "생존 (기준일",
     f'  <div class="stat" id="st-surv"><div class="l">생존 (기준일 대비 +)</div><div class="v" style="color:#059669">'
     f'{len(survivors)}</div><div class="s">생존율 {rate:.1f}% · 코스닥 {sv_kq}</div></div>')
setl(796, "가격 크로스 동반",
     f'  <div class="stat" id="st-above"><div class="l">가격 크로스 동반</div><div class="v" style="color:#2563eb">'
     f'{sv_above}</div><div class="s">생존자 중 240일선 위</div></div>')
phrase = ("절반 이상이 버티고 있어 아직 <b>오디션이 압축되지 않은</b> 국면입니다." if rate >= 50
          else "절반 아래로 줄어 <b>오디션이 압축되는</b> 국면입니다.")
setl(799, '<div class="verdict">',
     f'<div class="verdict" id="verdict">{d_iso(GZ)} 종가를 <b>그라운드 제로</b>로 두고 {d_iso(ASOF)}까지 '
     f'{LI - GI + 1}거래일을 추적했습니다. 기준일 대비 플러스가 <b>{len(survivors)}종목({rate:.0f}%)</b>입니다 — {phrase}</div>')
rep(800, "시총 2조 이상", M)
L[801] = (f'  <div class="filt" data-topn="30"><button class="on" data-mkt="전체">전체 <span>{len(live_all)}</span></button>'
          f'<button data-mkt="코스피">코스피 <span>{n_kp}</span></button>'
          f'<button data-mkt="코스닥">코스닥 <span>{n_kq}</span></button>'
          f'<span class="filt-note">시장별로 상위 30종목까지 표시</span></div>')
assert 'data-topn="30"' in text.split("\n")[801]
rows_html = "".join(row(s, i + 1) for i, s in enumerate(passed_sorted))
must(943, "<tr")
L[942] = rows_html + "</tbody></table></div>"
setl(944, "실적 컷을 통과한", (
    f'  <p class="note">실적 컷을 통과한 종목만 있다. 적자·부채비율 200% 이상·매출 2년 연속 감소 <span id="cutn">{len(cut_pos)}</span>종목은 아래 「실적 탈락」 표로 내렸다. '
    f'강의의 순서가 추세로 줄을 세운 뒤 실적으로 자르는 것이기 때문이다. '
    f'"가격이 아무리 급등을 해도 실적이 좋지 않으면 고려하지 않는다"(3강 2021 업데이트).</p>'))
rep(955, "+1,597%", f"{se41:+,.0f}%")
rep(955, "+1,895%", f"{se49:+,.0f}%")
setl(962, "⚠ 셈은 화면에서 한다", "  ⚠ 셈은 화면에서 한다. 종목마다 종가와 순매수를 통째로 실어 보내고 고른 두 날을 집어 계산한다.")
setl(963, "종가는 반올림 없이", "  종가는 액면분할·병합·무상증자를 보정해 실었다(보정한 종가는 정수로 반올림). 순매수는 백만원 단위로 적어 쌍끌이 판정의 부호가 뒤집히지 않는다.</p>")
setl(968, "당일 열은", (
    f'  <p class="note">당일 등락은 KRX {d_iso(ASOF)} 기준이다. 랭킹과 나머지 열도 전종목 같은 기준(KRX {d_iso(ASOF)})으로 계산했다. '
    f'기간을 바꾸면 종가·시가총액·최근 1주는 구간 끝일 값으로 바뀐다(시가총액은 최신 시총에 그날 종가 비율을 곱한 근사). '
    f'240일선·고점대비·거래량비·재무는 최신일 기준 그대로이다. 열 제목을 클릭하면 그 기준으로 정렬된다(다시 클릭하면 역순). '
    f'위 시장 버튼으로 코스피·코스닥을 따로 볼 수 있다.</p>'))
setl(969, "상위 30 중", (f'  <p class="note">상위 30 중 코스닥이 <span id="top30kq">{top30_kq}</span>종목이다. 코스닥이 상위권에 들어오기 시작하면 '
                         f'위험선호 회복의 초기 신호로 읽는다.</p>'))
setl(979, "그날 코스피·코스닥", (
    f"      그날 코스피·코스닥 전 종목 거래량이 앞 20거래일 평균의 <b>{vol_ratio:.2f}배</b>였고, 그 20거래일 가운데 "
    + ("<b>가장 많았다</b>." if vol_rank == 1 else f"<b>{vol_rank}번째로 많았다</b>.")
    + " (기준일은 원본 페이지의 날짜를 그대로 가져왔다.)"))
setl(986, "이익이 급변하는", "      이익이 급변하는 종목은 실제보다 높게 보일 수 있다.")
L[986] = ""
rep(991, "시총 1조 이상", M)
rep(992, "강의 기준 그대로이다.", f"강의의 기준은 1조이지만 이 복제본은 {FLOOR_TXT}으로 넓혔다.")
rep(1004, "2022년 이후 고점", f"{d_iso(RD[0])} 이후 고점")
setl(1006, "⚠ 2026-09-11", "      ⚠ <b>52주가 아니라 보유 자료 전체의 고점이다.</b> 강의가 말하는 것은 52주 고점이 아니라")
rep(1007, "1177거래일", f"{N}거래일")
rep(1013, "시총 1조원 이상", f"시총 {FLOOR_TXT}원 이상")
setl(1016, "강의의 재무 등급", (
    f'    <dd>강의의 재무 등급 기준을 따른다. <b>특등급 = OPM 40%+ &amp; ROE 20%+</b>, <b>1등급 = OPM 20%+ &amp; ROE 10%+</b>, '
    f'<b>2등급 = 그 밖의 흑자</b>. 강의는 \'분기로 보면 안 된다, 반드시 연간·3년 이상\'이라 했으므로 <b>등급은 사업보고서(연간) 기준</b>으로 매기고, '
    f'사업보고서가 없는 종목만 반기 값으로 매긴다. 등급에 마우스를 올리면 기준이 나온다. <b>★</b>는 최근 3년 내내 그 등급을 지킨 종목이다. '
    f'<b>부채비율</b> = 부채총계 ÷ 자본총계. <b>100% 이상이면 특등급·1등급을 인정하지 않고 2등급으로 내리며</b>, '
    f'<b>200% 이상·적자·자본잠식·매출 2년 연속 감소는 실적 탈락</b>으로 내린다. 금융·보험 업종은 부채비율과 매출 감소를 보지 않는다.</dd>'))
setl(1018, "이 표는 2차 스크리닝", (
    '  <p class="note" style="margin-top:4px">이 표는 2차 스크리닝(실적 컷)까지이다. 강의의 완성형은 여기서 주도업종 + '
    '3MC(가격·재무·수급 크로스)로 2차 스크리닝을 해 20~30개 숏리스트를 만들고, 그다음 비중을 정하는 타게팅으로 넘어간다. '
    '이 복제본이 자동화한 것은 가격 축(구간 상승률·240일선·고점대비), 실적 컷(적자·부채비율·매출 감소), 그리고 3MC 가운데 가격·수급(1급수)·재무 크로스이다.</p>'))
setl(1022, "강의의 수급 크로스는", (
    "  강의의 수급 크로스는 품절주(대주주와 외국인이 90% 초과)와 1급수(외국인·기관 쌍끌이 매수)인데, 이 복제본은 외국인·기관 일별 순매수로 "
    "1급수만 잰다. 품절주는 지분 자료가 없어 못 잰다."))
L[1022] = ""
rep(1024, "2022년 이후 고점", f"{d_iso(RD[0])} 이후 고점")
setl(1030, 'data-sm="sec"', f'    <button class="on" data-sm="sec">KRX 업종 <span>{sec_n}</span></button>')
L[1030] = ""
setl(1032, "filt-note", '    <span class="filt-note">업종은 한 종목에 하나가 붙습니다</span>')
L[1033] = '  <div id="secbox" class="secbox"></div>'
must(1068, "</div>")
for n in range(1035, 1068):
    L[n - 1] = ""
L[1034] = (
    '  <p class="note">강의의 주도업종 판별 자리이다. 4강 7번이 1차 스크리닝 다음에 두는 관문이다. 업종은 한국투자증권 현재가 시세의 '
    f'업종명(KRX 지수업종)이고 {d_iso(ASOF)}에 받은 값이다. '
    '표가 아니라 유니버스 전체로 세다. 업종은 시장이 어디로 가는지를 보는 것이라 표본이 넓은 쪽이 맞다. 종목이 4개 미만인 업종은 뺐다.</p>\n'
    '  <p class="note">이렇게 읽으면 안 된다. 1등 업종을 사라는 뜻이 아니다. 구간을 바꿔 보면 주도가 언제 바뀌었는지가 보인다. '
    '짧은 구간에서 1등이던 업종이 긴 구간에서도 1등이면 아직 주도가 이어지는 것이고, 짧은 구간에서 뒤로 밀렸으면 교체가 시작된 것이다. '
    '⚠ 업종은 받아 둔 시점의 값이라 매일 갱신되지 않는다. KRX 업종은 분류를 그대로 쓰므로 사업 내용과 어긋나 보이는 자리가 있다. '
    '테마 분류는 출처가 없어 싣지 않았다.</p>')
L[1070] = '  <div id="mcsum" class="mcsum"></div>'
must(1071, "mcsum") if False else None
rep(1080, "2022년 이후 고점", f"{d_iso(RD[0])} 이후 고점")
rep(1094, "주도업종은 종목별 업종 자료가 없어 이 덱에 '없습니다'.", "주도업종은 위 「지금 어느 업종이 움직이나」에서 업종별 중앙 수익률로 봅니다.")
# 실적 탈락 · 탈락 하위 10
rep(1100, '<span class="sub2">35종목</span>', f'<span class="sub2" id="cutcnt">{len(cut_pos)}종목</span>')
must(1102, "<tbody><tr")
must(1136, "</tbody></table></div>")
for n in range(1102, 1137):
    L[n - 1] = ""
L[1101] = "  <tbody>" + "".join(row(s, 0, " · ".join(s["reasons"])) for s in cut_pos) + "</tbody></table></div>"
must(1141, "<tbody><tr")
must(1150, "</tbody></table></div>")
for n in range(1141, 1151):
    L[n - 1] = ""
lose_pool = by_ret[::-1][:80]      # 시총 선택에 따라 화면이 이 가운데 앞 10개를 고른다
L[1140] = "  <tbody>" + "".join(row(s, 0) for s in lose_pool) + "</tbody></table></div>"
# 차트 패널
must(1158, "ct-now")
L[1157] = '  <div class="chart"><canvas id="ac"></canvas></div>'
rep(1161, "시총 2조 이상", M_DYN)
rep(1161, "코스피를 이긴", "코스피(시총가중 직접 계산)를 이긴")
setl(1164, "42.6%", f'      <div class="v" id="b-now" style="color:#2563eb">{b_now:.1f}%</div>')
setl(1165, "10/28 기준", f'      <div class="s" id="b-now-s">{RD[-1][4:6].lstrip("0")}/{RD[-1][6:].lstrip("0")} 기준 · <b>{b_word}</b></div></div>')
rep(1166, '<div class="v" style="font-size:1.5rem">49%</div>', f'<div class="v" id="b-med" style="font-size:1.5rem">{b_med:.0f}%</div>')
rep(1167, "2022년 이후 1117거래일 중앙값", f"{d_iso(RD[W])} 이후 {len(breadth)}거래일 중앙값")
rep(1168, '<div class="v" style="font-size:1.5rem;color:#f59e0b">42%</div>',
    f'<div class="v" id="b-narrow" style="font-size:1.5rem;color:#f59e0b">{b_narrow:.0f}%</div>')
rep(1170, '<div class="v" style="font-size:1.5rem;color:#dc2626">31%</div>',
    f'<div class="v" id="b-ext" style="font-size:1.5rem;color:#dc2626">{b_ext:.0f}%</div>')
must(1173, "ct-now")
L[1172] = '  <div class="chart"><canvas id="wc"></canvas></div>'
setl(1174, "평상 범위이다.", f'  <p class="note"><span id="b-note">지금은 {b_word} 범위이다.</span>')
rep(1176, "볼 수 있다.</p>", "볼 수 있다. 코스피 지수 자료의 접근 권한이 없어, 코스피 상장 종목의 시가총액 가중 수익률(KRX 일별 자료로 직접 계산)을 "
    "지수 대신 썼다. 실제 코스피 지수와는 조금 다를 수 있다.</p>")
must(1177, "background:color-mix")
must(1183, "</p></div>")
for n in range(1177, 1183):
    L[n - 1] = ""
L[1182] = "</div>"
# 차트 데이터
rep(1185, "./오디션 피라미딩_files/chart-4.4.7.umd.min.js.다운로드", "./assets/chart.min.js")
rep(1187, "./오디션 피라미딩_files/chart-theme.js.다운로드", "./assets/chart-theme.js")
L[1190] = f" data:{{labels:{json.dumps(labels_s)},datasets:["
L[1191] = ("  {label:'생존 종목 수(기준일 대비 +)',data:" + json.dumps(surv_cnt) +
           ",borderColor:'#059669',backgroundColor:'rgba(5,150,105,.10)',borderWidth:2.4,pointRadius:0,tension:.2,fill:true,yAxisID:'y'},")
L[1192] = ("  {label:'생존율(%)',data:" + json.dumps(surv_rate) +
           ",borderColor:'#2563eb',borderWidth:2,borderDash:[5,4],pointRadius:0,tension:.2,yAxisID:'y1'}]},")
L[1201] = f" data:{{labels:{json.dumps(blabels)},datasets:["
L[1202] = ("  {label:'후보 폭(%)',data:" + json.dumps(breadth) +
           ",borderColor:'#7c3aed',backgroundColor:'rgba(124,58,237,.10)',borderWidth:2.2,pointRadius:0,tension:.2,fill:true}]},")
rep(1214, "시총 1조 컷", f"시총 {FLOOR_TXT} 컷")
setl(1221, "<p>3MC 중 수급 크로스가 없다.", (
    "<p>3MC 중 수급 크로스는 품절주(대주주·외국인 지분 90% 초과)를 재지 못한다. 지분 자료가 없어 외국인·기관 쌍끌이 매수(1급수)만 잰다. "
    "재무 크로스는 사업보고서 최근 두 해의 ROE와 PER(연말 시가총액 ÷ 순이익)로 잰다. 적자인 해가 끼거나 우선주면 「못 잼」이다.</p>"))
setl(1222, "<p>주도업종 필터가 없다.", (
    f"<p>주도업종 필터는 「지금 어느 업종이 움직이나」의 업종별 중앙 수익률로 대신한다. 업종은 {d_iso(ASOF)}에 받은 값이고 테마 분류는 싣지 않았다.</p>"))
must(1226, "TOPICNEWS")
L[1225] = None
setl(1227, "<footer>", (
    "<footer><p>본 자료는 정보 제공·교육 목적이며 투자 권유가 아니다. 투자의 최종 판단과 책임은 투자자 본인에게 있다. · "
    "방법론: 이야기꾼 시나리오투자법(3MC 오디션 피라미딩) · "
    f"데이터: KRX Open API 코스피·코스닥 전종목 일별매매정보(이력, {d_iso(RD[0])}~{d_iso(ASOF)}) · "
    "한국투자증권 Open API(업종 · PBR · 투자자별 매매동향) · DART Open API(최신 반기 주요계정 · 사업보고서 3년치). 기준일이 휴장이면 직전 거래일로 자동 보정된다. "
    "이 페이지는 「찰리의 시투 추종」의 오디션 피라미딩 페이지를 제작자의 허락을 받아 복제하고, 시총 기준을 "
    f"{FLOOR_TXT} 이상으로 바꿔 데이터를 새로 수집해 만든 것이다.</p></footer>"))
# JS 데이터
must(1235, "var RD=")
must(1240, "var THN=")
must(1241, "var secMode")
secof = {s["code"]: s["sector"] for s in stocks if s["sector"]}
pxs = {s["code"]: encode(s["adj"]) for s in stocks}
# 수급: 날짜별 [외국인, 기관] 순매수(백만원)를 RD 순서의 36진수로 — 없는 날은 빈칸(0)
flw = {}
for s in stocks:
    fl_ = flows.get(s["code"])
    if not fl_:
        continue
    cols = ([], [])
    for d in RD:
        v = fl_.get(d)
        cols[0].append(b36(v[0]) if v else "")
        cols[1].append(b36(v[1]) if v else "")
    flw[s["code"]] = [",".join(cols[0]), ",".join(cols[1])]
meta = {s["code"]: [1 if s["mkt"] == "코스닥" else 0, s["cap"], -1 if s["above"] == "" else int(s["above"])]
        for s in stocks}
CAP_JS = r"""
  var CAPALL=500000000000, CAPMIN=CAPALL;
  var CAPOPT={"5000":"5000억","7000":"7000억","10000":"1조","15000":"1.5조","20000":"2조"};
  (function(){
    var m=/[#&]cap=(\d+)/.exec(location.hash||''), v=m?m[1]:null;
    if(!v){ try{ v=localStorage.getItem('aud-cap'); }catch(e){} }
    if(v&&CAPOPT[v]) CAPMIN=parseInt(v,10)*100000000;
  })();
  function capKey(){ return String(Math.round(CAPMIN/100000000)); }
  function CAPTXT(){ return CAPOPT[capKey()]||'5000억'; }
  function capOK(r){ return parseFloat(r.getAttribute('data-cap')||'0')>=CAPMIN; }
  function capOKc(c){ var m=META[c]; return !!m&&m[1]>=CAPMIN; }
  function $id(i){ return document.getElementById(i); }
  function qtl(x,p){ var m=x.length, pos=p*(m+1), j=Math.floor(pos);
    if(j<1)return x[0]; if(j>=m)return x[m-1]; return x[j-1]+(pos-j)*(x[j]-x[j-1]); }
  function top30kq(rows){
    var el=$id('top30kq'); if(!el)return;
    var live=rows.filter(function(r){return r.__v!==null&&r.__v>0&&capOK(r)})
                 .sort(function(a,b){return b.__v-a.__v}).slice(0,30);
    el.textContent=live.filter(function(r){return r.getAttribute('data-mkt')==='코스닥'}).length;
  }
  function capTables(){
    var n=0;
    document.querySelectorAll('#tbl-cut tbody tr').forEach(function(r){
      var ok=capOK(r); r.style.display=ok?'':'none'; if(ok)n++;
    });
    var a=$id('cutcnt'), b=$id('cutn'); if(a)a.textContent=n+'종목'; if(b)b.textContent=n;
    var k=0;
    document.querySelectorAll('#tbl-lose tbody tr').forEach(function(r){
      if(k<10&&capOK(r)){ k++; r.style.display=''; var c=r.querySelector('.rk'); if(c)c.textContent=k; }
      else r.style.display='none';
    });
  }
  function setChart(id,series){
    try{
      var ch=window.Chart&&Chart.getChart&&Chart.getChart(id); if(!ch)return;
      series.forEach(function(s,i){ ch.data.datasets[i].data=s; });
      ch.update('none');
    }catch(e){}
  }
  function capUpdate(){
    var arrs=[], uni=[], n=0, kp=0, kq=0, sv=0, svq=0, sa=0;
    for(var c in META){
      if(META[c][1]<CAPMIN)continue;
      var a=px(c); if(!a)continue; arrs.push(a);
      if(a[GI]){
        var q=META[c][0]; uni.push(a); n++; if(q)kq++; else kp++;
        if(a[LI]&&a[LI]>a[GI]){ sv++; if(q)svq++; if(META[c][2]===1)sa++; }
      }
    }
    var rate=n?sv/n*100:0;
    function card(id,v,s){ var e=$id(id); if(!e)return; e.querySelector('.v').textContent=v; if(s!==null)e.querySelector('.s').innerHTML=s; }
    card('st-univ',n,'시총 <span class="capt">'+CAPTXT()+'</span> 이상 · 코스피 '+kp+' · 코스닥 '+kq);
    card('st-surv',sv,'생존율 '+rate.toFixed(1)+'% · 코스닥 '+svq);
    card('st-above',sa,null);
    var vd=$id('verdict');
    if(vd)vd.innerHTML=fmtD(RD[GI])+' 종가를 <b>그라운드 제로</b>로 두고 '+fmtD(RD[LI])+'까지 '+(LI-GI+1)
      +'거래일을 추적했습니다. 기준일 대비 플러스가 <b>'+sv+'종목('+Math.round(rate)+'%)</b>입니다 — '
      +(rate>=50?'절반 이상이 버티고 있어 아직 <b>오디션이 압축되지 않은</b> 국면입니다.'
                :'절반 아래로 줄어 <b>오디션이 압축되는</b> 국면입니다.');
    var cnt=[], rt=[];
    for(var t=GI;t<=LI;t++){
      var k=0; for(var i=0;i<uni.length;i++){ var u=uni[i]; if(u[t]&&u[t]>u[GI])k++; }
      cnt.push(k); rt.push(n?Math.round(k/n*1000)/10:0);
    }
    var W=60, br=[];
    for(var t2=W;t2<RD.length;t2++){
      var kr=KIDX[t2]/KIDX[t2-W]-1, tot=0, win=0;
      for(var j=0;j<arrs.length;j++){ var b=arrs[j]; if(b[t2]&&b[t2-W]){ tot++; if(b[t2]/b[t2-W]-1>kr)win++; } }
      br.push(tot?Math.round(win/tot*1000)/10:0);
    }
    var now=br[br.length-1], srt=br.slice().sort(function(x,y){return x-y});
    var med=qtl(srt,0.5), nar=qtl(srt,0.25), ext=qtl(srt,0.10), wide=qtl(srt,0.75);
    var word=now<=ext?'극단적으로 좁은':(now<=nar?'좁은':(now>=wide?'넓은':'보통'));
    function put(id,h){ var e=$id(id); if(e)e.innerHTML=h; }
    put('b-now',now.toFixed(1)+'%');
    put('b-now-s',(+RD[LI].slice(4,6))+'/'+(+RD[LI].slice(6,8))+' 기준 · <b>'+word+'</b>');
    put('b-med',Math.round(med)+'%'); put('b-narrow',Math.round(nar)+'%'); put('b-ext',Math.round(ext)+'%');
    put('b-note','지금은 '+word+' 범위이다.');
    setChart('ac',[cnt,rt]); setChart('wc',[br]);
    // 차트 위 «지금 값» 타일은 chart-theme.js 가 다시 그릴 때 갱신된다 — 클래스 변화로 그 경로를 한 번 태운다
    var h=document.documentElement; h.classList.add('cap-tick'); h.classList.remove('cap-tick');
  }
  function capApply(){
    document.querySelectorAll('.capt').forEach(function(e){ e.textContent=CAPTXT(); });
    document.querySelectorAll('#capbar button').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-cap')===capKey());
    });
    repaint(); apply(); capTables(); capUpdate();
  }
  function capInit(){
    document.querySelectorAll('#capbar button').forEach(function(b){
      b.addEventListener('click',function(){
        var v=b.getAttribute('data-cap'); CAPMIN=parseInt(v,10)*100000000;
        try{ localStorage.setItem('aud-cap',v); }catch(e){}
        try{ history.replaceState(null,'','#cap='+v); }catch(e){}
        capApply();
      });
    });
    if(CAPMIN!==CAPALL) capApply();
    else {
      document.querySelectorAll('#capbar button').forEach(function(b){ b.classList.toggle('on', b.getAttribute('data-cap')==='5000'); });
      capTables();
    }
  }
"""
data_js = "\n".join([
    "  var RD=" + json.dumps(RD) + ";",
    "  var META=" + json.dumps(meta, separators=(",", ":")) + ";",
    "  var KIDX=" + json.dumps([round(x, 6) for x in kidx]) + ";",
    "  var PXS=" + json.dumps(pxs, ensure_ascii=False, separators=(",", ":")) + ";",
    "  var FLW=" + json.dumps(flw, separators=(",", ":")) + ";",
    "  var SECOF=" + json.dumps(secof, ensure_ascii=False, separators=(",", ":")) + ";",
    f"  var GI={GI}, LI=RD.length-1;",
    "  var THN=[], THM={};",
    CAP_JS,
])
L[1234] = data_js
for n in range(1236, 1241):
    L[n - 1] = None
rep(1383, "시총 2조 이상", "시총 '+CAPTXT()+' 이상")
# 시총 선택 — 기존 함수에 필터를 끼운다
rep(1394, "r.__v>0);", "r.__v>0&&capOK(r));")
rep(1407, "mcSummary(rows);", "mcSummary(rows); top30kq(rows);")
rep(1416, "r.__v>0})", "r.__v>0&&capOK(r)})")
rep(1457, "for(var c in SECOF){", "for(var c in SECOF){ if(!capOKc(c))continue;")
rep(1471, "a.sort(function(x,y){return y[1]-x[1]});",
    "a.sort(function(x,y){return y[1]-x[1]}); var sb=document.querySelector('button[data-sm=\"sec\"] span'); if(sb&&secMode==='sec')sb.textContent=a.length;")
rep(1513, "r.__v>0})", "r.__v>0&&capOK(r)})")
must(1640, "repaint(); apply();")
L[1639] = L[1639].replace("repaint(); apply();", "repaint(); apply(); capInit();")
rep(1098, "업종과 사업 내용은 관심종목 등록부에 한 줄 설명이 있는 종목만 옮겼고, 없는 종목은 시장과 시가총액까지만 적었다. 없는 설명을 지어 넣지 않는다.", "종목별 사업 설명은 싣지 않았다. 없는 설명을 지어 넣지 않는다.")
hdr = f"당일 등락 {int(ASOF[4:6])}/{int(ASOF[6:])}"
for n in (803, 1101, 1140):
    rep(n, "당일 등락 10/28", hdr)
L[800] = L[800].replace("2026-10-28", d_iso(ASOF))
# 사이트 메뉴·검색 스크립트 제거
must(1644, "<script>")
must(1660, "</script>")
for n in range(1644, 1662):
    L[n - 1] = None
must(1686, "SEARCH:BEGIN")
L[1685] = None
must(1688, "srch-bg")
L[1687] = "</body></html>"

out_text = "\n".join(x for x in L if x is not None)
(OUT / "assets").mkdir(parents=True, exist_ok=True)
src_files = ROOT / "오디션 피라미딩_files"
shutil.copyfile(src_files / "fonts.css", OUT / "assets" / "fonts.css")
shutil.copyfile(src_files / "chart-4.4.7.umd.min.js.다운로드", OUT / "assets" / "chart.min.js")
shutil.copyfile(src_files / "chart-theme.js.다운로드", OUT / "assets" / "chart-theme.js")
(OUT / "index.html").write_text(out_text, encoding="utf-8")
def check_at(T):
    """선택 기능 검증용: 시총 T 이상일 때 JS 가 내야 하는 값을 파이썬으로 따로 센다."""
    sub = [s for s in stocks if s["cap"] >= T]
    uni = [s for s in sub if s["adj"][GI]]
    sv = sum(1 for s in uni if s["adj"][LI] and s["adj"][LI] > s["adj"][GI])
    kr = kidx[LI] / kidx[LI - W] - 1
    tot = win = 0
    for s in sub:
        a = s["adj"]
        if a[LI] and a[LI - W]:
            tot += 1
            win += (a[LI] / a[LI - W] - 1) > kr
    return dict(T=T, universe=len(uni), survivors=sv, breadth=round(win / tot * 100, 1))


print(json.dumps([check_at(t) for t in (5e11, 7e11, 1e12, 1.5e12, 2e12)], ensure_ascii=False))
print(json.dumps(dict(
    universe=len(codes), with_gz=len(univ0), kospi=kp, kosdaq=kq, survivors=len(survivors), rate=round(rate, 1),
    passed=len(passed), cut=len(cut), cut_positive=len(cut_pos), sectors=sec_n, with_sector=with_sec,
    breadth_now=b_now, breadth_word=b_word, vol_ratio=round(vol_ratio, 2), vol_rank=vol_rank,
    days=N, gi=GI, size_kb=len(out_text.encode("utf-8")) // 1024), ensure_ascii=False))


