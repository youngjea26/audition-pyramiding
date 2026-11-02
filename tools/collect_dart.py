"""DART 주요계정으로 시총 기준 이상 종목의 OPM·ROE·부채비율을 계산해 JSON으로 저장한다.

사용: python -I collect_dart.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <시총 하한(원)>
최신 보고서부터 3분기 → 반기 → 1분기 순으로 찾고, 연결재무제표(CFS)를 우선한다.
손익은 누적(thstrm_add_amount, 없으면 thstrm_amount), ROE 는 연환산한다(1Q×4, 반기×2, 3Q×4/3).
"""
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPORTS = (("11014", 4 / 3, "3분기"), ("11012", 2.0, "반기"), ("11013", 4.0, "1분기"))
YEAR = sys.argv[5] if len(sys.argv) > 5 else "2026"    # 최신 분기·반기 보고서 연도
BATCH = 90


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


def get(url, params, binary=False):
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(full, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data.decode("utf-8"))
        except Exception:
            time.sleep(2 * (attempt + 1))
    sys.exit("재시도 초과: " + url)


def corp_codes(key, cache):
    f = cache / "corpcode.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    raw = get("https://opendart.fss.or.kr/api/corpCode.xml", {"crtfc_key": key}, binary=True)
    z = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for e in root.iter("list"):
        sc = (e.findtext("stock_code") or "").strip()
        if sc:
            m[sc] = e.findtext("corp_code").strip()
    f.write_text(json.dumps(m), encoding="utf-8")
    return m


def universe(krx_dir, floor):
    days = sorted(p for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5)
    rows = json.loads(days[-1].read_text(encoding="utf-8"))
    return days[-1].stem, [r for r in rows if int(r["MKTCAP"] or 0) >= floor]


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def parse(items, rpt):
    """corp_code 별 {account: amount} — CFS 우선."""
    by = {}
    for it in items:
        cc, nm, div = it.get("corp_code"), it.get("account_nm", "").strip(), it.get("fs_div")
        if nm.startswith("당기순이익"):
            nm = "당기순이익"          # 보고서에는 「당기순이익(손실)」로 온다
        if nm.startswith("영업이익"):
            nm = "영업이익"            # 「영업이익(손실)」로 오는 회사도 있다
        if nm not in ("매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계", "수익(매출액)"):
            continue
        nm = "매출액" if nm == "수익(매출액)" else nm
        stock = nm in ("자산총계", "부채총계", "자본총계")
        amt = num(it.get("thstrm_amount")) if stock or rpt == "11013" else (
            num(it.get("thstrm_add_amount")) if num(it.get("thstrm_add_amount")) is not None
            else num(it.get("thstrm_amount")))
        slot = by.setdefault(cc, {})
        cur = slot.get(nm)
        if cur is None or (div == "CFS" and cur[1] != "CFS"):
            slot[nm] = (amt, div)
    return {cc: {k: v[0] for k, v in d.items()} for cc, d in by.items()}


def main():
    env_path, krx_dir, out_dir, floor = sys.argv[1:5]
    key = load_env(env_path)["DART_API_KEY"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cmap = corp_codes(key, out)
    day, uni = universe(krx_dir, int(floor))
    print("유니버스 %s 기준 %d종목" % (day, len(uni)), flush=True)

    # 우선주(코드 끝자리 0 이 아닌 종목)는 같은 회사 보통주 재무를 쓴다.
    common = {}
    for r in uni:
        code = r["ISU_CD"]
        base = code[:-1] + "0"
        common[code] = base if base in cmap else code
    need = sorted({c for c in common.values() if c in cmap})
    missing = sorted({c for c in common.values() if c not in cmap})

    fin = {}
    todo = list(need)
    for rpt, ann, label in REPORTS:
        if not todo:
            break
        found = {}
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            res = get("https://opendart.fss.or.kr/api/fnlttMultiAcnt.json", {
                "crtfc_key": key, "corp_code": ",".join(cmap[c] for c in chunk),
                "bsns_year": YEAR, "reprt_code": rpt})
            if res.get("status") not in ("000", "013"):
                sys.exit("DART 오류 %s %s" % (res.get("status"), res.get("message")))
            found.update(parse(res.get("list", []), rpt))
            time.sleep(0.3)
        inv = {v: k for k, v in cmap.items()}
        got = []
        for cc, a in found.items():
            sc = inv[cc]
            eq, ni, rev, op, li = a.get("자본총계"), a.get("당기순이익"), a.get("매출액"), a.get("영업이익"), a.get("부채총계")
            fin[sc] = {
                "보고서": label,
                "opm": round(op / rev * 100, 1) if op is not None and rev else None,
                "roe": round(ni * ann / eq * 100, 1) if ni is not None and eq and eq > 0 else None,
                "debt": round(li / eq * 100) if li is not None and eq and eq > 0 else None,
                "equity": eq,
            }
            got.append(sc)
        todo = [c for c in todo if c not in got]
        print("%s: %d종목 확보, 남은 %d" % (label, len(got), len(todo)), flush=True)

    result = {"asof": day, "year": YEAR, "fin": {}, "no_fin": sorted(set(todo) | set(missing))}
    for code, base in common.items():
        if base in fin:
            result["fin"][code] = fin[base]
    (out / "fin.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print("저장 %d종목, 재무 없음 %d종목" % (len(result["fin"]), len(result["no_fin"])), flush=True)


main()
