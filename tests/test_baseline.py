import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import baseline as B  # noqa: E402


def ann(ni, op, rev, eq=1000):
    """연간 3개년(전전·전·당기). 각 인자는 3개 값 목록."""
    return {"y": [2023, 2024, 2025], "ni": ni, "op": op, "rev": rev, "eq": [eq] * 3}


def fin(opm=10.0, roe=12.0, debt=80, equity=1000):
    return {"opm": opm, "roe": roe, "debt": debt, "equity": equity, "보고서": "반기"}


class Risk(unittest.TestCase):
    def test_normal_and_caution(self):
        self.assertEqual(B.risk_of({"mang_issu_cls_code": "N", "mrkt_warn_cls_code": "00", "iscd_stat_cls_code": "55"}), ([], False))
        self.assertEqual(B.risk_of({"mrkt_warn_cls_code": "01"}), ([], True))          # 투자주의는 표시만

    def test_each_exclusion(self):
        self.assertIn("관리종목", B.risk_of({"mang_issu_cls_code": "Y"})[0])
        self.assertIn("거래정지", B.risk_of({"temp_stop_yn": "Y"})[0])
        self.assertIn("투자경고·위험", B.risk_of({"mrkt_warn_cls_code": "02"})[0])
        self.assertIn("투자경고·위험", B.risk_of({"mrkt_warn_cls_code": "03"})[0])
        self.assertIn("단기과열", B.risk_of({"short_over_yn": "Y"})[0])
        self.assertIn("정리매매", B.risk_of({"sltr_yn": "Y"})[0])
        self.assertTrue(B.risk_of({"iscd_stat_cls_code": "51"})[0])
        self.assertEqual(B.risk_of({"iscd_stat_cls_code": "57"})[0], [])               # 증거금 100% 는 위험 종목이 아니다
        self.assertEqual(B.risk_of({})[0], [])                                          # 플래그가 없으면 제외하지 않는다


class Fundamental(unittest.TestCase):
    def status(self, f, a, sector="전기·전자"):
        return B.fundamental("111110", {"111110": f} if f else {}, {"111110": a} if a else {}, sector)[0]

    def test_pass(self):
        self.assertEqual(self.status(fin(), ann([5, 6, 8], [6, 7, 9], [100, 110, 130])), "PASS")

    def test_turnaround(self):
        self.assertEqual(self.status(fin(), ann([-5, -2, 8], [-3, -1, 9], [100, 110, 130])), "TURNAROUND")
        self.assertEqual(self.status(fin(), ann([5, -2, -1], [6, -1, -1], [100, 110, 130])), "TURNAROUND")   # 연간은 아직 적자, 최신 반기는 흑자

    def test_fail_reasons(self):
        self.assertEqual(self.status(fin(opm=-3), ann([5, 6, 8], [6, 7, 9], [100, 110, 130])), "FAIL")        # 최신 반기 적자
        self.assertEqual(self.status(fin(debt=250), ann([5, 6, 8], [6, 7, 9], [100, 110, 130])), "FAIL")      # 부채비율 200%+
        self.assertEqual(self.status(fin(), ann([5, 6, 8], [6, 7, 9], [130, 110, 100])), "FAIL")              # 매출 2년 연속 감소
        self.assertEqual(self.status(fin(), ann([5, 6, 8], [6, 7, 9], [130, 110, 100]), sector="금융"), "PASS")   # 금융은 매출 컷 제외
        self.assertEqual(self.status(fin(debt=900), ann([5, 6, 8], [6, 7, 9], [100, 110, 130]), sector="보험"), "PASS")

    def test_unknown_without_any_financials(self):
        self.assertEqual(self.status(None, None), "UNKNOWN")

    def test_preferred_stock_uses_common_stock_financials(self):
        s = B.fundamental("111115", {}, {"111110": ann([5, 6, 8], [6, 7, 9], [100, 110, 130])}, "화학")[0]
        self.assertEqual(s, "PASS")


def metrics(**kw):
    m = {"mcap": 800e9, "avg_val20": 9e9, "rs1m": 85, "rs3m": 90, "ma5w_up": 1, "above_ma20w": 1, "fund_status": "PASS",
         "risk_excluded": 0, "ma5w": 110, "ma20w": 100, "above_ma240d": 1, "bbw_pctile": 20, "sector_rs": 80,
         "sector_near_ratio": 0.5, "roe": 15, "opm": 12}
    m.update(kw)
    return m


class GateAndScore(unittest.TestCase):
    def test_all_pass(self):
        self.assertEqual(B.gate(metrics()), [])

    def test_each_condition_fails_independently(self):
        cases = {"시총": {"mcap": 499e9}, "거래대금": {"avg_val20": 4.9e9}, "RS1M": {"rs1m": 69.9}, "RS3M": {"rs3m": None},
                 "5주선": {"ma5w_up": 0}, "20주선": {"above_ma20w": 0}, "실적": {"fund_status": "FAIL"}, "위험종목": {"risk_excluded": 1}}
        for name, change in cases.items():
            self.assertEqual(B.gate(metrics(**change)), [name], name)

    def test_boundaries_are_inclusive(self):
        self.assertEqual(B.gate(metrics(mcap=500e9, avg_val20=5e9, rs1m=70, rs3m=70, fund_status="TURNAROUND")), [])

    def test_static_score_parts(self):
        s = B.static_score(metrics(), atr_rank=10)
        self.assertAlmostEqual(s["rs"], 25 * (90 + 85) / 200, places=2)          # 21.875 -> 21.88 (소수 2자리로 반올림해 저장)
        self.assertEqual(s["fundamental"], 21)                                   # PASS 15 + ROE 15(>=10) 4 + OPM 12(>=10) 2
        self.assertEqual(s["trend"], 10)                                         # 5주선 상승 3 + 20주선 위 3 + 5주>20주 2 + 240일선 위 2

    def test_static_score_never_exceeds_84(self):
        best = metrics(rs1m=100, rs3m=100, roe=30, opm=30, bbw_pctile=0, sector_rs=100, sector_near_ratio=1.0)
        s = B.static_score(best, atr_rank=0)
        self.assertLessEqual(s["total"], 84.0)
        self.assertAlmostEqual(s["total"], 84.0, places=1)                       # 25 + 25 + 16 + 8 + 10

    def test_fundamental_score_is_capped_at_25(self):
        self.assertEqual(B.static_score(metrics(roe=99, opm=99), 50)["fundamental"], 25)


if __name__ == "__main__":
    unittest.main()
