"""DART 사업보고서(연간) 3년치와 연말 시총을 받아 등급·재무 크로스 재료를 만든다.

사업보고서 한 번에 당기·전기·전전기가 같이 온다. 연도는 최근 확정 사업보고서 연도(기본 2025)다.
출력: <출력 폴더>/annual.json
  {code: {"y": [2023, 2024, 2025], "rev": [...], "op": [...], "ni": [...], "eq": [...]},
   "_cap": {"2023": {code: 시총}, ...}}
사용: python -I collect_dart_annual.py <env 경로> <KRX 캐시 폴더> <출력 폴더> <시총 하한(원)> [연도]
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


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


def get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(full, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(2 * (attempt + 1))
    sys.exit("재시도 초과: " + url)


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def year_end_caps(krx_dir, years):
    """해마다 마지막 거래일 시총. KRX 캐시에 없는 해(2023 등)는 호출자가 따로 채운다."""
    days = sorted(p.stem for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5)
    out = {}
    for y in years:
        cands = [d for d in days if d.startswith(str(y))]
        if cands:
            rows = json.loads((Path(krx_dir) / (cands[-1] + ".json")).read_text(encoding="utf-8"))
            out[str(y)] = {"date": cands[-1], "cap": {r["ISU_CD"]: int(r["MKTCAP"] or 0) for r in rows}}
    return out


def main():
    env_path, krx_dir, out_dir, floor = sys.argv[1:5]
    year = int(sys.argv[5]) if len(sys.argv) > 5 else 2025
    env = load_env(env_path)
    key = env["DART_API_KEY"]
    out = Path(out_dir)
    cmap = json.loads((out / "corpcode.json").read_text(encoding="utf-8"))
    days = sorted(p for p in Path(krx_dir).glob("*.json") if p.stat().st_size > 5)
    rows = json.loads(days[-1].read_text(encoding="utf-8"))
    codes = [r["ISU_CD"] for r in rows if int(r["MKTCAP"] or 0) >= int(floor)]
    need = sorted({(c[:-1] + "0") if (c[:-1] + "0") in cmap else c for c in codes} & set(cmap))
    inv = {v: k for k, v in cmap.items()}
    res = {}
    for i in range(0, len(need), 90):
        chunk = need[i:i + 90]
        j = get("https://opendart.fss.or.kr/api/fnlttMultiAcnt.json", {
            "crtfc_key": key, "corp_code": ",".join(cmap[c] for c in chunk),
            "bsns_year": str(year), "reprt_code": "11011"})
        if j.get("status") not in ("000", "013"):
            sys.exit("DART 오류 %s %s" % (j.get("status"), j.get("message")))
        tmp = {}
        for it in j.get("list", []):
            nm = it.get("account_nm", "").strip()
            nm = "매출액" if nm == "수익(매출액)" else nm
            if nm.startswith("당기순이익"):
                nm = "당기순이익"      # 보고서에는 「당기순이익(손실)」로 온다
            if nm.startswith("영업이익"):
                nm = "영업이익"        # 「영업이익(손실)」로 오는 회사도 있다
            if nm not in ("매출액", "영업이익", "당기순이익", "자본총계"):
                continue
            sc = inv[it["corp_code"]]
            vals = [num(it.get("bfefrmtrm_amount")), num(it.get("frmtrm_amount")), num(it.get("thstrm_amount"))]
            slot = tmp.setdefault(sc, {})
            cur = slot.get(nm)
            if cur is None or (it.get("fs_div") == "CFS" and cur[1] != "CFS"):
                slot[nm] = (vals, it.get("fs_div"))
        for sc, a in tmp.items():
            res[sc] = {"y": [year - 2, year - 1, year],
                       "rev": a.get("매출액", ([None] * 3, 0))[0], "op": a.get("영업이익", ([None] * 3, 0))[0],
                       "ni": a.get("당기순이익", ([None] * 3, 0))[0], "eq": a.get("자본총계", ([None] * 3, 0))[0]}
        time.sleep(0.3)
        print("진행 %d/%d" % (min(i + 90, len(need)), len(need)), flush=True)
    caps = year_end_caps(krx_dir, [year - 1, year])
    res["_cap"] = {y: v for y, v in caps.items()}
    (out / "annual.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("저장 %d종목, 연말 시총 %s" % (len(res) - 1, {y: v["date"] for y, v in caps.items()}), flush=True)


main()
