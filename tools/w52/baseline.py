"""배치: 전 종목 52주 신고가 기준 지표·게이트·정적 점수를 계산해 SQLite 와 baseline.json 으로 저장한다.

기준일 D 는 캐시의 마지막 거래일(저녁 배치라면 KIS 로 채운 당일 포함)이고, 결과는 D+1 장의 기준이 된다.
사용: python -I tools/w52/baseline.py <my-agent 폴더> [DB 경로]
"""
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # tools/
from w52 import indicators as ix  # noqa: E402
from w52 import store  # noqa: E402
from w52.config import PARAMS as P, RISK_STAT_CODES  # noqa: E402

KST = timezone(timedelta(hours=9))
FIN_WORDS = ("금융", "증권", "보험", "은행")
LOOKBACK = 330            # 52주(250) + ATR·ADX 워밍업과 주봉 20주를 위한 여유


# ───────────────────────── 데이터 적재
def add_provisional(root, krx):
    """KRX 확정 자료가 없는 날(보통 오늘)을 한국투자증권 일자별 시세로 채운다. build_audition.py 와 같은 규칙."""
    ddir = root / "cache" / "kis_daily"
    if not (ddir / "_meta.json").exists():
        return []
    last = max(krx)
    base, per_day, files = krx[last], {}, 0
    for p in ddir.glob("*.json"):
        if p.stem.startswith("_") or p.stem not in base:
            continue
        files += 1
        b = base[p.stem]
        shares = int(b["LIST_SHRS"] or 0)
        for d, vals in json.loads(p.read_text(encoding="utf-8")).items():
            if d > last:
                c, v, f = vals[:3]
                o, h, lo = (vals[3:6] + [c, c, c])[:3]
                per_day.setdefault(d, {})[p.stem] = {
                    "ISU_CD": p.stem, "ISU_NM": b["ISU_NM"], "MKT": b["MKT"], "TDD_CLSPRC": str(c),
                    "TDD_OPNPRC": str(o), "TDD_HGPRC": str(h), "TDD_LWPRC": str(lo), "FLUC_RT": str(f),
                    "ACC_TRDVOL": str(v), "ACC_TRDVAL": "0", "MKTCAP": str(c * shares), "LIST_SHRS": str(shares)}
    used = []
    for d in sorted(per_day):
        if files and len(per_day[d]) >= 0.9 * files:
            krx[d] = per_day[d]
            used.append(d)
    return used


def load_days(root):
    files = sorted(p for p in (root / "cache" / "krx").glob("*.json") if p.stat().st_size > 5 and p.stem >= "20250401")
    files = files[-LOOKBACK:]
    krx = {p.stem: {r["ISU_CD"]: r for r in json.loads(p.read_text(encoding="utf-8"))} for p in files}
    return krx, add_provisional(root, krx)


def build_series(krx, dates, code):
    """날짜별 (종가, 고가, 저가, 거래량, 거래대금, 상장주식수)를 만들고 분할을 보정한다. 결측은 건너뛴 채 날짜 목록과 함께 돌려준다."""
    ds, cl, hi, lo, op, vo, va, sh = [], [], [], [], [], [], [], []
    miss = []                      # 날짜별로 고가·저가가 없어 종가로 대신한 날(1) 표시
    for d in dates:
        r = krx[d].get(code)
        if not r:
            continue
        c = int(r["TDD_CLSPRC"] or 0)
        if c <= 0:
            continue
        h, l = int(r.get("TDD_HGPRC") or 0), int(r.get("TDD_LWPRC") or 0)
        if h <= 0 or l <= 0:
            h, l = c, c                                  # 고가·저가가 없는 날은 종가로 대신한다(백필 전 캐시)
            miss.append(1)
        else:
            miss.append(0)
        o = int(r.get("TDD_OPNPRC") or 0) or c
        ds.append(d), cl.append(c), hi.append(max(h, c, o)), lo.append(min(l, c, o)), op.append(o)
        vo.append(int(r.get("ACC_TRDVOL") or 0)), va.append(int(r.get("ACC_TRDVAL") or 0)), sh.append(int(r["LIST_SHRS"] or 0))
    if not ds:
        return None
    cl, hi, lo, op = ix.adjust_splits(cl, sh, hi, lo, op)
    return {"ds": ds, "close": cl, "high": hi, "low": lo, "open": op, "vol": vo, "val": va, "miss": miss}


# ───────────────────────── 실적 상태 (docs/w52_spec.md §2)
def grade_of(opm, roe, ni, op):
    if (ni is not None and ni < 0) or (op is not None and op < 0):
        return None
    if opm is None and roe is None:
        return None
    if opm is not None and roe is not None and opm >= 40 and roe >= 20:
        return "특등급"
    if roe is not None and roe >= 10 and (opm is None or opm >= 20):
        return "1등급"
    return "2등급"


def fundamental(code, fin, annual, sector):
    """(상태, 등급, ROE, OPM). 상태: PASS / TURNAROUND / FAIL / UNKNOWN."""
    f = fin.get(code)
    base = code[:-1] + "0"
    a = annual.get(base) if base in annual else annual.get(code)
    if f is None and a is None:
        return "UNKNOWN", None, None, None
    is_fin = any(w in sector for w in FIN_WORDS)
    opm, roe, debt = (f["opm"], f["roe"], f["debt"]) if f else (None, None, None)
    rows = []
    if a:
        for k in range(3):
            rows.append({x: a[x][k] for x in ("rev", "op", "ni", "eq")})
    loss = (opm is not None and opm < 0) or (roe is not None and roe < 0)
    capital_erosion = f is not None and roe is None and f.get("equity") is not None and f["equity"] <= 0
    debt_cut = (not is_fin) and debt is not None and debt >= 200
    rev_cut = False
    if rows and not is_fin:
        rv = [r["rev"] for r in rows]
        rev_cut = None not in rv and rv[0] > rv[1] > rv[2]
    cur, prev = (rows[2], rows[1]) if rows else (None, None)
    cur_profit = bool(cur and cur["ni"] is not None and cur["op"] is not None and cur["ni"] > 0 and cur["op"] > 0)
    prev_loss = bool(prev and prev["ni"] is not None and prev["op"] is not None and (prev["ni"] <= 0 or prev["op"] <= 0))
    half_profit = bool(f and (opm is None or opm > 0) and (roe is None or roe > 0))
    if cur_profit:
        grade = grade_of((cur["op"] / cur["rev"] * 100) if cur["rev"] else None,
                         (cur["ni"] / cur["eq"] * 100) if cur["eq"] and cur["eq"] > 0 else None, cur["ni"], cur["op"])
    else:
        grade = grade_of(opm, roe, None, None) if f else None
    if loss or capital_erosion or debt_cut or rev_cut:
        return "FAIL", grade, roe, opm
    if prev_loss and (cur_profit or half_profit):
        return "TURNAROUND", grade, roe, opm
    if cur_profit and (opm is None or opm > 0):
        return "PASS", grade, roe, opm
    return "FAIL", grade, roe, opm


# ───────────────────────── 위험 종목 (docs/w52_spec.md §3)
def risk_of(k):
    why = []
    if (k.get("mang_issu_cls_code") or "N") not in ("N", "00"):
        why.append("관리종목")
    if k.get("temp_stop_yn") == "Y":
        why.append("거래정지")
    if k.get("mrkt_warn_cls_code") in ("02", "03"):
        why.append("투자경고·위험")
    if k.get("short_over_yn") == "Y":
        why.append("단기과열")
    if k.get("sltr_yn") == "Y":
        why.append("정리매매")
    if k.get("iscd_stat_cls_code") in RISK_STAT_CODES:
        why.append("상태코드 " + k["iscd_stat_cls_code"])
    caution = k.get("mrkt_warn_cls_code") == "01" or k.get("invt_caful_yn") == "Y"
    return why, caution


# ───────────────────────── 게이트·점수 (docs/w52_spec.md §4, §6)
def gate(m):
    fails = []
    if m["mcap"] < P.mcap_min:
        fails.append("시총")
    if (m["avg_val20"] or 0) < P.val_min:
        fails.append("거래대금")
    if m["rs1m"] is None or m["rs1m"] < P.rs_min:
        fails.append("RS1M")
    if m["rs3m"] is None or m["rs3m"] < P.rs_min:
        fails.append("RS3M")
    if not m["ma5w_up"]:
        fails.append("5주선")
    if not m["above_ma20w"]:
        fails.append("20주선")
    if m["fund_status"] not in ("PASS", "TURNAROUND"):
        fails.append("실적")
    if m["risk_excluded"]:
        fails.append("위험종목")
    return fails


def static_score(m, atr_rank):
    rs = 25 * ((m["rs3m"] or 0) + (m["rs1m"] or 0)) / 200
    fund = {"PASS": 15, "TURNAROUND": 12}.get(m["fund_status"], 0)
    roe, opm = m.get("roe"), m.get("opm")
    if m["fund_status"] in ("PASS", "TURNAROUND"):
        fund += 6 if (roe or 0) >= 20 else 4 if (roe or 0) >= 10 else 2 if (roe or 0) >= 5 else 0
        fund += 4 if (opm or 0) >= 20 else 2 if (opm or 0) >= 10 else 0
    fund = min(25, fund)
    ind = 12 * (m["sector_rs"] or 0) / 100 + 4 * (m["sector_near_ratio"] or 0)
    q = 0.0
    if m["bbw_pctile"] is not None:
        q += 5 * (1 - m["bbw_pctile"] / 100)
    if atr_rank is not None:
        q += 3 * (1 - atr_rank / 100)
    trend = 3 * bool(m["ma5w_up"]) + 3 * bool(m["above_ma20w"]) + 2 * bool(
        m["ma5w"] is not None and m["ma20w"] is not None and m["ma5w"] > m["ma20w"]) + 2 * bool(m["above_ma240d"])
    return {"rs": round(rs, 2), "fundamental": round(fund, 2), "industry": round(ind, 2),
            "quality": round(q, 2), "trend": round(float(trend), 2),
            "total": round(rs + fund + ind + q + trend, 2)}


# ───────────────────────── 본체
def run(root, db_path=None):
    root = Path(root)
    krx, prov = load_days(root)
    dates = sorted(krx)
    D = dates[-1]
    last = krx[D]
    fin = json.loads((root / "cache" / "dart" / "fin.json").read_text(encoding="utf-8"))["fin"]
    annual = json.loads((root / "cache" / "dart" / "annual.json").read_text(encoding="utf-8"))
    annual.pop("_cap", None)
    kis = json.loads((root / "cache" / "kis" / "kis.json").read_text(encoding="utf-8"))

    rs_codes = [c for c, r in last.items() if int(r["MKTCAP"] or 0) >= P.rs_universe_mcap]
    series = {c: s for c in rs_codes if (s := build_series(krx, dates, c))}

    # RS1M / RS3M: 모집단 안의 수익률 백분위
    def ret(s, n):
        c = s["close"]
        return c[-1] / c[-1 - n] - 1 if len(c) > n and s["ds"][-1] == D else None

    rs1 = ix.percentile_ranks({c: ret(s, P.rs1m_days) for c, s in series.items()})
    rs3 = ix.percentile_ranks({c: ret(s, P.rs3m_days) for c, s in series.items()})

    metrics = {}
    for c, s in series.items():
        mcap = int(last[c]["MKTCAP"] or 0)
        if mcap < P.mcap_min * 0.8 or s["ds"][-1] != D:        # 5,000억의 80% 이상만 상세 지표(게이트는 5,000억)
            continue
        cl, hi, lo, ds = s["close"], s["high"], s["low"], s["ds"]
        cutoff = (datetime.strptime(D, "%Y%m%d") - timedelta(days=P.window_days)).strftime("%Y%m%d")
        win = [(h, d) for h, d in zip(hi, ds) if d >= cutoff]
        h52, h52_date = max(win)
        wc = ix.weekly_closes(ds, cl)
        ma5, ma5_prev = ix.weekly_ma(wc, 5)
        ma20 = ix.sma(wc, 20)
        ma240 = ix.sma(cl, 240)
        bb = ix.bbw_series(cl[-(P.bbw_hist + P.bbw_window):], P.bbw_window)
        bbw_now = bb[-1]
        atr14 = ix.atr(hi, lo, cl, P.atr_period)
        k = kis.get(c, {})
        sector = k.get("sector", "")
        why, caution = risk_of(k)
        vals = [v for v in s["val"][-20:] if v > 0]
        fstat, fgrade, froe, fopm = fundamental(c, fin, annual, sector)
        metrics[c] = {
            "symbol": c, "asof": D, "name": last[c]["ISU_NM"].strip(), "market": last[c]["MKT"], "sector": sector,
            "mcap": mcap, "close": cl[-1], "high_52w_prev": h52, "high_52w_date": h52_date,
            "gap_to_high": cl[-1] / h52 - 1, "rs1m": rs1.get(c), "rs3m": rs3.get(c),
            "fund_status": fstat, "fund_grade": fgrade, "roe": froe, "opm": fopm,
            "ma5w": ma5, "ma5w_up": int(ma5 is not None and ma5_prev is not None and ma5 > ma5_prev),
            "ma20w": ma20, "above_ma20w": int(ma20 is not None and cl[-1] > ma20),
            "ma240d": ma240, "above_ma240d": int(ma240 is not None and cl[-1] > ma240),
            "bbw": bbw_now, "bbw_pctile": ix.pctile_in_history(bbw_now, bb[:-1]),
            "atr14": atr14, "atr_pct": (atr14 / cl[-1]) if atr14 else None,
            "adx14": ix.adx(hi, lo, cl, P.adx_period),
            "avg_vol20": sum(s["vol"][-20:]) / max(1, len(s["vol"][-20:])),
            "vol5_ratio": (sum(s["vol"][-5:]) / 5) / (sum(s["vol"][-20:]) / 20) if len(s["vol"]) >= 20 and sum(s["vol"][-20:]) else None,
            "high_10d": max(hi[-10:]),
            "avg_val20": (sum(vals) / len(vals)) if vals else 0,
            "risk_excluded": int(bool(why)), "risk_reason": ",".join(why), "caution": int(caution),
            "kis_w52": float(k["w52_hgpr"]) if k.get("w52_hgpr") else None, "ohlc_missing_days": sum(s["miss"][-len(win):]),
        }

    # 업종 RS: 업종 내 RS3M 중앙값을 업종 간 백분위로
    by_sec = {}
    for m in metrics.values():
        if m["sector"] and m["rs3m"] is not None:
            by_sec.setdefault(m["sector"], []).append(m)
    sec_med = {s: statistics.median(x["rs3m"] for x in ms) for s, ms in by_sec.items() if len(ms) >= P.sector_min_members}
    sec_rank = ix.percentile_ranks(sec_med)
    sec_near = {s: sum(1 for x in ms if x["gap_to_high"] >= -0.05) / len(ms) for s, ms in by_sec.items()}
    atr_rank = ix.percentile_ranks({c: m["atr_pct"] for c, m in metrics.items()})
    for c, m in metrics.items():
        m["sector_rs"] = sec_rank.get(m["sector"])
        m["sector_near_ratio"] = sec_near.get(m["sector"], 0.0)
        fails = gate(m)
        m["gate_pass"], m["gate_fail"] = int(not fails), ",".join(fails)
        m["score"] = static_score(m, atr_rank.get(c))

    save(root, db_path, D, metrics, prov)
    save_replay(root, D, metrics, series)
    return D, metrics, prov


def save(root, db_path, D, metrics, prov):
    out = root / "cache" / "w52"
    out.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db_path or str(out / "w52.db"))
    cols = ["symbol", "asof", "name", "market", "sector", "mcap", "close", "high_52w_prev", "high_52w_date",
            "gap_to_high", "rs1m", "rs3m", "fund_status", "fund_grade", "ma5w", "ma5w_up", "ma20w", "above_ma20w",
            "ma240d", "above_ma240d", "bbw", "bbw_pctile", "atr14", "atr_pct", "adx14", "sector_rs",
            "sector_near_ratio", "avg_vol20", "vol5_ratio", "high_10d", "avg_val20", "risk_excluded", "risk_reason", "caution",
            "gate_pass", "gate_fail"]
    conn.execute("DELETE FROM daily_metrics WHERE asof=?", (D,))
    conn.execute("DELETE FROM scores WHERE asof=?", (D,))
    conn.executemany("INSERT INTO daily_metrics (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))),
                     [tuple(m[c] for c in cols) for m in metrics.values()])
    conn.executemany("INSERT INTO scores (symbol, asof, rs, fundamental, industry, quality, trend, total) VALUES (?,?,?,?,?,?,?,?)",
                     [(c, D, m["score"]["rs"], m["score"]["fundamental"], m["score"]["industry"], m["score"]["quality"],
                       m["score"]["trend"], m["score"]["total"]) for c, m in metrics.items()])
    store.set_meta(conn, "last_asof", D)
    store.set_meta(conn, "last_asof_provisional", int(D in prov))
    store.set_meta(conn, "generated_at", datetime.now(KST).isoformat(timespec="seconds"))
    conn.commit()
    conn.close()
    payload = {"asof": D, "provisional": D in prov, "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
               "stocks": [{k: v for k, v in m.items() if k != "kis_w52"} for m in metrics.values()]}
    (out / "baseline.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def save_replay(root, D, metrics, series):
    """게이트 통과 종목의 상태를 일봉으로 재현해 저장한다(정적 페이지용). 서버 없이도 장 마감 후 상태를 볼 수 있다."""
    from w52 import replay as R
    out, events = {}, []
    for c, m in metrics.items():
        if not m["gate_pass"]:
            continue
        st, ev = R.replay_stock(c, series[c])
        out[c] = {"state": R.end_of_day_state(st, m["gap_to_high"] * 100), "since": st.since,
                  "broke_today": bool(st.broke_today), "breakout_level": st.breakout_level or None}
        events += [dict(e, symbol=c) for e in ev]
    payload = {"asof": D, "states": out, "events": sorted(events, key=lambda e: (e["day"], e["symbol"]))}
    (root / "cache" / "w52" / "static_states.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def summary(D, metrics):
    ms = list(metrics.values())
    gp = [m for m in ms if m["gate_pass"]]
    fails = {}
    for m in ms:
        for f in filter(None, m["gate_fail"].split(",")):
            fails[f] = fails.get(f, 0) + 1
    cmp_ = [(m["high_52w_prev"], m["kis_w52"]) for m in ms if m["kis_w52"]]
    close = sum(1 for a, b in cmp_ if abs(a / b - 1) <= 0.01)
    print("기준일 %s | 상세 지표 %d종목 | 게이트 통과 %d종목" % (D, len(ms), len(gp)))
    print("게이트 탈락 사유(중복 포함):", dict(sorted(fails.items(), key=lambda x: -x[1])))
    print("실적 상태:", {s: sum(1 for m in ms if m["fund_status"] == s) for s in ("PASS", "TURNAROUND", "FAIL", "UNKNOWN")})
    print("KIS 52주 고가와 ±1%% 일치: %d / %d (%.0f%%)" % (close, len(cmp_), close / len(cmp_) * 100 if cmp_ else 0))
    print("고가·저가 결측일이 있는 종목: %d" % sum(1 for m in ms if m["ohlc_missing_days"]))
    top = sorted(gp, key=lambda m: -m["score"]["total"])[:5]
    print("정적 점수 상위:", [(m["name"], m["score"]["total"], round(m["gap_to_high"] * 100, 1)) for m in top])


if __name__ == "__main__":
    D, metrics, prov = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    summary(D, metrics)
