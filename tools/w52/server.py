"""52주 신고가 화면용 웹 서버(표준 라이브러리만). REST + SSE, 토큰 인증.

  GET /            화면(ui/w52.html)
  GET /api/rows    전 종목 현재 상태 {mode, version, day, rows[]}
  GET /api/events  최근 상태 전이 이벤트
  GET /api/stream  SSE — 시세가 갱신될 때마다 rows 를 밀어 준다
  GET /healthz     인증 없이 «살아 있음»만
토큰(LIVE_AUTH_TOKEN)은 서버 환경변수에서만 읽는다. 토큰이 없으면 서버가 뜨지 않는다(실시간 시세를 아무에게나 보여 주지 않기 위해).
?token=… 로 처음 열면 쿠키에 심어 이후엔 주소에 토큰이 남지 않는다.
"""
import hmac
import json
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

UI = Path(__file__).resolve().parent / "ui" / "w52.html"
COOKIE = "w52_token"


class App:
    def __init__(self, service, conn, token, ui_path=UI):
        if not token:
            raise RuntimeError("LIVE_AUTH_TOKEN 환경변수가 없다 — 토큰 없이는 서버를 열지 않는다")
        self.service, self.conn, self.token, self.ui_path = service, conn, token, Path(ui_path)

    def payload(self):
        s = self.service
        return {"mode": s.mode, "version": s.version, "day": s.session_day or "", "rows": s.rows()}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _authorized(self, query):
            tok = (query.get("token") or [""])[0]
            hdr = self.headers.get("Authorization", "")
            if hdr.startswith("Bearer "):
                tok = tok or hdr[7:]
            c = SimpleCookie(self.headers.get("Cookie", ""))
            if COOKIE in c:
                tok = tok or c[COOKIE].value
            return hmac.compare_digest(tok.encode(), app.token.encode()), (query.get("token") or [""])[0]

        def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/healthz":
                return self._send(200, "ok", "text/plain")
            ok, from_query = self._authorized(q)
            if not ok:
                return self._send(401, json.dumps({"error": "unauthorized"}))
            cookie = {"Set-Cookie": "%s=%s; HttpOnly; SameSite=Strict; Path=/" % (COOKIE, app.token)} if from_query else None
            if u.path == "/":
                return self._send(200, app.ui_path.read_bytes(), "text/html; charset=utf-8", cookie)
            if u.path == "/api/rows":
                return self._send(200, json.dumps(app.payload(), ensure_ascii=False), headers=cookie)
            if u.path == "/api/events":
                limit = min(int((q.get("limit") or ["200"])[0]), 1000)
                return self._send(200, json.dumps(app.service.recent_events(app.conn, limit), ensure_ascii=False), headers=cookie)
            if u.path == "/api/stream":
                return self._stream()
            return self._send(404, json.dumps({"error": "not found"}))

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            seen, beat = -1, time.time()
            try:
                while not app.service.stop.is_set():
                    if app.service.version != seen:
                        seen = app.service.version
                        self.wfile.write(("event: rows\ndata: %s\n\n" % json.dumps(app.payload(), ensure_ascii=False)).encode("utf-8"))
                        self.wfile.flush()
                        beat = time.time()
                    elif time.time() - beat > 15:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        beat = time.time()
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return Handler


def serve(app, host="127.0.0.1", port=8052):
    """기본은 이 PC 안에서만(127.0.0.1) 연다. 밖으로 내보낼 때는 터널(Cloudflare Tunnel 등)을 앞에 둔다."""
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    srv.daemon_threads = True
    return srv


def serve_in_thread(app, host="127.0.0.1", port=0):
    srv = serve(app, host, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
