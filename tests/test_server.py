import http.client
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from w52 import server, service as svc, store  # noqa: E402
from w52.engine import Engine  # noqa: E402
from w52.providers.mock import MockMarketDataProvider  # noqa: E402
from test_engine import baseline  # noqa: E402


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = store.connect(":memory:")
        eng = Engine({"AAA": baseline("AAA", "S1"), "BBB": baseline("BBB", "S2")}, conn)
        cls.service = svc.LiveService(eng, MockMarketDataProvider({}))
        cls.srv = server.serve_in_thread(server.App(cls.service, conn, "secret"))
        cls.port = cls.srv.server_address[1]
        cls.url = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.service.stop.set()
        cls.srv.shutdown()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8"), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers

    def test_health_needs_no_token(self):
        self.assertEqual(self.get("/healthz")[:2], (200, "ok"))

    def test_rows_require_token(self):
        self.assertEqual(self.get("/api/rows")[0], 401)
        self.assertEqual(self.get("/api/rows?token=wrong")[0], 401)
        self.assertEqual(self.get("/api/rows", {"Authorization": "Bearer wrong"})[0], 401)

    def test_rows_with_bearer_token(self):
        code, body, _ = self.get("/api/rows", {"Authorization": "Bearer secret"})
        d = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual({r["symbol"] for r in d["rows"]}, {"AAA", "BBB"})
        self.assertIn("mode", d)

    def test_query_token_sets_cookie_then_cookie_works(self):
        code, _, h = self.get("/api/rows?token=secret")
        self.assertEqual(code, 200)
        cookie = h["Set-Cookie"].split(";")[0]
        self.assertEqual(self.get("/api/rows", {"Cookie": cookie})[0], 200)
        self.assertIn("HttpOnly", h["Set-Cookie"])

    def test_page_is_served_and_not_indexed(self):
        code, body, h = self.get("/", {"Authorization": "Bearer secret"})
        self.assertEqual(code, 200)
        self.assertIn("52주 신고가 매매", body)
        self.assertIn("noindex", body)
        self.assertEqual(h["X-Robots-Tag"], "noindex")

    def test_events_endpoint(self):
        code, body, _ = self.get("/api/events?limit=5", {"Authorization": "Bearer secret"})
        self.assertEqual((code, json.loads(body)), (200, []))

    def test_stream_sends_rows_event(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/stream", headers={"Authorization": "Bearer secret"})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream")
        first = r.fp.readline().decode("utf-8")
        self.assertEqual(first.strip(), "event: rows")
        c.close()

    def test_server_refuses_to_start_without_token(self):
        with self.assertRaises(RuntimeError):
            server.App(self.service, None, "")


if __name__ == "__main__":
    unittest.main()
