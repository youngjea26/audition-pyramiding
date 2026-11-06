"""주문 기능이 코드에 들어오지 않게 막는 테스트. 52주 신고가 화면은 후보 검토용이며 자동매매·주문 기능은 없다.

w52 패키지와 그 화면 생성 코드에서 주문 경로·주문 TR 코드·주문 함수 이름이 나오면 실패한다.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = [
    r"order-cash", r"order-rvsecncl", r"order-resv", r"inquire-psbl-order", r"/trading/order",
    r"TTTC0011U", r"TTTC0012U", r"TTTC0013U", r"TTTC0801U", r"TTTC0802U", r"TTTC0803U", r"VTTC0802U", r"VTTC0801U",
    r"place_order", r"send_order", r"SendOrder", r"submit_order", r"create_order", r"cancel_order",
]


def sources():
    files = list((ROOT / "tools" / "w52").rglob("*.py")) + [ROOT / "tools" / "build_52w.py"]
    return [p for p in files if p.exists()]


class NoOrders(unittest.TestCase):
    def test_no_order_paths_or_functions(self):
        offenders = []
        for p in sources():
            text = p.read_text(encoding="utf-8")
            for pat in FORBIDDEN:
                if re.search(pat, text):
                    offenders.append((p.name, pat))
        self.assertEqual(offenders, [], "주문 관련 코드가 들어 있다: %s" % offenders)

    def test_provider_interface_is_read_only(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from w52.providers.base import MarketDataProvider
        public = {n for n in dir(MarketDataProvider) if not n.startswith("_")}
        self.assertEqual(public, {"snapshot", "subscribe", "stream", "close", "name", "max_subscriptions"})

    def test_guard_actually_catches_a_violation(self):
        sample = "def run():\n    return call('/uapi/domestic-stock/v1/trading/order-cash', tr_id='TTTC0012U')\n"
        self.assertTrue(any(re.search(p, sample) for p in FORBIDDEN))


if __name__ == "__main__":
    unittest.main()
